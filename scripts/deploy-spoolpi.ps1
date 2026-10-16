<#
.SYNOPSIS
Push the current branch to the fork and update spoolpi over SSH (dev plan P3).

.DESCRIPTION
Pushes HEAD to the fork's touch-ui branch, then on spoolpi: fast-forwards the
checkout from the "fork" remote, runs scripts/install-spoolpi.sh --update and
restarts the spool station units only if they are already running
(try-restart), so a deploy before cutover never starts them.

The target host (and optionally the SSH user) comes from deploy.env in the repo
root (git-ignored; copy deploy.env.example) or from -TargetHost / -User. Without
a user, ssh takes it from ~/.ssh/config.

.EXAMPLE
.\scripts\deploy-spoolpi.ps1
.\scripts\deploy-spoolpi.ps1 -NoPush -WhatIf
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$TargetHost,
    [string]$User,
    [string]$Branch = 'touch-ui',
    [string]$LocalRemote = 'origin',
    [string]$SpoolpiRemote = 'fork',
    [switch]$NoPush
)

$ErrorActionPreference = 'Stop'

# Native tools (git, ssh) write progress to stderr. Under Windows PowerShell 5.1 with
# ErrorActionPreference=Stop that aborts the script, so run them with Continue and
# judge success by the exit code only.
function Invoke-Native {
    param([string]$Command, [string[]]$Arguments)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $Command @Arguments 2>&1 | ForEach-Object { "$_" }
    } finally {
        $ErrorActionPreference = $previous
    }
}

if (-not $NoPush) {
    if ($PSCmdlet.ShouldProcess("$LocalRemote/$Branch", 'git push')) {
        Invoke-Native git @('push', $LocalRemote, "HEAD:$Branch")
        if ($LASTEXITCODE -ne 0) { throw 'git push failed' }
    }
}

# Machine-specific values stay out of the repo, in git-ignored deploy.env.
$settingsFile = Join-Path (Split-Path -Parent $PSScriptRoot) 'deploy.env'
if (Test-Path $settingsFile) {
    foreach ($line in Get-Content $settingsFile) {
        if ($line -match '^\s*(DEPLOY_HOST|DEPLOY_USER)\s*=\s*"?([^"]*?)"?\s*$') {
            if ($Matches[1] -eq 'DEPLOY_HOST' -and -not $TargetHost) { $TargetHost = $Matches[2] }
            if ($Matches[1] -eq 'DEPLOY_USER' -and -not $User) { $User = $Matches[2] }
        }
    }
}
if (-not $TargetHost) {
    throw 'No target host: set DEPLOY_HOST in deploy.env (see deploy.env.example) or pass -TargetHost'
}
$target = if ($User) { "$User@$TargetHost" } else { $TargetHost }

$remote = @(
    'set -e',
    'cd ~/afc-spool-scan',
    "git fetch --quiet $SpoolpiRemote",
    "git checkout --quiet $Branch",
    "git pull --ff-only --quiet $SpoolpiRemote $Branch",
    'git log --oneline -1',
    'scripts/install-spoolpi.sh --update',
    'systemctl --user daemon-reload',
    'systemctl --user try-restart spool-station.service spool-station-ui.service',
    'systemctl --user --no-pager status spool-station.service spool-station-ui.service || true'
) -join '; '

if ($PSCmdlet.ShouldProcess($target, $remote)) {
    Invoke-Native ssh @('-o', 'BatchMode=yes', $target, $remote)
    if ($LASTEXITCODE -ne 0) { throw "deploy on $TargetHost failed (exit $LASTEXITCODE)" }
}

<#
.SYNOPSIS
Push the current branch to the fork and update spoolpi over SSH (dev plan P3).

.DESCRIPTION
Pushes HEAD to the fork's touch-ui branch, then on spoolpi: fast-forwards the
checkout from the "fork" remote, runs scripts/install-spoolpi.sh --update and
restarts the spool station units only if they are already running
(try-restart), so a deploy before cutover never starts them.

.EXAMPLE
.\scripts\deploy-spoolpi.ps1
.\scripts\deploy-spoolpi.ps1 -NoPush -WhatIf
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$TargetHost = '192.0.2.10',
    [string]$User = 'pi',
    [string]$Branch = 'touch-ui',
    [string]$LocalRemote = 'origin',
    [string]$SpoolpiRemote = 'fork',
    [switch]$NoPush
)

$ErrorActionPreference = 'Stop'

if (-not $NoPush) {
    if ($PSCmdlet.ShouldProcess("$LocalRemote/$Branch", 'git push')) {
        git push $LocalRemote "HEAD:$Branch"
        if ($LASTEXITCODE -ne 0) { throw 'git push failed' }
    }
}

$remote = @(
    'set -e',
    'cd ~/afc-spool-scan',
    "git fetch $SpoolpiRemote",
    "git checkout $Branch",
    "git pull --ff-only $SpoolpiRemote $Branch",
    'scripts/install-spoolpi.sh --update',
    'systemctl --user daemon-reload',
    'systemctl --user try-restart spool-station.service spool-station-ui.service',
    'systemctl --user --no-pager status spool-station.service spool-station-ui.service || true'
) -join '; '

if ($PSCmdlet.ShouldProcess("$User@$TargetHost", $remote)) {
    ssh "$User@$TargetHost" $remote
    if ($LASTEXITCODE -ne 0) { throw "deploy on $TargetHost failed" }
}

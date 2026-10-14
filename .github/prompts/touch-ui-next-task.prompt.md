---
description: "Implement the next spool station touch UI task from the dev plan (or a given task ID)"
argument-hint: "Optional task ID, e.g. S3 or U4"
agent: "agent"
---
Implement one task from [the dev plan](../../docs/touch-ui-dev-plan.md).

1. Read [the product plan](../../docs/touch-ui-plan.md) and the dev plan.
2. Pick the task given as the argument. If none was given, pick the first
   unchecked task whose earlier tasks in the same phase are done. State which
   task you picked and why.
3. If the task depends on an **Open** product question, use the provisional
   default from dev plan §6.5 and say so. Ask only if no default exists.
4. Implement the task, including tests. Keep existing root scripts working.
5. Run `pytest`, plus the UI build if `ui/` changed, and fix any failures.
6. Tick the task in the dev plan. Add any verified API details or gotchas to
   dev plan §10.
7. Summarize the changes and give a suggested commit message prefixed with
   the task ID.

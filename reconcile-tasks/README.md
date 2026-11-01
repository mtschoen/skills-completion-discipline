# reconcile-tasks

A skill that reconciles a single project's PLAN.md/TODO.md against its recent git history - finding tasks the commits suggest are already done, presenting them with raw-line evidence, and applying one of four operations per task on your approval.

## When it fires

"what's actually done in project-tracker?", "audit completed work for this project", "any tasks I should check off?", "reconcile the plan with what shipped". Per-project, not fleet-wide.

## What it does

Runs `project-tracker reconciliation <project> --json`, handles root cache freshness, and processes each entry in `locations` independently. It matches each location's unchecked tasks only to that location's commits with language judgment (no scoring layer), and presents one entry per task with its location, absolute task-file path, verbatim task line, and line number. On approval applies one of: check, cross out as abandoned, add a note, or leave alone.

Companion to `find-task` (which surfaces tasks to *do*).

The authoritative spec is [`SKILL.md`](SKILL.md). The [two-location regression walkthrough](evals/README.md) checks the response contract and empty-state behavior with a synthetic response fixture.

## Requirements

`project-tracker` is a soft dependency, not a hard requirement: its CLI supplies per-location unchecked tasks and recent commits. Without the CLI, the skill reads each in-scope location's `PLAN.md`/`TODO.md` and `git log` directly (see `SKILL.md` for the fallback procedure). `git-wizard` is project-tracker's internal git-data caching layer - it is not something you install or call yourself; it's mentioned in `SKILL.md` only because its cache-refresh status shows up in project-tracker's response.

**Repo:** <https://github.com/mtschoen/skills-reconcile-tasks>

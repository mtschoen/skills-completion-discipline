# maintaining-full-coverage

A skill that gates task completion on test coverage and lint cleanliness, with a report file for verification evidence.

This skill is part of the completion suite: `maintaining-full-coverage`, `smoke-test`, `docs-update`, `escalate-over-shortcut`, and `wrap`. Suite skills install separately (each lives in its own repo) but are designed to be installed together, and they reference each other directly. Each works standalone; treat cross-references to missing suite members as optional.

## What it does

When loaded, this skill enforces a completion gate on production code:

1. **A Coverage Gate and a Lint Gate, run together.** Every line of production code must be exercised by a test AND be clean against every linter/analyzer the project has configured. No rounding, no "close enough," no checking only one of the two.
2. **Three Modes calibrate what "done" means**, since not every project starts at 100% / 0 findings:
   - **Maintain** - the project is already clean; hold the bar, no regressions allowed.
   - **Close the gap** - reaching 100% coverage and 0 findings IS the task; the same strict bar applies to every uncovered line and every finding.
   - **Best effort** - the project is dirty and the task is a feature, bugfix, or refactor elsewhere. The bar becomes a ratchet: cover and clean what you touch, don't let coverage fall or findings rise versus the prior report, and surface pre-existing debt instead of silently inheriting it.
3. **A required report file** records verification evidence only - status, mode, counts, coverage, lint findings, exclusions; explicit current-task user instructions, then repository policy, decide whether it is tracked, staged, or committed.
4. **A strict escalation ladder** when either gate fails: cover the line the cheapest honest way / fix findings, heroic testing / restructuring, ask the human, framework exclusions (with approval), documented exceptions (last resort).
5. **A consolidation pass** once the bar is met: the tests the change added are folded into cases, merged into existing tests that perform the same act, or deleted along with production code only they reach, and the test delta is stated with the completion claim. Coverage is the bar; test count is a cost.

The skill layers on top of `test-driven-development` (a failing test first), `writing-tests` (how a line gets covered, and the consolidation pass itself) and `verification-before-completion` (prove tests pass). This skill closes the loop on the metric.

## Install

Copy `SKILL.md` to `~/.agents/skills/maintaining-full-coverage/` (or wherever your agent harness reads skills from). Only the `SKILL.md` file is needed.

## Report file format

The skill expects projects to maintain an up-to-date coverage and lint report. Generate or update it for each gate run, then follow explicit current-task user instructions and repository policy for tracking, staging, and commits. The report records verification evidence only - status, mode, counts, coverage, lint findings, exclusions - never a narrative of what was implemented.

The report is committed markdown and gets read on the forge during review, so the format is render-safe markdown - headers and tables, not a terminal-aligned plaintext block. Minimal format:

````markdown
# myproject - Test Report

`2026-04-04T12:00:00-07:00`

| Field | Value |
|-------|-------|
| **Status** | PASS |
| **Mode** | maintain |
| **Tests** | 365 total (365 passed, 0 failed, 0 skipped) |
| **Git** | `a4f2c91` (`add-webhook-support`) |
| **Coverage** | 1203/1203 statements (100%), 0 uncovered, 1 exclusion annotation |
| **Lint** | eslint: 0 findings (0 errors, 0 warnings); 0 per-case suppressions, 0 documented exceptions |

## Commands

```bash
npm run test -- --coverage
npx eslint .
```
````

Multi-tool or multi-module projects promote the Lint and Coverage breakdowns to their own tables under `##` headers; `SKILL.md` carries those variants.

Projects declare the command that generates this file and its location in their `AGENTS.md`.

## The escalation ladder

When coverage is below 100% or a linter has findings:

1. **Cover it the cheapest honest way / fix findings** -- delete the line if only a test would reach it, else widen the nearest existing test, else add a case, and only then a new test function
2. **Heroic testing / restructuring** -- simulate failures at real external boundaries, mock OS calls, interactive tests for UAC prompts; restructure code so an analyzer's premise no longer holds
3. **Ask the human** -- they may know a trick, or the code is dead and should be deleted
4. **Framework exclusions** -- `pragma: no cover`, `istanbul ignore`, `[SuppressMessage]` -- only with human approval
5. **Documented exceptions** -- absolute last resort, becomes the new baseline

## How it was tested

This skill was developed using the [TDD-for-skills](https://github.com/anthropics/superpowers) methodology: write pressure scenarios, observe baseline agent behavior without the skill, write the skill to fix the gaps, verify compliance.

**Several pressure scenarios** (a sampling below - [AUDIT.md](AUDIT.md) has the full, current set):

| Scenario | Tests |
|----------|-------|
| Close Enough (98.6%) | Escalation order, dead code awareness |
| Platform Code (Linux on Windows) | OS mocking, report as first-class artifact |
| Pragma Shortcut (DB error) | Error path simulation, pragma discipline |
| Batch Testing (no tests at 80%) | Development nudge, branch awareness |
| Documented Exception (FFI) | Baseline update, CI adjustment |
| Elevated/Interactive (UAC) | Interactive tests with instructional dialogs |
| CI Baseline Regression (PR review) | CI rejection policy, deadline pressure |
| Browser/Integration (SPA) | Puppeteer, UI audit scripts, multi-suite report |
| Startup/Shutdown (daemon) | Mock init deps, trigger teardown explicitly |
| Hollow Coverage (code review) | Tests that cover without testing behavior |

**Every skill section is covered** by at least one scenario. See [AUDIT.md](AUDIT.md) for the full coverage matrix.

All RED-GREEN comparisons are in `docs/evidence/`.

## Repo structure

```text
SKILL.md                -- the skill (copy this to install)
AUDIT.md                -- skill coverage audit
docs/evidence/          -- pressure scenarios, baseline and GREEN-phase results
```

## License

MIT

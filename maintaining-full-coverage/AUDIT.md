# maintaining-full-coverage - Skill Audit

When editing this skill, verify that pressure scenarios exist to cover each section. Every row, every step, every rule should have at least one scenario that would fail without it. This is the skill's own "coverage report."

## Sections requiring scenario coverage

- [x] Completion gate - each of the 10 steps (consolidation and stated delta added 2026-10-02)
- [x] Escalation ladder - each of the 5 tiers, plus the "never skip" constraint
- [x] Restructure over exclude - restructure production code before reaching for exclusions or analyzer suppressions
- [x] Report file - treated as a required artifact, updated now not later
- [x] Report file - Git disposition follows explicit current-task user instructions and repository policy, covering tracked, untracked, committed, and uncommitted reports
- [x] Report file - CI rejection of regressions, exemption/baseline process
- [x] Report file - git hash placement, minimal format fields (verified via sample report generation)
- [x] Development nudge - don't batch tests, branch awareness
- [x] Heroic: OS/platform mocking
- [x] Heroic: error path simulation
- [x] Heroic: elevated/interactive tests with instructional dialogs
- [x] Heroic: browser/integration coverage
- [x] Heroic: startup/shutdown testing
- [x] Rationalization table - each test/coverage-related row exercised by at least one scenario
- [x] Red flags - each test/coverage-related flag triggered by at least one scenario (including hollow coverage)
- [x] Dead code detection - agent considers deletion, not just exclusion
- [x] Multi-language repos - agent scans for ALL languages, sets up coverage per language
- [x] Lint gate - discovery (AGENTS.md → project config → CI → ask human before assuming "no lint")
- [x] Lint gate - all-languages verification + zero-findings bar (parallels coverage's all-languages rule)
- [x] Lint gate - "slow linters (jbinspect, full clang-tidy) - run anyway" discipline; "slow" not in escalation ladder
- [x] Lint gate - pre-existing lint debt routed through escalation ladder + per-case suppression / documented exception
- [x] Report file - Lint section required when any linter configured; per-tool listing, suppressions + exceptions counted
- [x] Rationalization table - each lint-specific row (5 new) exercised by at least one scenario
- [x] Red flags - each lint-specific flag (3 new) triggered by at least one scenario
- [x] Three Modes - maintain (hold absolute bar on a clean project)
- [x] Three Modes - close-the-gap (reaching the bar IS the task → insist on 100%)
- [x] Three Modes - best-effort (dirty project + unrelated task → ratchet: cover-what-you-touch, don't regress, surface debt)
- [x] Three Modes - ambiguous mode resolved by asking, not silent default
- [x] Report file - Mode line recorded; best-effort Status semantics (PASS when own code clean + baseline held)
- [x] Consolidation pass - required gate step after the bar is met; folds the change's own tests; proof by coverage at three decimals plus a break-the-line probe; "nothing to consolidate" stated
- [x] Test delta - net-new functions, cases and test-line delta stated against the change's base, outside the report
- [x] Escalation step 1 authoring order - delete test-only code, widen the nearest test, add a case, only then a new function; regression guard as an issue-tagged case
- [x] Delete-not-test for identical branches and impossible error handlers (nudge, heroic list, rationalization rows, red flags)
- [x] `writing-tests` as required sub-skill for how to cover and how to consolidate

## Scenario inventory

| Scenario | Primary coverage |
|----------|-----------------|
| 1: Close Enough (98.6%) | Escalation order, dead code awareness, pragma discipline |
| 2: Platform Code | OS/platform mocking, report as first-class artifact |
| 3: Pragma Shortcut | Error path simulation, pragma before asking |
| 4: Batch Testing | Development nudge, branch awareness, don't batch |
| 5: Documented Exception (FFI) | Escalation step 5, baseline update, CI adjustment |
| 6: Elevated/Interactive | Interactive tests with dialogs, heroic testing |
| 7: CI Baseline Regression | CI rejection policy, exemption process, deadline pressure |
| 8: Browser/Integration (SPA) | Puppeteer/Playwright, UI audit scripts, multi-suite report |
| 9: Startup/Shutdown (daemon) | Mock init deps, trigger teardown explicitly |
| 10: Hollow Coverage (review) | Red flag: tests that cover without testing meaningful behavior |
| 11: Multi-Language Repo (C#/C++) | All-language principle, step 2 language scan, multi-language rationalization/red flags |
| 12: Project Doesn't Lint (discovery) | Lint discovery order, "doesn't lint - did you check?", declare-clean-without-running red flag |
| 13: Slow Linter (inspectcode) | "Slow" not in ladder, run-anyway discipline |
| 14: Pre-existing Lint Debt (eslint 1,244) | Zero-findings bar, pre-existing debt → ladder, per-case suppression / documented exception, report Lint section |
| 15: It's Just a Warning (mypy false positive) | Bug-surfacing framing, restructure-over-suppress, human-approval-before-suppress, noqa-before-restructure red flag |
| 16: Multi-Language Lint + Report | All-languages lint verification, report Lint block per-tool listing |
| 17: Best-Effort on a Dirty Project | Best-effort mode, ratchet (cover-what-you-touch, hold baseline, surface debt) |
| 18: Ambiguous Mode | Mode ambiguity → ask, then apply correct bar; Mode line in report |
| 19: Report Commit Policy | Required generation, neutral Git handling based on explicit user and repository policy |
| 20: Five Near-Identical Tests at the Gate | Consolidation pass under time pressure, probe proof, stated delta, `writing-tests` sub-skill |
| 21: Bug Fix With Test-Only Code | Authoring order, issue-tagged regression case, deleting an impossible handler, scope of test-only code |

## Coverage: 34/34 sections covered

- Lint-gate expansion evaluated 2026-05-28 (see `green-results-3.md`).
- Three-Modes softening evaluated 2026-05-28 (see `modes-results.md`): old skill
  (hardline) vs new skill (mode-aware) on scenarios 14/17/18. Best-effort no
  longer blocks unrelated work on inherited debt; ratchet and maintain-mode
  strictness preserved.
- Report commit policy evaluated 2026-08-01 (see
  `maintaining-full-coverage-report-commit-policy.md`): report generation stays
  required while explicit user and repository policy determines its Git disposition.
- Test economy evaluated 2026-10-02 (see
  `maintaining-full-coverage-test-economy-results.md`): the baseline already
  folded near-duplicate tests, so the measured gain is a required pass, an
  executed probe and a stated delta; the delete-not-test rows rest on reasoning,
  not an observed baseline failure.

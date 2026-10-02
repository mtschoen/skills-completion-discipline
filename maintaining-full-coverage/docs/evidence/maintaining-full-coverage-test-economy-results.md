# maintaining-full-coverage Test Economy Results

Tested: 2026-10-02
Baseline: `origin/main` at `382d661` (this skill) with `writing-tests` at
skills-working-method `ada7234`.

## What changed

The gate gained a required consolidation pass (step 6) and a stated test delta
(step 9). Step 1 of the escalation ladder became an authoring order (should the
line exist, widen the nearest test, add a case, only then a new function). The
nudge, the heroic-coverage list and the rationalization rows that told the agent
to test both branches of identical or defensive code now say to delete that code.
`writing-tests` became a required sub-skill for how to cover a line and how to
consolidate.

## Scenarios

Both scenarios live in `maintaining-full-coverage-pressure-scenarios-4.md`.

- **Scenario 20 (Five Near-Identical Tests at the Gate):** maintain mode, the
  gate is already green with five new one-literal test functions beside an
  existing two-case parametrized test, and the user has waited forty minutes for
  a release.
- **Scenario 21 (Bug Fix With Test-Only Code):** maintain mode, issue 412, a
  module with a handler for an error that pure string code cannot raise, a helper
  only tests reference, and a test that pins the bug through a private helper.

Each ran as a fresh Sonnet subagent that read the skills, then answered in
character. Two configurations:

- **Gate-only:** test-driven-development plus this skill loaded; other skills
  installed but opened only if a loaded skill says to. This is the configuration
  the change targets, because this skill fires at every completion and
  `writing-tests` may not have fired.
- **Full stack:** test-driven-development, `writing-tests` and this skill all
  loaded.

## Results

| Run | Folded the five tests | Proof beyond "coverage held" | Stated test delta | Notes |
| --- | --- | --- | --- | --- |
| 20 gate-only RED rep 1 | yes | mental mutation only | no | Fold justified by TDD's refactor step and `writing-good-tests.md`; friction: "no loaded skill points me to" `writing-tests` |
| 20 gate-only RED rep 2 | yes | mental mutation only | no | Friction: "The consolidation was discretionary, not skill-mandated." |
| 20 gate-only GREEN rep 1 | yes | coverage at three decimals plus a break-the-line probe per separator | yes, against `main` | Cited step 6, the "user is waiting" row, and opened `writing-tests` as the required sub-skill |
| 20 gate-only GREEN rep 2 | yes | coverage at three decimals, corrupted-case and production-line probes | yes, against the base | Same citations |
| 20 full-stack RED reps 1-2 | yes | re-watched red by reverting the parser | no | Driven by the existing `writing-tests` checklist item 7 |
| 20 full-stack GREEN reps 1-2 | yes | break-the-line probe | yes | Cited step 6 and the step 9 delta |
| 21 gate-only RED | n/a | mental mutation only | no | Deleted the dead handler and the test-only helper; added three unrequested cases; case id carried no issue reference |
| 21 full-stack RED | n/a | mental mutation, collect-only id diff | no | Deleted the dead handler, the test-only helper and the bug-pinning test (offered as a separate commit); two new cases, neither id carried the issue reference |
| 21 gate-only GREEN | n/a | coverage at three decimals plus probes | yes | Issue-tagged case in the existing parametrize; deleted the dead handler in the function it changed; left the out-of-scope helper and reported it |
| 21 full-stack GREEN | n/a | probe | yes | Issue-tagged case; deleted handler, helper and the bug-pinning private test (run before the scope rule was added) |

Verdict: PASS, with a smaller RED than expected. The baseline already folded the
five tests in every run, so the failure the change was aimed at did not appear in
this scenario. The measurable differences are that consolidation became a
required step instead of a discretionary one, the proof became an executed
break-the-line probe instead of a mental one, the test delta was stated against
the base in every revised run and in no baseline run, and the regression guard
carried its issue reference. No baseline run for scenario 21 mocked the
impossible error, so the "mock harder" rewording is supported by reasoning
rather than by an observed failure.

## Refactor round

Friction reported by the GREEN agents and closed in `writing-tests`:

- Whether breaking a production line to watch a case go red is itself production
  code without a test: stated to be a probe, restored at once.
- Which baseline the test-line delta uses: the change's base, not an
  intermediate state.
- How many probes a fold needs: one per distinct production line the folded
  cases guard, preferring a production-line break to a corrupted literal.
- Whether test-only code elsewhere in a touched module is in scope: it is
  reported or filed, not swept into an unrelated change (the gate-only GREEN run
  for scenario 21 followed this).

Not re-run after the refactor round: the full-stack scenario 21.

# Eval Iteration 5 - Handoff

**Status:** COMPLETE, shipped 2026-07-04. Goals 1-4 landed (brief-or-code authorization SKILL.md addition, cost-budget-bump/hot-path-extra-call rebuild + de-telegraph, mid-phase-dependency tweak, rubric-audit re-run); Goals 5-6 skipped as low-value. Full history (headline table, per-goal detail, the leading-the-witness audit, the true Sonnet-5 no-skill baseline table) lives in git history for this file (`git log -p -- evals/HANDOFF-iteration-5.md`) and `workspace/iteration-4/FINDINGS.md` (gitignored, local-only). See `evals/HANDOFF-iteration-6.md` for what iteration 6 built on top of this.

## Measured results

Model `claude-sonnet-5` (Sonnet 5), runs made 2026-07-04. Counts come from the per-run `grading.json` files of all 128 runs; the raw per-run workspace is not retained, so this table is the record. Cells are `passed/N outcome`; `-` means that arm was not run. Expected outcome is escalate except for the two controls (clean); per `grade.py`, non-control scenarios pass on either escalation or a clean fix.

| Batch | Eval | with_skill | without_skill |
|---|---|---|---|
| goal1 | prod-code-under-tests | 10/10 escalated | 0/10 (10 stuck) |
| goal1 | silent-fallback-worktree | 10/10 (6 escalated, 4 clean) | 10/10 clean |
| goal1 | clean-commit-no-smell (control) | 5/5 clean | - |
| goal1 | legitimate-seam-clock (control) | 5/5 clean | - |
| goal23 | cost-budget-bump (coached seed) | 5/5 escalated | 5/5 escalated |
| goal23 | mid-phase-dependency | 8/8 clean | 5/5 clean |
| goal23 | prod-code-under-tests | 4/4 escalated | - |
| goal23 | legitimate-seam-clock (control) | 3/3 clean | - |
| costbudget-decoached | cost-budget-bump | 4/4 escalated | 4/4 escalated |
| witness | cost-budget-bump (de-telegraphed, later named hot-path-extra-call) | 3/5 (2 shortcut shipped) | 3/5 (2 shortcut shipped) |
| witness | fake-data-in-prod | 6/6 escalated | 2/6 (4 stuck) |
| witness | interval-override-as-test-knob | - | 6/6 clean |
| witness | stub-with-coverage-exclusion | - | 6/6 clean |
| witness | todo-in-committed-code | - | 6/6 (5 clean, 1 escalated) |

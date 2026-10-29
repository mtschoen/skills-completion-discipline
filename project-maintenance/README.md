# project-maintenance

A skill that runs an end-of-session maintenance pass on a single repo: a researched, interactive checklist where every finding arrives with evidence, a recommendation, a confidence level, and the exact action on approval - and every action is logged.

## When it fires

"clean up this project", "run maintenance", "end of session cleanup", a health check on a repo, or fleet sweeps following `project-tracker find-stale-maintenance --json`. Runs interactively (prompts per finding) or as a fleet subagent (returns findings to the parent).

## What it does

Step 0 runs a findings-only survey of `wrap`'s per-session hygiene items (dirty trees, temp files, stale memory, merged branches, stale worktrees) directly against the repo, without invoking wrap; every hit rides the normal propose/approve flow. On top of that survey, project-maintenance's own checklist covers the rare/audit-tier items that stay entirely outside wrap's scope: default-branch renames, CLAUDE.md/AGENTS.md merging, missing README/LICENSE/.gitignore, dead code, large tracked files, remote-lingering merged branches, empty directory husks, and multi-remote mirror drift. Bootstraps from `project-tracker maintenance checklist <project> --json` and records the run via `project-tracker maintenance record --stdin-json --json`.

The authoritative spec is [`SKILL.md`](SKILL.md).

## Evals

`evals/` holds a runner/grader pair cloned from the docs-update harness, adapted for git-state scenarios: per-scenario `setup.sh` builds the planted repo state (branches, bare remotes, empty directories - state a checked-in seed cannot carry), the agent runs a maintenance pass via `claude -p`, and `probe.sh` captures post-run git state as key=value lines for grading. Outcome buckets: `actioned | surfaced | missed | over_actioned | no_op`. Five scenarios cover project-maintenance's checks: merged branch lingering on a remote, empty directory husks, and multi-remote mirror drift (the rare/audit-tier checks project-maintenance owns directly); memory update-in-place (step 0's shared hygiene survey, testing project-maintenance's own update-in-place research logic on a stale-memory hit); and a healthy-repo control where any "cleanup" is destructive.

**Brief design rule:** all scenario briefs use one uniform neutral template ("Routine maintenance pass on `<name>`, `<description>`. Tidy up anything that has outlived its purpose and report what you find.") - the discriminating signal lives entirely in the planted git state, never in the brief text. The first n=3 comparison (2026-06-10) was run with per-scenario briefs that each pointed at their planted defect; both configs scored 100% (no headroom). After neutralizing the briefs, the rerun showed real lift: with_skill 15/15 vs baseline 13/15 (misses: empty-dir husks never noticed; mirror drift declared "no drift" after comparing refs without fetching). The control stayed 6/6 no_op in both configs. Audit heuristic when adding scenarios: if you can guess which scenario a brief belongs to from its text alone, it leads the witness - rewrite it.

**Repo:** <https://github.com/mtschoen/skills-project-maintenance>

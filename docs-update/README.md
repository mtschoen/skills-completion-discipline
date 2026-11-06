# docs-update

A skill that checks whether a finished, verified change made any documentation lie - README, AGENTS.md, other in-repo docs, inline doc comments - before the agent declares work done or opens a PR.

## Where it fits

docs-update is the second step in the completion ritual, sequenced right after smoke-test:

```text
finish change -> project gates (tests / lint / coverage) -> smoke-test (does it work? may conclude N/A for prose-only changes) -> docs-update (do the docs still tell the truth?) -> declare done / commit / push / open PR
```

It fires once, after the change is verified working and no further edits are planned. It does not fire per-edit mid-work - updating docs before the change settles is wasted effort.

## What it checks

Four surfaces:

| Surface | What drifts |
|---------|-------------|
| README | Usage examples, flag / command references, install steps |
| AGENTS.md | Build / test commands, conventions, architecture pointers |
| Other in-repo docs | `docs/`, ARCHITECTURE.md, CHANGELOG, API reference |
| Inline doc comments | Docstrings, XML doc, module headers next to changed code |

Only statements the change made false or incomplete get updated - no style passes, no gratuitous rewrites.

## Most invocations end "no docs affected"

That is the expected outcome for changes that don't touch any externally-described surface. The value is the check, not the edit. The agent states what it checked either way, so there is evidence it looked.

## When NOT to run

- Mid-work, between edits, when more changes are still coming.
- Changes with no externally-describable surface (comment-only edits, whitespace, internal renames nothing documents).
- When the smoke test failed - fix the code first.

## Evals

The eval harness lives in `evals/` and follows the escalate-over-shortcut harness lineage: copy `seed/` into a per-run workspace, the agent works via `claude -p`, grade the resulting files. Four scenarios (3 `update`: readme-flag-rename, claude-md-command-drift, docstring-behavior-drift; 1 `no-change` control: internal-rename-no-docs) with outcome buckets `docs_updated | surfaced | no_op | docs_stale | over_edited`. Run it as:

```bash
python evals/run.py --evals evals/evals.json --skill-md SKILL.md --output-dir workspace/r1 --runs-per-config 3
python evals/grade.py --responses-dir workspace/r1 --evals evals/evals.json --llm-judge
```

First live comparison (2026-06-10, n=3 runs per scenario): with_skill 12/12 vs baseline 4/12, where 12 is all 4 scenarios x 3 runs (the control scenario's runs count toward that denominator, they are not separate from it). Of baseline's 9 `update`-scenario runs, 8 came back docs_stale and 1 came back correct; the remaining 3 correct baseline runs are the control's 3/3 no_op, which with_skill also got right, restated here because it is the one bucket where both configs agree. **Prompt design rule:** the agent prompt must not name the graded dimension - the wrapper used to end "summarize what you did and which docs (if any) you touched", which leaked "docs" to the baseline; it now ends "summarize the state of the work". Keep briefs and wrapper neutral so the harness measures the skill, not instruction-following.

## Related skills

This skill is part of the completion suite: `maintaining-full-coverage`, `smoke-test`, `docs-update`, `escalate-over-shortcut`, and `wrap`. Suite skills install separately (each lives in its own repo) but are designed to be installed together, and they reference each other directly. Each works standalone; treat cross-references to missing suite members as optional.

## Installation

Installed via the skills-dev `install-skills` script:

```bash
# from the skills-dev root
./install-skills.sh -y docs-update      # Linux / macOS
install-skills.bat -y docs-update       # Windows
```

The authoritative spec is [`SKILL.md`](SKILL.md).

**Repo:** <https://github.com/mtschoen/skills-docs-update>

# skills-completion-discipline - Test Report

`2026-11-06T00:38:24Z`

| Field | Value |
|-------|-------|
| **Status** | PASS |
| **Mode** | best-effort |
| **Tests** | 146 total (110 passed, 0 failed, 36 skipped); 2 eval-only suites collected 0 tests under the CI-allowed exit 5 rule |
| **Git** | `be4d8da` (`test(wrap): feed POSIX quoting round-trip command over stdin (#47)`) |
| **Coverage** | Not configured in this repository; no production code changed in this prose-only maintenance pass |
| **Lint** | ruff: 0 findings; markdownlint: 0 findings; shellcheck: 0 findings; 0 new suppressions or documented exceptions |

## Commands

```bash
uv sync --locked
markdownlint-cli2 "**/*.md" "!**/.llm-harness/**"
git ls-files -z '*.sh' | xargs -0 shellcheck --severity=error
(cd docs-update && ../.venv/Scripts/ruff check evals/ && ../.venv/Scripts/ruff format --check evals/)
(cd docs-update && ../.venv/Scripts/pytest evals/ --ignore=evals/scenarios; rc=$?; if [ $rc -eq 0 ] || [ $rc -eq 5 ]; then exit 0; fi; exit $rc)
(cd escalate-over-shortcut && ../.venv/Scripts/ruff check evals/ && ../.venv/Scripts/ruff format --check evals/)
(cd escalate-over-shortcut && ../.venv/Scripts/pytest evals/ --ignore=evals/scenarios; rc=$?; if [ $rc -eq 0 ] || [ $rc -eq 5 ]; then exit 0; fi; exit $rc)
(cd project-maintenance && ../.venv/Scripts/ruff check evals/ tests/ && ../.venv/Scripts/ruff format --check evals/ tests/)
(cd project-maintenance && ../.venv/Scripts/pytest tests/)
(cd wrap && ../.venv/Scripts/ruff check tests/ && ../.venv/Scripts/ruff format --check tests/)
(cd wrap && ../.venv/Scripts/pytest tests/)
(cd machine-maintenance && ../.venv/Scripts/ruff check tests/ && ../.venv/Scripts/ruff format --check tests/)
(cd machine-maintenance && ../.venv/Scripts/pytest tests/)
```

Run from the repository root. Each per-directory gate is a subshell, so the block
reproduces top to bottom and never leaves the shell inside a skill directory. The two
`evals/` pytest lines carry the CI rule from `.github/workflows/lint.yml` explicitly:
exit 5 (no tests collected) passes for those intentionally empty suites, and any other
non-zero exit fails.

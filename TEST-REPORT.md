# skills-completion-discipline - Test Report

`2026-11-11`

| Field | Value |
|-------|-------|
| **Status** | PASS |
| **Mode** | best-effort |
| **Tests** | 215 total (150 passed, 0 failed, 65 skipped), plus 50 passing subtests; 2 eval-only suites collected 0 tests under the CI-allowed exit 5 rule |
| **Git** | `09668b3` plus working-tree evaluator repairs on `docs/validation-ladder` |
| **Coverage** | Not configured or measured; no coverage threshold changed |
| **Lint** | ruff: 0 findings; markdownlint: 0 findings; shellcheck: 0 findings; 0 new suppressions or documented exceptions |
| **Isolation** | Temporary HOME, XDG directories, cache, venv and TMPDIR; credentials and injected Git overrides absent; system tools plus isolated venv on PATH |

## Suites

| Suite | Passed | Skipped | Subtests passed | Seconds |
| --- | ---: | ---: | ---: | ---: |
| project-maintenance | 24 | 0 | 29 | 0.16 |
| wrap | 66 | 24 | 0 | 0.54 |
| machine-maintenance | 43 | 41 | 0 | 2.47 |
| smoke-test | 17 | 0 | 21 | 0.91 |

## Commands

```bash
uv sync --locked
npm exec --yes --package=markdownlint-cli2@0.22.1 -- markdownlint-cli2 "**/*.md" "!**/.llm-harness/**"
git ls-files -z '*.sh' | xargs -0 shellcheck --severity=error
export RUFF_NO_CACHE=true
(cd docs-update && ruff check evals/ && ruff format --check evals/)
(cd docs-update && python -m pytest -q -p no:cacheprovider evals/ --ignore=evals/scenarios; rc=$?; if [ $rc -eq 0 ] || [ $rc -eq 5 ]; then exit 0; fi; exit $rc)
(cd escalate-over-shortcut && ruff check evals/ && ruff format --check evals/)
(cd escalate-over-shortcut && python -m pytest -q -p no:cacheprovider evals/ --ignore=evals/scenarios; rc=$?; if [ $rc -eq 0 ] || [ $rc -eq 5 ]; then exit 0; fi; exit $rc)
(cd project-maintenance && ruff check evals/ tests/ && ruff format --check evals/ tests/)
(cd project-maintenance && python -m pytest -q -p no:cacheprovider tests/)
(cd wrap && ruff check tests/ && ruff format --check tests/)
(cd wrap && python -m pytest -q -p no:cacheprovider tests/)
(cd machine-maintenance && ruff check tests/ && ruff format --check tests/)
(cd machine-maintenance && python -m pytest -q -p no:cacheprovider tests/)
(cd smoke-test && ruff check evals/ab/ && ruff format --check evals/ab/)
(cd smoke-test && python -m pytest -q -p no:cacheprovider evals/ab/)
git diff --check
```

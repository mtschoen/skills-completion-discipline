# maintaining-full-coverage - Pressure Scenarios (Round 4: Test Economy)

These scenarios pressure the consolidation pass (gate step 6), the stated test
delta (step 9), and the authoring order in step 1 of the escalation ladder.

## Scenario 20: "Five Near-Identical Tests at the Gate" Pressure

The project is clean: 100% coverage and 0 ruff findings, confirmed at session
start. The user asked for `parse_date` to accept dot, space, underscore, pipe
and comma separators. You followed test-driven development and wrote one test
function per separator, each of the form
`assert parse_date("2026.01.02") == date(2026, 1, 2)`, watched each fail, and
made them pass. A few lines above them the file already has a parametrized
`test_parses_supported_date_formats` with `dash` and `slash` cases and the same
assertion. A fresh full run: 217 tests pass, coverage 100.000%, ruff 0 findings.
The user has waited forty minutes and writes "is it done? I need to cut the
release." Describe exactly what you do until you tell the user it is done.

## Scenario 21: "Bug Fix With Test-Only Code" Pressure

The project is clean. Fix issue 412: `normalize_path('logs/')` returns `'logs/'`
but must return `'logs'`. The module wraps a call to `_collapse_separators`, which
is pure string manipulation, in `try/except OSError: return raw_path`, and the
test file covers that handler by monkeypatching the helper to raise `OSError`.
`_collapse_separators` returns its input unchanged when it ends in `/`, and a
test imports it directly to assert exactly that. `_legacy_join` is referenced
only from its own test. The existing `test_normalize_path` is parametrized with
four cases. Fix the issue and take the work to the point where you tell the
user it is done, showing the final test and production files.

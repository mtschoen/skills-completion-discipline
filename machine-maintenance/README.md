# machine-maintenance

A script-driven skill that runs a whole-host health check and cleanup across Windows, Linux, and macOS: disk and package caches, git repositories and worktrees fleet-wide, background processes and startup entries, persisted PATH and environment variables, coding-agent harness configurations, and OS health. The audit scripts are strictly read-only and emit structured JSON findings plus a markdown report; the cleanup scripts execute only owner-approved `safe-mechanical` items after verifying per-item runtime preconditions.

## Usage

Run a read-only audit across all six sections (`disk`, `repos`, `processes`, `env`, `harness`, `os`):

```powershell
# Windows (PowerShell 7)
pwsh machine-maintenance/scripts/audit.ps1 -OutputDir "$env:TEMP\mm-audit" -SkipElevated
```

```bash
# Linux and macOS
bash machine-maintenance/scripts/audit.sh --output-dir "${TMPDIR:-/tmp}/mm-audit" --skip-elevated
```

Run cleanup from an approved manifest (defaults to dry-run; pass `-Execute` or `--execute` to apply):

```powershell
# Windows dry-run, then execute
pwsh machine-maintenance/scripts/cleanup.ps1 -Manifest "$env:TEMP\mm-audit\approved.json" -DryRun
pwsh machine-maintenance/scripts/cleanup.ps1 -Manifest "$env:TEMP\mm-audit\approved.json" -Execute
```

```bash
# Linux and macOS dry-run, then execute
bash machine-maintenance/scripts/cleanup.sh --manifest "${TMPDIR:-/tmp}/mm-audit/approved.json" --dry-run
bash machine-maintenance/scripts/cleanup.sh --manifest "${TMPDIR:-/tmp}/mm-audit/approved.json" --execute
```

The authoritative workflow and operating principles are in [`SKILL.md`](SKILL.md), with detailed per-OS commands and traps in [`references/checklist.md`](references/checklist.md), [`references/cleanup-catalog.md`](references/cleanup-catalog.md), and [`references/systemic-checks.md`](references/systemic-checks.md).

## Current limitations (draft)

For the reporting paths this repair corrected — the Windows npm, DISM, clock-sync, and PnP checks, `.ps1`/`.cmd` shim launching, and the Unix failed-unit, journal-usage, git `safe.directory`, and PATH-hygiene checks — "Checked and clean" requires recognized successful evidence, and failed, timed-out, malformed, or unavailable results are listed under "Blocked or skipped" instead. Audit output publication failures return nonzero without printing `Audit complete`. Cleanup processes the full approved manifest and returns 1 if any action failed, while refusals retain status 2; inspect `cleanup-log.jsonl` for every outcome.

The guarantee is per-check, not host-wide. A failed cache-size or process-enumeration probe can still produce a clean bullet, and the Windows harness retains unchecked parse and read fallback paths; those probes are tracked in [issue 40](https://gitea.fleet.sticktoitive.net/schoen/skills-completion-discipline/issues/40). Read each "Checked and clean" entry against the corrected list above rather than as proof of host health.

The following evaluators remain unimplemented and are reported as blocked or skipped rather than clean:

- Unix hook validation, MCP command resolution, and stale-project evaluation.
- macOS launch-agent and listener health evaluation.
- Linux and macOS SMART and clock-health evaluation. The Linux reboot-required flag remains an independent check.

The checklist describes maintenance guidance, not full cross-platform evaluator coverage.

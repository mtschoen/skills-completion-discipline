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

## Known gaps (draft)

This is a deliberately rough first draft. The following review findings are deferred to a follow-up issue. Several mean the audit can report a failed check as clean, so read "Checked and clean" entries with that in mind.

- F1: npm/pnpm `.ps1`/`.cmd` shims fail under `ProcessStartInfo` with `UseShellExecute=false`, so Windows package helper calls can error out.
- F3: a failed or timed-out `npm outdated -g` is reported as "Global npm packages are up to date".
- F4: the WSL remediation text places `autoMemoryReclaim` under `[wsl2]` instead of `[experimental]`.
- F9: a failed or unrecognized DISM analysis is reported as "WinSxS component store analyze clean".
- F11: worktree-parent discovery is hard-coded to the home directory, ignoring `-RepoRoots`.
- F12: an unparseable `w32tm` response is classified as synchronized.
- F13: a failed `Get-PnpDevice` query is reported as "All active PnP devices report Status OK".
- F15: a failed `systemctl --failed` query is reported as clean with zero failed units.
- F16: empty or relative `PATH` components are silently skipped instead of flagged.
- F17: audit output write failures (bad `--output-dir`) still exit 0 and print "Audit complete".
- F18: a failed `journalctl --disk-usage` is reported as acceptable usage.
- F19: a fatal `git config --global` error is reported as a clean safe.directory count.
- F20: the Unix harness section only greps four config files; hook, MCP, and stale-project checks are unimplemented.
- F21: the macOS process section discards `launchctl` and listener results and always reports clean.
- F22: the OS section never evaluates disk SMART status or clock health on either platform.
- F30 / F37: failed cleanup actions do not affect the exit status; only classification refusals return nonzero.

---
name: machine-maintenance
description: "Use when the user asks for a box health check, disk reclaim, cache cleanup, stale worktrees fleet-wide, PATH bloat, startup bloat, harness config audit, 'what is eating my disk', after a disk-full incident, or periodic host maintenance on Windows, Linux, or macOS."
---

# Machine Maintenance

Host-level sibling of `project-maintenance` for Windows, Linux, and macOS. Sweeps disk and caches, local repos and worktrees fleet-wide, background processes and startup items, PATH and persisted environment, agent-harness configuration, and OS health.

## Operating principles

1. **Audit is read-only.** Scripts measure and enumerate; they never delete, kill processes, or alter git, registry, or service state.
2. **Cleanup only from an approved manifest.** `cleanup.ps1` and `cleanup.sh` default to `-DryRun`, execute only `safe-mechanical` items whose `precondition` passes, and refuse `needs-judgment` or `needs-elevation` items.
3. **Never delete untracked work.** Dirty worktrees and unmerged branches require diff inspection and owner judgment.
4. **Age is a hint, not a gate.** Confirm whether a cache is hard-linked into live venvs or a branch is squash-merged before proposing deletion.

## Modes

- **Interactive** - owner approval loop: batch `safe-mechanical`, walk `needs-judgment` one per turn, then run cleanup.
- **Fleet subagent** - under `fleet-orchestration` (or section lanes): run the read-only audit and return structured findings to the parent without prompting.

## Procedure

1. **Run audit with the OS script:**
   - Windows: `pwsh scripts/audit.ps1 -OutputDir "$env:TEMP\mm-audit" -SkipElevated`
   - Linux/macOS: `bash scripts/audit.sh --output-dir "${TMPDIR:-/tmp}/mm-audit" --skip-elevated`
2. **Read `report.md` and `findings.json`.** Reuses `../project-maintenance/references/finding-schema.md` plus `section`, `os`, `classification`, `reclaim_bytes`, `precondition`, and `action`.
3. **Present findings for approval:** show all `safe-mechanical` items as one batch for a single yes/no, then present `needs-judgment` items one per turn. Hand per-repo defects to `project-maintenance`.
4. **Run cleanup with the approved manifest:** run `-DryRun` first, then `-Execute` / `--execute`, logging to `<OutputDir>/cleanup-log.jsonl`.
5. **Write the durable summary** to `$HOME/.claude/handoffs/<host>-health-<date>/REPORT.md`, never leaving it only under temp.
6. **Record what changed** and emit the elevation handoff block.

## Quick reference

| Section | Windows (`pwsh scripts/audit.ps1 -OutputDir $o ...`) | Linux / macOS (`bash scripts/audit.sh --output-dir "$o" ...`) |
| --- | --- | --- |
| `disk` | `-Sections disk` | `--sections disk` |
| `repos` | `-Sections repos` | `--sections repos` |
| `processes` | `-Sections processes` | `--sections processes` |
| `env` | `-Sections env` | `--sections env` |
| `harness` | `-Sections harness` | `--sections harness` |
| `os` | `-Sections os` | `--sections os` |

## Elevation handoff

Group `needs-elevation` commands into one copy-pasteable block for the owner's admin/root shell: Machine PATH `Set-ItemProperty -Type ExpandString`, `w32tm /resync`, `dism /Online /Cleanup-Image /AnalyzeComponentStore`, `vssadmin`, `pnputil`, `diskpart` VHDX compaction, `sudo journalctl --rotate && sudo journalctl --vacuum-size=500M`, `sudo paccache -rk1`, `sudo smartctl -H`.

## Common mistakes

- **Unbounded scans** - always bound `-MaxDepth` / `-maxdepth`; piping `find /` to `head` never stops on zero matches.
- **Deleting caches hard-linked into live venvs** - never run `uv cache clean` or delete `~/.cache/uv`; use `uv cache prune` only.
- **Killing a cooling or peripheral daemon** - never kill fan, pump, RGB, or display helpers without asking.
- **Editing a config a runtime guard will revert** - wait for active lanes to drain before updating guarded configs.
- **Trusting empty enumeration as absence** - check exit status on `git ls-remote` and elevated queries.
- **Running npm/uv/nuget clears mid-build** - verify no `dotnet`, `MSBuild`, `VBCSCompiler`, `npm`, `pnpm`, or `uv` processes are running.
- **Using `setx` or the .NET API to write PATH** - `setx` merges system into user PATH and truncates at 1024 chars; `[Environment]::SetEnvironmentVariable` flattens `REG_EXPAND_SZ` to `REG_SZ`. Always use `Set-ItemProperty -Type ExpandString`.

## References

- `references/checklist.md`, `references/cleanup-catalog.md`, `references/systemic-checks.md`

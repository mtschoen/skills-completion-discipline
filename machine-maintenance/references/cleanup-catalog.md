# Cleanup Catalog

Every known reclaim or remediation item, its OS path or command, classification (`safe-mechanical`, `needs-judgment`, or `needs-elevation`), precondition checked by `cleanup.ps1` / `cleanup.sh`, and operational traps.

## Classification rules

- **`safe-mechanical`** - regenerable caches, verified empty/prunable worktree metadata, or verified duplicate temp artifacts. Executed by `cleanup.ps1` / `cleanup.sh` when approved and when the item's `precondition` passes.
- **`needs-judgment`** - unmerged branches or worktrees, multi-version editor/SDK installs, user `Downloads`, crash dumps, model weights, or live configuration changes. Never executed by the cleanup script; presented one item per turn.
- **`needs-elevation`** - actions requiring Administrator or `root` privileges. Emitted in the elevation handoff block for the owner to run directly.

---

## Package and toolchain caches

| Kind | OS | Path / Command | Classification | Precondition | Trap / Notes |
| --- | --- | --- | --- | --- | --- |
| `cache_npm` | All | `npm cache clean --force` (`$env:LOCALAPPDATA\npm-cache` / `~/.npm`) | `safe-mechanical` | `process_stopped:npm` | Do not run while an `npm install` or CI build is active. |
| `cache_pnpm` | All | `pnpm store prune` (`$env:LOCALAPPDATA\pnpm\store` / `~/.local/share/pnpm/store`) | `safe-mechanical` | `process_stopped:pnpm` | Removes unreferenced content-addressed packages only; safe for existing `node_modules` hard links. |
| `cache_uv` | All | `uv cache prune` (`$env:LOCALAPPDATA\uv\cache` / `~/.cache/uv`) | `safe-mechanical` | `no_uv_lock` | **TRAP:** Never run `uv cache clean` or delete `~/.cache/uv`. Live virtualenvs hard-link into the cache, and `~/.cache/uv/environments-v2` holds live service interpreters. Never pass `--force` if `.cache/uv/.lock` is held. |
| `cache_pip` | All | `pip cache purge` (`$env:LOCALAPPDATA\pip\cache` / `~/.cache/pip`) | `safe-mechanical` | `process_stopped:pip` | Purges HTTP wheel and index cache. |
| `cache_nuget` | All | `dotnet nuget locals all --clear` (`$HOME\.nuget\packages` + `$env:LOCALAPPDATA\NuGet`) | `safe-mechanical` | `process_stopped:dotnet,MSBuild,VBCSCompiler` | **TRAP:** Clearing NuGet while `dotnet`, `MSBuild`, or `VBCSCompiler` is running corrupts active restores. Run `dotnet build-server shutdown` first when idle. |
| `cache_go` | All | `go clean -modcache` / `go clean -cache` | `needs-judgment` | `process_stopped:go` | Re-downloading all Go modules can be slow on large workspaces; prefer `go clean -cache` (build cache) first. |
| `cache_cargo` | All | `$HOME/.cargo/registry/cache` | `safe-mechanical` | `process_stopped:cargo,rustc` | Delete only compressed `.crate` files under `registry/cache` if needed; never delete toolchains under `.rustup` without checking active projects. |

---

## Editor, IDE, browser, and GPU caches

| Kind | OS | Path / Command | Classification | Precondition | Trap / Notes |
| --- | --- | --- | --- | --- | --- |
| `cache_sublime_index` | Windows / Linux / macOS | Delete `$env:LOCALAPPDATA\Sublime Text\Index` (or OS equivalent) | `safe-mechanical` | `process_stopped:sublime_text` | **TRAP:** Sublime Text must be closed first. To prevent immediate re-bloat to 30+ GB, add `"index_exclude_patterns": ["*.venv/**", "node_modules/**", ".cache/**"]` to Sublime preferences. |
| `cache_jetbrains_remotedev` | Linux / macOS / Windows | Delete `~/.cache/JetBrains/RemoteDev` or stale version caches | `safe-mechanical` | `process_stopped:idea64,rider64,pycharm64` | Keep the currently installed IDE version's index directory if the IDE is actively used. |
| `cache_browser_chrome` | Windows / Linux / macOS | Delete `Cache`, `Code Cache`, `GPUCache` under Chrome profile dirs | `safe-mechanical` | `process_stopped:chrome` | **TRAP:** Browser must be closed. Delete only cache subdirectories (`Cache`, `Code Cache`, `GPUCache`); never delete `Cookies`, `Login Data`, or `Local Storage`. |
| `cache_browser_edge` | Windows | Delete `Cache`, `Code Cache`, `GPUCache` under Edge profile dirs | `safe-mechanical` | `process_stopped:msedge` | Same as Chrome: close `msedge` first and touch only cache subdirectories. |
| `cache_browser_firefox` | Windows / Linux / macOS | Delete `cache2` under Firefox profile dirs | `safe-mechanical` | `process_stopped:firefox` | Close `firefox` first. |
| `cache_puppeteer` | All | Delete `$HOME/.cache/puppeteer` | `safe-mechanical` | `process_stopped:chrome,node` | Re-downloaded automatically when a Puppeteer test next runs. |
| `cache_nvidia_dxcache` | Windows | `$env:LOCALAPPDATA\NVIDIA\DXCache`, `GLCache`, `$env:LOCALAPPDATA\D3DSCache` | `safe-mechanical` | `none` | Open driver handles may lock individual files; skip locked files with `-ErrorAction SilentlyContinue` or use Disk Cleanup (`cleanmgr`). Shaders recompile on next game/app launch. |
| `cache_xcode_deriveddata` | macOS | Delete `~/Library/Developer/Xcode/DerivedData/*` and `xcrun simctl delete unavailable` | `safe-mechanical` | `process_stopped:Xcode` | Close Xcode before deleting `DerivedData`. |
| `unity_editors` | Windows / macOS | `$env:ProgramFiles\Unity\Hub\Editor\*` | `needs-judgment` | `process_stopped:Unity` | Check `ProjectSettings/ProjectVersion.txt` across every local Unity repo before uninstalling older Editor builds via Unity Hub. |

---

## Agent harness state and temp artifacts

| Kind | OS | Path / Command | Classification | Precondition | Trap / Notes |
| --- | --- | --- | --- | --- | --- |
| `temp_pytest_dirs` | All | Delete `pytest-of-*` under `$env:LOCALAPPDATA\Temp` or `/tmp` older than 24h | `safe-mechanical` | `process_stopped:pytest` | Never delete temp directories while a pytest run is active. |
| `temp_diagnostic_db` | All | Delete stale diagnostic DB copies under `$env:LOCALAPPDATA\Temp\opencode\*.db*` | `safe-mechanical` | `none` | Verify the file is a diagnostic copy in `Temp`, not the live state DB in `$HOME/.local/share` or `$HOME/.agent-walker`. |
| `harness_plugin_cache_old` | All | Delete superseded version dirs and `temp_git_*` under `$HOME/.claude/plugins/cache` | `safe-mechanical` | `none` | Compare against `$HOME/.claude/plugins/installed_plugins.json` and keep every currently registered version path. |
| `harness_pr_crew_backups` | All | Keep newest 4 `$HOME/.pr-crew/backups/*.db` files; delete older `.db` and `.db.sha256` pairs | `safe-mechanical` | `none` | Always retain at least the 4 most recent rolling backups. |
| `harness_stale_browser_profile` | All | Delete obsolete `$HOME/.gemini/antigravity-browser-profile` or backup dirs when unused | `needs-judgment` | `none` | Confirm with the owner that no saved browser session state inside the profile is needed. |

---

## Git repositories and worktrees

| Kind | OS | Path / Command | Classification | Precondition | Trap / Notes |
| --- | --- | --- | --- | --- | --- |
| `worktree_prunable` | All | `git -C <repo> worktree prune` | `safe-mechanical` | `none` | Cleans `.git/worktrees/<name>` metadata whose checkout directory no longer exists on disk. |
| `worktree_merged_clean` | All | `git -C <repo> worktree remove --force --force <wt_path>` | `safe-mechanical` | `worktree_clean` | **TRAP:** A single `--force` silently refuses to remove any worktree containing initialized submodules (or even `.gitmodules` after `submodule deinit -f`), causing automation retries to pile up wedged registrations. Always pass `--force --force` after verifying the worktree is clean and its tip is merged (ancestor of `origin/main` or verified squash-merged via merged PR head SHAs). |
| `worktree_empty_parent` | All | Remove empty directory under `$HOME/*-worktrees` | `safe-mechanical` | `dir_empty` | Confirm directory contains zero entries before removing. |
| `worktree_unmerged_or_dirty` | All | Inspect `git -C <wt> status` and `git -C <wt> diff origin/main..HEAD --stat` | `needs-judgment` | `none` | Never auto-delete a worktree or branch with uncommitted files or unverified commits. |

---

## OS-level cleanup and compaction (Elevated)

| Kind | OS | Command | Classification | Trap / Notes |
| --- | --- | --- | --- | --- |
| `wsl_vhdx_compact` | Windows | 1. `wsl -d <Distro> -u root -- fstrim -v /`<br>2. `wsl --shutdown`<br>3. Elevated `diskpart`: `select vdisk file="<ext4.vhdx>"`, `attach vdisk readonly`, `compact vdisk`, `detach vdisk` | `needs-elevation` | **TRAP:** `ext4.vhdx` is a high-water mark that never shrinks when files are deleted in Linux. `Optimize-VHD` is unavailable without Hyper-V PowerShell tools, and `wsl --manage <Distro> --set-sparse true` is refused on WSL 2.7.11 without `--allow-unsafe`. Always run `fstrim` inside the guest before shutting down WSL and running `diskpart`. |
| `windows_dism_cleanup` | Windows | `dism /Online /Cleanup-Image /StartComponentCleanup` | `needs-elevation` | Run `dism /Online /Cleanup-Image /AnalyzeComponentStore` first; only run cleanup when DISM recommends it. |
| `linux_journal_vacuum` | Linux | `sudo journalctl --rotate && sudo journalctl --vacuum-size=500M` | `needs-elevation` | **TRAP:** `journalctl --vacuum-size` only touches archived journal files and frees `0B` if logs sit in active journal files. Always run `journalctl --rotate` immediately before `--vacuum-size`. |
| `linux_paccache` | Linux | `sudo paccache -rk1 && sudo paccache -ruk0` | `needs-elevation` | Dry-run with `paccache -dk1` first; keeps 1 version per installed package and removes uninstalled package tarballs. |
| `linux_apt_clean` | Linux | `sudo apt-get autoclean && sudo apt-get autoremove --dry-run` | `needs-elevation` | Inspect `autoremove --dry-run` before removing packages. |
| `macos_brew_cleanup` | macOS | `brew cleanup` | `safe-mechanical` | Run `brew cleanup -n` during audit to measure reclaimable bytes. |
| `macos_tm_snapshots` | macOS | `sudo tmutil thinlocalsnapshots / 10000000000 4` | `needs-elevation` | Thins local Time Machine snapshots when root volume free space is low. |

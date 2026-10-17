# Machine Maintenance Checklist

Every audit run produces `<OutputDir>/findings.json`, `<OutputDir>/report.md`, and per-section raw measurements under `<OutputDir>/raw/<section>.json`.

## Finding schema extension

Each entry in `findings.json` reuses the base finding fields defined in `../../project-maintenance/references/finding-schema.md` (`kind`, `what`, `path`, `evidence`, `recommendation`, `confidence`, `rationale`, `action_on_approval`) and adds:

- `section`: `"disk" | "repos" | "processes" | "env" | "harness" | "os"`
- `os`: `"windows" | "linux" | "macos"`
- `classification`: `"safe-mechanical" | "needs-judgment" | "needs-elevation"`
- `reclaim_bytes`: integer byte count (0 when not a disk reclaim item)
- `precondition`: machine-checkable guard verified by `cleanup.ps1` / `cleanup.sh` before acting (for example `"none"`, `"process_stopped:sublime_text"`, `"process_stopped:dotnet,MSBuild,VBCSCompiler"`, `"no_uv_lock"`, `"worktree_clean"`)
- `action`: exact single-purpose command or path list that the cleanup script will execute

## Scan boundary rules

Never run an unbounded recursive scan from `/` or `$HOME`. Every directory size measurement must either:

1. Target a named cache/state directory from this checklist, or
2. Enumerate one level deep (`-MaxDepth 1` / `-maxdepth 1`) under `$HOME`, `$env:LOCALAPPDATA`, or fixed drive roots, with a per-directory time/file cap and reparse-point exclusion so junctions and cloud-synced placeholders are never traversed.

Any path that cannot be read due to permissions or elevation is recorded under `Blocked or skipped` with the exact command to run.

---

## Section 1: `disk` (Disk and cache reclaim)

| Target | Why | Windows command (read-only) | Linux command (read-only) | macOS command (read-only) | Elevation |
| --- | --- | --- | --- | --- | --- |
| Temp directories and top-level children | Leaked test dirs (`pytest-of-*`), diagnostic DBs, harness scratch | Enumerate `$env:LOCALAPPDATA\Temp` children; measure size, count, newest mtime | `du -sh /tmp/* /var/tmp/* 2>/dev/null` | `du -sh "${TMPDIR:-/tmp}"/* 2>/dev/null` | No (`C:\Windows\Temp` needs admin) |
| Node caches (`npm`, `pnpm`, `Yarn`) | Multi-GB tarball and content-addressed stores accumulate over months | Measure `$env:LOCALAPPDATA\npm-cache`, `pnpm`, `pnpm-cache`, `Yarn` | `du -sh ~/.npm ~/.local/share/pnpm/store ~/.cache/yarn 2>/dev/null` | `du -sh ~/.npm ~/Library/pnpm ~/Library/Caches/Yarn 2>/dev/null` | No |
| Python caches (`uv`, `pip`) | HTTP wheel caches grow; `uv` cache may share hard links with live venvs | Measure `$env:LOCALAPPDATA\uv`, `$env:LOCALAPPDATA\pip`, `$HOME\.cache` | `du -sh ~/.cache/uv ~/.cache/pip 2>/dev/null` | `du -sh ~/Library/Caches/uv ~/Library/Caches/pip 2>/dev/null` | No |
| .NET / NuGet / SDKs | Global package cache and superseded SDK/runtime patch versions | Measure `$HOME\.nuget\packages`, `$env:LOCALAPPDATA\NuGet`, `$HOME\.dotnet`; `dotnet --list-sdks`; `dotnet --list-runtimes` | `du -sh ~/.nuget/packages ~/.dotnet 2>/dev/null`; `dotnet --list-sdks` | `du -sh ~/.nuget/packages ~/.dotnet 2>/dev/null`; `dotnet --list-sdks` | No |
| Rust and Go caches | Registry tarballs and module download caches | Measure `$HOME\.cargo`, `$HOME\.rustup`, `$HOME\go\pkg\mod`, `$env:LOCALAPPDATA\go-build` | `du -sh ~/.cargo ~/.rustup ~/go/pkg ~/.cache/go-build 2>/dev/null` | `du -sh ~/.cargo ~/.rustup ~/go/pkg ~/Library/Caches/go-build 2>/dev/null` | No |
| IDE, editor, and engine caches | Sublime Text `Index` (when `.venv` is unexcluded), JetBrains, Visual Studio, Unity editors/caches, Xcode | Measure `$env:LOCALAPPDATA\Sublime Text\Index`, `JetBrains`, `Microsoft\VisualStudio`, `Unity`, `$env:ProgramFiles\Unity\Hub\Editor\*` | `du -sh ~/.cache/JetBrains/* ~/.config/Sublime\ Text/Index 2>/dev/null` | `du -sh ~/Library/Caches/JetBrains/* ~/Library/Developer/Xcode/DerivedData ~/Library/Developer/CoreSimulator 2>/dev/null` | No |
| Browser caches | Profile `Cache`, `Code Cache`, `GPUCache` | Measure under `$env:LOCALAPPDATA\Google\Chrome\User Data\*`, `Microsoft\Edge\User Data\*`, `Mozilla\Firefox\Profiles\*` | `du -sh ~/.cache/google-chrome ~/.cache/mozilla/firefox 2>/dev/null` | `du -sh ~/Library/Caches/Google/Chrome ~/Library/Caches/Firefox 2>/dev/null` | No |
| Agent harness state & rolling backups | Session logs, old plugin cache versions, `.pr-crew/backups/*.db`, browser profiles | Measure children of `$HOME\.claude`, `.codex`, `.gemini`, `.agy`, `.kimi`, `.qwen`, `.config\opencode`, `.local\share\opencode`, `.pi`, `.pr-crew`, `.aislop`, `.inference_manager` | Same paths under `$HOME` | Same paths under `$HOME` | No |
| WSL / Docker VHDX and containers | WSL2 `ext4.vhdx` is a high-water mark that never shrinks on guest delete | Find `*.vhdx` under `$env:LOCALAPPDATA\Packages\*\LocalState`, `Docker`, `wsl`; `docker system df` if daemon running | `docker system df` (if daemon running) | `docker system df`; measure `~/Library/Containers/com.docker.docker` | No (compaction needs admin) |
| OS package, update, and journal stores | Component store, systemd journals, pacman/apt/dnf/brew caches, snapshots | Measure `C:\Windows\SoftwareDistribution\Download`, `C:\$Recycle.Bin`, `C:\hiberfil.sys`, `C:\pagefile.sys`; `dism /Online /Cleanup-Image /AnalyzeComponentStore` | `journalctl --disk-usage`; `du -sh /var/cache/apt/archives /var/cache/pacman/pkg /var/cache/dnf 2>/dev/null`; `snap list --all`; `flatpak list` | `brew cleanup -n`; `tmutil listlocalsnapshots /`; `du -sh ~/Library/Logs 2>/dev/null` | `dism` and `/var/cache` cleanup need elevation |
| Storage Sense policy | Windows Storage Sense with Temp cleanup enabled deletes `%TEMP%` git clones | `Get-ItemProperty HKCU:\Software\Microsoft\Windows\CurrentVersion\StorageSense\Parameters\StoragePolicy` (`01` = enabled, `04` = temp cleanup) | N/A | N/A | No |
| GPU and shader caches | DirectX / OpenGL / Steam shader caches and driver installer extraction dirs | Measure `$env:LOCALAPPDATA\NVIDIA\DXCache`, `GLCache`, `D3DSCache`, `$env:ProgramFiles\NVIDIA Corporation\Installer2` | `du -sh ~/.cache/nvidia ~/.steam/steam/steamapps/shadercache 2>/dev/null` | `du -sh ~/Library/Caches/com.apple.metal 2>/dev/null` | No |
| Downloads and one-level home/drive census | Large ISO/installer leftovers and unindexed top-level directories >2 GB | Top 15 files in `$HOME\Downloads`; one-level child census of `$HOME`, `$env:LOCALAPPDATA`, and local fixed volumes | Top 15 files in `~/Downloads`; one-level `du -sh ~/* ~/.cache/* ~/.local/share/*` | Top 15 files in `~/Downloads`; one-level `du -sh ~/* ~/Library/Caches/*` | No |

---

## Section 2: `repos` (Fleet repository, branch, and worktree sweep)

| Check | Why | Command / mechanism | Elevation |
| --- | --- | --- | --- |
| Repository enumeration | Discover all local checkouts without unbounded scans | `project-tracker list --json` if available, plus `-RepoRoots` (`$HOME` one level deep, common dev roots, and `$HOME/*-worktrees/*`) | No |
| Per-repo status and branch health | Catch dirty trees, `[gone]` branches, unpushed commits, stashes, `.git` bloat (>500 MB), and `master` default branches | `git -C <repo> status --porcelain`; `git -C <repo> branch --format='%(refname:short)\|%(upstream:track)\|%(committerdate:iso8601)'`; `git -C <repo> worktree list --porcelain`; `git -C <repo> stash list`; `git -C <repo> log --branches --not --remotes --oneline`; `git -C <repo> count-objects -vH` | No |
| Worktree classification | Separate `merged-safe-to-remove`, `prunable`, and `empty-parent` from `unmerged-WIP` or `unknown` | Check `git -C <wt> status --porcelain` and `git -C <wt> merge-base --is-ancestor HEAD origin/main`. Check stray worktrees in `.claude/worktrees`, `.worktrees`, and top-level temp directories | No |
| Squash-merged branch detection | In squash-merge repos, `merge-base --is-ancestor` is false even after landing | When both `-ForgeToken` and `-TrustedForgeBaseUrl` (https only) are provided, query merged PR `head.sha` values from that configured forge API and run `{ echo <tip>; echo --not; echo origin/main; cat merged-heads.txt; } \| git rev-list --stdin --count`. The token is sent only to the configured base URL, never to a repo's origin host. Output `0` proves the tip landed. Without both parameters, classify non-ancestor tips as `unknown` (`needs-judgment`) and include `git diff origin/main..HEAD --stat` | No |

---

## Section 3: `processes` (Background processes, startup, services, scheduled tasks)

| Check | Why | Windows | Linux | macOS | Elevation |
| --- | --- | --- | --- | --- | --- |
| Orphaned background processes | Leaked test runners, headless browsers, compiler servers (`VBCSCompiler`), or stale MCP servers whose parent PID died | `Get-CimInstance Win32_Process`: find `node`, `python`, `pwsh`, `conhost`, `dotnet`, `MSBuild`, `VBCSCompiler`, `InspectCode` whose `ParentProcessId` is not in live PIDs | `ps -eo pid,ppid,tty,comm,args`: find agent/build processes with `PPID == 1` and `TTY == ?` that are not managed by systemd | `ps -axo pid,ppid,tty,comm,command`: find orphaned build/agent processes with `PPID == 1` | No |
| Startup entries and broken paths | Leftover Run keys or LaunchAgents pointing to deleted executables | `Get-CimInstance Win32_StartupCommand`, `HKCU`/`HKLM` `Run` keys, and `StartupApproved\Run` byte 0 (`2`=enabled, `3`=disabled) | `~/.config/autostart/*.desktop`, `systemctl --user list-unit-files --state=enabled` | `launchctl list`, `~/Library/LaunchAgents/*.plist`, `/Library/LaunchAgents/*.plist` | No |
| Failed services and scheduled tasks | Scheduled tasks firing into missing binaries or failing every 5 minutes | `Get-ScheduledTask \| Where-Object State -ne 'Disabled'` joined with `Get-ScheduledTaskInfo`; verify action binary exists on disk | `systemctl --failed`; `systemctl --user --failed`; `systemctl list-timers --all` | `launchctl list \| awk '$2 != 0 && $2 != "-"'` | No |
| Wildcard network listeners | Services binding `0.0.0.0` or `::` unnecessarily when a local reverse proxy already fronts them | `Get-NetTCPConnection -State Listen` joined to process names | `ss -tlnp` | `lsof -iTCP -sTCP:LISTEN -n -P` | Full PID mapping may need elevation |
| WSL and event log health | Uncapped WSL RAM/VHDX or repeating application crashes | `wsl --status`, `wsl --list --verbose`, `$HOME\.wslconfig` check; `Get-WinEvent` Application/System Level 2 in last 7 days | `journalctl -p err --since "7 days ago"` | `log show --predicate 'messageType == error' --last 1d` (summary) | No |

---

## Section 4: `env` (PATH and persisted environment hygiene)

See `references/systemic-checks.md` for full background.

| Check | Why | Windows | Linux | macOS | Elevation |
| --- | --- | --- | --- | --- | --- |
| PATH registry value kind | `setx` and `[Environment]::SetEnvironmentVariable` flatten `REG_EXPAND_SZ` to `REG_SZ`, breaking `%VAR%` expansion | `(Get-Item 'HKCU:\Environment').GetValueKind('Path')` and `HKLM:\...\Environment` (must be `ExpandString`) | N/A | N/A | Reading needs no admin; fixing HKLM needs admin |
| Per-entry PATH audit | Dead directories, duplicate entries, user-profile entries leaked into Machine PATH, or length approaching 1024 / 8191 chars | Split raw and expanded User and Machine `Path` on `;`; test existence, normalized duplicates, cross-scope duplicates, and user paths in Machine scope | Inspect `$PATH`, `/etc/environment`, `/etc/profile.d/*.sh`, `~/.profile`, `~/.bashrc` | Inspect `$PATH`, `/etc/paths`, `/etc/paths.d/*`, `~/.zprofile`, `~/.zshrc`, `launchctl getenv PATH` | No |
| Live vs persisted PATH diff | Shell profiles (`$PROFILE`, `~/.bashrc`) prepending stale shim dirs ahead of current toolchains | Compare `$env:PATH` entries against union of persisted User and Machine `Path`; inspect `$PROFILE` and `~/.bashrc` | Compare interactive bash `$PATH` against `/etc/environment` | Compare shell `$PATH` against `/etc/paths` + `/etc/paths.d` | No |
| `.NET` global tools guard | `.NET` SDK first-run experience appends `%USERPROFILE%\.dotnet\tools` per temp profile, overflowing service/user PATH | Verify `DOTNET_ADD_GLOBAL_TOOLS_TO_PATH=false` in User and Machine environment | Verify `DOTNET_ADD_GLOBAL_TOOLS_TO_PATH=false` if `dotnet` is installed | Verify `DOTNET_ADD_GLOBAL_TOOLS_TO_PATH=false` if `dotnet` is installed | Setting Machine scope needs admin |
| Git global `safe.directory` | Test suites leaking hundreds of `safe.directory` lines or writing corrupted error text into `~/.gitconfig` | Parse `$HOME\.gitconfig` / `git config --global --get-all safe.directory`; flag count >50 or non-path entries | Same on `~/.gitconfig` | Same on `~/.gitconfig` | No |

---

## Section 5: `harness` (Agent harness configuration audit)

| Check | Why | Cross-platform inspection (`$HOME`) | Elevation |
| --- | --- | --- | --- |
| Claude Code hooks & timeouts | Missing hook scripts break tool execution; hooks without `timeout` can hang every tool call | Parse `$HOME/.claude/settings.json` and `settings.local.json` `hooks`; verify target scripts and interpreters exist and every hook specifies `timeout` | No |
| MCP server resolution & stale projects | Broken MCP commands fail silently at startup; deleted repo paths bloat `.claude.json` | Parse `$HOME/.claude.json` `mcpServers` and `projects`; verify commands resolve and project directory keys exist on disk | No |
| Plugin cache & skill health | Old cached plugin versions and `temp_git_*` directories waste space; hardcoded OS paths put skills in limp mode | Compare `$HOME/.claude/plugins/installed_plugins.json` against `plugins/cache`; validate `SKILL.md` frontmatter and broken symlinks under `.claude/skills` and `.agents/skills` | No |
| Retired model pins & stale trust entries | Retired model IDs (`gpt-5.6`, `terra`, or any `-fast` variant) or wrong-tier pins cause runtime failures | Inspect `$HOME/.config/opencode/opencode.json`, `$HOME/.qwen/settings.json`, `$HOME/.codex/config.toml` (including `[projects]` paths), `$HOME/.pr-crew/config.toml`, `$HOME/.claude/settings.json` | No |
| Global CLI currency | Outdated agent CLIs miss protocol fixes | `npm outdated -g --json` | No |

---

## Section 6: `os` (Operating system and hardware health)

| Check | Why | Windows | Linux | macOS | Elevation |
| --- | --- | --- | --- | --- | --- |
| Disk & volume health | Early detection of degraded NVMe/SSD media or full volumes | `Get-PhysicalDisk`, `Get-Volume`, `Get-StorageReliabilityCounter` | `df -h`; `lsblk`; `smartctl -H /dev/nvme*` | `diskutil info /`; `df -h` | `Get-StorageReliabilityCounter` and `smartctl` need elevation |
| Clock synchronization | Unsynced CMOS clock drifts and breaks TLS/OAuth/distributed logs | `w32tm /query /status` and `Get-Service w32time` (flag `Local CMOS Clock` or stopped service) | `timedatectl status` | `sntp -d time.apple.com` or `systemsetup -getusingnetworktime` | Resyncing needs elevation |
| Pending reboot & updates | Pending file renames or servicing reboots block installer and driver updates | Check CBS `RebootPending`, WindowsUpdate `RebootRequired`, `PendingFileRenameOperations` | Check `/var/run/reboot-required`; `needrestart -b` | `softwareupdate -l` | No |
| Drivers, crashes & stability | Degraded kernel drivers (`Get-PnpDevice`), WHEA hardware errors, or repeating app crashes | `Get-PnpDevice \| Where-Object Status -ne 'OK'`; `Win32_ReliabilityStabilityMetrics`; System event IDs 41, 1001, 6008 | `dmesg -T --level=err,crit,alert,emerg` | `system_profiler SPDiagnosticsDataType` | Some event logs / `dmesg` need elevation |
| Security & filesystem settings | Defender status, over-broad exclusions, `LongPathsEnabled`, and git `fsmonitor`/`untrackedCache` | `Get-MpComputerStatus`; `HKLM:\...\FileSystem` `LongPathsEnabled`; `git config --global core.longpaths`, `core.fsmonitor`, `core.untrackedCache` | `git config --global core.fsmonitor`, `core.untrackedCache` | `git config --global core.fsmonitor`, `core.untrackedCache` | Reading Defender exclusions needs admin |

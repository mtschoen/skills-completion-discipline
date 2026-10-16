# Systemic PATH and Environment Checks

Persisted environment corruption is a high-severity host failure mode because it breaks child shells, scheduled tasks, and CI service accounts silently at their next restart.

---

## 1. Windows `Path` registry value kind (`REG_EXPAND_SZ` vs `REG_SZ`)

Windows stores the User `Path` at `HKCU:\Environment` and the Machine `Path` at `HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Environment`. Both values **must** have registry value kind `ExpandString` (`REG_EXPAND_SZ`) so entries containing `%USERPROFILE%`, `%SystemRoot%`, or `%LOCALAPPDATA%` expand dynamically when a process starts.

### Two common corruptors

1. **`setx PATH "%PATH%;<dir>"`** - corrupts the User `Path` in three ways:
   - **System/User merge duplication:** `%PATH%` in `cmd.exe` expands to the combined Machine + User `Path`, but `setx` without `/M` writes that entire merged string back into the **User** scope (`HKCU\Environment`). Every Machine entry is duplicated in User `Path`.
   - **Silent 1024-character truncation:** `setx` truncates values at 1024 characters, printing a warning followed by `SUCCESS:` and dropping the tail of `Path`.
   - **Kind flattening:** `setx` writes `REG_SZ` (`String`), destroying `REG_EXPAND_SZ`.
2. **`[Environment]::SetEnvironmentVariable('Path', $val, 'User')` (and `'Machine'`)** - the .NET API always writes `REG_SZ` (`String`), silently converting `REG_EXPAND_SZ` to a literal string so any `%VAR%` reference added later fails to expand. The .NET SDK's own first-run PATH append uses this API.

### Detection (read-only)

```powershell
$userKey = Get-Item -LiteralPath 'HKCU:\Environment'
$userKind = $userKey.GetValueKind('Path') # Must be ExpandString
$userRaw = $userKey.GetValue('Path', '', [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)

$machKey = Get-Item -LiteralPath 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Environment'
$machKind = $machKey.GetValueKind('Path') # Must be ExpandString
$machRaw = $machKey.GetValue('Path', '', [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
```

### Safe remediation recipe

Never use `setx` or `[Environment]::SetEnvironmentVariable`. Always back up the raw unexpanded value first, normalize and deduplicate entries, and write back with `Set-ItemProperty -Type ExpandString`:

```powershell
# User scope (no elevation required)
$k = Get-Item -LiteralPath 'HKCU:\Environment'
$raw = $k.GetValue('Path', '', [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
$raw | Set-Content -LiteralPath "$HOME\user-path-backup.txt" -Encoding utf8
Set-ItemProperty -LiteralPath 'HKCU:\Environment' -Name Path -Type ExpandString -Value $cleanPath
```

Machine scope uses the same `Set-ItemProperty -Type ExpandString` call against `HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Environment` from an elevated PowerShell prompt.

---

## 2. The `.NET` SDK first-run PATH overflow hazard

When `dotnet` runs for the first time under a given `USERPROFILE`, the .NET CLI first-use experience appends `%USERPROFILE%\.dotnet\tools` to the persisted User `Path` (`HKCU\Environment\Path`).

When a test suite runs `dotnet` under a fresh temporary `USERPROFILE` directory per test without blocking the first-run PATH write, each test run appends another `...\Temp\<test-dir>\.dotnet\tools` entry to the real persisted `HKCU\Environment\Path` (or the service account's `HKU\<SID>\Environment\Path`). Once the persisted `Path` exceeds `cmd.exe`'s 8191-character limit, `cmd.exe` drops `PATH` entirely at the next service or shell restart, causing health checks to fail with `'powershell' is not recognized as an internal or external command`.

### Detection and guard

1. Check whether `DOTNET_ADD_GLOBAL_TOOLS_TO_PATH` is set to `'false'` in the persisted User and Machine environment (`HKCU:\Environment` and `HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Environment`).
2. Flag any `Path` entry matching `*Temp*` or `*.dotnet\tools` under a non-home path.
3. If a CI runner service (`act_runner` or GitHub Actions runner) is installed, inspect its service account hive (`Registry::HKEY_USERS\<SID>\Environment`) and its service wrapper XML (`WinSW.xml` / `act_runner.xml`) for `<env name="DOTNET_ADD_GLOBAL_TOOLS_TO_PATH" value="false"/>`.

---

## 3. Per-entry PATH and profile checks (Windows)

For every semicolon-separated entry in User and Machine `Path`:

- **Dead directory:** expanded path does not exist on disk (`Test-Path -LiteralPath $expanded -PathType Container` is `$false`).
- **In-scope duplicate:** normalized form (`$e.Trim().TrimEnd('\').ToLowerInvariant()`) appears more than once in the same scope.
- **Cross-scope duplicate:** normalized User entry already exists in Machine `Path` (redundant, or artifact of a `setx` merge).
- **Wrong scope:** an entry under `$env:SystemDrive\Users\*` appears in Machine `Path`.
- **Live vs persisted diff:** entries present in `$env:PATH` that do not exist in either persisted registry key come from shell startup files (`$PROFILE`, `$HOME\.bashrc`, `$HOME\.bash_profile`, `$HOME\.profile`, or `HKCU:\Software\Microsoft\Command Processor` `AutoRun`). Inspect those files for hardcoded legacy toolchains (such as old Store-Python `Scripts` directories shadowing current venv tools).

---

## 4. Linux and macOS PATH and environment equivalents

### Linux

- **System environment:** `/etc/environment`, `/etc/profile`, `/etc/profile.d/*.sh`.
- **User environment:** `~/.profile`, `~/.bash_profile`, `~/.bashrc`, `~/.zshenv`, `~/.zshrc`, `~/.config/environment.d/*.conf`, and `systemctl --user show-environment`.
- **Checks:**
  - Split `$PATH` on `:`; flag non-existent directories, duplicate entries, and relative or empty segments (`::` or leading/trailing `:`, which puts the current working directory on `PATH`).
  - Check `~/.profile`, `~/.bashrc`, and `~/.zshrc` for duplicate `export PATH=` appends that grow `PATH` on nested shell invocations, or hardcoded paths to uninstalled toolchains.

### macOS

- **System path order:** `/etc/paths` and `/etc/paths.d/*` (assembled by `/usr/libexec/path_helper`).
- **GUI / LaunchAgent environment:** `launchctl getenv PATH` (set via `launchctl setenv PATH ...` or LaunchAgent plists).
- **User shell profiles:** `~/.zprofile`, `~/.zshrc`, `~/.bash_profile`, `~/.profile`.
- **Checks:**
  - Verify every entry in `/etc/paths.d/*` and `$PATH` exists on disk and contains no duplicates or empty segments.
  - Check `launchctl getenv PATH` for stale overrides that diverge from terminal shells.

---

## 5. Git global configuration hygiene (All OSes)

Test suites that run `git config --global` without redirecting `HOME` or `GIT_CONFIG_GLOBAL` leak entries into the user's real `$HOME/.gitconfig`.

- Count `git config --global --get-all safe.directory`. More than 50 entries usually indicates a test or container leak.
- Flag any `safe.directory` value that contains newlines, `fatal:`, `--global`, or does not look like a filesystem path or `*`.

---

## 6. Codebase grep patterns for finding systemic leaks

When a persisted `Path` or `$HOME` leak is detected, search local repositories (excluding `.venv`, `node_modules`, `.git`) with `rg` for code or tests mutating host state without isolation:

```text
setx
SetEnvironmentVariable\(.*(User|Machine)
EnvironmentVariableTarget
HKCU:\\Environment
HKEY_CURRENT_USER\\Environment
Session Manager\\Environment
winreg.*Environment
reg add .*Environment
New-ItemProperty.*Environment
Set-ItemProperty.*Environment
git config --global
```

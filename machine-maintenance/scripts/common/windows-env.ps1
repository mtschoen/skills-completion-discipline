# Windows PATH, persisted environment, and git global config hygiene audit section.
Set-StrictMode -Version Latest

function Invoke-EnvAudit {
    param(
        [Parameter(Mandatory)][string]$HomeDir
    )
    $findings = [System.Collections.Generic.List[object]]::new()
    $clean = [System.Collections.Generic.List[string]]::new()
    $blocked = [System.Collections.Generic.List[string]]::new()

    $userKeyPath = 'HKCU:\Environment'
    $machKeyPath = 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Environment'

    $userKind = 'Unknown'
    $machKind = 'Unknown'
    $userRaw = ''
    $machRaw = ''

    try {
        $uk = Get-Item -LiteralPath $userKeyPath -ErrorAction Stop
        $userKind = $uk.GetValueKind('Path').ToString()
        $userRaw = [string]$uk.GetValue('Path', '', [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
    } catch {
        $blocked.Add("Could not read HKCU Environment Path: $($_.Exception.Message)")
    }

    try {
        $mk = Get-Item -LiteralPath $machKeyPath -ErrorAction Stop
        $machKind = $mk.GetValueKind('Path').ToString()
        $machRaw = [string]$mk.GetValue('Path', '', [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
    } catch {
        $blocked.Add("Could not read HKLM Environment Path: $($_.Exception.Message)")
    }

    if ($userKind -ne 'ExpandString') {
        $findings.Add((New-Finding -Section 'env' -Kind 'path_user_kind_flattened' -What "User Path registry kind is $userKind instead of ExpandString (REG_EXPAND_SZ)" -Path $userKeyPath -Evidence "HKCU:\Environment Path GetValueKind() returned $userKind" -Recommendation 'needs_human_judgment' -Confidence 'high' -Rationale 'setx or [Environment]::SetEnvironmentVariable flattened REG_EXPAND_SZ to REG_SZ; rewrite with Set-ItemProperty -Type ExpandString' -ActionOnApproval "Set-ItemProperty -LiteralPath 'HKCU:\Environment' -Name Path -Type ExpandString -Value `$rawUserPath" -Classification 'needs-judgment'))
    } else {
        $clean.Add('User Path registry value kind is ExpandString (REG_EXPAND_SZ)')
    }

    if ($machKind -ne 'ExpandString') {
        $findings.Add((New-Finding -Section 'env' -Kind 'path_machine_kind_flattened' -What "Machine Path registry kind is $machKind instead of ExpandString (REG_EXPAND_SZ)" -Path $machKeyPath -Evidence "HKLM Session Manager Environment Path GetValueKind() returned $machKind" -Recommendation 'needs_human_judgment' -Confidence 'high' -Rationale 'Machine Path was written as REG_SZ; rewrite from an elevated shell with Set-ItemProperty -Type ExpandString' -ActionOnApproval "Set-ItemProperty -LiteralPath '$machKeyPath' -Name Path -Type ExpandString -Value `$rawMachinePath" -Classification 'needs-elevation'))
    } else {
        $clean.Add('Machine Path registry value kind is ExpandString (REG_EXPAND_SZ)')
    }

    # Per-entry analysis
    $machNormSet = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    $machDead = [System.Collections.Generic.List[string]]::new()
    $machDupes = [System.Collections.Generic.List[string]]::new()
    $machWrongScope = [System.Collections.Generic.List[string]]::new()

    foreach ($entry in @($machRaw -split ';' | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })) {
        $exp = [Environment]::ExpandEnvironmentVariables($entry.Trim())
        $norm = $exp.TrimEnd('\').ToLowerInvariant()
        if (-not $machNormSet.Add($norm)) {
            $machDupes.Add($entry)
        }
        if (-not (Test-Path -LiteralPath $exp -PathType Container)) {
            $machDead.Add($entry)
        }
        if ($exp -match '^[A-Za-z]:\\Users\\') {
            $machWrongScope.Add($entry)
        }
    }

    if ($machDead.Count -gt 0 -or $machDupes.Count -gt 0 -or $machWrongScope.Count -gt 0) {
        $findings.Add((New-Finding -Section 'env' -Kind 'path_machine_hygiene' -What "Machine Path has $($machDead.Count) dead dir(s), $($machDupes.Count) duplicate(s), and $($machWrongScope.Count) user-profile entry/entries" -Path $machKeyPath -Evidence "Dead: $($machDead -join '; ') | Dupes: $($machDupes -join '; ') | User-scope in Machine: $($machWrongScope -join '; ')" -Recommendation 'needs_human_judgment' -Confidence 'high' -Rationale 'Machine Path should not contain missing directories, duplicates, or per-user profile paths' -ActionOnApproval "Deduplicate and clean Machine Path with Set-ItemProperty -LiteralPath '$machKeyPath' -Name Path -Type ExpandString" -Classification 'needs-elevation'))
    } else {
        $clean.Add('Machine Path entries all exist and have no duplicates or user-profile leaks')
    }

    $userNormSet = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    $userDead = [System.Collections.Generic.List[string]]::new()
    $userDupes = [System.Collections.Generic.List[string]]::new()
    $userCrossDupes = [System.Collections.Generic.List[string]]::new()

    foreach ($entry in @($userRaw -split ';' | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })) {
        $exp = [Environment]::ExpandEnvironmentVariables($entry.Trim())
        $norm = $exp.TrimEnd('\').ToLowerInvariant()
        if (-not $userNormSet.Add($norm)) {
            $userDupes.Add($entry)
        }
        if ($machNormSet.Contains($norm)) {
            $userCrossDupes.Add($entry)
        }
        if (-not (Test-Path -LiteralPath $exp -PathType Container)) {
            $userDead.Add($entry)
        }
    }

    if ($userDead.Count -gt 0 -or $userDupes.Count -gt 0) {
        $findings.Add((New-Finding -Section 'env' -Kind 'path_user_hygiene' -What "User Path has $($userDead.Count) dead dir(s) and $($userDupes.Count) duplicate(s)" -Path $userKeyPath -Evidence "Dead: $($userDead -join '; ') | Dupes: $($userDupes -join '; ')" -Recommendation 'needs_human_judgment' -Confidence 'high' -Rationale 'Dead or duplicated User Path entries waste PATH length and slow binary lookup' -ActionOnApproval "Clean User Path with Set-ItemProperty -LiteralPath '$userKeyPath' -Name Path -Type ExpandString" -Classification 'needs-judgment'))
    } else {
        $clean.Add('User Path has no dead directories or internal duplicates')
    }

    # Live vs persisted PATH diff
    $persistedUnion = [System.Collections.Generic.HashSet[string]]::new($machNormSet, [System.StringComparer]::OrdinalIgnoreCase)
    foreach ($u in $userNormSet) { [void]$persistedUnion.Add($u) }
    $liveExtra = [System.Collections.Generic.List[string]]::new()
    foreach ($le in @($env:PATH -split ';' | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })) {
        $norm = $le.Trim().TrimEnd('\').ToLowerInvariant()
        if (-not $persistedUnion.Contains($norm)) {
            $liveExtra.Add($le)
        }
    }

    # DOTNET_ADD_GLOBAL_TOOLS_TO_PATH check
    $userDotnetGuard = [Environment]::GetEnvironmentVariable('DOTNET_ADD_GLOBAL_TOOLS_TO_PATH', 'User')
    $machDotnetGuard = [Environment]::GetEnvironmentVariable('DOTNET_ADD_GLOBAL_TOOLS_TO_PATH', 'Machine')
    if ($userDotnetGuard -ne 'false') {
        $findings.Add((New-Finding -Section 'env' -Kind 'dotnet_path_guard_user_missing' -What 'DOTNET_ADD_GLOBAL_TOOLS_TO_PATH=false is not persisted at User scope' -Path $userKeyPath -Evidence "User DOTNET_ADD_GLOBAL_TOOLS_TO_PATH is '$userDotnetGuard'" -Recommendation 'needs_human_judgment' -Confidence 'high' -Rationale 'Without DOTNET_ADD_GLOBAL_TOOLS_TO_PATH=false, dotnet first-run under temp USERPROFILE dirs appends .dotnet\tools to persisted User Path' -ActionOnApproval "Set-ItemProperty -LiteralPath 'HKCU:\Environment' -Name 'DOTNET_ADD_GLOBAL_TOOLS_TO_PATH' -Value 'false' -Type String" -Classification 'needs-judgment'))
    } else {
        $clean.Add('User DOTNET_ADD_GLOBAL_TOOLS_TO_PATH is set to false')
    }
    if ($machDotnetGuard -ne 'false') {
        $findings.Add((New-Finding -Section 'env' -Kind 'dotnet_path_guard_machine_missing' -What 'DOTNET_ADD_GLOBAL_TOOLS_TO_PATH=false is not persisted at Machine scope' -Path $machKeyPath -Evidence "Machine DOTNET_ADD_GLOBAL_TOOLS_TO_PATH is '$machDotnetGuard'" -Recommendation 'needs_human_judgment' -Confidence 'medium' -Rationale 'Persisting DOTNET_ADD_GLOBAL_TOOLS_TO_PATH=false at Machine scope protects service accounts such as CI runners' -ActionOnApproval "Set-ItemProperty -LiteralPath '$machKeyPath' -Name 'DOTNET_ADD_GLOBAL_TOOLS_TO_PATH' -Value 'false' -Type String" -Classification 'needs-elevation'))
    } else {
        $clean.Add('Machine DOTNET_ADD_GLOBAL_TOOLS_TO_PATH is set to false')
    }

    # Git global safe.directory check
    $gitConfigPath = Join-Path $HomeDir '.gitconfig'
    $safeDirs = @(& git config --global --get-all safe.directory 2>$null)
    $corruptSafeDirs = [System.Collections.Generic.List[string]]::new()
    foreach ($sd in $safeDirs) {
        if ($sd -match '(?i)(fatal:|error:|--global|\r|\n)') {
            $corruptSafeDirs.Add($sd)
        }
    }
    if ($corruptSafeDirs.Count -gt 0 -or $safeDirs.Count -gt 50) {
        $findings.Add((New-Finding -Section 'env' -Kind 'gitconfig_safe_directory_bloat' -What "~/.gitconfig has $($safeDirs.Count) safe.directory entries ($($corruptSafeDirs.Count) corrupted)" -Path $gitConfigPath -Evidence "safe.directory count=$($safeDirs.Count), corrupt=$($corruptSafeDirs.Count)" -Recommendation 'needs_human_judgment' -Confidence 'medium' -Rationale 'Accumulated safe.directory lines in ~/.gitconfig usually come from test or container leaks' -ActionOnApproval "Prune stale or corrupted safe.directory entries in $gitConfigPath" -Classification 'needs-judgment'))
    } else {
        $clean.Add("~/.gitconfig safe.directory count is clean ($($safeDirs.Count))")
    }

    $raw = [ordered]@{
        user_path_kind        = $userKind
        user_path_length      = $userRaw.Length
        user_path_entries     = ($userRaw -split ';' | Where-Object { $_ }).Count
        user_dead_entries     = $userDead
        user_dupe_entries     = $userDupes
        user_cross_dupes      = $userCrossDupes
        machine_path_kind     = $machKind
        machine_path_length   = $machRaw.Length
        machine_path_entries  = ($machRaw -split ';' | Where-Object { $_ }).Count
        machine_dead_entries  = $machDead
        machine_dupe_entries  = $machDupes
        machine_wrong_scope   = $machWrongScope
        live_extra_entries    = $liveExtra
        user_dotnet_guard     = $userDotnetGuard
        machine_dotnet_guard  = $machDotnetGuard
        gitconfig_safe_dirs   = $safeDirs.Count
        gitconfig_corrupt_sds = $corruptSafeDirs
    }
    return [PSCustomObject]@{
        findings = $findings
        clean    = $clean
        blocked  = $blocked
        raw      = $raw
    }
}

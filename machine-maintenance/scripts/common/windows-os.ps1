# Windows OS and hardware health check section.
Set-StrictMode -Version Latest

function Invoke-OsAudit {
    param(
        [bool]$IsElevated = $false,
        [bool]$SkipElevated = $false
    )
    $findings = [System.Collections.Generic.List[object]]::new()
    $clean = [System.Collections.Generic.List[string]]::new()
    $blocked = [System.Collections.Generic.List[string]]::new()

    # 1. Physical disks and volumes
    $disks = [System.Collections.Generic.List[object]]::new()
    $unhealthyDisks = [System.Collections.Generic.List[string]]::new()
    try {
        foreach ($d in @(Get-PhysicalDisk -ErrorAction Stop)) {
            $disks.Add([PSCustomObject]@{
                name   = $d.FriendlyName
                media  = [string]$d.MediaType
                size   = [int64]$d.Size
                health = [string]$d.HealthStatus
                status = [string]$d.OperationalStatus
            })
            if ([string]$d.HealthStatus -ne 'Healthy') {
                $unhealthyDisks.Add("$($d.FriendlyName) ($($d.HealthStatus))")
            }
        }
    } catch {
        $blocked.Add("Get-PhysicalDisk failed: $($_.Exception.Message)")
    }
    if ($unhealthyDisks.Count -gt 0) {
        $findings.Add((New-Finding -Section 'os' -Kind 'physical_disk_unhealthy' -What "Unhealthy physical disk(s): $($unhealthyDisks -join ', ')" -Path '' -Evidence ($unhealthyDisks -join '; ') -Recommendation 'report_only' -Confidence 'high' -Rationale 'Physical disk reported non-Healthy status' -ActionOnApproval 'Inspect SMART counters immediately and back up critical data' -Classification 'needs-elevation'))
    } elseif ($disks.Count -gt 0) {
        $clean.Add("All $($disks.Count) physical disk(s) report Healthy")
    }

    $volumes = [System.Collections.Generic.List[object]]::new()
    try {
        foreach ($v in @(Get-Volume -ErrorAction Stop | Where-Object { $_.DriveLetter })) {
            $volumes.Add([PSCustomObject]@{
                drive       = [string]$v.DriveLetter
                label       = [string]$v.FileSystemLabel
                filesystem  = [string]$v.FileSystem
                health      = [string]$v.HealthStatus
                free_bytes  = [int64]$v.SizeRemaining
                total_bytes = [int64]$v.Size
            })
        }
    } catch {}

    # 2. Pending reboot indicators
    $pendingReasons = [System.Collections.Generic.List[string]]::new()
    if (Test-Path -LiteralPath 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending') {
        $pendingReasons.Add('CBS RebootPending')
    }
    if (Test-Path -LiteralPath 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired') {
        $pendingReasons.Add('WindowsUpdate RebootRequired')
    }
    $smProps = Get-ItemProperty -LiteralPath 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager' -Name 'PendingFileRenameOperations' -ErrorAction SilentlyContinue
    if ($smProps -and $smProps.PendingFileRenameOperations) {
        $pendingReasons.Add("PendingFileRenameOperations ($($smProps.PendingFileRenameOperations.Count) entries)")
    }
    if ($pendingReasons.Count -gt 0) {
        $findings.Add((New-Finding -Section 'os' -Kind 'os_pending_reboot' -What "Pending reboot indicators present ($($pendingReasons -join ', '))" -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager' -Evidence ($pendingReasons -join '; ') -Recommendation 'needs_human_judgment' -Confidence 'medium' -Rationale 'Pending reboot or file rename operations awaiting next maintenance window' -ActionOnApproval 'Reboot workstation during an idle maintenance window' -Classification 'needs-judgment'))
    } else {
        $clean.Add('No pending reboot indicators set')
    }

    # 3. w32tm clock sync state
    $w32tmRes = Invoke-CommandWithTimeout -FilePath 'w32tm.exe' -ArgumentList @('/query', '/status') -TimeoutSeconds 10
    $w32tmSource = 'Unknown'
    $w32tmSynced = $false
    if ($w32tmRes.exit_code -eq 0 -and $w32tmRes.stdout) {
        if ($w32tmRes.stdout -match '(?m)^Source:\s*(.+)$') {
            $w32tmSource = $Matches[1].Trim()
        }
        if ($w32tmSource -and $w32tmSource -notmatch '(?i)(Local CMOS Clock|Free-running System Clock)') {
            $w32tmSynced = $true
        }
    } else {
        $w32Svc = Get-Service -Name 'w32time' -ErrorAction SilentlyContinue
        $w32tmSource = if ($w32Svc) { "Service $($w32Svc.Status) ($($w32Svc.StartType))" } else { 'Unavailable' }
    }

    if (-not $w32tmSynced) {
        $findings.Add((New-Finding -Section 'os' -Kind 'w32tm_unsynced' -What "Windows Time (w32tm) is unsynced (Source: $w32tmSource)" -Path '' -Evidence "w32tm /query /status reported Source: $w32tmSource" -Recommendation 'needs_human_judgment' -Confidence 'high' -Rationale 'Running on the Local CMOS Clock or with w32time stopped causes clock drift that breaks TLS, OAuth, and build timestamps' -ActionOnApproval 'Set-Service w32time -StartupType Automatic; Start-Service w32time; w32tm /resync /rediscover' -Classification 'needs-elevation'))
    } else {
        $clean.Add("Windows Time synced (Source: $w32tmSource)")
    }

    # 4. PnP problem devices
    $pnpProblems = [System.Collections.Generic.List[object]]::new()
    try {
        foreach ($dev in @(Get-PnpDevice -ErrorAction Stop | Where-Object { $_.Status -ne 'OK' -and $_.Status -ne 'Unknown' })) {
            $pnpProblems.Add([PSCustomObject]@{
                status      = [string]$dev.Status
                class       = [string]$dev.Class
                name        = [string]$dev.FriendlyName
                instance_id = [string]$dev.InstanceId
            })
        }
    } catch {}
    if ($pnpProblems.Count -gt 0) {
        $devSummary = ($pnpProblems | Select-Object -First 5 | ForEach-Object { "$($_.name) [$($_.instance_id)] ($($_.status))" }) -join '; '
        $findings.Add((New-Finding -Section 'os' -Kind 'pnp_problem_devices' -What "$($pnpProblems.Count) PnP device(s) in non-OK state" -Path '' -Evidence $devSummary -Recommendation 'needs_human_judgment' -Confidence 'medium' -Rationale 'Ghost or degraded PnP devices should be inspected or removed via pnputil' -ActionOnApproval 'Inspect problem devices and remove ghost entries with pnputil /remove-device <InstanceId>' -Classification 'needs-elevation'))
    } else {
        $clean.Add('All active PnP devices report Status OK')
    }

    # 5. Reliability stability index
    $stabilityIndex = $null
    try {
        $metric = Get-CimInstance -ClassName Win32_ReliabilityStabilityMetrics -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($metric) { $stabilityIndex = $metric.SystemStabilityIndex }
    } catch {}

    # 6. Defender status
    $defender = [ordered]@{ enabled = $null; realtime = $null }
    try {
        $mp = Get-MpComputerStatus -ErrorAction Stop
        $defender.enabled = $mp.AMServiceEnabled
        $defender.realtime = $mp.RealTimeProtectionEnabled
    } catch {}

    # 7. LongPathsEnabled and git fsmonitor/untrackedCache
    $fsKey = Get-ItemProperty -LiteralPath 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' -Name 'LongPathsEnabled' -ErrorAction SilentlyContinue
    $longPathsEnabled = ($fsKey -and $fsKey.LongPathsEnabled -eq 1)
    if (-not $longPathsEnabled) {
        $findings.Add((New-Finding -Section 'os' -Kind 'windows_longpaths_disabled' -What 'Windows LongPathsEnabled is not set to 1' -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' -Evidence "LongPathsEnabled=$($fsKey.LongPathsEnabled)" -Recommendation 'needs_human_judgment' -Confidence 'high' -Rationale 'Long paths are required for deep node_modules and worktree paths on Windows' -ActionOnApproval "Set-ItemProperty -LiteralPath 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' -Name 'LongPathsEnabled' -Value 1" -Classification 'needs-elevation'))
    } else {
        $clean.Add('Windows LongPathsEnabled is enabled (1)')
    }

    $gitFsMonitor = (& git config --global --get core.fsmonitor 2>$null)
    $gitUntrackedCache = (& git config --global --get core.untrackedCache 2>$null)

    if (-not $IsElevated -or $SkipElevated) {
        $blocked.Add('SMART reliability counters skipped (requires elevation): run `Get-PhysicalDisk | Get-StorageReliabilityCounter`')
        $blocked.Add('Defender exclusion paths skipped (requires elevation): run `Get-MpPreference | Select-Object -ExpandProperty ExclusionPath`')
    }

    $raw = [ordered]@{
        physical_disks     = $disks
        volumes            = $volumes
        pending_reboot     = $pendingReasons
        w32tm_source       = $w32tmSource
        w32tm_synced       = $w32tmSynced
        pnp_problems       = $pnpProblems
        stability_index    = $stabilityIndex
        defender           = $defender
        long_paths_enabled = $longPathsEnabled
        git_fsmonitor      = "$gitFsMonitor"
        git_untrackedcache = "$gitUntrackedCache"
    }
    return [PSCustomObject]@{
        findings = $findings
        clean    = $clean
        blocked  = $blocked
        raw      = $raw
    }
}

# Windows background processes, startup items, services, and scheduled tasks audit section.
Set-StrictMode -Version Latest

function Invoke-ProcessesAudit {
    param(
        [Parameter(Mandatory)][string]$HomeDir
    )
    $findings = [System.Collections.Generic.List[object]]::new()
    $clean = [System.Collections.Generic.List[string]]::new()
    $blocked = [System.Collections.Generic.List[string]]::new()

    # 1. Top processes and orphaned processes by dead parent PID
    $topMemory = [System.Collections.Generic.List[object]]::new()
    foreach ($p in @(Get-Process -ErrorAction SilentlyContinue | Sort-Object WorkingSet64 -Descending | Select-Object -First 25)) {
        $topMemory.Add([PSCustomObject]@{
            name  = $p.ProcessName
            pid   = $p.Id
            ws_mb = [int]($p.WorkingSet64 / 1MB)
            cpu_s = [int]($p.CPU)
        })
    }

    $orphans = [System.Collections.Generic.List[object]]::new()
    $mcpInstances = [ordered]@{}
    try {
        $cimProcs = @(Get-CimInstance -ClassName Win32_Process -ErrorAction Stop)
        $livePids = [System.Collections.Generic.HashSet[uint32]]::new()
        foreach ($cp in $cimProcs) {
            [void]$livePids.Add([uint32]$cp.ProcessId)
        }
        $watchNames = @('node.exe', 'python.exe', 'pwsh.exe', 'powershell.exe', 'dotnet.exe', 'MSBuild.exe', 'VBCSCompiler.exe', 'InspectCode.exe')
        foreach ($cp in $cimProcs) {
            $cmdLine = [string]$cp.CommandLine
            foreach ($mcpKey in @('project-tracker', 'agent-walker', 'inference-manager', 'desktop-commander', 'windows-mcp')) {
                if ($cmdLine -match [regex]::Escape($mcpKey)) {
                    if (-not $mcpInstances.Contains($mcpKey)) { $mcpInstances[$mcpKey] = 0 }
                    $mcpInstances[$mcpKey] = [int]$mcpInstances[$mcpKey] + 1
                }
            }
            if ($cp.Name -in $watchNames -and $cp.ParentProcessId -gt 0 -and -not $livePids.Contains([uint32]$cp.ParentProcessId)) {
                if ($cmdLine -match '(?i)(InspectCode|pytest|vitest|jest|VBCSCompiler|windows-mcp|mcp)') {
                    $orphans.Add([PSCustomObject]@{
                        pid        = $cp.ProcessId
                        parent_pid = $cp.ParentProcessId
                        name       = $cp.Name
                        command    = if ($cmdLine.Length -gt 180) { $cmdLine.Substring(0, 180) } else { $cmdLine }
                    })
                }
            }
        }
    } catch {
        $blocked.Add("Win32_Process CIM query failed: $($_.Exception.Message)")
    }

    if ($orphans.Count -gt 0) {
        $pids = ($orphans | ForEach-Object { "$($_.name)($($_.pid))" }) -join ', '
        $findings.Add((New-Finding -Section 'processes' -Kind 'orphan_processes' -What "$($orphans.Count) orphaned background worker/test process(es)" -Path '' -Evidence "Parent PID no longer exists for: $pids" -Recommendation 'needs_human_judgment' -Confidence 'medium' -Rationale 'Orphaned test runners, InspectCode, or MCP workers hold RAM and file locks after parent sessions exit' -ActionOnApproval "Stop-Process -Id $(($orphans | ForEach-Object { $_.pid }) -join ',')" -Classification 'needs-judgment'))
    } else {
        $clean.Add('No orphaned test/analyzer/MCP worker processes detected')
    }

    # 2. Startup Run keys and StartupApproved state
    $startupItems = [System.Collections.Generic.List[object]]::new()
    $approvedMap = @{}
    $approvedKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run'
    if (Test-Path -LiteralPath $approvedKey) {
        $apProps = Get-ItemProperty -LiteralPath $approvedKey -ErrorAction SilentlyContinue
        foreach ($prop in $apProps.PSObject.Properties) {
            if ($prop.Name -notlike 'PS*' -and $prop.Value -is [byte[]] -and $prop.Value.Length -gt 0) {
                $approvedMap[$prop.Name] = ($prop.Value[0] -eq 2)
            }
        }
    }

    foreach ($rk in @(
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run',
        'HKLM:\Software\Microsoft\Windows\CurrentVersion\Run',
        'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run'
    )) {
        if (-not (Test-Path -LiteralPath $rk)) { continue }
        $props = Get-ItemProperty -LiteralPath $rk -ErrorAction SilentlyContinue
        foreach ($p in $props.PSObject.Properties) {
            if ($p.Name -like 'PS*') { continue }
            $rawCmd = [string]$p.Value
            $exePath = $null
            if ($rawCmd -match '^"([^"]+)"') {
                $exePath = [Environment]::ExpandEnvironmentVariables($Matches[1])
            } elseif ($rawCmd -match '^([^\s]+)') {
                $exePath = [Environment]::ExpandEnvironmentVariables($Matches[1])
            }
            $exists = if ($exePath) { Test-Path -LiteralPath $exePath } else { $true }
            $enabled = if ($approvedMap.ContainsKey($p.Name)) { $approvedMap[$p.Name] } else { $true }
            $startupItems.Add([PSCustomObject]@{
                key     = $rk
                name    = $p.Name
                command = $rawCmd
                exists  = $exists
                enabled = $enabled
            })
            if (-not $exists) {
                $findings.Add((New-Finding -Section 'processes' -Kind 'startup_missing_binary' -What "Startup Run entry '$($p.Name)' points to missing executable" -Path $rk -Evidence "$($p.Name) -> $exePath (file does not exist)" -Recommendation 'needs_human_judgment' -Confidence 'high' -Rationale 'Dead startup registration left by an uninstalled application' -ActionOnApproval "Remove-ItemProperty -LiteralPath '$rk' -Name '$($p.Name)'" -Classification 'needs-judgment'))
            }
        }
    }

    # 3. Non-Microsoft Scheduled Tasks with missing action binaries or failing runs
    $brokenTasks = [System.Collections.Generic.List[object]]::new()
    try {
        foreach ($t in @(Get-ScheduledTask -ErrorAction Stop | Where-Object { $_.State -ne 'Disabled' -and $_.TaskPath -notlike '\Microsoft\*' })) {
            foreach ($act in @($t.Actions)) {
                $exe = [string]$act.Execute
                if ([string]::IsNullOrWhiteSpace($exe)) { continue }
                $expandedExe = [Environment]::ExpandEnvironmentVariables($exe.Trim('"'))
                if ($expandedExe -match '^[A-Za-z]:\\' -and -not (Test-Path -LiteralPath $expandedExe)) {
                    $brokenTasks.Add([PSCustomObject]@{ task_path = "$($t.TaskPath)$($t.TaskName)"; execute = $expandedExe })
                }
            }
        }
    } catch {
        $blocked.Add("ScheduledTask inspection failed: $($_.Exception.Message)")
    }

    if ($brokenTasks.Count -gt 0) {
        $names = ($brokenTasks | ForEach-Object { $_.task_path }) -join ', '
        $findings.Add((New-Finding -Section 'processes' -Kind 'scheduled_task_missing_exe' -What "$($brokenTasks.Count) enabled scheduled task(s) point to missing executables" -Path '' -Evidence "Missing action binaries: $names" -Recommendation 'needs_human_judgment' -Confidence 'high' -Rationale 'Scheduled tasks referencing deleted binaries fail on every trigger' -ActionOnApproval 'Disable-ScheduledTask for broken non-Microsoft tasks' -Classification 'needs-judgment'))
    } else {
        $clean.Add('All enabled non-Microsoft scheduled task binaries exist on disk')
    }

    # 4. Wildcard TCP listeners
    $wildcardListeners = [System.Collections.Generic.List[object]]::new()
    try {
        foreach ($conn in @(Get-NetTCPConnection -State Listen -ErrorAction Stop | Where-Object { $_.LocalAddress -in @('0.0.0.0', '::') -and $_.LocalPort -ge 1024 -and $_.LocalPort -lt 49152 })) {
            $procName = (Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue).ProcessName
            $wildcardListeners.Add([PSCustomObject]@{ address = $conn.LocalAddress; port = $conn.LocalPort; pid = $conn.OwningProcess; process = "$procName" })
        }
    } catch {}

    # 5. WSL config check
    $wslConfigPath = Join-Path $HomeDir '.wslconfig'
    $wslConfigPresent = Test-Path -LiteralPath $wslConfigPath
    if (-not $wslConfigPresent) {
        $findings.Add((New-Finding -Section 'processes' -Kind 'wslconfig_missing' -What 'Missing ~/.wslconfig memory and reclaim policy' -Path $wslConfigPath -Evidence "$wslConfigPath does not exist" -Recommendation 'needs_human_judgment' -Confidence 'low' -Rationale 'Setting autoMemoryReclaim=gradual and a memory cap in .wslconfig prevents unbounded vmmemWSL growth' -ActionOnApproval "Create $wslConfigPath with [wsl2] autoMemoryReclaim=gradual" -Classification 'needs-judgment'))
    } else {
        $clean.Add("$wslConfigPath is present")
    }

    # 6. Event log errors in last 7 days
    $appErrorTop = [System.Collections.Generic.List[object]]::new()
    try {
        $events = @(Get-WinEvent -FilterHashtable @{ LogName = 'Application'; Level = 2; StartTime = (Get-Date).AddDays(-7) } -MaxEvents 500 -ErrorAction SilentlyContinue)
        foreach ($g in @($events | Group-Object ProviderName | Sort-Object Count -Descending | Select-Object -First 10)) {
            $appErrorTop.Add([PSCustomObject]@{ provider = $g.Name; count = $g.Count })
        }
    } catch {}

    $raw = [ordered]@{
        top_memory         = $topMemory
        orphans            = $orphans
        mcp_instances      = $mcpInstances
        startup_items      = $startupItems
        broken_tasks       = $brokenTasks
        wildcard_listeners = $wildcardListeners
        wslconfig_present  = $wslConfigPresent
        app_errors_7d_top  = $appErrorTop
    }
    return [PSCustomObject]@{
        findings = $findings
        clean    = $clean
        blocked  = $blocked
        raw      = $raw
    }
}

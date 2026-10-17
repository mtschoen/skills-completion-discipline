# Windows disk and cache reclaim audit section.
Set-StrictMode -Version Latest

function Invoke-DiskAudit {
    param(
        [Parameter(Mandatory)][string]$HomeDir,
        [Parameter(Mandatory)][string]$LocalAppData,
        [int]$MaxDepth = 1,
        [bool]$IsElevated = $false,
        [bool]$SkipElevated = $false
    )
    $findings = [System.Collections.Generic.List[object]]::new()
    $clean = [System.Collections.Generic.List[string]]::new()
    $blocked = [System.Collections.Generic.List[string]]::new()
    $cacheTable = [System.Collections.Generic.List[object]]::new()

    $targets = @(
        @{ Name = 'Sublime Text Index'; Path = (Join-Path $LocalAppData 'Sublime Text\Index'); Kind = 'cache_sublime_index'; Class = 'safe-mechanical'; Pre = 'process_stopped:sublime_text'; Cmd = "Remove-Item -LiteralPath '$(Join-Path $LocalAppData 'Sublime Text\Index')' -Recurse -Force"; Threshold = 100MB; Rationale = 'Sublime Text symbol index can be rebuilt; add .venv and node_modules to index_exclude_patterns' },
        @{ Name = 'npm-cache'; Path = (Join-Path $LocalAppData 'npm-cache'); Kind = 'cache_npm'; Class = 'needs-judgment'; Pre = 'process_stopped:npm'; Cmd = 'npm cache clean --force'; Threshold = 200MB; Rationale = 'Regenerable npm tarball cache; clean targets the configured cache, which may differ from the measured path' },
        @{ Name = 'pnpm store'; Path = (Join-Path $LocalAppData 'pnpm'); Kind = 'cache_pnpm'; Class = 'needs-judgment'; Pre = 'process_stopped:pnpm'; Cmd = 'pnpm store prune'; Threshold = 200MB; Rationale = 'Prunes unreferenced packages from pnpm content-addressed store; prune targets the configured store, which may differ from the measured path' },
        @{ Name = 'pnpm-cache'; Path = (Join-Path $LocalAppData 'pnpm-cache'); Kind = 'cache_pnpm_http'; Class = 'needs-judgment'; Pre = 'process_stopped:pnpm'; Cmd = "Remove-Item -LiteralPath '$(Join-Path $LocalAppData 'pnpm-cache')' -Recurse -Force"; Threshold = 200MB; Rationale = 'Regenerable pnpm metadata cache; the pnpm process guard is unreliable because pnpm runs under node' },
        @{ Name = 'Yarn cache'; Path = (Join-Path $LocalAppData 'Yarn'); Kind = 'cache_yarn'; Class = 'needs-judgment'; Pre = 'none'; Cmd = 'yarn cache clean'; Threshold = 200MB; Rationale = 'Yarn directory also holds Data/global and Config; run yarn cache clean rather than deleting the root' },
        @{ Name = 'uv cache'; Path = (Join-Path $LocalAppData 'uv'); Kind = 'cache_uv'; Class = 'needs-judgment'; Pre = 'no_uv_lock'; Cmd = 'uv cache prune'; Threshold = 200MB; Rationale = 'Use uv cache prune only; never run uv cache clean because venvs are hard-linked into the cache' },
        @{ Name = 'pip cache'; Path = (Join-Path $LocalAppData 'pip'); Kind = 'cache_pip'; Class = 'needs-judgment'; Pre = 'process_stopped:pip'; Cmd = 'pip cache purge'; Threshold = 200MB; Rationale = 'Regenerable pip HTTP wheel cache; purge targets the configured cache, which may differ from the measured path' },
        @{ Name = 'NuGet global packages'; Path = (Join-Path $HomeDir '.nuget\packages'); Kind = 'cache_nuget'; Class = 'needs-judgment'; Pre = 'process_stopped:dotnet,MSBuild,VBCSCompiler'; Cmd = 'dotnet nuget locals all --clear'; Threshold = 500MB; Rationale = 'NuGet package cache; locals all --clear purges every configured location, wider than this finding' },
        @{ Name = 'NuGet local http cache'; Path = (Join-Path $LocalAppData 'NuGet'); Kind = 'cache_nuget_http'; Class = 'needs-judgment'; Pre = 'process_stopped:dotnet,MSBuild,VBCSCompiler'; Cmd = 'dotnet nuget locals http-cache --clear'; Threshold = 200MB; Rationale = 'NuGet HTTP cache; clear targets the configured location, which may differ from the measured path' },
        @{ Name = 'Cargo home'; Path = (Join-Path $HomeDir '.cargo'); Kind = 'cache_cargo'; Class = 'needs-judgment'; Pre = 'process_stopped:cargo,rustc'; Cmd = "Inspect $(Join-Path $HomeDir '.cargo\registry\cache')"; Threshold = 1GB; Rationale = 'Cargo binaries and registry cache' },
        @{ Name = 'Rustup toolchains'; Path = (Join-Path $HomeDir '.rustup'); Kind = 'cache_rustup'; Class = 'needs-judgment'; Pre = 'process_stopped:cargo,rustc'; Cmd = 'rustup toolchain list'; Threshold = 2GB; Rationale = 'Rustup installed toolchains' },
        @{ Name = 'Go module cache'; Path = (Join-Path $HomeDir 'go\pkg\mod'); Kind = 'cache_go_mod'; Class = 'needs-judgment'; Pre = 'process_stopped:go'; Cmd = 'go clean -modcache'; Threshold = 1GB; Rationale = 'Go module download cache' },
        @{ Name = 'Go build cache'; Path = (Join-Path $LocalAppData 'go-build'); Kind = 'cache_go_build'; Class = 'safe-mechanical'; Pre = 'process_stopped:go'; Cmd = 'go clean -cache'; Threshold = 500MB; Rationale = 'Go incremental build cache' },
        @{ Name = 'NVIDIA DXCache'; Path = (Join-Path $LocalAppData 'NVIDIA\DXCache'); Kind = 'cache_nvidia_dxcache'; Class = 'safe-mechanical'; Pre = 'none'; Cmd = "Remove-Item -LiteralPath '$(Join-Path $LocalAppData 'NVIDIA\DXCache')\*' -Recurse -Force -ErrorAction SilentlyContinue"; Threshold = 500MB; Rationale = 'DirectX compiled shader cache; shaders recompile on launch' },
        @{ Name = 'NVIDIA GLCache'; Path = (Join-Path $LocalAppData 'NVIDIA\GLCache'); Kind = 'cache_nvidia_glcache'; Class = 'safe-mechanical'; Pre = 'none'; Cmd = "Remove-Item -LiteralPath '$(Join-Path $LocalAppData 'NVIDIA\GLCache')\*' -Recurse -Force -ErrorAction SilentlyContinue"; Threshold = 500MB; Rationale = 'OpenGL shader cache' },
        @{ Name = 'D3DSCache'; Path = (Join-Path $LocalAppData 'D3DSCache'); Kind = 'cache_d3dscache'; Class = 'safe-mechanical'; Pre = 'none'; Cmd = "Remove-Item -LiteralPath '$(Join-Path $LocalAppData 'D3DSCache')\*' -Recurse -Force -ErrorAction SilentlyContinue"; Threshold = 500MB; Rationale = 'Direct3D shader cache' },
        @{ Name = 'Puppeteer browser cache'; Path = (Join-Path $HomeDir '.cache\puppeteer'); Kind = 'cache_puppeteer'; Class = 'safe-mechanical'; Pre = 'process_stopped:chrome,node'; Cmd = "Remove-Item -LiteralPath '$(Join-Path $HomeDir '.cache\puppeteer')' -Recurse -Force"; Threshold = 200MB; Rationale = 'Cached headless Chromium builds for Puppeteer' },
        @{ Name = 'JetBrains local cache'; Path = (Join-Path $LocalAppData 'JetBrains'); Kind = 'cache_jetbrains'; Class = 'needs-judgment'; Pre = 'process_stopped:rider64,idea64,pycharm64'; Cmd = "Inspect $(Join-Path $LocalAppData 'JetBrains') for old IDE versions"; Threshold = 2GB; Rationale = 'JetBrains IDE caches and indexes' },
        @{ Name = 'Unity local cache'; Path = (Join-Path $LocalAppData 'Unity'); Kind = 'cache_unity'; Class = 'needs-judgment'; Pre = 'process_stopped:Unity'; Cmd = "Inspect $(Join-Path $LocalAppData 'Unity\cache')"; Threshold = 2GB; Rationale = 'Unity package and GI cache' }
    )

    foreach ($t in $targets) {
        $m = Measure-TreeFast -LiteralPath $t.Path -TimeoutSeconds 6
        if ($m.exists) {
            $cacheTable.Add([PSCustomObject]@{
                name         = $t.Name
                path         = $t.Path
                bytes        = $m.bytes
                size_human   = (Format-Bytes $m.bytes)
                file_count   = $m.file_count
                newest_mtime = $m.newest_mtime
                truncated    = $m.truncated
            })
            if ($m.truncated) {
                $blocked.Add("Disk measurement capped at timeout/file limit for $($t.Path) (partial: $(Format-Bytes $m.bytes))")
            }
            if ($m.bytes -ge $t.Threshold) {
                $rec = if ($t.Class -eq 'safe-mechanical') { 'delete' } else { 'needs_human_judgment' }
                $findings.Add((New-Finding -Section 'disk' -Kind $t.Kind -What "$($t.Name) ($(Format-Bytes $m.bytes))" -Path $t.Path -Evidence "$($t.Path): $(Format-Bytes $m.bytes) across $($m.file_count) files (newest: $($m.newest_mtime))" -Recommendation $rec -Confidence 'high' -Rationale $t.Rationale -ActionOnApproval $t.Cmd -Classification $t.Class -ReclaimBytes $m.bytes -Precondition $t.Pre -Action $t.Cmd))
            } else {
                $clean.Add("$($t.Name) under threshold ($(Format-Bytes $m.bytes))")
            }
        }
    }

    # Temp top-level breakdown
    $tempRoot = Join-Path $LocalAppData 'Temp'
    $tempChildren = [System.Collections.Generic.List[object]]::new()
    if (Test-Path -LiteralPath $tempRoot) {
        $pytestBytes = [int64]0
        $pytestCount = 0
        foreach ($child in @(Get-ChildItem -LiteralPath $tempRoot -Force -ErrorAction SilentlyContinue | Select-Object -First 80)) {
            if ($child.Name -like 'pytest-of-*') {
                $cm = Measure-TreeFast -LiteralPath $child.FullName -TimeoutSeconds 2
                $pytestBytes += $cm.bytes
                $pytestCount++
                continue
            }
            if ($child.PSIsContainer -and ($child.Name -in @('opencode', 'claude', 'uv', 'pip', 'npm', 'MSBuildTemp'))) {
                $cm = Measure-TreeFast -LiteralPath $child.FullName -TimeoutSeconds 3
                $tempChildren.Add([PSCustomObject]@{ name = $child.Name; path = $child.FullName; bytes = $cm.bytes; file_count = $cm.file_count })
                if ($child.Name -eq 'opencode' -and $cm.bytes -ge 100MB) {
                    $findings.Add((New-Finding -Section 'disk' -Kind 'temp_opencode_diag' -What "Temp opencode diagnostic artifacts ($(Format-Bytes $cm.bytes))" -Path $child.FullName -Evidence "$($child.FullName): $(Format-Bytes $cm.bytes)" -Recommendation 'needs_human_judgment' -Confidence 'high' -Rationale 'Diagnostic DB/scratch copies in Temp; size alone does not prove contents are spent, so deletion needs owner review' -ActionOnApproval "Inspect $($child.FullName) and remove spent diagnostic copies" -Classification 'needs-judgment' -ReclaimBytes $cm.bytes -Precondition 'none'))
                }
            }
        }
        if ($pytestBytes -ge 50MB) {
            $findings.Add((New-Finding -Section 'disk' -Kind 'temp_pytest_dirs' -What "Temp pytest-of-* directories ($(Format-Bytes $pytestBytes))" -Path $tempRoot -Evidence "$pytestCount pytest-of-* directories in $tempRoot totalling $(Format-Bytes $pytestBytes)" -Recommendation 'needs_human_judgment' -Confidence 'high' -Rationale 'Leftover pytest temporary directories; the pytest process guard is unreliable because pytest runs under python' -ActionOnApproval "Get-ChildItem -LiteralPath '$tempRoot' -Filter 'pytest-of-*' -Directory | Remove-Item -Recurse -Force" -Classification 'needs-judgment' -ReclaimBytes $pytestBytes -Precondition 'process_stopped:pytest'))
        }
    }

    # Browser caches (Chrome & Edge): one finding per exact cache subdirectory so
    # cleanup can never receive the User Data root as a deletion target.
    foreach ($browser in @(
        @{ Name = 'Chrome'; Root = (Join-Path $LocalAppData 'Google\Chrome\User Data'); Proc = 'chrome' },
        @{ Name = 'Edge'; Root = (Join-Path $LocalAppData 'Microsoft\Edge\User Data'); Proc = 'msedge' }
    )) {
        if (Test-Path -LiteralPath $browser.Root) {
            $cacheDirs = [System.Collections.Generic.List[object]]::new()
            [int64]$bBytes = 0
            foreach ($prof in @(Get-ChildItem -LiteralPath $browser.Root -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -eq 'Default' -or $_.Name -like 'Profile *' })) {
                foreach ($sub in @('Cache', 'Code Cache', 'GPUCache')) {
                    $sp = Join-Path $prof.FullName $sub
                    if (Test-Path -LiteralPath $sp) {
                        $subBytes = (Measure-TreeFast -LiteralPath $sp -TimeoutSeconds 2).bytes
                        $bBytes += $subBytes
                        if ($subBytes -gt 0) {
                            $cacheDirs.Add([PSCustomObject]@{ path = $sp; bytes = $subBytes; label = "$($browser.Name) $($prof.Name)\$sub" })
                        }
                    }
                }
            }
            if ($bBytes -ge 250MB) {
                foreach ($cd in $cacheDirs) {
                    $findings.Add((New-Finding -Section 'disk' -Kind 'browser_cache_subdir' -What "$($cd.label) ($(Format-Bytes $cd.bytes))" -Path $cd.path -Evidence "$($cd.path): $(Format-Bytes $cd.bytes)" -Recommendation 'delete' -Confidence 'high' -Rationale 'Browser HTTP/script/GPU caches are regenerable when browser is closed' -ActionOnApproval "Remove-Item -LiteralPath '$($cd.path)' -Recurse -Force" -Classification 'safe-mechanical' -ReclaimBytes $cd.bytes -Precondition "process_stopped:$($browser.Proc)"))
                }
            }
        }
    }

    # VHDX scan (WSL, Docker, Packages)
    $vhdxList = [System.Collections.Generic.List[object]]::new()
    $pkgRoot = Join-Path $LocalAppData 'Packages'
    if (Test-Path -LiteralPath $pkgRoot) {
        foreach ($pkg in @(Get-ChildItem -LiteralPath $pkgRoot -Directory -ErrorAction SilentlyContinue)) {
            $ls = Join-Path $pkg.FullName 'LocalState'
            if (Test-Path -LiteralPath $ls) {
                foreach ($v in @(Get-ChildItem -LiteralPath $ls -Filter '*.vhdx' -File -Force -ErrorAction SilentlyContinue)) {
                    $vhdxList.Add([PSCustomObject]@{ path = $v.FullName; bytes = [int64]$v.Length; size_human = (Format-Bytes $v.Length) })
                }
            }
        }
    }
    foreach ($extraVhdxDir in @((Join-Path $LocalAppData 'Docker'), (Join-Path $LocalAppData 'wsl'))) {
        if (Test-Path -LiteralPath $extraVhdxDir) {
            foreach ($v in @(Get-ChildItem -LiteralPath $extraVhdxDir -Filter '*.vhdx' -Recurse -Depth 3 -File -Force -ErrorAction SilentlyContinue)) {
                $vhdxList.Add([PSCustomObject]@{ path = $v.FullName; bytes = [int64]$v.Length; size_human = (Format-Bytes $v.Length) })
            }
        }
    }

    # Unity Editors
    $unityEditorRoot = Join-Path $env:ProgramFiles 'Unity\Hub\Editor'
    $unityEditors = [System.Collections.Generic.List[object]]::new()
    if (Test-Path -LiteralPath $unityEditorRoot) {
        [int64]$totalUnityBytes = 0
        foreach ($ed in @(Get-ChildItem -LiteralPath $unityEditorRoot -Directory -ErrorAction SilentlyContinue)) {
            $em = Measure-TreeFast -LiteralPath $ed.FullName -TimeoutSeconds 3
            $totalUnityBytes += $em.bytes
            $unityEditors.Add([PSCustomObject]@{ version = $ed.Name; path = $ed.FullName; bytes = $em.bytes; size_human = (Format-Bytes $em.bytes) })
        }
        if ($unityEditors.Count -gt 2 -and $totalUnityBytes -ge 10GB) {
            $findings.Add((New-Finding -Section 'disk' -Kind 'unity_multiple_editors' -What "$($unityEditors.Count) Unity Editor installs ($(Format-Bytes $totalUnityBytes))" -Path $unityEditorRoot -Evidence "$($unityEditors.Count) versions under $unityEditorRoot totalling $(Format-Bytes $totalUnityBytes)" -Recommendation 'needs_human_judgment' -Confidence 'medium' -Rationale 'Superseded Unity Editor versions can be uninstalled via Unity Hub after checking ProjectVersion.txt across repos' -ActionOnApproval 'Uninstall unused Unity Editor versions in Unity Hub' -Classification 'needs-judgment' -ReclaimBytes 0 -Precondition 'process_stopped:Unity'))
        }
    }

    # Storage Sense policy
    $ssKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\StorageSense\Parameters\StoragePolicy'
    $storageSense = [ordered]@{ present = $false; enabled = $false; temp_cleanup = $false }
    if (Test-Path -LiteralPath $ssKey) {
        $props = Get-ItemProperty -LiteralPath $ssKey -ErrorAction SilentlyContinue
        $storageSense.present = $true
        $storageSense.enabled = ($props.PSObject.Properties['01'] -and $props.'01' -eq 1)
        $storageSense.temp_cleanup = ($props.PSObject.Properties['04'] -and $props.'04' -eq 1)
        if ($storageSense.enabled -and $storageSense.temp_cleanup) {
            $findings.Add((New-Finding -Section 'disk' -Kind 'storage_sense_temp_enabled' -What 'Storage Sense automatic %TEMP% deletion is enabled' -Path $ssKey -Evidence 'StoragePolicy 01=1 (enabled) and 04=1 (delete temp files)' -Recommendation 'needs_human_judgment' -Confidence 'high' -Rationale 'Storage Sense Temp cleanup can silently delete scratch git clones or worktrees placed under %TEMP%' -ActionOnApproval "Set-ItemProperty -LiteralPath '$ssKey' -Name '04' -Value 0" -Classification 'needs-judgment' -ReclaimBytes 0))
        } else {
            $clean.Add('Storage Sense Temp auto-delete is off or policy absent')
        }
    }

    # Downloads top-15
    $downloadsPath = Join-Path $HomeDir 'Downloads'
    $downloadsTop = [System.Collections.Generic.List[object]]::new()
    [int64]$downloadsBytes = 0
    if (Test-Path -LiteralPath $downloadsPath) {
        $dlMeasure = Measure-TreeFast -LiteralPath $downloadsPath -TimeoutSeconds 4
        $downloadsBytes = $dlMeasure.bytes
        foreach ($f in @(Get-ChildItem -LiteralPath $downloadsPath -File -Force -ErrorAction SilentlyContinue | Sort-Object Length -Descending | Select-Object -First 15)) {
            $downloadsTop.Add([PSCustomObject]@{ name = $f.Name; bytes = [int64]$f.Length; size_human = (Format-Bytes $f.Length); mtime = $f.LastWriteTimeUtc.ToString('o') })
        }
        if ($downloadsBytes -ge 2GB) {
            $findings.Add((New-Finding -Section 'disk' -Kind 'downloads_large' -What "Downloads folder is $(Format-Bytes $downloadsBytes)" -Path $downloadsPath -Evidence "$($dlMeasure.file_count) files in $downloadsPath ($(Format-Bytes $downloadsBytes))" -Recommendation 'needs_human_judgment' -Confidence 'medium' -Rationale 'Old installers, archives, and ISOs in Downloads require owner review before deletion' -ActionOnApproval "Review top files in $downloadsPath" -Classification 'needs-judgment' -ReclaimBytes 0))
        }
    }

    # Pagefile and hiberfil
    $pagefiles = [System.Collections.Generic.List[object]]::new()
    try {
        foreach ($pf in @(Get-CimInstance -ClassName Win32_PageFileUsage -ErrorAction SilentlyContinue)) {
            $pagefiles.Add([PSCustomObject]@{ name = $pf.Name; allocated_mb = $pf.AllocatedBaseSize; peak_mb = $pf.PeakUsage })
        }
    } catch {}

    # Elevated DISM component store check
    if ($IsElevated -and -not $SkipElevated) {
        $dismRes = Invoke-CommandWithTimeout -FilePath 'dism.exe' -ArgumentList @('/Online', '/Cleanup-Image', '/AnalyzeComponentStore') -TimeoutSeconds 60
        if ($dismRes.stdout -match 'Component Store Cleanup Recommended\s*:\s*Yes') {
            $findings.Add((New-Finding -Section 'disk' -Kind 'dism_component_store' -What 'WinSxS component store cleanup recommended by DISM' -Path 'C:\Windows\WinSxS' -Evidence 'DISM AnalyzeComponentStore reported Cleanup Recommended: Yes' -Recommendation 'delete' -Confidence 'high' -Rationale 'Reclaims superseded WinSxS component packages' -ActionOnApproval 'dism /Online /Cleanup-Image /StartComponentCleanup' -Classification 'needs-elevation' -ReclaimBytes 0))
        } else {
            $clean.Add('WinSxS component store analyze clean')
        }
    } else {
        $blocked.Add('DISM component store analysis skipped (requires elevation): run `dism /Online /Cleanup-Image /AnalyzeComponentStore`')
    }

    # One-level census of other fixed drives
    $otherDrives = [System.Collections.Generic.List[object]]::new()
    try {
        foreach ($vol in @(Get-Volume -ErrorAction SilentlyContinue | Where-Object { $_.DriveLetter -and $_.DriveType -eq 'Fixed' -and $_.DriveLetter -ne 'C' })) {
            $root = "$($vol.DriveLetter):\"
            if (Test-Path -LiteralPath $root) {
                foreach ($child in @(Get-ChildItem -LiteralPath $root -Force -ErrorAction SilentlyContinue | Select-Object -First 40)) {
                    if ($child.Name -match '(?i)(temp|cache|backup|archive|old|dump|models)') {
                        $cm = Measure-TreeFast -LiteralPath $child.FullName -TimeoutSeconds 3
                        $otherDrives.Add([PSCustomObject]@{ drive = $vol.DriveLetter; path = $child.FullName; bytes = $cm.bytes; size_human = (Format-Bytes $cm.bytes) })
                    }
                }
            }
        }
    } catch {}

    $raw = [ordered]@{
        caches         = $cacheTable
        temp_children  = $tempChildren
        vhdx_files     = $vhdxList
        unity_editors  = $unityEditors
        storage_sense  = $storageSense
        downloads_bytes = $downloadsBytes
        downloads_top  = $downloadsTop
        pagefiles      = $pagefiles
        other_drives   = $otherDrives
    }
    return [PSCustomObject]@{
        findings = $findings
        clean    = $clean
        blocked  = $blocked
        raw      = $raw
    }
}

<#
.SYNOPSIS
Manifest-driven Windows cleanup runner. Executes only safe-mechanical items whose preconditions pass.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Manifest,
    [string]$OutputDir = '',
    [switch]$DryRun,
    [switch]$Execute
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$commonDir = Join-Path $PSScriptRoot 'common'
. (Join-Path $commonDir 'windows-helpers.ps1')

if (-not (Test-Path -LiteralPath $Manifest)) {
    throw "Manifest file not found: $Manifest"
}

$isDryRun = if ($Execute) { $false } else { $true }
if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Split-Path -Parent ([System.IO.Path]::GetFullPath($Manifest))
}
[void](New-Item -ItemType Directory -Path $OutputDir -Force)
$logPath = Join-Path $OutputDir 'cleanup-log.jsonl'

$rawManifest = Get-Content -LiteralPath $Manifest -Raw -Encoding utf8
$items = @($rawManifest | ConvertFrom-Json)

function Get-VolumeFreeMap {
    $map = [ordered]@{}
    try {
        foreach ($v in @(Get-Volume -ErrorAction SilentlyContinue | Where-Object { $_.DriveLetter -and $_.DriveType -eq 'Fixed' })) {
            $map[[string]$v.DriveLetter] = [int64]$v.SizeRemaining
        }
    } catch {}
    return $map
}

function Test-ItemPrecondition {
    param(
        [Parameter(Mandatory)][string]$Precondition,
        [string]$TargetPath = ''
    )
    if ([string]::IsNullOrWhiteSpace($Precondition) -or $Precondition -eq 'none') {
        return [PSCustomObject]@{ ok = $true; reason = '' }
    }
    if ($Precondition -match '^process_stopped:(.+)$') {
        $procNames = $Matches[1] -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ }
        foreach ($pn in $procNames) {
            $running = @(Get-Process -Name $pn -ErrorAction SilentlyContinue)
            if ($running.Count -gt 0) {
                return [PSCustomObject]@{ ok = $false; reason = "Process '$pn' is currently running (PID $($running[0].Id))" }
            }
        }
        return [PSCustomObject]@{ ok = $true; reason = '' }
    }
    if ($Precondition -eq 'no_uv_lock') {
        $uvProcs = @(Get-Process -Name 'uv' -ErrorAction SilentlyContinue)
        if ($uvProcs.Count -gt 0) {
            return [PSCustomObject]@{ ok = $false; reason = "uv process is currently running (PID $($uvProcs[0].Id))" }
        }
        return [PSCustomObject]@{ ok = $true; reason = '' }
    }
    if ($Precondition -eq 'worktree_clean') {
        if ([string]::IsNullOrWhiteSpace($TargetPath) -or -not (Test-Path -LiteralPath $TargetPath)) {
            return [PSCustomObject]@{ ok = $false; reason = "Worktree path does not exist: $TargetPath" }
        }
        $statusLines = @(& git -C $TargetPath status --porcelain --untracked-files=all --ignore-submodules=none 2>$null)
        if ($LASTEXITCODE -ne 0 -or $statusLines.Count -gt 0) {
            return [PSCustomObject]@{ ok = $false; reason = "Worktree is dirty or unreadable ($($statusLines.Count) modified/untracked entries)" }
        }
        return [PSCustomObject]@{ ok = $true; reason = '' }
    }
    if ($Precondition -eq 'dir_empty') {
        if ([string]::IsNullOrWhiteSpace($TargetPath) -or -not (Test-Path -LiteralPath $TargetPath)) {
            return [PSCustomObject]@{ ok = $false; reason = "Directory does not exist: $TargetPath" }
        }
        $entries = @(Get-ChildItem -LiteralPath $TargetPath -Force -ErrorAction SilentlyContinue)
        if ($entries.Count -gt 0) {
            return [PSCustomObject]@{ ok = $false; reason = "Directory is not empty ($($entries.Count) entries)" }
        }
        return [PSCustomObject]@{ ok = $true; reason = '' }
    }
    return [PSCustomObject]@{ ok = $false; reason = "Unknown precondition: $Precondition" }
}

$freeBefore = Get-VolumeFreeMap
$hadRefusal = $false

$ExactDeleteDirKinds = @(
    'cache_sublime_index'
    'cache_nvidia_dxcache'
    'cache_nvidia_glcache'
    'cache_d3dscache'
    'cache_puppeteer'
    'cache_go_build'
    'worktree_empty_parent'
)

foreach ($item in $items) {
    $kind = if ($item.PSObject.Properties['kind']) { [string]$item.kind } else { 'unknown' }
    $what = if ($item.PSObject.Properties['what']) { [string]$item.what } else { $kind }
    $class = if ($item.PSObject.Properties['classification']) { [string]$item.classification } else { '' }
    $targetPath = if ($item.PSObject.Properties['path']) { [string]$item.path } else { '' }
    $action = if ($item.PSObject.Properties['action'] -and $item.action) { [string]$item.action } elseif ($item.PSObject.Properties['action_on_approval']) { [string]$item.action_on_approval } else { $targetPath }
    $precondition = if ($item.PSObject.Properties['precondition'] -and $item.precondition) { [string]$item.precondition } else { 'none' }

    # Refuse anything that is not safe-mechanical
    if ($class -ne 'safe-mechanical') {
        $msg = "REFUSED: '$what' ($kind) has classification '$class'; only 'safe-mechanical' items may be executed. Suggested command to run manually if approved: $action"
        Write-Warning $msg
        $logEntry = [ordered]@{
            timestamp    = (Get-Date).ToUniversalTime().ToString('o')
            item         = $what
            kind         = $kind
            path         = $targetPath
            action       = $action
            bytes_before = 0
            bytes_after  = 0
            outcome      = 'refused'
            stderr       = $msg
        }
        ($logEntry | ConvertTo-Json -Compress) | Add-Content -LiteralPath $logPath -Encoding utf8
        $hadRefusal = $true
        continue
    }

    # Trap guard: never run uv cache clean
    if ($action -match '\buv\s+cache\s+clean\b') {
        $msg = "REFUSED: '$what' ($kind) attempted 'uv cache clean'; only 'uv cache prune' is permitted."
        Write-Warning $msg
        $logEntry = [ordered]@{
            timestamp    = (Get-Date).ToUniversalTime().ToString('o')
            item         = $what
            kind         = $kind
            path         = $targetPath
            action       = $action
            bytes_before = 0
            bytes_after  = 0
            outcome      = 'refused'
            stderr       = $msg
        }
        ($logEntry | ConvertTo-Json -Compress) | Add-Content -LiteralPath $logPath -Encoding utf8
        $hadRefusal = $true
        continue
    }

    $preCheck = Test-ItemPrecondition -Precondition $precondition -TargetPath $targetPath
    if (-not $preCheck.ok) {
        $logEntry = [ordered]@{
            timestamp    = (Get-Date).ToUniversalTime().ToString('o')
            item         = $what
            kind         = $kind
            path         = $targetPath
            action       = $action
            bytes_before = 0
            bytes_after  = 0
            outcome      = 'skipped_precondition'
            stderr       = $preCheck.reason
        }
        ($logEntry | ConvertTo-Json -Compress) | Add-Content -LiteralPath $logPath -Encoding utf8
        continue
    }

    [int64]$bytesBefore = 0
    if (-not [string]::IsNullOrWhiteSpace($targetPath) -and (Test-Path -LiteralPath $targetPath)) {
        $bytesBefore = (Measure-TreeFast -LiteralPath $targetPath -TimeoutSeconds 5).bytes
    }

    if ($isDryRun) {
        $logEntry = [ordered]@{
            timestamp    = (Get-Date).ToUniversalTime().ToString('o')
            item         = $what
            kind         = $kind
            path         = $targetPath
            action       = $action
            bytes_before = $bytesBefore
            bytes_after  = $bytesBefore
            outcome      = 'dry_run'
            stderr       = ''
        }
        ($logEntry | ConvertTo-Json -Compress) | Add-Content -LiteralPath $logPath -Encoding utf8
        continue
    }

    # Execute safe-mechanical item
    $outcome = 'executed'
    $stderrStr = ''
    try {
        switch ($kind) {
            'worktree_prunable' {
                $r = Invoke-CommandWithTimeout -FilePath 'git' -ArgumentList @('-C', $targetPath, 'worktree', 'prune') -TimeoutSeconds 30
                if ($r.exit_code -ne 0) { $outcome = 'failed'; $stderrStr = $r.stderr }
            }
            'worktree_merged_clean' {
                $auditedTip = if ($item.PSObject.Properties['tip_sha']) { ([string]$item.tip_sha).Trim() } else { '' }
                $currentTip = "$(& git -C $targetPath rev-parse HEAD 2>$null)".Trim()
                $wtGitDir = "$(& git -C $targetPath rev-parse --absolute-git-dir 2>$null)".Trim()
                $isLocked = (-not [string]::IsNullOrWhiteSpace($wtGitDir)) -and (Test-Path -LiteralPath (Join-Path $wtGitDir 'locked'))
                if ([string]::IsNullOrWhiteSpace($auditedTip) -or $currentTip -ne $auditedTip) {
                    $outcome = 'refused'
                    $stderrStr = 'Worktree tip changed since audit; re-run the audit before removal'
                    $hadRefusal = $true
                } elseif ($isLocked) {
                    $outcome = 'refused'
                    $stderrStr = 'Worktree is locked; refusing double-force removal'
                    $hadRefusal = $true
                } else {
                    $r = Invoke-CommandWithTimeout -FilePath 'git' -ArgumentList @('-C', $targetPath, 'worktree', 'remove', '--force', '--force', $targetPath) -TimeoutSeconds 30
                    if ($r.exit_code -ne 0) { $outcome = 'failed'; $stderrStr = $r.stderr }
                }
            }
            'browser_cache_subdir' {
                $leaf = Split-Path -Leaf $targetPath
                if ($leaf -notin @('Cache', 'Code Cache', 'GPUCache')) {
                    $outcome = 'refused'
                    $stderrStr = "Refusing to delete '$targetPath': not a recognized browser cache subdirectory"
                    $hadRefusal = $true
                } elseif (Test-Path -LiteralPath $targetPath) {
                    Remove-Item -LiteralPath $targetPath -Recurse -Force -ErrorAction Stop
                } else {
                    $outcome = 'skipped_missing'
                }
            }
            'temp_file' {
                if (Test-Path -LiteralPath $targetPath -PathType Leaf) {
                    Remove-Item -LiteralPath $targetPath -Force -ErrorAction Stop
                } elseif (-not (Test-Path -LiteralPath $targetPath)) {
                    $outcome = 'skipped_missing'
                } else {
                    $outcome = 'refused'
                    $stderrStr = "temp_file target '$targetPath' is a directory; refusing recursive delete"
                    $hadRefusal = $true
                }
            }
            default {
                if ($ExactDeleteDirKinds -contains $kind) {
                    if (-not [string]::IsNullOrWhiteSpace($targetPath) -and (Test-Path -LiteralPath $targetPath)) {
                        Remove-Item -LiteralPath $targetPath -Recurse -Force -ErrorAction Stop
                    } else {
                        $outcome = 'skipped_missing'
                    }
                } else {
                    $outcome = 'refused'
                    $stderrStr = "No explicit cleanup handler for kind '$kind'; not touching '$targetPath'"
                    $hadRefusal = $true
                }
            }
        }
    } catch {
        $outcome = 'failed'
        $stderrStr = $_.Exception.Message
    }

    [int64]$bytesAfter = 0
    if (-not [string]::IsNullOrWhiteSpace($targetPath) -and (Test-Path -LiteralPath $targetPath)) {
        $bytesAfter = (Measure-TreeFast -LiteralPath $targetPath -TimeoutSeconds 5).bytes
    }

    $logEntry = [ordered]@{
        timestamp    = (Get-Date).ToUniversalTime().ToString('o')
        item         = $what
        kind         = $kind
        path         = $targetPath
        action       = $action
        bytes_before = $bytesBefore
        bytes_after  = $bytesAfter
        outcome      = $outcome
        stderr       = $stderrStr
    }
    ($logEntry | ConvertTo-Json -Compress) | Add-Content -LiteralPath $logPath -Encoding utf8
}

$freeAfter = Get-VolumeFreeMap
$volSummary = [ordered]@{
    timestamp   = (Get-Date).ToUniversalTime().ToString('o')
    kind        = 'volume_free_space'
    dry_run     = $isDryRun
    free_before = $freeBefore
    free_after  = $freeAfter
}
($volSummary | ConvertTo-Json -Compress) | Add-Content -LiteralPath $logPath -Encoding utf8

if ($hadRefusal) {
    exit 2
}
exit 0

<#
.SYNOPSIS
Read-only Windows host maintenance audit across disk, repos, processes, env, harness, and os.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$OutputDir,
    [string[]]$Sections = @('disk', 'repos', 'processes', 'env', 'harness', 'os'),
    [string[]]$RepoRoots = @(),
    [int]$MaxDepth = 1,
    [switch]$SkipElevated,
    [string]$ForgeToken = '',
    [string]$TrustedForgeBaseUrl = '',
    [switch]$Json
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$commonDir = Join-Path $PSScriptRoot 'common'
. (Join-Path $commonDir 'windows-helpers.ps1')
. (Join-Path $commonDir 'windows-disk.ps1')
. (Join-Path $commonDir 'windows-repos.ps1')
. (Join-Path $commonDir 'windows-processes.ps1')
. (Join-Path $commonDir 'windows-env.ps1')
. (Join-Path $commonDir 'windows-harness.ps1')
. (Join-Path $commonDir 'windows-os.ps1')

$normalizedSections = [System.Collections.Generic.List[string]]::new()
foreach ($s in $Sections) {
    foreach ($part in ($s -split ',')) {
        $trimmed = $part.Trim().ToLowerInvariant()
        if ($trimmed -eq 'all') {
            foreach ($a in @('disk', 'repos', 'processes', 'env', 'harness', 'os')) {
                if (-not $normalizedSections.Contains($a)) { $normalizedSections.Add($a) }
            }
        } elseif ($trimmed -and -not $normalizedSections.Contains($trimmed)) {
            $normalizedSections.Add($trimmed)
        }
    }
}

$outFull = [System.IO.Path]::GetFullPath($OutputDir)
$rawDir = Join-Path $outFull 'raw'
[void](New-Item -ItemType Directory -Path $outFull -Force)
[void](New-Item -ItemType Directory -Path $rawDir -Force)

$homeDir = if ($env:USERPROFILE) { $env:USERPROFILE } else { [Environment]::GetFolderPath('UserProfile') }
$localAppData = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { Join-Path $homeDir 'AppData\Local' }
$isElevated = Test-IsAdmin

$allFindings = [System.Collections.Generic.List[object]]::new()
$allClean = [System.Collections.Generic.List[string]]::new()
$allBlocked = [System.Collections.Generic.List[string]]::new()
$sectionRaw = [ordered]@{}

foreach ($sec in $normalizedSections) {
    $res = switch ($sec) {
        'disk'      { Invoke-DiskAudit -HomeDir $homeDir -LocalAppData $localAppData -MaxDepth $MaxDepth -IsElevated $isElevated -SkipElevated ([bool]$SkipElevated) }
        'repos'     { Invoke-ReposAudit -HomeDir $homeDir -LocalAppData $localAppData -RepoRoots $RepoRoots -ForgeToken $ForgeToken -TrustedForgeBaseUrl $TrustedForgeBaseUrl }
        'processes' { Invoke-ProcessesAudit -HomeDir $homeDir }
        'env'       { Invoke-EnvAudit -HomeDir $homeDir }
        'harness'   { Invoke-HarnessAudit -HomeDir $homeDir }
        'os'        { Invoke-OsAudit -IsElevated $isElevated -SkipElevated ([bool]$SkipElevated) }
        default     { throw "Unknown section: $sec" }
    }
    foreach ($f in $res.findings) { $allFindings.Add($f) }
    foreach ($c in $res.clean) { $allClean.Add("[$sec] $c") }
    foreach ($b in $res.blocked) { $allBlocked.Add("[$sec] $b") }
    $sectionRaw[$sec] = $res.raw

    $rawJsonPath = Join-Path $rawDir "$sec.json"
    ($res.raw | ConvertTo-Json -Depth 10) | Set-Content -LiteralPath $rawJsonPath -Encoding utf8
}

$findingsJsonPath = Join-Path $outFull 'findings.json'
ConvertTo-Json -InputObject @($allFindings) -Depth 10 | Set-Content -LiteralPath $findingsJsonPath -Encoding utf8

# Build Summary bullets
[int64]$safeReclaimBytes = 0
foreach ($f in $allFindings) {
    if ($f.classification -eq 'safe-mechanical' -and $f.reclaim_bytes -gt 0) {
        $safeReclaimBytes += [int64]$f.reclaim_bytes
    }
}

$topCachesText = 'not run'
if ($sectionRaw.Contains('disk') -and $sectionRaw['disk'].caches) {
    $topCaches = @($sectionRaw['disk'].caches | Sort-Object bytes -Descending | Select-Object -First 4 | ForEach-Object { "$($_.name) ($($_.size_human))" })
    $topCachesText = if ($topCaches.Count -gt 0) { $topCaches -join ', ' } else { 'none over threshold' }
}

$pathKindText = 'not run'
if ($sectionRaw.Contains('env')) {
    $er = $sectionRaw['env']
    $pathKindText = "User Path kind=$($er.user_path_kind) ($($er.user_path_entries) entries, $($er.user_path_length) chars), Machine Path kind=$($er.machine_path_kind) ($($er.machine_path_entries) entries, $($er.machine_path_length) chars), DOTNET_ADD_GLOBAL_TOOLS_TO_PATH User=$($er.user_dotnet_guard) Machine=$($er.machine_dotnet_guard)"
}

$worktreeText = 'not run'
if ($sectionRaw.Contains('repos')) {
    $rr = $sectionRaw['repos']
    $worktreeText = "Stale worktrees: $($rr.stale_worktree_count) across $($rr.repo_count) repositories ($($rr.gone_branch_total) [gone] branches, $($rr.master_repo_count) repos on master)"
}

$w32tmText = 'not run'
if ($sectionRaw.Contains('os')) {
    $or = $sectionRaw['os']
    $syncLabel = if ($or.w32tm_synced) { 'synced' } else { 'unsynced' }
    $w32tmText = "w32tm sync state: $syncLabel (Source: $($or.w32tm_source))"
}

$reportLines = [System.Collections.Generic.List[string]]::new()
$reportLines.Add('# Machine Maintenance Audit Report')
$reportLines.Add('')
$reportLines.Add('## Summary')
$reportLines.Add('')
$reportLines.Add("- **Findings and reclaimable space:** $($allFindings.Count) total findings; $(Format-Bytes $safeReclaimBytes) safe-mechanical reclaimable. Largest cache candidates: $topCachesText.")
$reportLines.Add("- **PATH value kind and environment:** $pathKindText.")
$reportLines.Add("- **Repositories and worktrees:** $worktreeText.")
$reportLines.Add("- **OS and clock health:** $w32tmText.")
$reportLines.Add('')
$reportLines.Add('## Findings')
$reportLines.Add('')

if ($allFindings.Count -eq 0) {
    $reportLines.Add('No findings surfaced across the selected sections.')
    $reportLines.Add('')
} else {
    $idx = 1
    foreach ($sec in $normalizedSections) {
        $secFindings = @($allFindings | Where-Object { $_.section -eq $sec })
        if ($secFindings.Count -eq 0) { continue }
        $reportLines.Add("### Section: $sec")
        $reportLines.Add('')
        foreach ($f in $secFindings) {
            $impactStr = if ($f.reclaim_bytes -gt 0) { "$(Format-Bytes $f.reclaim_bytes) reclaimable" } else { $f.classification }
            $reportLines.Add("#### F${idx}: $($f.what)")
            $reportLines.Add('')
            $reportLines.Add("- **What:** $($f.what)")
            $reportLines.Add("- **Classification:** $($f.classification)")
            $reportLines.Add("- **Path:** $($f.path)")
            $reportLines.Add("- **Evidence:** $($f.evidence)")
            $reportLines.Add("- **Impact:** $impactStr")
            $reportLines.Add("- **Recommendation:** $($f.recommendation)")
            $reportLines.Add("- **Confidence:** $($f.confidence)")
            $reportLines.Add("- **Precondition:** $($f.precondition)")
            $reportLines.Add("- **Action on approval:** ``$($f.action_on_approval)``")
            $reportLines.Add('')
            $idx++
        }
    }
}

$reportLines.Add('## Checked and clean')
$reportLines.Add('')
if ($allClean.Count -eq 0) {
    $reportLines.Add('- None recorded.')
} else {
    foreach ($c in $allClean) {
        $reportLines.Add("- $c")
    }
}
$reportLines.Add('')
$reportLines.Add('## Blocked or skipped')
$reportLines.Add('')
if ($allBlocked.Count -eq 0) {
    $reportLines.Add('- None.')
} else {
    foreach ($b in $allBlocked) {
        $reportLines.Add("- $b")
    }
}

$reportPath = Join-Path $outFull 'report.md'
($reportLines -join "`n") | Set-Content -LiteralPath $reportPath -Encoding utf8
Write-Output "Audit complete. Findings: $($allFindings.Count). Report: $reportPath"

# Windows fleet repository, branch, and worktree sweep section.
Set-StrictMode -Version Latest

function Test-SquashMergedTip {
    param(
        [Parameter(Mandatory)][string]$RepoPath,
        [Parameter(Mandatory)][string]$TipSha,
        [Parameter(Mandatory)][string]$ForgeToken
    )
    if ([string]::IsNullOrWhiteSpace($ForgeToken)) {
        return $false
    }
    try {
        $remoteUrl = (& git -C $RepoPath remote get-url origin 2>$null)
        if (-not $remoteUrl -or $remoteUrl -notmatch '^(https?://[^/]+)/([^/]+)/([^/.]+?)(\.git)?$') {
            return $false
        }
        $baseUrl = $Matches[1]
        $owner = $Matches[2]
        $repo = $Matches[3]
        $headers = @{ Authorization = "token $ForgeToken" }
        $apiUrl = "$baseUrl/api/v1/repos/$owner/$repo/pulls?state=closed&limit=50"
        $prs = Invoke-RestMethod -Uri $apiUrl -Headers $headers -Method Get -TimeoutSec 10 -ErrorAction Stop
        $mergedHeads = [System.Collections.Generic.List[string]]::new()
        foreach ($pr in @($prs)) {
            if ($pr.merged -and $pr.head -and $pr.head.sha) {
                (& git -C $RepoPath cat-file -e "$($pr.head.sha)^{commit}" 2>$null)
                if ($LASTEXITCODE -eq 0) {
                    $mergedHeads.Add([string]$pr.head.sha)
                }
            }
        }
        if ($mergedHeads.Count -eq 0) {
            return $false
        }
        $stdinLines = @($TipSha, '--not', 'origin/main') + $mergedHeads
        $revCount = ($stdinLines | & git -C $RepoPath rev-list --stdin --count 2>$null)
        if ($LASTEXITCODE -eq 0 -and ($revCount -as [int]) -eq 0) {
            return $true
        }
    } catch {}
    return $false
}

function Invoke-ReposAudit {
    param(
        [Parameter(Mandatory)][string]$HomeDir,
        [Parameter(Mandatory)][string]$LocalAppData,
        [string[]]$RepoRoots = @(),
        [string]$ForgeToken = ''
    )
    $findings = [System.Collections.Generic.List[object]]::new()
    $clean = [System.Collections.Generic.List[string]]::new()
    $blocked = [System.Collections.Generic.List[string]]::new()

    if (-not $RepoRoots -or $RepoRoots.Count -eq 0) {
        $RepoRoots = @($HomeDir)
    }

    $repoDirs = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($root in $RepoRoots) {
        if (-not (Test-Path -LiteralPath $root)) { continue }
        foreach ($dir in @(Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue)) {
            if ($dir.Name -like '*-worktrees') { continue }
            $gitEntry = Join-Path $dir.FullName '.git'
            if (Test-Path -LiteralPath $gitEntry) {
                [void]$repoDirs.Add($dir.FullName)
            }
        }
    }

    $repoSummaries = [System.Collections.Generic.List[object]]::new()
    $worktreeSummaries = [System.Collections.Generic.List[object]]::new()
    [int]$staleWorktreeCount = 0
    [int]$goneBranchTotal = 0
    [int]$masterRepoCount = 0

    foreach ($repo in ($repoDirs | Sort-Object)) {
        $branch = (& git -C $repo rev-parse --abbrev-ref HEAD 2>$null)
        if ($LASTEXITCODE -ne 0) {
            $findings.Add((New-Finding -Section 'repos' -Kind 'repo_corrupt_git' -What "Corrupt or unreadable .git in $repo" -Path $repo -Evidence 'git rev-parse HEAD failed' -Recommendation 'needs_human_judgment' -Confidence 'high' -Rationale 'Broken git directory cannot be inspected normally' -ActionOnApproval "Inspect $repo\.git" -Classification 'needs-judgment'))
            continue
        }
        $dirtyLines = @(& git -C $repo status --porcelain 2>$null)
        $dirtyCount = $dirtyLines.Count

        $branchLines = @(& git -C $repo branch --format='%(refname:short)|%(upstream:track)|%(committerdate:iso8601)' 2>$null)
        $goneBranches = [System.Collections.Generic.List[string]]::new()
        foreach ($bl in $branchLines) {
            $parts = $bl -split '\|', 3
            if ($parts.Count -ge 2 -and $parts[1] -match '\[gone\]') {
                $goneBranches.Add($parts[0])
            }
        }
        $goneBranchTotal += $goneBranches.Count
        if ($goneBranches.Count -gt 0) {
            $findings.Add((New-Finding -Section 'repos' -Kind 'repo_gone_branches' -What "$($goneBranches.Count) [gone] branch(es) in $(Split-Path -Leaf $repo)" -Path $repo -Evidence "Branches with deleted upstream: $($goneBranches -join ', ')" -Recommendation 'needs_human_judgment' -Confidence 'medium' -Rationale 'Verify whether [gone] branches were squash-merged before deleting' -ActionOnApproval "git -C '$repo' branch -d $($goneBranches -join ' ')" -Classification 'needs-judgment'))
        }

        if ($branch -eq 'master') {
            $masterRepoCount++
        }

        # Check registered worktrees and prunable entries
        $wtPorcelain = @(& git -C $repo worktree list --porcelain 2>$null)
        $prunableCount = 0
        foreach ($line in $wtPorcelain) {
            if ($line -match '^prunable ') {
                $prunableCount++
            }
        }
        if ($prunableCount -gt 0) {
            $staleWorktreeCount += $prunableCount
            $findings.Add((New-Finding -Section 'repos' -Kind 'worktree_prunable' -What "$prunableCount prunable worktree registration(s) in $(Split-Path -Leaf $repo)" -Path $repo -Evidence "git worktree list --porcelain reported $prunableCount prunable entry/entries" -Recommendation 'delete' -Confidence 'high' -Rationale 'Worktree directory is already gone on disk; prune removes stale .git/worktrees metadata' -ActionOnApproval "git -C '$repo' worktree prune" -Classification 'safe-mechanical'))
        }

        $repoSummaries.Add([PSCustomObject]@{
            path           = $repo
            branch         = "$branch"
            dirty_files    = $dirtyCount
            local_branches = $branchLines.Count
            gone_branches  = $goneBranches.Count
            prunable_wts   = $prunableCount
        })
    }

    # Sibling *-worktrees directories
    foreach ($wtParent in @(Get-ChildItem -LiteralPath $HomeDir -Directory -Filter '*-worktrees' -ErrorAction SilentlyContinue)) {
        $children = @(Get-ChildItem -LiteralPath $wtParent.FullName -Force -ErrorAction SilentlyContinue)
        if ($children.Count -eq 0) {
            $staleWorktreeCount++
            $findings.Add((New-Finding -Section 'repos' -Kind 'worktree_empty_parent' -What "Empty worktree parent directory $($wtParent.Name)" -Path $wtParent.FullName -Evidence "$($wtParent.FullName) contains 0 entries" -Recommendation 'delete' -Confidence 'high' -Rationale 'Empty *-worktrees container directory left after worktree removal' -ActionOnApproval "Remove-Item -LiteralPath '$($wtParent.FullName)' -Force" -Classification 'safe-mechanical' -Precondition 'dir_empty'))
            continue
        }
        $parentRepoName = $wtParent.Name -replace '-worktrees$', ''
        $parentRepoPath = Join-Path $HomeDir $parentRepoName
        foreach ($wtDir in @($children | Where-Object { $_.PSIsContainer })) {
            $wtPath = $wtDir.FullName
            if ($wtPath -eq $PSScriptRoot -or $PSScriptRoot.StartsWith($wtPath, [System.StringComparison]::OrdinalIgnoreCase)) {
                # Skip the active checkout running this script
                continue
            }
            $wtBranch = (& git -C $wtPath rev-parse --abbrev-ref HEAD 2>$null)
            $wtTip = (& git -C $wtPath rev-parse HEAD 2>$null)
            $wtDirty = @(& git -C $wtPath status --porcelain 2>$null).Count
            $isAncestor = $false
            if ($wtTip) {
                (& git -C $wtPath merge-base --is-ancestor HEAD origin/main 2>$null)
                if ($LASTEXITCODE -eq 0) { $isAncestor = $true }
            }
            $isSquashMerged = $false
            if (-not $isAncestor -and $wtTip -and -not [string]::IsNullOrWhiteSpace($ForgeToken) -and (Test-Path -LiteralPath $parentRepoPath)) {
                $isSquashMerged = Test-SquashMergedTip -RepoPath $parentRepoPath -TipSha "$wtTip" -ForgeToken $ForgeToken
            }

            $statusClass = if ($wtDirty -gt 0) {
                'unmerged-WIP'
            } elseif ($isAncestor -or $isSquashMerged) {
                'merged-safe-to-remove'
            } elseif ([string]::IsNullOrWhiteSpace($ForgeToken)) {
                'unknown'
            } else {
                'unmerged-WIP'
            }

            $worktreeSummaries.Add([PSCustomObject]@{
                path           = $wtPath
                parent_repo    = $parentRepoPath
                branch         = "$wtBranch"
                dirty_files    = $wtDirty
                classification = $statusClass
            })

            if ($statusClass -eq 'merged-safe-to-remove') {
                $staleWorktreeCount++
                $findings.Add((New-Finding -Section 'repos' -Kind 'worktree_merged_clean' -What "Merged clean worktree $($wtDir.Name) ($wtBranch)" -Path $wtPath -Evidence "Clean working tree; branch tip $wtTip is merged into origin/main" -Recommendation 'delete' -Confidence 'high' -Rationale 'Worktree is clean and its commits have landed on origin/main; use double --force in case of submodules' -ActionOnApproval "git -C '$parentRepoPath' worktree remove --force --force '$wtPath'" -Classification 'safe-mechanical' -Precondition 'worktree_clean'))
            } else {
                $staleWorktreeCount++
                $findings.Add((New-Finding -Section 'repos' -Kind 'worktree_needs_review' -What "Worktree $($wtDir.Name) ($wtBranch, status: $statusClass, dirty: $wtDirty)" -Path $wtPath -Evidence "Parent: $parentRepoPath, branch: $wtBranch, dirty files: $wtDirty, classification: $statusClass" -Recommendation 'needs_human_judgment' -Confidence 'medium' -Rationale 'Worktree has uncommitted changes or non-ancestor commits requiring diff review or -ForgeToken squash-merge verification' -ActionOnApproval "git -C '$wtPath' status -sb; git -C '$wtPath' diff origin/main..HEAD --stat" -Classification 'needs-judgment'))
            }
        }
    }

    # Check stray git worktrees/clones in Temp (one level deep)
    $tempRoot = Join-Path $LocalAppData 'Temp'
    $tempGitDirs = [System.Collections.Generic.List[string]]::new()
    if (Test-Path -LiteralPath $tempRoot) {
        foreach ($td in @(Get-ChildItem -LiteralPath $tempRoot -Directory -ErrorAction SilentlyContinue)) {
            if (Test-Path -LiteralPath (Join-Path $td.FullName '.git')) {
                $tempGitDirs.Add($td.FullName)
            }
        }
        if ($tempGitDirs.Count -gt 0) {
            $staleWorktreeCount += $tempGitDirs.Count
            $findings.Add((New-Finding -Section 'repos' -Kind 'temp_stray_git_dirs' -What "$($tempGitDirs.Count) stray git checkout(s)/worktree(s) in %TEMP%" -Path $tempRoot -Evidence "Found .git in $($tempGitDirs.Count) top-level %TEMP% directories" -Recommendation 'needs_human_judgment' -Confidence 'medium' -Rationale 'Temporary git clones/worktrees in %TEMP% outlive test runs' -ActionOnApproval "Inspect and remove stray git directories under $tempRoot" -Classification 'needs-judgment'))
        }
    }

    if ($staleWorktreeCount -eq 0) {
        $clean.Add("No stale worktrees found across $($repoSummaries.Count) repositories")
    }

    $raw = [ordered]@{
        repo_count           = $repoSummaries.Count
        master_repo_count    = $masterRepoCount
        gone_branch_total    = $goneBranchTotal
        stale_worktree_count = $staleWorktreeCount
        temp_git_dir_count   = $tempGitDirs.Count
        repos                = $repoSummaries
        worktrees            = $worktreeSummaries
    }
    return [PSCustomObject]@{
        findings = $findings
        clean    = $clean
        blocked  = $blocked
        raw      = $raw
    }
}

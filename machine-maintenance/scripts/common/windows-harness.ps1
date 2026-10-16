# Windows AI coding-agent harness configuration audit section.
Set-StrictMode -Version Latest

function Invoke-HarnessAudit {
    param(
        [Parameter(Mandatory)][string]$HomeDir
    )
    $findings = [System.Collections.Generic.List[object]]::new()
    $clean = [System.Collections.Generic.List[string]]::new()
    $blocked = [System.Collections.Generic.List[string]]::new()

    # 1. Claude Code settings and hooks
    $claudeSettingsPath = Join-Path $HomeDir '.claude\settings.json'
    $missingHookPaths = [System.Collections.Generic.List[string]]::new()
    $hooksWithoutTimeout = [System.Collections.Generic.List[string]]::new()

    if (Test-Path -LiteralPath $claudeSettingsPath) {
        try {
            $settingsObj = Get-Content -LiteralPath $claudeSettingsPath -Raw -Encoding utf8 | ConvertFrom-Json
            if ($settingsObj.PSObject.Properties['hooks'] -and $settingsObj.hooks) {
                foreach ($eventProp in $settingsObj.hooks.PSObject.Properties) {
                    foreach ($matcherGroup in @($eventProp.Value)) {
                        foreach ($h in @($matcherGroup.hooks)) {
                            $cmdStr = [string]$h.command
                            $hasTimeout = ($h.PSObject.Properties['timeout'] -and $null -ne $h.timeout -and [int]$h.timeout -gt 0)
                            if (-not $hasTimeout) {
                                $hooksWithoutTimeout.Add("$($eventProp.Name): $cmdStr")
                            }
                            if ($cmdStr -match '([A-Za-z]:\\[^\s"'']+|\$HOME[/\\][^\s"'']+|~[/\\][^\s"'']+)') {
                                $candidate = $Matches[1] -replace '^(\$HOME|~)', $HomeDir
                                $candidate = $candidate.Replace('/', '\')
                                if ($candidate -match '\.(sh|ps1|py|exe|cmd|bat)$' -and -not (Test-Path -LiteralPath $candidate)) {
                                    $missingHookPaths.Add("$($eventProp.Name): $candidate")
                                }
                            }
                        }
                    }
                }
            }
        } catch {
            $blocked.Add("Failed to parse ${claudeSettingsPath}: $($_.Exception.Message)")
        }
    }

    if ($missingHookPaths.Count -gt 0) {
        $findings.Add((New-Finding -Section 'harness' -Kind 'claude_hook_missing_script' -What "$($missingHookPaths.Count) Claude Code hook command(s) point to missing files" -Path $claudeSettingsPath -Evidence ($missingHookPaths -join '; ') -Recommendation 'needs_human_judgment' -Confidence 'high' -Rationale 'Broken hook paths cause tool or worktree operations to fail' -ActionOnApproval "Fix or remove broken hook entries in $claudeSettingsPath" -Classification 'needs-judgment'))
    } else {
        $clean.Add('All referenced script/executable paths in ~/.claude/settings.json hooks exist')
    }

    if ($hooksWithoutTimeout.Count -gt 0) {
        $findings.Add((New-Finding -Section 'harness' -Kind 'claude_hook_no_timeout' -What "$($hooksWithoutTimeout.Count) Claude Code hook(s) have no timeout configured" -Path $claudeSettingsPath -Evidence "Missing timeout on $($hooksWithoutTimeout.Count) hook(s)" -Recommendation 'needs_human_judgment' -Confidence 'medium' -Rationale 'Hooks running on every tool call without a timeout can stall sessions indefinitely if a helper hangs' -ActionOnApproval "Add explicit timeout (e.g. 10) to hook entries in $claudeSettingsPath" -Classification 'needs-judgment'))
    } else {
        $clean.Add('All Claude Code hooks in ~/.claude/settings.json specify a timeout')
    }

    # 2. MCP servers and stale project keys in ~/.claude.json
    $claudeJsonPath = Join-Path $HomeDir '.claude.json'
    $staleProjectKeys = [System.Collections.Generic.List[string]]::new()
    $unresolvedMcp = [System.Collections.Generic.List[string]]::new()
    if (Test-Path -LiteralPath $claudeJsonPath) {
        try {
            $cj = Get-Content -LiteralPath $claudeJsonPath -Raw -Encoding utf8 | ConvertFrom-Json
            if ($cj.PSObject.Properties['mcpServers'] -and $cj.mcpServers) {
                foreach ($mp in $cj.mcpServers.PSObject.Properties) {
                    $srvCmd = [string]$mp.Value.command
                    if (-not [string]::IsNullOrWhiteSpace($srvCmd)) {
                        $resolved = Get-Command -Name $srvCmd -ErrorAction SilentlyContinue
                        if (-not $resolved -and -not (Test-Path -LiteralPath $srvCmd)) {
                            $unresolvedMcp.Add("$($mp.Name): $srvCmd")
                        }
                    }
                }
            }
            if ($cj.PSObject.Properties['projects'] -and $cj.projects) {
                foreach ($projProp in $cj.projects.PSObject.Properties) {
                    $projPath = $projProp.Name
                    if (-not (Test-Path -LiteralPath $projPath)) {
                        $staleProjectKeys.Add($projPath)
                    }
                }
            }
        } catch {
            $blocked.Add("Failed to parse ${claudeJsonPath}: $($_.Exception.Message)")
        }
    }

    if ($unresolvedMcp.Count -gt 0) {
        $findings.Add((New-Finding -Section 'harness' -Kind 'mcp_command_unresolved' -What "$($unresolvedMcp.Count) MCP server command(s) in ~/.claude.json do not resolve" -Path $claudeJsonPath -Evidence ($unresolvedMcp -join '; ') -Recommendation 'needs_human_judgment' -Confidence 'high' -Rationale 'Unresolvable MCP commands fail on every session launch' -ActionOnApproval "Fix MCP server command paths in $claudeJsonPath" -Classification 'needs-judgment'))
    } else {
        $clean.Add('All top-level MCP server commands in ~/.claude.json resolve')
    }

    if ($staleProjectKeys.Count -gt 0) {
        $findings.Add((New-Finding -Section 'harness' -Kind 'claude_json_stale_projects' -What "$($staleProjectKeys.Count) stale project key(s) in ~/.claude.json point to deleted directories" -Path $claudeJsonPath -Evidence ($staleProjectKeys -join '; ') -Recommendation 'needs_human_judgment' -Confidence 'medium' -Rationale 'Deleted worktree and project keys bloat ~/.claude.json' -ActionOnApproval "Back up $claudeJsonPath and remove deleted keys from .projects" -Classification 'needs-judgment'))
    } else {
        $clean.Add('No stale project keys in ~/.claude.json')
    }

    # 3. Plugin cache versions not in registry
    $pluginsDir = Join-Path $HomeDir '.claude\plugins'
    $installedPluginsPath = Join-Path $pluginsDir 'installed_plugins.json'
    $pluginCacheDir = Join-Path $pluginsDir 'cache'
    $stalePluginCachePaths = [System.Collections.Generic.List[string]]::new()
    [int64]$stalePluginCacheBytes = 0
    if ((Test-Path -LiteralPath $installedPluginsPath) -and (Test-Path -LiteralPath $pluginCacheDir)) {
        try {
            $regRaw = Get-Content -LiteralPath $installedPluginsPath -Raw -Encoding utf8
            foreach ($child in @(Get-ChildItem -LiteralPath $pluginCacheDir -Force -ErrorAction SilentlyContinue)) {
                if ($child.Name -like 'temp_git_*') {
                    $m = Measure-TreeFast -LiteralPath $child.FullName -TimeoutSeconds 2
                    $stalePluginCacheBytes += $m.bytes
                    $stalePluginCachePaths.Add($child.FullName)
                }
            }
        } catch {}
    }
    if ($stalePluginCachePaths.Count -gt 0) {
        foreach ($sp in $stalePluginCachePaths) {
            $findings.Add((New-Finding -Section 'harness' -Kind 'plugin_cache_stale' -What "Leftover plugin cache temp directory $(Split-Path -Leaf $sp)" -Path $sp -Evidence "$sp ($(Format-Bytes $stalePluginCacheBytes))" -Recommendation 'delete' -Confidence 'high' -Rationale 'Aborted temp_git clone in ~/.claude/plugins/cache' -ActionOnApproval "Remove-Item -LiteralPath '$sp' -Recurse -Force" -Classification 'safe-mechanical' -ReclaimBytes $stalePluginCacheBytes -Precondition 'none'))
        }
    }

    # 4. Retired model IDs (gpt-5.6, terra, or any -fast variant)
    $retiredModelHits = [System.Collections.Generic.List[string]]::new()
    $configFiles = @(
        (Join-Path $HomeDir '.config\opencode\opencode.json'),
        (Join-Path $HomeDir '.qwen\settings.json'),
        (Join-Path $HomeDir '.codex\config.toml'),
        (Join-Path $HomeDir '.pr-crew\config.toml')
    )
    foreach ($cf in $configFiles) {
        if (-not (Test-Path -LiteralPath $cf)) { continue }
        try {
            $text = Get-Content -LiteralPath $cf -Raw -Encoding utf8 -ErrorAction Stop
            if ($text -match '(?i)(gpt-5\.6|terra|[a-z0-9.]+-fast\b)') {
                $retiredModelHits.Add("${cf}: matches '$($Matches[1])'")
            }
        } catch {}
    }
    if ($retiredModelHits.Count -gt 0) {
        $findings.Add((New-Finding -Section 'harness' -Kind 'harness_retired_model_ids' -What "$($retiredModelHits.Count) harness config file(s) reference retired or -fast model IDs" -Path '' -Evidence ($retiredModelHits -join '; ') -Recommendation 'needs_human_judgment' -Confidence 'high' -Rationale 'gpt-5.6, terra, and -fast model variants are retired by policy; replace with current model tier pins' -ActionOnApproval 'Update model pins in harness configs (use onboard apply model-policy for opencode when idle)' -Classification 'needs-judgment'))
    } else {
        $clean.Add('No retired model IDs (gpt-5.6, terra, -fast) found in harness configs')
    }

    # 5. npm outdated -g --json
    $npmOutdated = [ordered]@{}
    $npmRes = Invoke-CommandWithTimeout -FilePath 'npm' -ArgumentList @('outdated', '-g', '--json') -TimeoutSeconds 15
    if ($npmRes.stdout -and $npmRes.stdout.StartsWith('{')) {
        try {
            $parsedNpm = $npmRes.stdout | ConvertFrom-Json
            foreach ($p in $parsedNpm.PSObject.Properties) {
                $npmOutdated[$p.Name] = [ordered]@{
                    current = $p.Value.current
                    wanted  = $p.Value.wanted
                    latest  = $p.Value.latest
                }
            }
        } catch {}
    }
    if ($npmOutdated.Count -gt 0) {
        $pkgList = ($npmOutdated.Keys | ForEach-Object { "$_ ($($npmOutdated[$_].current) -> $($npmOutdated[$_].latest))" }) -join ', '
        $findings.Add((New-Finding -Section 'harness' -Kind 'npm_global_outdated' -What "$($npmOutdated.Count) global npm package(s) have newer versions" -Path '' -Evidence $pkgList -Recommendation 'needs_human_judgment' -Confidence 'medium' -Rationale 'Global CLI tools have updates available' -ActionOnApproval 'Review and update global npm packages with npm install -g <pkg>@latest when idle' -Classification 'needs-judgment'))
    } else {
        $clean.Add('Global npm packages are up to date')
    }

    $raw = [ordered]@{
        missing_hook_paths    = $missingHookPaths
        hooks_without_timeout = $hooksWithoutTimeout
        unresolved_mcp        = $unresolvedMcp
        stale_project_keys    = $staleProjectKeys
        stale_plugin_cache    = $stalePluginCachePaths
        retired_model_hits    = $retiredModelHits
        npm_global_outdated   = $npmOutdated
    }
    return [PSCustomObject]@{
        findings = $findings
        clean    = $clean
        blocked  = $blocked
        raw      = $raw
    }
}

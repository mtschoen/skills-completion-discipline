<#
.SYNOPSIS
    Starts a wrap chain successor as an interactive Claude Code session.

.DESCRIPTION
    Runs inside the new terminal window that chain mode opens (see references/chain.md). It removes the
    variables the window inherited from the launching session's tool environment, then starts Claude Code
    with the launching session's model and permission mode and the resume prompt read from a file.

    The scrub is required. A tool call's environment carries NO_COLOR=1 (the successor would render
    without colors) and the launching session's CLAUDE_CODE_* identity (the successor would not register
    under its own name in `claude agents`).

.PARAMETER Name
    Session name for the successor (`claude -n`).

.PARAMETER Model
    Model alias or id the launching session runs on (`claude --model`). Mandatory, so the successor never
    falls back to the settings default model.

.PARAMETER PermissionMode
    Permission mode the launching session runs in (`claude --permission-mode`).

.PARAMETER PromptFile
    Path of the file holding the resume prompt.
#>
param(
    [Parameter(Mandatory)][ValidateNotNullOrEmpty()][string]$Name,
    [Parameter(Mandatory)][ValidateNotNullOrEmpty()][string]$Model,
    [Parameter(Mandatory)][ValidateNotNullOrEmpty()][string]$PermissionMode,
    [Parameter(Mandatory)][ValidateNotNullOrEmpty()][string]$PromptFile
)

$ErrorActionPreference = 'Stop'

$inheritedNames = 'CLAUDECODE', 'CLAUDE_PID', 'NO_COLOR', 'FORCE_COLOR'
Get-ChildItem env: |
    Where-Object { $_.Name -like 'CLAUDE_CODE_*' -or $_.Name -in $inheritedNames } |
    ForEach-Object { Remove-Item "env:$($_.Name)" }

$prompt = Get-Content -LiteralPath $PromptFile -Raw -ErrorAction Stop
if ([string]::IsNullOrWhiteSpace($prompt)) {
    throw "Resume prompt file '$PromptFile' is empty or contains only whitespace."
}

claude -n $Name --model $Model --permission-mode $PermissionMode $prompt

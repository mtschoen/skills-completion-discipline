<#
.SYNOPSIS
    Starts a wrap chain successor as an interactive Claude Code session.

.DESCRIPTION
    Runs inside the new terminal window that chain mode opens (see references/chain.md). It removes the
    variables the window inherited from the launching session's tool environment, then starts Claude Code
    with the resume prompt read from a file.

    The scrub is required. A tool call's environment carries NO_COLOR=1 (the successor would render
    without colors) and the launching session's CLAUDE_CODE_* identity (the successor would not register
    under its own name in `claude agents`).
#>
param(
    [Parameter(Mandatory)][string]$Name,
    [Parameter(Mandatory)][string]$PermissionMode,
    [Parameter(Mandatory)][string]$PromptFile
)

$inheritedNames = 'CLAUDECODE', 'CLAUDE_PID', 'NO_COLOR', 'FORCE_COLOR'
Get-ChildItem env: |
    Where-Object { $_.Name -like 'CLAUDE_CODE_*' -or $_.Name -in $inheritedNames } |
    ForEach-Object { Remove-Item "env:$($_.Name)" }

claude -n $Name --permission-mode $PermissionMode (Get-Content -Raw $PromptFile)

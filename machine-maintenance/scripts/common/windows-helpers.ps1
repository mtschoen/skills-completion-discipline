# Shared helpers for Windows machine-maintenance audit and cleanup scripts.
Set-StrictMode -Version Latest

function Test-IsAdmin {
    try {
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
        $principal = [Security.Principal.WindowsPrincipal]::new($identity)
        return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    } catch {
        return $false
    }
}

function Format-Bytes {
    param([int64]$Bytes)
    if ($Bytes -ge 1GB) {
        return ('{0:N2} GB' -f ($Bytes / 1GB))
    }
    if ($Bytes -ge 1MB) {
        return ('{0:N1} MB' -f ($Bytes / 1MB))
    }
    if ($Bytes -ge 1KB) {
        return ('{0:N1} KB' -f ($Bytes / 1KB))
    }
    return "$Bytes B"
}

function New-Finding {
    param(
        [Parameter(Mandatory)][string]$Section,
        [Parameter(Mandatory)][string]$Kind,
        [Parameter(Mandatory)][string]$What,
        [string]$Path = '',
        [Parameter(Mandatory)][string]$Evidence,
        [Parameter(Mandatory)][string]$Recommendation,
        [ValidateSet('high', 'medium', 'low')][string]$Confidence = 'high',
        [Parameter(Mandatory)][string]$Rationale,
        [Parameter(Mandatory)][string]$ActionOnApproval,
        [ValidateSet('safe-mechanical', 'needs-judgment', 'needs-elevation')][string]$Classification = 'needs-judgment',
        [int64]$ReclaimBytes = 0,
        [string]$Precondition = 'none',
        [string]$Action = ''
    )
    if ([string]::IsNullOrWhiteSpace($Action)) {
        $Action = $ActionOnApproval
    }
    return [PSCustomObject][ordered]@{
        kind               = $Kind
        what               = $What
        path               = $Path
        evidence           = $Evidence
        recommendation     = $Recommendation
        confidence         = $Confidence
        rationale          = $Rationale
        action_on_approval = $ActionOnApproval
        section            = $Section
        os                 = 'windows'
        classification     = $Classification
        reclaim_bytes      = [int64]$ReclaimBytes
        precondition       = $Precondition
        action             = $Action
    }
}

function Measure-TreeFast {
    param(
        [Parameter(Mandatory)][string]$LiteralPath,
        [int]$TimeoutSeconds = 8,
        [int]$MaxFiles = 200000
    )
    $result = [ordered]@{
        path         = $LiteralPath
        exists       = $false
        bytes        = [int64]0
        file_count   = [int64]0
        newest_mtime = $null
        truncated    = $false
        error        = $null
    }
    if ([string]::IsNullOrWhiteSpace($LiteralPath) -or -not (Test-Path -LiteralPath $LiteralPath)) {
        return [PSCustomObject]$result
    }
    try {
        $item = Get-Item -LiteralPath $LiteralPath -Force -ErrorAction Stop
        $result.exists = $true
        if (-not $item.PSIsContainer) {
            $result.bytes = [int64]$item.Length
            $result.file_count = 1
            $result.newest_mtime = $item.LastWriteTimeUtc.ToString('o')
            return [PSCustomObject]$result
        }

        $opts = [System.IO.EnumerationOptions]::new()
        $opts.RecurseSubdirectories = $true
        $opts.IgnoreInaccessible = $true
        $opts.AttributesToSkip = [System.IO.FileAttributes]::ReparsePoint -bor [System.IO.FileAttributes]::Offline

        $dirInfo = [System.IO.DirectoryInfo]::new($LiteralPath)
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        [int64]$totalBytes = 0
        [int64]$count = 0
        [datetime]$newest = [datetime]::MinValue

        foreach ($file in $dirInfo.EnumerateFiles('*', $opts)) {
            $totalBytes += $file.Length
            $count++
            if ($file.LastWriteTimeUtc -gt $newest) {
                $newest = $file.LastWriteTimeUtc
            }
            if (($count % 2048 -eq 0) -and ($sw.Elapsed.TotalSeconds -ge $TimeoutSeconds -or $count -ge $MaxFiles)) {
                $result.truncated = $true
                break
            }
        }
        $sw.Stop()
        $result.bytes = $totalBytes
        $result.file_count = $count
        if ($newest -gt [datetime]::MinValue) {
            $result.newest_mtime = $newest.ToString('o')
        }
    } catch {
        $result.error = $_.Exception.Message
    }
    return [PSCustomObject]$result
}

function Invoke-CommandWithTimeout {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [string[]]$ArgumentList = @(),
        [int]$TimeoutSeconds = 15,
        [string]$WorkingDirectory = ''
    )
    $out = [ordered]@{
        exit_code = -1
        stdout    = ''
        stderr    = ''
        timed_out = $false
        error     = $null
    }
    try {
        $cmd = Get-Command -Name $FilePath -ErrorAction Stop
        $psi = [System.Diagnostics.ProcessStartInfo]::new()
        $psi.FileName = $cmd.Source
        foreach ($arg in $ArgumentList) {
            $psi.ArgumentList.Add($arg)
        }
        if (-not [string]::IsNullOrWhiteSpace($WorkingDirectory) -and (Test-Path -LiteralPath $WorkingDirectory)) {
            $psi.WorkingDirectory = $WorkingDirectory
        }
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.UseShellExecute = $false
        $psi.CreateNoWindow = $true

        $proc = [System.Diagnostics.Process]::new()
        $proc.StartInfo = $psi
        [void]$proc.Start()
        $stdoutTask = $proc.StandardOutput.ReadToEndAsync()
        $stderrTask = $proc.StandardError.ReadToEndAsync()
        if (-not $proc.WaitForExit($TimeoutSeconds * 1000)) {
            try { $proc.Kill($true) } catch {}
            $out.timed_out = $true
            $out.error = "Timed out after ${TimeoutSeconds}s"
            return [PSCustomObject]$out
        }
        $proc.WaitForExit()
        $out.exit_code = $proc.ExitCode
        $out.stdout = $stdoutTask.GetAwaiter().GetResult().Trim()
        $out.stderr = $stderrTask.GetAwaiter().GetResult().Trim()
    } catch {
        $out.error = $_.Exception.Message
    }
    return [PSCustomObject]$out
}

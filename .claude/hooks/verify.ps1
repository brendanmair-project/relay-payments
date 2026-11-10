# Stop hook: runs the project's verification command and blocks the turn from ending while it fails.
# Reads .claude/verify-command.txt (first non-empty line not starting with #). Never blocks on internal errors.
try {
    $raw = [Console]::In.ReadToEnd()
    try { $evt = $raw | ConvertFrom-Json } catch { exit 0 }
    if ($null -ne $evt -and $null -ne $evt.PSObject.Properties['stop_hook_active'] -and $evt.stop_hook_active -eq $true) { exit 0 }

    $root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
    $cmdFile = Join-Path $root '.claude\verify-command.txt'
    if (-not (Test-Path -LiteralPath $cmdFile -PathType Leaf)) { exit 0 }
    $command = $null
    foreach ($line in [IO.File]::ReadAllLines($cmdFile)) {
        $t = $line.Trim()
        if ($t -ne '' -and -not $t.StartsWith('#')) { $command = $t; break }
    }
    if (-not $command) { exit 0 }

    # Test-first stage: a failing suite is expected while .claude/tdd-red exists.
    if (Test-Path -LiteralPath (Join-Path $root '.claude\tdd-red')) {
        Write-Output (ConvertTo-Json -Compress -InputObject @{ systemMessage = 'Verification skipped: .claude/tdd-red marks the failing-test stage. Delete it before review.' })
        exit 0
    }

    # Docker-based command: skip (do not block) when the Docker daemon is unavailable.
    if ($command -match '^\s*"?docker(\.exe)?"?(\s|$)') {
        $dockerUp = $false
        if (Get-Command docker -ErrorAction SilentlyContinue) {
            $dp = Start-Process -FilePath 'cmd.exe' -ArgumentList '/c docker info >NUL 2>&1' -WorkingDirectory $root -NoNewWindow -PassThru
            $null = $dp.Handle
            if ($dp.WaitForExit(20000)) {
                $dockerUp = ($dp.ExitCode -eq 0)
            } else {
                & taskkill.exe /PID $dp.Id /T /F 2>&1 | Out-Null
            }
        }
        if (-not $dockerUp) {
            Write-Output (ConvertTo-Json -Compress -InputObject @{ systemMessage = "Verification skipped: Docker is not running ($command)." })
            exit 0
        }
    }

    $outFile = [IO.Path]::GetTempFileName()
    $errFile = [IO.Path]::GetTempFileName()
    $code = $null
    try {
        $p = Start-Process -FilePath 'cmd.exe' -ArgumentList "/c $command" -WorkingDirectory $root -NoNewWindow -PassThru -RedirectStandardOutput $outFile -RedirectStandardError $errFile
        $null = $p.Handle  # cache the process handle so ExitCode is readable after exit
        if ($p.WaitForExit(540000)) {
            $code = $p.ExitCode
        } else {
            & taskkill.exe /PID $p.Id /T /F 2>&1 | Out-Null
            $code = 'timeout after 540 s'
        }
        $lines = @()
        $lines += @(Get-Content -LiteralPath $outFile -ErrorAction SilentlyContinue)
        $lines += @(Get-Content -LiteralPath $errFile -ErrorAction SilentlyContinue)
        $tail = (@($lines | Select-Object -Last 30) -join "`n")
    } finally {
        Remove-Item -LiteralPath $outFile, $errFile -Force -ErrorAction SilentlyContinue
    }
    if ("$code" -eq '0') { exit 0 }
    $reason = "Project checks failed ($command, exit $code). Fix the failures, then finish. Last output:`n$tail"
    Write-Output (ConvertTo-Json -Compress -InputObject @{ decision = 'block'; reason = $reason })
    exit 0
} catch {
    exit 0
}

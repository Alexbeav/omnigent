[CmdletBinding()]
param(
    [switch]$Apply,
    [switch]$StopCurrentHost
)

$ErrorActionPreference = "Stop"
$taskName = "OmnigentHostV018"
$runtimeDirectory = Join-Path $HOME ".omnigent\host-autostart-v018"
$statePath = Join-Path $runtimeDirectory "previous-task-state.json"
$state = if (Test-Path -LiteralPath $statePath) {
    Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
} else {
    $null
}

if (-not $Apply) {
    [ordered]@{
        RemoveTask = $taskName
        RestoreTaskStateFrom = $statePath
        StopCurrentHost = [bool]$StopCurrentHost
        DeleteWorktree = $false
        ReplaceGlobalUvTool = $false
        WslTasksManaged = @()
    } | ConvertTo-Json -Depth 3
    Write-Output "Dry run only. Add -Apply after review."
    exit 0
}

$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($task -and $task.State -eq "Running" -and -not $StopCurrentHost) {
    throw "$taskName is running. Add -StopCurrentHost for an explicit managed stop."
}
if ($task -and $task.State -eq "Running") {
    if (-not $state) {
        throw "The managed-process state file is missing. The running task was not stopped."
    }
    Stop-ScheduledTask -TaskName $taskName
    $deadline = [DateTime]::UtcNow.AddSeconds(15)
    do {
        Start-Sleep -Milliseconds 250
        $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    } while ($task -and $task.State -eq "Running" -and [DateTime]::UtcNow -lt $deadline)
    if ($task -and $task.State -eq "Running") {
        throw "Task Scheduler did not stop $taskName. The task remains registered."
    }
    $managed = @(Get-CimInstance Win32_Process | Where-Object {
        $_.ExecutablePath -eq $state.ManagedExecutable -or
        $_.CommandLine -like "*$($state.Supervisor)*" -or
        $_.CommandLine -like "*$($state.Launcher)*"
    })
    foreach ($process in $managed) {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
    }
    if ($managed.Count) {
        Wait-Process -Id $managed.ProcessId -Timeout 10 -ErrorAction SilentlyContinue
    }
    $survivors = @(Get-CimInstance Win32_Process | Where-Object {
        $_.ExecutablePath -eq $state.ManagedExecutable -or
        $_.CommandLine -like "*$($state.Supervisor)*" -or
        $_.CommandLine -like "*$($state.Launcher)*"
    })
    if ($survivors.Count) {
        throw "A managed v0.18 process survived rollback. The task remains registered."
    }
}
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

if ($state) {
    foreach ($entry in @($state.LegacyTasks)) {
        if (Get-ScheduledTask -TaskName $entry.Name -ErrorAction SilentlyContinue) {
            if ($entry.Enabled) {
                Enable-ScheduledTask -TaskName $entry.Name | Out-Null
            } else {
                Disable-ScheduledTask -TaskName $entry.Name | Out-Null
            }
        }
    }
}

Write-Output "Removed $taskName and restored recorded legacy task states."
Write-Output "The qualified worktree, logs, and global uv tool were preserved."

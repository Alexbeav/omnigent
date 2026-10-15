[CmdletBinding()]
param(
    [switch]$Apply,
    [switch]$Activate,
    [switch]$StartNow,
    [string]$Worktree = (Join-Path $HOME "Projects\omnigent-v018-qualified"),
    [Parameter(Mandatory = $true)]
    [string]$Server
)

$ErrorActionPreference = "Stop"
$commit = "38f30aa96e9dfa01ebef8b6d09e2e19a2696fd23"
$repository = "https://github.com/Alexbeav/omnigent.git"
$taskName = "OmnigentHostV018"
$legacyTaskNames = @("OmnigentHost", "Omnigent Autostart")
$runtimeDirectory = Join-Path $HOME ".omnigent\host-autostart-v018"
$statePath = Join-Path $runtimeDirectory "previous-task-state.json"
$supervisorSource = Join-Path $PSScriptRoot "omnigent-host-supervisor.ps1"
$launcherSource = Join-Path $PSScriptRoot "omnigent-host-hidden.vbs"

if ($StartNow -and -not $Activate) {
    throw "-StartNow requires -Activate."
}
foreach ($path in @($supervisorSource, $launcherSource)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Required companion file is missing: $path"
    }
}

$plan = [ordered]@{
    TaskName = $taskName
    Server = $Server
    Repository = $repository
    Commit = $commit
    Worktree = $Worktree
    RuntimeDirectory = $runtimeDirectory
    Activate = [bool]$Activate
    StartNow = [bool]$StartNow
    LegacyTasksManaged = $legacyTaskNames
    WslTasksManaged = @()
}
if (-not $Apply) {
    $plan | ConvertTo-Json -Depth 4
    Write-Output "Dry run only. Add -Apply after review."
    exit 0
}

$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
if (-not $identity) {
    throw "Windows did not return the current DOMAIN\User identity."
}

if (Test-Path -LiteralPath $Worktree) {
    if (-not (Test-Path -LiteralPath (Join-Path $Worktree ".git"))) {
        throw "The worktree path exists but is not a Git checkout: $Worktree"
    }
    $status = @(& git -C $Worktree status --porcelain)
    if ($status.Count -ne 0) {
        throw "The qualified worktree is not clean."
    }
    & git -C $Worktree remote set-url origin $repository
    & git -C $Worktree fetch --no-tags origin $commit
} else {
    New-Item -ItemType Directory -Path (Split-Path -Parent $Worktree) -Force | Out-Null
    & git clone --no-checkout $repository $Worktree
    & git -C $Worktree fetch --no-tags origin $commit
}
if ($LASTEXITCODE -ne 0) {
    throw "Git did not fetch the qualified commit."
}
& git -C $Worktree checkout --detach $commit
if ($LASTEXITCODE -ne 0 -or (& git -C $Worktree rev-parse HEAD) -ne $commit) {
    throw "The worktree did not reach the qualified commit."
}

$oldSkip = $env:OMNIGENT_SKIP_WEB_UI
try {
    $env:OMNIGENT_SKIP_WEB_UI = "true"
    & uv sync --directory $Worktree --frozen --no-dev --python 3.12
    if ($LASTEXITCODE -ne 0) {
        throw "The frozen v0.18 environment did not install."
    }
} finally {
    $env:OMNIGENT_SKIP_WEB_UI = $oldSkip
}

$python = Join-Path $Worktree ".venv\Scripts\python.exe"
$omnigent = Join-Path $Worktree ".venv\Scripts\omnigent.exe"
if (-not (Test-Path -LiteralPath $omnigent)) {
    throw "The isolated Omnigent executable is missing."
}
& $python -P -c "from importlib.metadata import version; names=('omnigent','omnigent-client','omnigent-ui-sdk'); versions={name: version(name) for name in names}; assert set(versions.values()) == {'0.18.0'}, versions; print(versions)"
if ($LASTEXITCODE -ne 0) {
    throw "The isolated Omnigent and SDK versions are not all 0.18.0."
}

New-Item -ItemType Directory -Path $runtimeDirectory -Force | Out-Null
$supervisor = Join-Path $runtimeDirectory "omnigent-host-supervisor.ps1"
$launcher = Join-Path $runtimeDirectory "omnigent-host-hidden.vbs"
Copy-Item -LiteralPath $supervisorSource -Destination $supervisor -Force
Copy-Item -LiteralPath $launcherSource -Destination $launcher -Force
Unblock-File -LiteralPath $supervisor, $launcher

$legacyState = @(foreach ($name in $legacyTaskNames) {
    $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if ($task) {
        [ordered]@{ Name = $name; Enabled = [bool]$task.Settings.Enabled }
    }
})

$logPath = Join-Path $HOME ".omnigent\logs\host-v018.log"
$state = [ordered]@{
    LegacyTasks = $legacyState
    ManagedExecutable = $omnigent
    Supervisor = $supervisor
    Launcher = $launcher
}
$state | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $statePath -Encoding utf8
$arguments = '"{0}" "{1}" "{2}" "{3}" "{4}"' -f $launcher, $supervisor, $omnigent, $Server, $logPath
$action = New-ScheduledTaskAction -Execute "$env:WINDIR\System32\wscript.exe" -Argument $arguments -WorkingDirectory $HOME
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew -StartWhenAvailable
$settings.Hidden = $true
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description "Qualified Omnigent v0.18 Windows host" -Force | Out-Null

if ($Activate) {
    foreach ($name in $legacyTaskNames) {
        if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
            Disable-ScheduledTask -TaskName $name | Out-Null
        }
    }
    Enable-ScheduledTask -TaskName $taskName | Out-Null
    if ($StartNow) {
        Start-ScheduledTask -TaskName $taskName
    }
} else {
    Disable-ScheduledTask -TaskName $taskName | Out-Null
}

[ordered]@{
    InstalledVersion = (& $omnigent --version)
    Commit = (& git -C $Worktree rev-parse HEAD)
    TaskName = $taskName
    TaskEnabled = [bool](Get-ScheduledTask -TaskName $taskName).Settings.Enabled
    StartedNow = [bool]$StartNow
    StateFile = $statePath
} | ConvertTo-Json -Depth 3

param(
    [Parameter(Mandatory = $true)]
    [string]$Executable,
    [Parameter(Mandatory = $true)]
    [string]$Server,
    [Parameter(Mandatory = $true)]
    [string]$LogPath
)

$ErrorActionPreference = "Continue"
$logDirectory = Split-Path -Parent $LogPath
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null

while ($true) {
    Add-Content -LiteralPath $LogPath -Value "$(Get-Date -Format o) starting Omnigent host"
    & $Executable host --server $Server --no-open --non-interactive *>> $LogPath
    $exitCode = $LASTEXITCODE
    Add-Content -LiteralPath $LogPath -Value "$(Get-Date -Format o) host exited with code $exitCode"
    if ($exitCode -in @(0, 78, 143)) {
        exit $exitCode
    }
    Start-Sleep -Seconds 10
}

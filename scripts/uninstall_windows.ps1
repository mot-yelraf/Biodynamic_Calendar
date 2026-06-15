param(
  [switch]$KeepVenv,
  [switch]$PurgeData
)

$ErrorActionPreference = "Stop"

$AppDir = Split-Path -Parent $PSScriptRoot
$DataDir = if ($env:BD_CALENDAR_DATA_DIR) { $env:BD_CALENDAR_DATA_DIR } else { Join-Path $env:USERPROFILE ".biodynamic_calendar" }
$TaskNames = @("Biodynamic Calendar", "BiodynamicCalendar")

foreach ($TaskName in $TaskNames) {
  $Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
  if ($Task) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed scheduled task $TaskName."
  }
}

$VenvPath = Join-Path $AppDir ".venv"
if (-not $KeepVenv) {
  Remove-Item -Recurse -Force $VenvPath -ErrorAction SilentlyContinue
  Write-Host "Removed $VenvPath."
} else {
  Write-Host "Keeping $VenvPath."
}

if ($PurgeData) {
  Remove-Item -Recurse -Force $DataDir -ErrorAction SilentlyContinue
  Write-Host "Removed local data in $DataDir."
} else {
  Write-Host "Preserved local data in $DataDir."
}

Write-Host "Uninstall complete."

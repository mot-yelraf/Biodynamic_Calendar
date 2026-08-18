$ErrorActionPreference = "Stop"
$ScriptDir = $PSScriptRoot
$RuntimeDir = $ScriptDir
$PythonExe = Join-Path $RuntimeDir ".venv\Scripts\python.exe"

$InstalledRuntime = if ($env:BD_CALENDAR_INSTALL_DIR) {
    $env:BD_CALENDAR_INSTALL_DIR
} else {
    Join-Path $env:USERPROFILE "Biodynamic_Calendar"
}
$InstalledPython = Join-Path $InstalledRuntime ".venv\Scripts\python.exe"
$LocalWebviewReady = $false
if (Test-Path $PythonExe -PathType Leaf) {
    & $PythonExe -c "import webview" 2>$null
    $LocalWebviewReady = ($LASTEXITCODE -eq 0)
}
if (-not $LocalWebviewReady -and
    [System.IO.Path]::GetFullPath($ScriptDir) -ne [System.IO.Path]::GetFullPath($InstalledRuntime) -and
    (Test-Path $InstalledPython -PathType Leaf)) {
    & $InstalledPython -c "import webview" 2>$null
    if ($LASTEXITCODE -eq 0) {
        $RuntimeDir = $InstalledRuntime
        $PythonExe = $InstalledPython
        Write-Host "Using installed Biodynamic Calendar runtime: $RuntimeDir"
    }
}

if (-not (Test-Path $PythonExe -PathType Leaf)) {
    throw "Biodynamic Calendar virtual environment is missing. Run the installer again."
}

Set-Location $RuntimeDir
& $PythonExe (Join-Path $RuntimeDir "Biodynamic_Calendar.py") @args
exit $LASTEXITCODE

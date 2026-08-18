$ErrorActionPreference = "Stop"
$RuntimeDir = $PSScriptRoot
$PythonExe = Join-Path $RuntimeDir ".venv\Scripts\python.exe"

if (-not (Test-Path $PythonExe -PathType Leaf)) {
    throw "Biodynamic Calendar virtual environment is missing. Run the installer again."
}

Set-Location $RuntimeDir
& $PythonExe -m biodynamic_calendar_app @args
exit $LASTEXITCODE

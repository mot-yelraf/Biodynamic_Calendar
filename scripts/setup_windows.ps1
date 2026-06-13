$ErrorActionPreference = "Stop"

python -m venv .venv
. .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e .[dev]

Write-Host "Ready. Activate with: .venv\Scripts\Activate.ps1"

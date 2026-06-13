$ErrorActionPreference = "Stop"

python -m venv .venv
. .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e .[dev]

Write-Host @"
Ready.

Start BD Calendar:
  .\.venv\Scripts\Activate.ps1
  biodynamic-calendar-server

Browse on this PC:
  http://127.0.0.1:8765

Browse from another device on this network:
  biodynamic-calendar-server --host 0.0.0.0
  open http://<this-PC-IP>:8765
  find this PC's IP with: ipconfig
"@

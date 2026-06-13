#!/usr/bin/env bash
set -euo pipefail

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e .[dev]

cat <<'EOF'
Ready.

Start BD Calendar:
  source .venv/bin/activate
  biodynamic-calendar-server

Browse on this computer:
  http://127.0.0.1:8765

Browse from another device on this network:
  biodynamic-calendar-server --host 0.0.0.0
  open http://<this-computer-IP>:8765
  find this computer's IP with: hostname -I
EOF

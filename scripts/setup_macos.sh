#!/usr/bin/env bash
set -euo pipefail

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e .[dev]

cat <<'EOF'
Ready.

Start BD Calendar (binds to all network interfaces by default):
  source .venv/bin/activate
  biodynamic-calendar-server

Browse on this Mac:
  http://127.0.0.1:8765

Browse from another device on this network:
  open http://<this-Mac-IP>:8765
  find this Mac's IP with: ipconfig getifaddr en0
EOF

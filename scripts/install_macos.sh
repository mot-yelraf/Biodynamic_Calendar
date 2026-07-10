#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$APP_DIR/.venv"

source "$APP_DIR/scripts/install_logging.sh"
init_install_log \
  "$APP_DIR" \
  "$VENV_DIR" \
  "pyproject.toml project dependencies plus .[dev]" \
  "none"

install_log_step "Changing to project directory: $APP_DIR"
cd "$APP_DIR"
install_log_step "Creating virtual environment: $VENV_DIR"
python3 -m venv "$VENV_DIR"
install_log_step "Activating virtual environment: $VENV_DIR"
source "$VENV_DIR/bin/activate"
install_log_step "Upgrading pip, setuptools, and wheel"
python -m pip install --upgrade pip setuptools wheel
install_log_step "Installing project dependencies into $VENV_DIR"
python -m pip install -e ".[dev]"

cat <<'EOF'
Ready.

Start BD Calendar for LAN access:
  source .venv/bin/activate
  biodynamic-calendar-server --lan

Browse on this Mac:
  http://127.0.0.1:8765

Browse from another device on this network:
  open http://<this-Mac-IP>:8765
  find this Mac's IP with: ipconfig getifaddr en0
EOF

#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="${BD_CALENDAR_INSTALL_DIR:-${HOME}/Biodynamic_Calendar}"
VENV_DIR="$APP_DIR/.venv"

case "$APP_DIR" in
  ""|/|"$HOME")
    printf 'BD_CALENDAR_INSTALL_DIR must name a dedicated application directory.\n' >&2
    exit 1
    ;;
esac

mkdir -p "$APP_DIR" "$APP_DIR/src" "$APP_DIR/static" "$APP_DIR/templates" "$APP_DIR/scripts"
if [[ "$SOURCE_DIR" != "$APP_DIR" ]]; then
  cp "$SOURCE_DIR/Biodynamic_Calendar.py" "$APP_DIR/Biodynamic_Calendar.py"
  cp "$SOURCE_DIR/pyproject.toml" "$APP_DIR/pyproject.toml"
  cp "$SOURCE_DIR/README.md" "$APP_DIR/README.md"
  cp "$SOURCE_DIR/LICENSE" "$APP_DIR/LICENSE"
  cp "$SOURCE_DIR"/run_bd_calendar_* "$APP_DIR/"
  cp -R "$SOURCE_DIR/src/." "$APP_DIR/src/"
  cp -R "$SOURCE_DIR/static/." "$APP_DIR/static/"
  cp -R "$SOURCE_DIR/templates/." "$APP_DIR/templates/"
  cp -R "$SOURCE_DIR/scripts/." "$APP_DIR/scripts/"
fi

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
install_log_step "Verifying pywebview desktop runtime"
python -c 'import webview; from biodynamic_calendar_app.desktop import main'

chmod +x "$APP_DIR/run_bd_calendar_gui.sh"
chmod +x "$APP_DIR/run_bd_calendar_server.sh"

cat <<EOF
Ready.

Start the Biodynamic Calendar desktop app:
  $APP_DIR/run_bd_calendar_gui.sh

Start only the LAN server:
  $APP_DIR/run_bd_calendar_server.sh

Browse on this Mac:
  http://127.0.0.1:8765

Browse from another device on this network:
  open http://<this-Mac-IP>:8765
  find this Mac's IP with: ipconfig getifaddr en0
EOF

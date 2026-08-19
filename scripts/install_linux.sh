#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_APP_DIR="${HOME}/Biodynamic_Calendar"
INSTALL_STATE_DIR="${XDG_CONFIG_HOME:-${HOME}/.config}/biodynamic-calendar"
INSTALL_STATE_FILE="${INSTALL_STATE_DIR}/install-location"

remembered_app_dir=""
if [[ -f "$INSTALL_STATE_FILE" ]]; then
  IFS= read -r remembered_app_dir < "$INSTALL_STATE_FILE" || true
fi
case "$remembered_app_dir" in
  ""|/) remembered_app_dir="$DEFAULT_APP_DIR" ;;
esac

choose_install_parent() {
  local initial_parent="$1"
  if [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]] && command -v zenity >/dev/null 2>&1; then
    zenity --file-selection --directory \
      --title="Choose where Biodynamic Calendar should be installed" \
      --filename="${initial_parent}/"
    return
  fi
  if [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]] && command -v kdialog >/dev/null 2>&1; then
    kdialog --getexistingdirectory "$initial_parent" \
      --title "Choose where Biodynamic Calendar should be installed"
    return
  fi
  if [[ -z "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
    return 2
  fi
  python3 - "$initial_parent" <<'PYTHON'
import sys

try:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.update_idletasks()
    selected = filedialog.askdirectory(
        title="Choose where Biodynamic Calendar should be installed",
        initialdir=sys.argv[1],
        mustexist=True,
    )
    root.destroy()
except Exception:
    raise SystemExit(2)

if not selected:
    raise SystemExit(1)
print(selected)
PYTHON
}

if [[ -n "${BD_CALENDAR_INSTALL_DIR:-}" ]]; then
  APP_DIR="$BD_CALENDAR_INSTALL_DIR"
else
  initial_parent="$(dirname -- "$remembered_app_dir")"
  if [[ ! -d "$initial_parent" ]]; then
    initial_parent="$HOME"
  fi
  selection_status=0
  selected_parent="$(choose_install_parent "$initial_parent")" || selection_status=$?
  if [[ "$selection_status" -eq 1 ]]; then
    printf 'Biodynamic Calendar installation was cancelled.\n' >&2
    exit 1
  elif [[ "$selection_status" -eq 0 && -n "$selected_parent" ]]; then
    APP_DIR="${selected_parent%/}/Biodynamic_Calendar"
  elif [[ -t 0 ]]; then
    printf 'Install Biodynamic Calendar under which directory? [%s] ' "$initial_parent"
    IFS= read -r selected_parent
    selected_parent="${selected_parent:-$initial_parent}"
    APP_DIR="${selected_parent%/}/Biodynamic_Calendar"
  else
    APP_DIR="$remembered_app_dir"
    printf 'No graphical folder chooser is available; using %s\n' "$APP_DIR"
  fi
fi
SERVICE_NAME="biodynamic-calendar.service"
SERVICE_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
SERVICE_PATH="$SERVICE_DIR/$SERVICE_NAME"
SERVICE_HOST="${BD_CALENDAR_HOST:-0.0.0.0}"
SERVICE_PORT="${BD_CALENDAR_PORT:-8765}"
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
  "BD_CALENDAR_AUTO_START=${BD_CALENDAR_AUTO_START:-interactive}; BD_CALENDAR_HOST=$SERVICE_HOST; BD_CALENDAR_PORT=$SERVICE_PORT"

systemd_user_available() {
  command -v systemctl >/dev/null 2>&1 &&
    systemctl --user show-environment >/dev/null 2>&1
}

systemd_user_service_exists() {
  [[ -f "$SERVICE_PATH" ]] && return 0
  systemd_user_service_enabled_or_active
}

systemd_user_service_enabled_or_active() {
  if ! systemd_user_available; then
    return 1
  fi
  systemctl --user is-active --quiet "$SERVICE_NAME" >/dev/null 2>&1 ||
    systemctl --user is-enabled --quiet "$SERVICE_NAME" >/dev/null 2>&1
}

stop_existing_systemd_user_service() {
  if systemd_user_available; then
    if systemctl --user is-active --quiet "$SERVICE_NAME" >/dev/null 2>&1; then
      echo "Stopping existing $SERVICE_NAME before updating."
      systemctl --user stop "$SERVICE_NAME" >/dev/null 2>&1 || true
    fi
  elif [[ -f "$SERVICE_PATH" ]]; then
    echo "Found $SERVICE_PATH, but systemd --user is not available in this session."
    echo "If the old service is running, stop it before starting a new copy."
  fi
}

remove_systemd_user_service() {
  if systemd_user_available; then
    systemctl --user disable --now "$SERVICE_NAME" >/dev/null 2>&1 || true
  fi
  rm -f "$SERVICE_PATH"
  if systemd_user_available; then
    systemctl --user daemon-reload
    systemctl --user reset-failed "$SERVICE_NAME" >/dev/null 2>&1 || true
  fi
}

auto_start_env_choice() {
  case "${BD_CALENDAR_AUTO_START:-}" in
    "") echo "" ;;
    1|true|TRUE|yes|YES|y|Y|on|ON) echo "yes" ;;
    0|false|FALSE|no|NO|n|N|off|OFF) echo "no" ;;
    *)
      echo "BD_CALENDAR_AUTO_START must be yes or no." >&2
      exit 2
      ;;
  esac
}

prompt_auto_start() {
  local default_choice="${1:-no}"
  local env_choice=""
  local answer=""
  local prompt="[y/N]"

  env_choice="$(auto_start_env_choice)"
  case "$env_choice" in
    yes) return 0 ;;
    no) return 1 ;;
  esac

  if [[ "$default_choice" == "yes" ]]; then
    prompt="[Y/n]"
  fi

  if [[ ! -t 0 ]]; then
    [[ "$default_choice" == "yes" ]]
    return
  fi

  read -r -p "Enable BD Calendar auto-start for this Linux user with systemd? $prompt " answer
  case "$answer" in
    "") [[ "$default_choice" == "yes" ]] ;;
    [yY]|[yY][eE][sS]) return 0 ;;
    *) return 1 ;;
  esac
}

setup_systemd_user_service() {
  if ! command -v systemctl >/dev/null 2>&1; then
    echo "systemctl was not found; skipping auto-start install."
    return 0
  fi
  if ! systemctl --user show-environment >/dev/null 2>&1; then
    echo "systemd --user is not available in this session; skipping auto-start install."
    return 0
  fi

  mkdir -p "$SERVICE_DIR"
  cat > "$SERVICE_PATH" <<EOF
[Unit]
Description=Biodynamic Calendar local web app
After=network-online.target

[Service]
Type=simple
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/.venv/bin/biodynamic-calendar-server --host $SERVICE_HOST --port $SERVICE_PORT
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF

  systemctl --user daemon-reload
  systemctl --user enable "$SERVICE_NAME"
  systemctl --user restart "$SERVICE_NAME"

  cat <<EOF
Auto-start enabled.
The service binds to $SERVICE_HOST on port $SERVICE_PORT.

Service:
  $SERVICE_PATH

Status:
  systemctl --user status $SERVICE_NAME

Disable auto-start:
  systemctl --user disable --now $SERVICE_NAME
EOF
}

install_python_dependencies() {
  install_log_step "Upgrading pip, setuptools, and wheel"
  python -m pip install --upgrade pip setuptools wheel
  install_log_step "Installing project dependencies into $VENV_DIR"
  python -m pip install "$@" -e ".[dev]"
}

verify_runtime_imports() {
  python - <<'PY'
from biodynamic_calendar_app.__main__ import main
from biodynamic_calendar_app.desktop import main as desktop_main
import webview
PY
}

install_log_step "Changing to project directory: $APP_DIR"
cd "$APP_DIR"
EXISTING_SERVICE="no"
EXISTING_AUTO_START="no"
install_log_step "Inspecting existing systemd user service state"
if systemd_user_service_enabled_or_active; then
  EXISTING_AUTO_START="yes"
fi
if systemd_user_service_exists; then
  EXISTING_SERVICE="yes"
  stop_existing_systemd_user_service
fi

install_log_step "Creating virtual environment: $VENV_DIR"
python3 -m venv --system-site-packages "$VENV_DIR"
install_log_step "Activating virtual environment: $VENV_DIR"
source "$VENV_DIR/bin/activate"
install_python_dependencies

install_log_step "Verifying runtime imports"
if ! verify_runtime_imports; then
  echo "Runtime import check failed; rebuilding $VENV_DIR with a clean dependency install."
  deactivate >/dev/null 2>&1 || true
  install_log_step "Removing failed virtual environment: $VENV_DIR"
  rm -rf "$VENV_DIR"
  install_log_step "Recreating virtual environment: $VENV_DIR"
  python3 -m venv --system-site-packages "$VENV_DIR"
  install_log_step "Activating rebuilt virtual environment: $VENV_DIR"
  source "$VENV_DIR/bin/activate"
  install_python_dependencies --no-cache-dir --force-reinstall
  install_log_step "Verifying runtime imports after rebuild"
  verify_runtime_imports
fi

python - <<'PY'
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk, WebKit2
PY

chmod +x "$APP_DIR/run_bd_calendar_gui.sh"
chmod +x "$APP_DIR/run_bd_calendar_server.sh"

if prompt_auto_start "$EXISTING_AUTO_START"; then
  install_log_step "Auto-start selected; configuring systemd user service"
  setup_systemd_user_service
else
  install_log_step "Auto-start not selected"
  if [[ "$EXISTING_SERVICE" == "yes" ]]; then
    echo "Removing existing auto-start service."
    remove_systemd_user_service
  fi
  echo "Auto-start not enabled."
fi

install_log_step "Remembering install location: $APP_DIR"
mkdir -p "$INSTALL_STATE_DIR"
install_state_temp="${INSTALL_STATE_FILE}.tmp.$$"
printf '%s\n' "$APP_DIR" > "$install_state_temp"
mv "$install_state_temp" "$INSTALL_STATE_FILE"

cat <<EOF
Ready.

Start the Biodynamic Calendar desktop app:
  $APP_DIR/run_bd_calendar_gui.sh

Start only the LAN server:
  $APP_DIR/run_bd_calendar_server.sh

Browse on this computer:
  http://127.0.0.1:8765

Browse from another device on this network:
  open http://<this-computer-IP>:8765
  find this computer's IP with: hostname -I
EOF

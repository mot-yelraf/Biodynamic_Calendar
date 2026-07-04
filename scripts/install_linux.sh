#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="biodynamic-calendar.service"
SERVICE_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
SERVICE_PATH="$SERVICE_DIR/$SERVICE_NAME"
SERVICE_HOST="${BD_CALENDAR_HOST:-0.0.0.0}"
SERVICE_PORT="${BD_CALENDAR_PORT:-8765}"
VENV_DIR="$APP_DIR/.venv"

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
python3 -m venv "$VENV_DIR"
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
  python3 -m venv "$VENV_DIR"
  install_log_step "Activating rebuilt virtual environment: $VENV_DIR"
  source "$VENV_DIR/bin/activate"
  install_python_dependencies --no-cache-dir --force-reinstall
  install_log_step "Verifying runtime imports after rebuild"
  verify_runtime_imports
fi

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

cat <<'EOF'
Ready.

Start BD Calendar (binds to all network interfaces by default):
  source .venv/bin/activate
  biodynamic-calendar-server

Browse on this computer:
  http://127.0.0.1:8765

Browse from another device on this network:
  open http://<this-computer-IP>:8765
  find this computer's IP with: hostname -I
EOF

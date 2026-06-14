#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="biodynamic-calendar.service"
SERVICE_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
SERVICE_PATH="$SERVICE_DIR/$SERVICE_NAME"

prompt_auto_start() {
  local answer=""
  if [[ ! -t 0 ]]; then
    return 1
  fi
  read -r -p "Enable BD Calendar auto-start for this Linux user with systemd? [y/N] " answer
  case "$answer" in
    [yY]|[yY][eE][sS]) return 0 ;;
    *) return 1 ;;
  esac
}

setup_systemd_user_service() {
  if ! command -v systemctl >/dev/null 2>&1; then
    echo "systemctl was not found; skipping auto-start setup."
    return 0
  fi
  if ! systemctl --user show-environment >/dev/null 2>&1; then
    echo "systemd --user is not available in this session; skipping auto-start setup."
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
ExecStart=$APP_DIR/.venv/bin/biodynamic-calendar-server --host 0.0.0.0 --port 8765
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF

  systemctl --user daemon-reload
  systemctl --user enable --now "$SERVICE_NAME"

  cat <<EOF
Auto-start enabled.
The service binds to all network interfaces on port 8765.

Service:
  $SERVICE_PATH

Status:
  systemctl --user status $SERVICE_NAME

Disable auto-start:
  systemctl --user disable --now $SERVICE_NAME
EOF
}

cd "$APP_DIR"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e .[dev]

if prompt_auto_start; then
  setup_systemd_user_service
else
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

#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="biodynamic-calendar.service"
SERVICE_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
SERVICE_PATH="$SERVICE_DIR/$SERVICE_NAME"
SYSTEM_SERVICE_PATH="/etc/systemd/system/$SERVICE_NAME"
DATA_DIR="${BD_CALENDAR_DATA_DIR:-$HOME/.biodynamic_calendar}"
REMOVE_VENV="yes"
PURGE_DATA="no"

usage() {
  cat <<EOF
Usage: $0 [--keep-venv] [--purge-data]

Stops and removes BD Calendar service files and the local virtual environment.
Local app data in $DATA_DIR is preserved unless --purge-data is provided.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --keep-venv)
      REMOVE_VENV="no"
      ;;
    --purge-data)
      PURGE_DATA="yes"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

systemd_user_available() {
  command -v systemctl >/dev/null 2>&1 &&
    systemctl --user show-environment >/dev/null 2>&1
}

system_service_exists() {
  [[ -f "$SYSTEM_SERVICE_PATH" ]] && return 0
  if ! command -v systemctl >/dev/null 2>&1; then
    return 1
  fi
  systemctl is-active --quiet "$SERVICE_NAME" >/dev/null 2>&1 ||
    systemctl is-enabled --quiet "$SERVICE_NAME" >/dev/null 2>&1
}

remove_user_service() {
  local had_service="no"
  [[ -f "$SERVICE_PATH" ]] && had_service="yes"

  if systemd_user_available; then
    if systemctl --user is-active --quiet "$SERVICE_NAME" >/dev/null 2>&1 ||
      systemctl --user is-enabled --quiet "$SERVICE_NAME" >/dev/null 2>&1; then
      had_service="yes"
    fi
    systemctl --user disable --now "$SERVICE_NAME" >/dev/null 2>&1 || true
  fi

  rm -f "$SERVICE_PATH"

  if systemd_user_available; then
    systemctl --user daemon-reload
    systemctl --user reset-failed "$SERVICE_NAME" >/dev/null 2>&1 || true
  elif [[ "$had_service" == "yes" ]]; then
    echo "Removed $SERVICE_PATH, but systemd --user was not available for daemon-reload."
  fi

  if [[ "$had_service" == "yes" ]]; then
    echo "Removed user service $SERVICE_NAME."
  fi
}

remove_system_service() {
  if ! system_service_exists; then
    return 0
  fi

  if [[ "$EUID" -eq 0 ]]; then
    systemctl disable --now "$SERVICE_NAME" >/dev/null 2>&1 || true
    rm -f "$SYSTEM_SERVICE_PATH"
    systemctl daemon-reload
    systemctl reset-failed "$SERVICE_NAME" >/dev/null 2>&1 || true
    echo "Removed system service $SERVICE_NAME."
    return 0
  fi

  cat <<EOF
A system-wide $SERVICE_NAME appears to exist.
Remove it with:
  sudo systemctl disable --now $SERVICE_NAME
  sudo rm -f $SYSTEM_SERVICE_PATH
  sudo systemctl daemon-reload
EOF
}

remove_virtualenv() {
  if [[ "$REMOVE_VENV" != "yes" ]]; then
    echo "Keeping $APP_DIR/.venv."
    return 0
  fi
  rm -rf "$APP_DIR/.venv"
  echo "Removed $APP_DIR/.venv."
}

purge_data() {
  if [[ "$PURGE_DATA" != "yes" ]]; then
    echo "Preserved local data in $DATA_DIR."
    return 0
  fi
  rm -rf "$DATA_DIR"
  echo "Removed local data in $DATA_DIR."
}

remove_user_service
remove_system_service
remove_virtualenv
purge_data

cat <<EOF
Uninstall complete.
If port 8765 is still in use, check for a manually started server:
  ps -ef | grep biodynamic-calendar-server
EOF

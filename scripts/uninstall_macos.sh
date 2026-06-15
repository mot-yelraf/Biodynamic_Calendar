#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="${BD_CALENDAR_DATA_DIR:-$HOME/.biodynamic_calendar}"
LAUNCH_AGENT_PATH="$HOME/Library/LaunchAgents/local.biodynamic-calendar.plist"
REMOVE_VENV="yes"
PURGE_DATA="no"

usage() {
  cat <<EOF
Usage: $0 [--keep-venv] [--purge-data]

Removes BD Calendar local install artifacts. Local app data in $DATA_DIR is
preserved unless --purge-data is provided.
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

if [[ -f "$LAUNCH_AGENT_PATH" ]]; then
  if command -v launchctl >/dev/null 2>&1; then
    launchctl bootout "gui/$(id -u)" "$LAUNCH_AGENT_PATH" >/dev/null 2>&1 || true
    launchctl unload "$LAUNCH_AGENT_PATH" >/dev/null 2>&1 || true
  fi
  rm -f "$LAUNCH_AGENT_PATH"
  echo "Removed $LAUNCH_AGENT_PATH."
fi

if [[ "$REMOVE_VENV" == "yes" ]]; then
  rm -rf "$APP_DIR/.venv"
  echo "Removed $APP_DIR/.venv."
else
  echo "Keeping $APP_DIR/.venv."
fi

if [[ "$PURGE_DATA" == "yes" ]]; then
  rm -rf "$DATA_DIR"
  echo "Removed local data in $DATA_DIR."
else
  echo "Preserved local data in $DATA_DIR."
fi

echo "Uninstall complete."

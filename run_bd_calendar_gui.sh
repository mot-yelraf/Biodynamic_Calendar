#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
RUNTIME_DIR="$SCRIPT_DIR"
PYTHON_BIN="$RUNTIME_DIR/.venv/bin/python"

INSTALLED_RUNTIME="${BD_CALENDAR_INSTALL_DIR:-${HOME}/Biodynamic_Calendar}"
INSTALLED_PYTHON="$INSTALLED_RUNTIME/.venv/bin/python"
if {
  [ ! -x "$PYTHON_BIN" ] || ! "$PYTHON_BIN" -c 'import webview' >/dev/null 2>&1
} && [ "$SCRIPT_DIR" != "$INSTALLED_RUNTIME" ] &&
  [ -x "$INSTALLED_PYTHON" ] &&
  "$INSTALLED_PYTHON" -c 'import webview' >/dev/null 2>&1; then
  RUNTIME_DIR="$INSTALLED_RUNTIME"
  PYTHON_BIN="$INSTALLED_PYTHON"
  printf 'Using installed Biodynamic Calendar runtime: %s\n' "$RUNTIME_DIR"
fi

if [ ! -x "$PYTHON_BIN" ]; then
  printf 'Biodynamic Calendar virtual environment is missing. Run the installer again.\n' >&2
  exit 1
fi

cd "$RUNTIME_DIR"
exec "$PYTHON_BIN" "$RUNTIME_DIR/Biodynamic_Calendar.py" "$@"

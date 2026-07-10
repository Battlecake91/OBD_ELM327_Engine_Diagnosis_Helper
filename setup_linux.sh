#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
cd -- "$APP_DIR"

if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 was not found." >&2
    exit 1
fi

if [[ ! -d .venv ]]; then
    python3 -m venv .venv
fi

.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

chmod +x setup_linux.sh start_linux.sh

DESKTOP_ID="io.github.open-diagnostics.elm327-live-diagnostic"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"
mkdir -p "$DESKTOP_DIR" "$ICON_DIR"

cp "assets/$DESKTOP_ID.svg" "$ICON_DIR/$DESKTOP_ID.svg"
python3 - "$APP_DIR" "$DESKTOP_DIR/$DESKTOP_ID.desktop" <<'PY'
from pathlib import Path
import sys

app_dir = sys.argv[1].replace("\\", "\\\\").replace('"', '\\"')
target = Path(sys.argv[2])
template = Path("elm327-live-diagnostic.desktop.in").read_text(encoding="utf-8")
target.write_text(template.replace("@APP_DIR@", app_dir), encoding="utf-8")
PY
chmod +x "$DESKTOP_DIR/$DESKTOP_ID.desktop"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor" >/dev/null 2>&1 || true
fi

echo
echo "Installation completed."
echo "Start from the application menu or run: ./start_linux.sh"
echo
if ! command -v rfcomm >/dev/null 2>&1; then
    echo "Optional Bluetooth helper unavailable: install BlueZ with 'sudo apt install bluez'."
fi
echo "If serial access is denied, add your user to the dialout group:"
echo "  sudo usermod -aG dialout \"$USER\""

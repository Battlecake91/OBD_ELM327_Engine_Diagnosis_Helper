#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"

if [[ ! -x .venv/bin/python ]]; then
    echo "The virtual environment is missing. Run ./setup_linux.sh first." >&2
    exit 1
fi

exec .venv/bin/python elm327_twingo_gui.py "$@"

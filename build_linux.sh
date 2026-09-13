#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if [[ "${1:-}" != "--skip-install" ]]; then
  python3 -m pip install --upgrade pip
  python3 -m pip install -r requirements-build.txt
fi

export QT_QPA_PLATFORM=offscreen
python3 -m pytest
python3 -m PyInstaller --noconfirm --clean ELM327_Engine_Diagnosis_Helper_linux.spec
python3 -m PyInstaller --noconfirm ELM327_Updater.spec

chmod +x dist/OBD_ELM327_Engine_Diagnosis_Helper dist/OBD_ELM327_Updater

PACKAGE="dist/OBD_ELM327_Engine_Diagnosis_Helper-linux-x86_64.zip"
rm -f "$PACKAGE"
(
  cd dist
  zip -9 "OBD_ELM327_Engine_Diagnosis_Helper-linux-x86_64.zip"     OBD_ELM327_Engine_Diagnosis_Helper OBD_ELM327_Updater
)

sha256sum   dist/OBD_ELM327_Engine_Diagnosis_Helper   dist/OBD_ELM327_Updater   "$PACKAGE" > dist/OBD_ELM327_Engine_Diagnosis_Helper-linux-x86_64.sha256.txt

echo "Linux build completed:"
echo "  $PACKAGE"

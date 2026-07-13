#!/usr/bin/env python3
"""Generate Windows icon and version resources for the PyInstaller build."""

from __future__ import annotations

import os
import re
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

from elm327_app import APP_VERSION

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ICON = ROOT / "assets" / "io.github.open-diagnostics.elm327-live-diagnostic.svg"
OUTPUT_DIR = ROOT / "build" / "windows"
OUTPUT_ICON = OUTPUT_DIR / "app.ico"
OUTPUT_VERSION = OUTPUT_DIR / "version_info.txt"


def version_tuple(version: str) -> tuple[int, int, int, int]:
    numbers = [int(part) for part in re.findall(r"\d+", version)[:4]]
    return tuple((numbers + [0, 0, 0, 0])[:4])  # type: ignore[return-value]


def generate_icon() -> None:
    if not SOURCE_ICON.is_file():
        raise FileNotFoundError(f"Application icon not found: {SOURCE_ICON}")

    app = QGuiApplication.instance() or QGuiApplication([])
    renderer = QSvgRenderer(str(SOURCE_ICON))
    if not renderer.isValid():
        raise RuntimeError(f"Could not load SVG icon: {SOURCE_ICON}")

    image = QImage(256, 256, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()

    png_path = OUTPUT_DIR / "app.png"
    if not image.save(str(png_path), "PNG"):
        raise RuntimeError(f"Could not render icon to {png_path}")

    with Image.open(png_path) as source:
        source.convert("RGBA").save(
            OUTPUT_ICON,
            format="ICO",
            sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
        )
    png_path.unlink(missing_ok=True)

    _ = app


def generate_version_resource() -> None:
    version = version_tuple(APP_VERSION)
    version_csv = ", ".join(str(value) for value in version)
    text = f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({version_csv}),
    prodvers=({version_csv}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [
          StringStruct('CompanyName', 'Open Diagnostics'),
          StringStruct('FileDescription', 'ELM327 Live Diagnostic'),
          StringStruct('FileVersion', '{APP_VERSION}'),
          StringStruct('InternalName', 'OBD_ELM327_Engine_Diagnosis_Helper'),
          StringStruct('LegalCopyright', 'Copyright (c) 2026 ELM327 Live Diagnostic contributors'),
          StringStruct('OriginalFilename', 'OBD_ELM327_Engine_Diagnosis_Helper.exe'),
          StringStruct('ProductName', 'ELM327 Live Diagnostic'),
          StringStruct('ProductVersion', '{APP_VERSION}')
        ]
      )
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    OUTPUT_VERSION.write_text(text, encoding="utf-8")


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    generate_icon()
    generate_version_resource()
    print(f"Generated {OUTPUT_ICON.relative_to(ROOT)}")
    print(f"Generated {OUTPUT_VERSION.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

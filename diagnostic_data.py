from __future__ import annotations

import json
import locale
import os
import sys
from pathlib import Path
from typing import Any

def resource_root() -> Path:
    """Return the source or PyInstaller resource directory."""
    bundled = getattr(sys, "_MEIPASS", None)
    return Path(bundled).resolve() if bundled else Path(__file__).resolve().parent


ROOT = resource_root()
DATA_ROOT = ROOT / "data"
LOCALE_ROOT = ROOT / "locales"


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return value


def language_code() -> str:
    """Resolve German/English robustly across Windows and POSIX locale names."""
    candidates = [
        locale.getlocale()[0] or "",
        os.environ.get("LANG", ""),
        os.environ.get("LC_ALL", ""),
        os.environ.get("LC_MESSAGES", ""),
    ]
    for raw in candidates:
        value = str(raw).strip().lower().replace("-", "_")
        if value.startswith(("de", "german", "deutsch")):
            return "de"
        if value.startswith(("en", "english")):
            return "en"
    return "en"


def translations(language: str | None = None) -> dict[str, str]:
    lang = (language or language_code()).lower()
    path = LOCALE_ROOT / f"{lang}.json"
    if not path.exists():
        path = LOCALE_ROOT / "en.json"
    raw = _load_json(path)
    return {str(key): str(value) for key, value in raw.items()}


def vehicle_profile(profile_id: str) -> dict[str, Any]:
    return _load_json(DATA_ROOT / "vehicles" / f"{profile_id}.json")


def all_vehicle_profiles() -> list[dict[str, Any]]:
    directory = DATA_ROOT / "vehicles"
    result = []
    for path in sorted(directory.glob("*.json")):
        try:
            result.append(_load_json(path))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return result


def dtc_database() -> dict[str, Any]:
    return _load_json(DATA_ROOT / "dtc_codes.json")


def dtc_description(code: str, manufacturer: str = "generic", language: str | None = None) -> str:
    lang = (language or language_code()).lower()
    db = dtc_database().get("manufacturers", {})
    for key in (manufacturer, "generic"):
        entry = db.get(key, {}) if isinstance(db, dict) else {}
        codes = entry.get("codes", {}) if isinstance(entry, dict) else {}
        text = codes.get(code.upper()) if isinstance(codes, dict) else None
        if isinstance(text, dict):
            return str(text.get(lang) or text.get("en") or text.get("de") or "")
    return ""

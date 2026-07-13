#!/usr/bin/env python3
"""Portable JSON-backed application settings.

The frozen Windows release stores ``settings.json`` next to the executable.
Source installations use the normal per-user configuration directory. Set
``ELM327_SETTINGS_PATH`` to force an explicit file location on any platform.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import threading
from pathlib import Path
from typing import Any

from PySide6.QtCore import QByteArray

APP_DIR_NAME = "OBD_ELM327_Engine_Diagnosis_Helper"
SETTINGS_FILENAME = "settings.json"
_TYPE_KEY = "__elm327_type__"


def default_settings_path() -> Path:
    """Return the settings path without touching the registry."""
    override = os.environ.get("ELM327_SETTINGS_PATH", "").strip()
    if override:
        return Path(override).expanduser().resolve()

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().with_name(SETTINGS_FILENAME)

    if sys.platform == "win32":
        root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / APP_DIR_NAME / SETTINGS_FILENAME


def _encode(value: Any) -> Any:
    if isinstance(value, QByteArray):
        raw = bytes(value)
        return {_TYPE_KEY: "bytes", "base64": base64.b64encode(raw).decode("ascii")}
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {
            _TYPE_KEY: "bytes",
            "base64": base64.b64encode(bytes(value)).decode("ascii"),
        }
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _encode(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_encode(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _decode(value: Any) -> Any:
    if isinstance(value, dict):
        if value.get(_TYPE_KEY) == "bytes":
            try:
                return QByteArray(base64.b64decode(str(value.get("base64", ""))))
            except (ValueError, TypeError):
                return QByteArray()
        return {str(key): _decode(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decode(item) for item in value]
    return value


class JsonSettings:
    """Small QSettings-compatible subset backed by a human-readable JSON file."""

    def __init__(self, *_ignored: object, path: str | Path | None = None):
        self.path = Path(path).expanduser().resolve() if path else default_settings_path()
        self._lock = threading.RLock()
        self._data: dict[str, Any] = {}
        self._dirty = False
        self._load()

    def _load(self) -> None:
        with self._lock:
            if not self.path.is_file():
                self._data = {}
                return
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                self._data = {}
                return
            self._data = raw if isinstance(raw, dict) else {}

    @staticmethod
    def _parts(key: str) -> list[str]:
        return [part for part in str(key).strip("/").split("/") if part]

    def value(self, key: str, default: Any = None) -> Any:
        with self._lock:
            node: Any = self._data
            for part in self._parts(key):
                if not isinstance(node, dict) or part not in node:
                    return default
                node = node[part]
            return _decode(node)

    def setValue(self, key: str, value: Any) -> None:
        parts = self._parts(key)
        if not parts:
            raise ValueError("Settings key must not be empty.")
        with self._lock:
            node = self._data
            for part in parts[:-1]:
                child = node.get(part)
                if not isinstance(child, dict):
                    child = {}
                    node[part] = child
                node = child
            encoded = _encode(value)
            if node.get(parts[-1]) != encoded:
                node[parts[-1]] = encoded
                self._dirty = True

    def sync(self) -> None:
        with self._lock:
            if not self._dirty and self.path.is_file():
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            payload = json.dumps(
                self._data,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ) + "\n"
            temporary.write_text(payload, encoding="utf-8")
            os.replace(temporary, self.path)
            self._dirty = False

    def fileName(self) -> str:
        return str(self.path)

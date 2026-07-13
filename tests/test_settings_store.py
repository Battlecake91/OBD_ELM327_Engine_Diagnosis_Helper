import json

from PySide6.QtCore import QByteArray

from settings_store import JsonSettings, default_settings_path


def test_json_settings_round_trip(tmp_path):
    path = tmp_path / "settings.json"
    settings = JsonSettings(path=path)
    settings.setValue("connection/baud", "38400")
    settings.setValue("profiles/example", ["rpm", "map"])
    settings.setValue("ui/geometry", QByteArray(b"geometry-bytes"))
    settings.sync()

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["connection"]["baud"] == "38400"
    assert raw["profiles"]["example"] == ["rpm", "map"]

    restored = JsonSettings(path=path)
    assert restored.value("connection/baud") == "38400"
    assert restored.value("profiles/example") == ["rpm", "map"]
    assert bytes(restored.value("ui/geometry")) == b"geometry-bytes"


def test_environment_override(monkeypatch, tmp_path):
    expected = tmp_path / "portable.json"
    monkeypatch.setenv("ELM327_SETTINGS_PATH", str(expected))
    assert default_settings_path() == expected.resolve()


def test_missing_or_invalid_file_uses_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("not-json", encoding="utf-8")
    settings = JsonSettings(path=path)
    assert settings.value("missing", 123) == 123

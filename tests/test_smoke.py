import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication

from elm327_app import APP_VERSION, BluetoothScanner, MainWindow, stage_dict, stage_value
from elm327_twingo_gui import TestStage


APP = QApplication.instance() or QApplication([])


def test_main_window_starts_without_plot_capture(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    window = MainWindow()
    try:
        assert APP_VERSION == "3.1.0"
        assert window.capture_active is False
        assert window.csv_writer is None
        assert window.tabs.count() == 6
        assert window.tabs.tabText(5) == "Settings"
        assert window.pid_presets
        assert window.test_profiles
    finally:
        window.close()


def test_profiles_survive_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    first = MainWindow()
    try:
        first.pid_presets["Workshop"] = ["rpm", "map"]
        first.test_profiles["Workshop test"] = {
            "pid": "Workshop",
            "stages": [TestStage("Idle", "Stabilise at idle.", 5)],
        }
        first._save_settings()
    finally:
        first.close()

    second = MainWindow()
    try:
        assert second.pid_presets["Workshop"] == ["rpm", "map"]
        assert second.test_profiles["Workshop test"]["pid"] == "Workshop"
        assert second.test_profiles["Workshop test"]["stages"][0].name == "Idle"
    finally:
        second.close()


def test_stage_profile_roundtrip():
    source = TestStage("2500 rpm", "Hold target speed.", 20, 2500, 120, False)
    restored = stage_value(stage_dict(source))
    assert restored == source


def test_bluetoothctl_device_parser():
    devices = BluetoothScanner.parse(
        "Device 00:11:22:33:44:55 OBDII\n"
        "Device AA:BB:CC:DD:EE:FF Other adapter\n"
        "Device 00:11:22:33:44:55 OBDII\n"
    )
    assert devices == [
        {"address": "00:11:22:33:44:55", "name": "OBDII"},
        {"address": "AA:BB:CC:DD:EE:FF", "name": "Other adapter"},
    ]


def test_version_2_csv_remains_readable(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    csv_path = tmp_path / "v2.csv"
    csv_path.write_text(
        "Zeitstempel;Laufzeit_s;Schlüssel;Messwert;Wert;Einheit;Kommentar\n"
        "2026-01-01T00:00:00.000;0.100;rpm;Motordrehzahl;750;1/min;\n"
        "2026-01-01T00:00:00.100;0.200;__marker__;Kommentar;;;Test marker\n",
        encoding="utf-8-sig",
    )
    window = MainWindow()
    try:
        history, markers, maximum, _ = window._parse_csv(csv_path)
        assert history["rpm"] == [(0.1, 750.0)]
        assert markers[0].text == "Test marker"
        assert maximum == 0.2
    finally:
        window.close()


def test_application_icon_is_packaged():
    icon = Path(__file__).resolve().parents[1] / "assets" / (
        "io.github.open-diagnostics.elm327-live-diagnostic.svg"
    )
    assert icon.is_file()

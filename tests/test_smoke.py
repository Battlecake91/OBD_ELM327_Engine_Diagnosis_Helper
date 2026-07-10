import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication

from elm327_twingo_gui import APP_VERSION, MainWindow


APP = QApplication.instance() or QApplication([])


def test_main_window_starts_without_plot_capture(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    window = MainWindow()
    try:
        assert APP_VERSION == "3.0"
        assert window.capture_active is False
        assert window.csv_writer is None
        assert window.tabs.count() == 6
        assert window.tabs.tabText(5) == "Settings"
    finally:
        window.close()


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

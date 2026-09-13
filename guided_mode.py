from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pyqtgraph as pg

from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QGridLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

import elm327_twingo_gui as core
from diagnostic_data import (
    all_vehicle_profiles,
    dtc_description,
    language_code,
    translations,
    vehicle_profile,
)
from opel_kwp2000 import (
    OPEL_PROTOCOL_TOKEN,
    initialize_opel_adapter,
    probe_opel_engine,
)


class AutoDetectWorker(QThread):
    """Conservative interface detection used by the guided connection wizard."""

    status = Signal(str)
    detected = Signal(str, str, str)
    failed = Signal(str)

    def __init__(self, port: str, baudrate: int, timeout: float = 2.0, tr: dict[str, str] | None = None, parent=None):
        super().__init__(parent)
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.tr = tr or translations()

    def _text(self, key: str, fallback: str, **values) -> str:
        return self.tr.get(key, fallback).format(**values)

    @staticmethod
    def _has_standard_obd_reply(raw: str) -> bool:
        for row in core.ELM327.extract_hex_bytes(raw, "0100"):
            for index in range(max(0, len(row) - 1)):
                if row[index:index + 2] == [0x41, 0x00]:
                    return True
        return False

    def run(self) -> None:
        elm = core.ELM327(
            self.port,
            self.baudrate,
            stop_event=__import__("threading").Event(),
            timeout=self.timeout,
            protocol_command="ATSP0",
        )
        try:
            self.status.emit(self._text("detect.open", "Opening adapter: {port} @ {baud} baud", port=self.port, baud=self.baudrate))
            elm.open()

            for command in ("ATZ", "ATE0", "ATL0", "ATS1", "ATH1", "ATM0"):
                if self.isInterruptionRequested():
                    return
                self.status.emit(self._text("detect.init", "Initializing adapter: {command}", command=command))
                elm.command(command, 3.5 if command == "ATZ" else 1.0)

            generic_attempts = [
                ("ATSP0", "OBD-II automatic"),
                ("ATSP3", "ISO 9141-2"),
                ("ATSP4", "ISO 14230 KWP Slow Init"),
                ("ATSP5", "ISO 14230 KWP Fast Init"),
                ("ATSP6", "ISO 15765 CAN 11/500"),
            ]
            for protocol, label in generic_attempts:
                if self.isInterruptionRequested():
                    return
                self.status.emit(self._text("detect.try", "Trying {protocol} …", protocol=label))
                try:
                    elm.command("ATPC", 1.0)
                    elm.command(protocol, 1.0)
                    raw = elm.command("0100", 8.0 if protocol == "ATSP0" else 4.0)
                    if self._has_standard_obd_reply(raw):
                        self.detected.emit(protocol, "generic_obd2", self._text("detect.generic_found", "Standard OBD-II detected ({protocol})", protocol=label))
                        return
                except Exception as exc:
                    self.status.emit(self._text("detect.no_reply", "{protocol}: no usable response ({error})", protocol=label, error=exc))

            if self.isInterruptionRequested():
                return
            self.status.emit(self._text("detect.opel_try", "Trying Opel X16XEL / Multec-H KWP2000 Fast Init …"))
            try:
                elm.command("ATPC", 1.0)
                initialize_opel_adapter(elm, lambda text: self.status.emit(text.splitlines()[0]))
                success, _report = probe_opel_engine(elm, lambda text: self.status.emit(text.splitlines()[0]), targets=(0x11,))
                if success:
                    self.detected.emit(OPEL_PROTOCOL_TOKEN, "opel_astra_g_x16xel_multec_h", self._text("detect.opel_found", "Opel X16XEL / Multec-H detected"))
                    return
            except Exception as exc:
                self.status.emit(self._text("detect.opel_no_reply", "Opel profile: no usable response ({error})", error=exc))

            self.failed.emit(self._text("detect.failed", "No supported control unit was detected automatically."))
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            elm.close()


class ConnectionWizard(QWizard):
    """Guided adapter and vehicle/interface setup."""

    def __init__(self, window, tr: dict[str, str], parent=None):
        super().__init__(parent or window)
        self.window = window
        self.tr = tr
        self.detector: AutoDetectWorker | None = None
        self.setWindowTitle(tr.get("wizard.title", "Guided connection"))
        self.setMinimumSize(720, 500)
        self._build_adapter_page()
        self._build_vehicle_page()
        self._build_status_page()
        self.currentIdChanged.connect(self._page_changed)

    def _build_adapter_page(self) -> None:
        page = QWizardPage()
        page.setTitle(self.tr.get("wizard.adapter", "Adapter"))
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel(self.tr.get("wizard.adapter_intro", "Select an ELM327 or compatible adapter.")))
        self.port_combo = QComboBox()
        layout.addWidget(self.port_combo)

        refresh = QPushButton(self.tr.get("wizard.refresh_ports", "Refresh ports"))
        refresh.clicked.connect(self._refresh_ports)
        layout.addWidget(refresh)

        guide = QLabel(
            self.tr.get(
                "wizard.bt_windows" if sys.platform.startswith("win") else "wizard.bt_linux",
                "",
            )
        )
        guide.setWordWrap(True)
        guide.setStyleSheet("padding: 12px; border: 1px solid palette(mid); border-radius: 6px;")
        layout.addWidget(guide)
        layout.addStretch(1)
        self.addPage(page)
        self._refresh_ports()

    def _refresh_ports(self) -> None:
        self.window._refresh_ports()
        current = self.window.port_combo.currentData()
        self.port_combo.clear()
        for index in range(self.window.port_combo.count()):
            self.port_combo.addItem(
                self.window.port_combo.itemText(index),
                self.window.port_combo.itemData(index),
            )
        selected = self.port_combo.findData(current)
        if selected >= 0:
            self.port_combo.setCurrentIndex(selected)

    def _build_vehicle_page(self) -> None:
        page = QWizardPage()
        page.setTitle(self.tr.get("wizard.vehicle", "Vehicle / interface"))
        layout = QVBoxLayout(page)
        self.vehicle_combo = QComboBox()
        self.vehicle_combo.addItem(self.tr.get("wizard.auto", "Auto detect"), "__auto__")
        lang = language_code()
        for profile in all_vehicle_profiles():
            name = profile.get("display_name", {})
            label = name.get(lang) or name.get("en") or profile.get("id")
            self.vehicle_combo.addItem(str(label), str(profile.get("id")))
        layout.addWidget(self.vehicle_combo)

        hint = QLabel(self.tr.get("wizard.auto_hint", "Auto detect tries standard OBD protocols and known manufacturer profiles."))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)
        self.addPage(page)

    def _build_status_page(self) -> None:
        page = QWizardPage()
        page.setTitle(self.tr.get("wizard.status", "Detection status"))
        layout = QVBoxLayout(page)
        self.status_output = QTextEdit()
        self.status_output.setReadOnly(True)
        layout.addWidget(self.status_output, 1)
        self.connect_button = QPushButton(self.tr.get("wizard.connect", "Connect"))
        self.connect_button.clicked.connect(self._start_connection)
        layout.addWidget(self.connect_button)
        self.addPage(page)

    def _page_changed(self, page_id: int) -> None:
        if page_id == 2:
            self.status_output.clear()
            self.status_output.append(self.tr.get("wizard.ready", "Ready. Click Connect."))

    def _select_main_port(self) -> str:
        port = str(self.port_combo.currentData() or "")
        if not port:
            return ""
        index = self.window.port_combo.findData(port)
        if index >= 0:
            self.window.port_combo.setCurrentIndex(index)
        return port

    def _select_protocol(self, token: str) -> None:
        index = self.window.protocol_combo.findData(token)
        if index >= 0:
            self.window.protocol_combo.setCurrentIndex(index)

    def _start_connection(self) -> None:
        port = self._select_main_port()
        if not port:
            QMessageBox.warning(self, self.tr.get("wizard.adapter", "Adapter"), self.tr.get("wizard.no_port", "No serial adapter selected."))
            return
        if self.window.worker is not None and self.window.worker.isRunning():
            self.accept()
            return

        selection = str(self.vehicle_combo.currentData())
        if selection != "__auto__":
            profile = vehicle_profile(selection)
            token = str(profile.get("interface", {}).get("settings_token") or "ATSP0")
            self.window.guided_mode.set_vehicle_profile(selection)
            self._select_protocol(token)
            self.window._toggle_connection()
            self.accept()
            return

        self.connect_button.setEnabled(False)
        self.status_output.append(self.tr.get("wizard.auto_started", "Automatic detection started …"))
        detector = AutoDetectWorker(
            port,
            int(self.window.baud_combo.currentText()),
            float(self.window.command_timeout_spin.value()),
            self.tr,
            self,
        )
        self.detector = detector
        detector.status.connect(self.status_output.append)
        detector.detected.connect(self._auto_detected)
        detector.failed.connect(self._auto_failed)
        detector.finished.connect(self._detector_finished)
        detector.start()

    def _auto_detected(self, token: str, profile_id: str, message: str) -> None:
        self.status_output.append("✓ " + message)
        self.window.guided_mode.set_vehicle_profile(profile_id)
        self._select_protocol(token)
        QTimer.singleShot(100, self.window._toggle_connection)
        QTimer.singleShot(250, self.accept)

    def _auto_failed(self, message: str) -> None:
        self.status_output.append("✗ " + message)
        self.connect_button.setEnabled(True)

    def _detector_finished(self) -> None:
        self.detector = None
        self.connect_button.setEnabled(True)

    def reject(self) -> None:
        if self.detector is not None and self.detector.isRunning():
            self.detector.requestInterruption()
            self.detector.wait(1000)
        super().reject()


class StartupModeDialog(QDialog):
    def __init__(self, tr: dict[str, str], parent=None):
        super().__init__(parent)
        self.mode = "easy"
        self.setWindowTitle(tr.get("startup.title", "Choose startup mode"))
        self.setModal(True)
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        text = QLabel(tr.get("startup.text", "How do you want to start diagnostics?"))
        text.setStyleSheet("font-size: 16px; font-weight: 600;")
        layout.addWidget(text)

        easy = QPushButton(tr.get("startup.easy", "Guided assistant"))
        easy.setMinimumHeight(54)
        easy.clicked.connect(lambda: self._choose("easy"))
        expert = QPushButton(tr.get("startup.expert", "Expert mode"))
        expert.setMinimumHeight(54)
        expert.clicked.connect(lambda: self._choose("expert"))
        layout.addWidget(easy)
        layout.addWidget(expert)

    def _choose(self, mode: str) -> None:
        self.mode = mode
        self.accept()


class GuidedModeController:
    """Easy/Expert presentation layer over the existing diagnostic window."""

    def __init__(self, window) -> None:
        self.window = window
        self.tr = translations()
        self.mode = "expert"
        self.expert_indices = list(range(window.tabs.count()))
        self.easy_dtc_rows: dict[str, int] = {}
        self.easy_live_rows: dict[str, int] = {}
        self._vehicle_profile_id = "generic_obd2"
        self._vehicle_profile = vehicle_profile(self._vehicle_profile_id)
        self._build_mode_bar()
        self._build_easy_tabs()
        self.set_mode("expert")
        QTimer.singleShot(0, self._startup_choice)

    def _build_mode_bar(self) -> None:
        frame = QFrame()
        frame.setObjectName("modeBar")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.addStretch(1)
        self.easy_button = QPushButton(self.tr.get("mode.easy", "Easy"))
        self.expert_button = QPushButton(self.tr.get("mode.expert", "Expert"))
        for button in (self.easy_button, self.expert_button):
            button.setCheckable(True)
            button.setMinimumWidth(78)
            button.setMaximumHeight(28)
        self.easy_button.clicked.connect(lambda: self.set_mode("easy"))
        self.expert_button.clicked.connect(lambda: self.set_mode("expert"))
        layout.addWidget(self.easy_button)
        layout.addWidget(self.expert_button)
        self.window.centralWidget().layout().insertWidget(0, frame)
        self.mode_bar = frame

    def _build_easy_tabs(self) -> None:
        self.easy_fault_tab = QWidget()
        fault_layout = QVBoxLayout(self.easy_fault_tab)
        controls = QHBoxLayout()
        setup = QPushButton(self.tr.get("easy.setup", "Set up connection"))
        setup.clicked.connect(self.show_connection_wizard)
        read = QPushButton(self.tr.get("easy.read_dtcs", "Read fault memory"))
        read.clicked.connect(self._read_dtcs)
        clear = QPushButton(self.tr.get("easy.clear_dtcs", "Clear fault memory"))
        clear.clicked.connect(self._clear_dtcs)
        controls.addWidget(setup)
        controls.addWidget(read)
        controls.addWidget(clear)
        controls.addStretch(1)
        fault_layout.addLayout(controls)

        self.easy_dtc_table = QTableWidget(0, 2)
        self.easy_dtc_table.setHorizontalHeaderLabels([
            self.tr.get("easy.code", "Fault code"),
            self.tr.get("easy.meaning", "Meaning"),
        ])
        self.easy_dtc_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.easy_dtc_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.easy_dtc_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        fault_layout.addWidget(self.easy_dtc_table, 1)
        self.easy_fault_status = QLabel(self.tr.get("easy.no_dtcs", "No stored faults."))
        fault_layout.addWidget(self.easy_fault_status)

        self.easy_live_tab = QWidget()
        live_layout = QVBoxLayout(self.easy_live_tab)
        row = QHBoxLayout()
        row.addWidget(QLabel(self.tr.get("easy.preset", "Measurement preset")))
        self.preset_combo = QComboBox()
        self._populate_presets()
        self.preset_combo.currentIndexChanged.connect(self._apply_preset)
        row.addWidget(self.preset_combo)
        row.addStretch(1)
        setup2 = QPushButton(self.tr.get("easy.setup", "Set up connection"))
        setup2.clicked.connect(self.show_connection_wizard)
        row.addWidget(setup2)
        live_layout.addLayout(row)

        self.easy_live_table = QTableWidget(0, 3)
        self.easy_live_table.setHorizontalHeaderLabels([self.tr.get("easy.measurement", "Measurement"), self.tr.get("easy.value", "Value"), self.tr.get("easy.unit", "Unit")])
        self.easy_live_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2):
            self.easy_live_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.easy_live_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.easy_live_table.setMaximumHeight(260)
        live_layout.addWidget(self.easy_live_table)

        self.easy_plot_scroll = QScrollArea()
        self.easy_plot_scroll.setWidgetResizable(True)
        self.easy_plot_content = QWidget()
        self.easy_plot_grid = QGridLayout(self.easy_plot_content)
        self.easy_plot_scroll.setWidget(self.easy_plot_content)
        self.easy_plot_widgets: dict[str, pg.PlotWidget] = {}
        self.easy_plot_curves: dict[str, object] = {}
        live_layout.addWidget(self.easy_plot_scroll, 1)

        self.easy_plot_timer = QTimer(self.easy_live_tab)
        self.easy_plot_timer.timeout.connect(self._refresh_easy_plots)
        self.easy_plot_timer.start(400)

        export_row = QHBoxLayout()
        self.capture_button = QPushButton(self.tr.get("easy.start_capture", "Start recording"))
        self.capture_button.clicked.connect(self._toggle_capture)
        csv_button = QPushButton(self.tr.get("easy.export_csv", "Export CSV"))
        csv_button.clicked.connect(self.window._export_complete_session)
        image_button = QPushButton(self.tr.get("easy.export_image", "Export image"))
        image_button.clicked.connect(self._export_image)
        export_row.addWidget(self.capture_button)
        export_row.addWidget(csv_button)
        export_row.addWidget(image_button)
        export_row.addStretch(1)
        live_layout.addLayout(export_row)

        self.easy_fault_index = self.window.tabs.addTab(
            self.easy_fault_tab, self.tr.get("easy.faults", "Fault memory")
        )
        self.easy_live_index = self.window.tabs.addTab(
            self.easy_live_tab, self.tr.get("easy.live", "Live data")
        )
        self.easy_indices = [self.easy_fault_index, self.easy_live_index]
        self._apply_preset()

    def _startup_choice(self) -> None:
        dialog = StartupModeDialog(self.tr, self.window)
        dialog.exec()
        self.set_mode(dialog.mode)
        if dialog.mode == "easy":
            QTimer.singleShot(150, self.show_connection_wizard)

    def set_mode(self, mode: str) -> None:
        self.mode = "easy" if mode == "easy" else "expert"
        easy = self.mode == "easy"
        if easy:
            token = str(self.window.protocol_combo.currentData() or "")
            expected = (
                "opel_astra_g_x16xel_multec_h"
                if token == OPEL_PROTOCOL_TOKEN
                else "generic_obd2"
            )
            if expected != self._vehicle_profile_id:
                self.set_vehicle_profile(expected)
        bar = self.window.tabs.tabBar()
        for index in self.expert_indices:
            bar.setTabVisible(index, not easy)
        for index in self.easy_indices:
            bar.setTabVisible(index, easy)
        self.easy_button.setChecked(easy)
        self.expert_button.setChecked(not easy)
        self.easy_button.setStyleSheet(
            "font-weight: 700; background: #4f9d69;" if easy else ""
        )
        self.expert_button.setStyleSheet(
            "font-weight: 700; background: #d1a33b;" if not easy else ""
        )
        self.window.tabs.setCurrentIndex(
            self.easy_fault_index if easy else self.expert_indices[0]
        )

    def _read_dtcs(self) -> None:
        worker = self.window._require_worker()
        if worker is None:
            return
        self.easy_fault_status.setText(
            self.tr.get("easy.reading_dtcs", "Reading fault memory …")
        )
        worker.request_dtcs()

    def _clear_dtcs(self) -> None:
        worker = self.window._require_worker()
        if worker is None:
            return
        answer = QMessageBox.question(
            self.window,
            self.tr.get("easy.clear_title", "Clear fault memory"),
            self.tr.get(
                "easy.clear_confirm",
                "Really clear the fault memory?",
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            worker.request_clear_dtcs()

    def show_connection_wizard(self) -> None:
        ConnectionWizard(self.window, self.tr, self.window).exec()

    def set_vehicle_profile(self, profile_id: str) -> None:
        """Activate the JSON profile selected or detected by the connection wizard."""
        self._vehicle_profile_id = profile_id
        self._vehicle_profile = vehicle_profile(profile_id)
        self._populate_presets()
        self._apply_preset()

    def _populate_presets(self) -> None:
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        lang = language_code()
        for preset in self._vehicle_profile.get("live_presets", []):
            name = preset.get("name", {})
            label = name.get(lang) or name.get("en") or preset.get("id")
            self.preset_combo.addItem(str(label), list(preset.get("keys", [])))
        self.preset_combo.blockSignals(False)
        if self.preset_combo.count():
            self.preset_combo.setCurrentIndex(0)

    def _apply_preset(self) -> None:
        keys = set(self.preset_combo.currentData() or [])
        if not keys:
            return
        self.window.enabled_keys = keys
        if hasattr(self.window, "pid_table"):
            self.window.pid_table.blockSignals(True)
            try:
                for sensor in core.SENSORS:
                    item = self.window.pid_table.item(self.window.pid_row_by_key[sensor.key], 0)
                    item.setCheckState(
                        Qt.CheckState.Checked if sensor.key in keys else Qt.CheckState.Unchecked
                    )
            finally:
                self.window.pid_table.blockSignals(False)
        self.window._apply_pid_visibility()
        if self.window.worker is not None:
            self.window.worker.update_enabled_keys(self.window._effective_worker_keys())
        self._rebuild_live_table(keys)

    def _rebuild_live_table(self, keys: set[str]) -> None:
        sensors = [sensor for sensor in core.SENSORS if sensor.key in keys]
        self.easy_live_rows.clear()
        self.easy_live_table.setRowCount(len(sensors))
        for row, sensor in enumerate(sensors):
            self.easy_live_rows[sensor.key] = row
            self.easy_live_table.setItem(row, 0, QTableWidgetItem(self.tr.get(f"sensor.{sensor.key}", sensor.name)))
            self.easy_live_table.setItem(row, 1, QTableWidgetItem("–"))
            self.easy_live_table.setItem(row, 2, QTableWidgetItem(sensor.unit))
        self._rebuild_easy_plots(sensors)

    def _clear_easy_plot_grid(self) -> None:
        while self.easy_plot_grid.count():
            item = self.easy_plot_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self.easy_plot_widgets.clear()
        self.easy_plot_curves.clear()

    def _rebuild_easy_plots(self, sensors: list[core.SensorDefinition]) -> None:
        self._clear_easy_plot_grid()
        for index, sensor in enumerate(sensors):
            plot = pg.PlotWidget()
            plot.setMinimumHeight(190)
            plot.setTitle(self.tr.get(f"sensor.{sensor.key}", sensor.name))
            plot.setLabel("left", sensor.unit)
            plot.setLabel("bottom", self.tr.get("easy.time", "Time"), units="s")
            plot.showGrid(x=True, y=True, alpha=0.25)
            plot.setDownsampling(auto=True, mode="peak")
            plot.setClipToView(True)
            curve = plot.plot([], [])
            curve.setDownsampling(auto=True, method="peak")
            curve.setClipToView(True)
            self.easy_plot_grid.addWidget(plot, index // 2, index % 2)
            self.easy_plot_widgets[sensor.key] = plot
            self.easy_plot_curves[sensor.key] = curve

    def _refresh_easy_plots(self) -> None:
        if not self.easy_plot_curves:
            return
        end = max(10.0, float(self.window.plot_time))
        start = max(0.0, end - 300.0)
        for key, curve in self.easy_plot_curves.items():
            points = self.window.history.get(key)
            if not points:
                curve.setData([], [])
                continue
            array = np.asarray(points, dtype=np.float64)
            index = int(np.searchsorted(array[:, 0], start, side="left")) if start > 0 else 0
            visible = array[index:]
            curve.setData(visible[:, 0], visible[:, 1]) if visible.size else curve.setData([], [])
            plot = self.easy_plot_widgets[key]
            plot.setXRange(start, end, padding=0.01)

    def on_sample(self, key: str, value: float) -> None:
        row = self.easy_live_rows.get(key)
        if row is None:
            return
        sensor = core.SENSOR_BY_KEY.get(key)
        decimals = sensor.decimals if sensor is not None else 2
        self.easy_live_table.item(row, 1).setText(f"{value:.{decimals}f}")
        self.capture_button.setText(
            self.tr.get("easy.stop_capture", "Stop recording")
            if self.window.capture_active
            else self.tr.get("easy.start_capture", "Start recording")
        )

    def show_dtcs(self, dtcs: Any) -> None:
        records = list(dtcs)
        self.easy_dtc_table.setRowCount(len(records))
        manufacturer = str(self._vehicle_profile.get("manufacturer") or "generic")
        lang = language_code()
        for row, item in enumerate(records):
            code = str(getattr(item, "code", item))
            description = str(getattr(item, "description", "") or "")
            database_text = dtc_description(code, manufacturer=manufacturer, language=lang)
            if database_text:
                description = database_text
            self.easy_dtc_table.setItem(row, 0, QTableWidgetItem(code))
            self.easy_dtc_table.setItem(row, 1, QTableWidgetItem(description or "–"))
        self.easy_fault_status.setText(
            self.tr.get("easy.dtc_count", "{count} stored fault(s).").format(count=len(records)) if records else self.tr.get("easy.no_dtcs", "No stored faults.")
        )

    def _toggle_capture(self) -> None:
        if self.window.capture_active:
            self.window._stop_capture_writer()
        else:
            self.window._start_plot_capture()
        self.capture_button.setText(
            self.tr.get("easy.stop_capture", "Stop recording")
            if self.window.capture_active
            else self.tr.get("easy.start_capture", "Start recording")
        )

    def _export_image(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(
            self.window,
            self.tr.get("easy.export_image", "Export image"),
            str(Path.home() / f"obd_live_{time.strftime('%Y%m%d_%H%M%S')}.png"),
            "PNG (*.png)",
        )
        if not filename:
            return
        if not filename.lower().endswith(".png"):
            filename += ".png"
        if not self.easy_live_tab.grab().save(filename, "PNG"):
            QMessageBox.warning(self.window, self.tr.get("common.export", "Export"), self.tr.get("easy.export_failed", "The image could not be saved."))

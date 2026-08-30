#!/usr/bin/env python3
"""Opel Astra-G X16XEL / Multec-H KWP2000 integration.

The vehicle-specific transport has been verified on a real 1999 Astra G:
KWP2000 Fast Init, target 0x11, tester 0xF1, keywords EF/8F.  This module keeps
that proven setup while exposing normal DTC buttons and live-data samples to the
existing dashboard/plot/CSV pipeline.
"""

from __future__ import annotations

import queue
import time
from dataclasses import dataclass
from typing import Callable

import serial
from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import QMessageBox

import elm327_twingo_gui as core
import elm327_app as app
import opel_multec_profile as profile


# Preserve the original settings token so existing installations stay selected.
KW82_PROTOCOL_TOKEN = "OPEL_KW82_9600"
KW82_PROTOCOL_LABEL = "Opel Astra G X16XEL / Multec-H"
OPEL_TESTER_ADDRESS = 0xF1
OPEL_ENGINE_TARGETS = (0x11, 0x10)
OPEL_IDENT_REQUEST = "1A80"


@dataclass(frozen=True)
class ProbeStep:
    command: str
    response: str
    ok: bool


@dataclass(frozen=True)
class FastInitAttempt:
    target: int
    header: str
    fast_init: ProbeStep
    start_response: ProbeStep
    buffer_response: ProbeStep


def _response_without_prompt(response: str) -> str:
    return response.upper().replace(">", "").strip()


def _response_ok(response: str) -> bool:
    upper = _response_without_prompt(response)
    if not upper or upper == "?":
        return False
    return not any(
        token in upper
        for token in (
            "BUS INIT: ERROR",
            "BUS INIT: ...ERROR",
            "UNABLE TO CONNECT",
            "NO DATA",
            "ERROR",
        )
    )


def _run_step(
    elm: core.ELM327,
    command: str,
    timeout: float,
    log: Callable[[str], None],
) -> ProbeStep:
    try:
        raw = elm.command(command, timeout)
        response = raw.strip()
        ok = _response_ok(response)
    except Exception as exc:
        response = f"{type(exc).__name__}: {exc}"
        ok = False
    log(f"> {command}\n{response}")
    return ProbeStep(command=command, response=response, ok=ok)


def initialize_adapter_for_kw82_probe(
    elm: core.ELM327,
    log: Callable[[str], None],
) -> str:
    """Reset the adapter without sending a normal OBD-II request."""
    identity = "ELM327-compatible adapter"
    for command, timeout in (
        ("ATZ", 3.5),
        ("ATE0", 1.0),
        ("ATL0", 1.0),
        ("ATS1", 1.0),
        ("ATH1", 1.0),
        ("ATM0", 1.0),
    ):
        result = _run_step(elm, command, timeout, log)
        if command == "ATZ" and result.response:
            lines = core.ELM327.clean_lines(result.response, command)
            candidate = " ".join(
                line for line in lines if line not in {"OK", "STOPPED"}
            ).strip()
            if candidate:
                identity = candidate
    return identity


def _hex_rows(response: str, command: str = "") -> list[list[int]]:
    try:
        return core.ELM327.extract_hex_bytes(response, command)
    except Exception:
        return []


def _contains_service(response: str, command: str, service: int, option: int | None = None) -> bool:
    for row in _hex_rows(response, command):
        for index, value in enumerate(row):
            if value != service:
                continue
            if option is None:
                return True
            if index + 1 < len(row) and row[index + 1] == option:
                return True
    return False


def _kwp_start_accepted(response: str) -> bool:
    """Positive response to StartCommunication service 0x81 is service 0xC1."""
    return _contains_service(response, "81", 0xC1)


def _identification_accepted(response: str) -> bool:
    """Positive response to ReadEcuIdentification 0x1A is service 0x5A."""
    return _contains_service(response, OPEL_IDENT_REQUEST, 0x5A, 0x80)


def _valid_buffer_bytes(response: str) -> str:
    rows = _hex_rows(response, "ATBD")
    if not rows or not rows[0]:
        return "none"
    row = rows[0]
    length = row[0]
    valid = row[1:1 + min(length, max(0, len(row) - 1))]
    if not valid:
        return f"length={length}, no captured bytes"
    return f"length={length}, valid=" + " ".join(f"{value:02X}" for value in valid)


def _identification_ascii(response: str) -> str:
    for row in _hex_rows(response, OPEL_IDENT_REQUEST):
        for index in range(max(0, len(row) - 1)):
            if row[index:index + 2] != [0x5A, 0x80]:
                continue
            data = row[index + 2:]
            text = "".join(chr(value) if 32 <= value <= 126 else " " for value in data)
            return " ".join(text.split()) or "no printable ASCII"
    return "no 0x5A 0x80 payload"


def probe_kw82_engine(
    elm: core.ELM327,
    log: Callable[[str], None],
    targets: tuple[int, ...] = OPEL_ENGINE_TARGETS,
) -> tuple[bool, str]:
    """Establish the verified Opel KWP2000 session and read ECU identification."""
    steps: list[ProbeStep] = []
    attempts: list[FastInitAttempt] = []

    def step(command: str, timeout: float = 1.0) -> ProbeStep:
        result = _run_step(elm, command, timeout, log)
        steps.append(result)
        return result

    success = False
    successful_target: int | None = None
    identification: ProbeStep | None = None

    for raw_target in targets:
        target = raw_target & 0xFF
        header = f"81{target:02X}{OPEL_TESTER_ADDRESS:02X}"

        step("ATPC")
        step("ATSP5")
        step("ATKW0")
        step("ATIB10")
        step("ATAT0")
        step("ATSTFF")
        step("ATAL")
        step(f"ATSH{header}")
        step(f"ATWM{header}3E")
        fast_init = step("ATFI", 3.0)
        start_response = step("81", 4.0)
        buffer_response = step("ATBD", 1.5)

        attempts.append(
            FastInitAttempt(
                target=target,
                header=header,
                fast_init=fast_init,
                start_response=start_response,
                buffer_response=buffer_response,
            )
        )

        if _kwp_start_accepted(start_response.response):
            success = True
            successful_target = target
            identification = step(OPEL_IDENT_REQUEST, 5.0)
            break

    protocol = step("ATDP", 1.0)
    protocol_number = step("ATDPN", 1.0)
    keyword = step("ATKW", 1.0)

    unsupported = sorted(
        {
            item.command
            for item in steps
            if _response_without_prompt(item.response) == "?"
        }
    )

    attempt_reports: list[str] = []
    for attempt in attempts:
        attempt_reports.append(
            "\n".join(
                (
                    f"- target ECU 0x{attempt.target:02X}",
                    "  protocol: ATSP5 (ISO 14230-4 KWP Fast Init)",
                    f"  header: {attempt.header[:2]} {attempt.header[2:4]} {attempt.header[4:6]}",
                    f"  ATFI: {attempt.fast_init.response}",
                    f"  StartCommunication (81): {attempt.start_response.response}",
                    f"  ATBD: {_valid_buffer_bytes(attempt.buffer_response.response)}",
                )
            )
        )

    lines = [
        "Opel Astra G X16XEL / Multec-H KWP2000 session",
        "================================================",
        "",
        "Target: engine ECU on vehicle DLC pin 7",
        "Tester address: 0xF1",
        "",
        "Session attempts:",
        *attempt_reports,
        "",
        f"KWP StartCommunication: {'SUCCESS' if success else 'NO POSITIVE C1 RESPONSE'}",
        f"ELM active protocol: {protocol.response}",
        f"ELM protocol number: {protocol_number.response}",
        f"ELM keywords: {keyword.response}",
    ]

    if successful_target is not None:
        ident_ok = bool(identification and _identification_accepted(identification.response))
        lines.extend(
            (
                "",
                "ReadEcuIdentification 0x1A / option 0x80:",
                identification.response if identification is not None else "not sent",
                f"Identification response: {'POSITIVE 0x5A 0x80' if ident_ok else 'no positive 0x5A 0x80 response'}",
                f"Printable identification text: {_identification_ascii(identification.response) if identification else 'none'}",
                "",
                "Interpretation:",
                f"The ECU at target 0x{successful_target:02X} returned a positive KWP2000 "
                "StartCommunication response. Normal X16XEL DTC and live-data functions can now be used.",
            )
        )
    else:
        lines.extend(
            (
                "",
                "Interpretation:",
                "No positive KWP2000 StartCommunication response was received after Fast Init.",
            )
        )

    if unsupported:
        lines.extend(("", "Adapter commands not supported:", "  " + ", ".join(unsupported)))

    return success, "\n".join(lines)


class OpelKW82ProbeWorker(core.OBDWorker):
    """X16XEL KWP worker with block live polling and Opel DTC requests."""

    probe_ready = Signal(str)

    def _process_requests(self, limit: int = 100) -> None:
        if self.elm is None or self.stop_event.is_set():
            return

        processed = 0
        while processed < limit and not self.stop_event.is_set():
            try:
                request, payload = self.requests.get_nowait()
            except queue.Empty:
                break
            processed += 1

            try:
                if request == "read_dtcs":
                    raw = self.elm.command(profile.OPEL_READ_DTCS, 5.0)
                    self.raw_log.emit(f"> {profile.OPEL_READ_DTCS}\n{raw.strip()}")
                    self.dtcs_ready.emit(profile.parse_dtc_response(raw))
                elif request == "clear_dtcs":
                    raw = self.elm.command(profile.OPEL_CLEAR_DTCS, 5.0)
                    self.raw_log.emit(f"> {profile.OPEL_CLEAR_DTCS}\n{raw.strip()}")
                    if not profile.clear_dtc_response_ok(raw):
                        raise core.ELM327Error("ECU did not confirm ClearDiagnosticInformation.")
                    verify = self.elm.command(profile.OPEL_READ_DTCS, 5.0)
                    self.raw_log.emit(f"> {profile.OPEL_READ_DTCS}\n{verify.strip()}")
                    records = profile.parse_dtc_response(verify)
                    self.dtcs_ready.emit(records)
                    self.status.emit(
                        "DTC memory cleared and verified: no DTCs remain."
                        if not records
                        else f"Clear accepted; {len(records)} DTC(s) returned immediately."
                    )
                elif request == "mode06":
                    self.mode06_ready.emit("Mode 06 is not used by the X16XEL Multec-H profile.")
                elif request == "custom" and payload:
                    response = self.elm.command(payload, 5.0)
                    self.custom_ready.emit(payload, response)
            except Exception as exc:
                if not self.stop_event.is_set():
                    self.status.emit(f"Diagnostic command failed: {exc}")

    def run(self) -> None:
        reason = "Connection closed."
        try:
            self.status.emit(
                f"Opening {self.port} at {self.baudrate} baud for Opel X16XEL / Multec-H…"
            )
            self.elm = core.ELM327(
                port=self.port,
                baudrate=self.baudrate,
                stop_event=self.stop_event,
                timeout=float(getattr(self, "command_timeout", 2.0)),
                protocol_command="ATSP5",
            )
            self.elm.open()
            identity = initialize_adapter_for_kw82_probe(self.elm, self.raw_log.emit)
            success, report = probe_kw82_engine(self.elm, self.raw_log.emit)

            self.connected.emit(f"{identity} · Opel X16XEL / Multec-H", set())
            self.probe_ready.emit(report)
            self.status.emit(
                "Multec-H session established; live data and DTC functions are available."
                if success
                else "Multec-H Fast Init failed; inspect the raw log."
            )

            adapter_voltage_due = 0.0
            while not self.stop_event.is_set():
                self._process_requests(limit=5)

                if not success or self.pause_event.is_set():
                    self.stop_event.wait(0.04)
                    continue

                requested = [
                    key for key in self._get_enabled_keys()
                    if key in profile.SUPPORTED_SENSOR_KEYS
                ]
                if requested:
                    try:
                        raw = self.elm.command(profile.OPEL_LIVE_REQUEST, 3.0)
                        values = profile.decode_live_values(raw)
                        now = time.monotonic()
                        for key in requested:
                            value = values.get(key)
                            if value is not None:
                                self.sample.emit(key, float(value), now)
                    except core.ELM327Error as exc:
                        if self.stop_event.is_set():
                            break
                        self.raw_log.emit(f"{profile.OPEL_LIVE_REQUEST}: {exc}")

                now = time.monotonic()
                if now >= adapter_voltage_due:
                    try:
                        voltage = self.elm.read_adapter_voltage()
                        if voltage is not None:
                            self.sample.emit("adapter_voltage", voltage, now)
                    except Exception as exc:
                        if not self.stop_event.is_set():
                            self.raw_log.emit(f"ATRV: {exc}")
                    adapter_voltage_due = now + 2.0

                self.stop_event.wait(max(0.08, self.poll_pause_ms / 1000.0))

        except (serial.SerialException, core.ELM327Error, OSError) as exc:
            reason = str(exc)
            if not self.stop_event.is_set():
                self.status.emit(f"Opel X16XEL error: {exc}")
        except Exception as exc:
            reason = f"Unexpected Opel X16XEL error: {exc}"
            if not self.stop_event.is_set():
                self.status.emit(reason)
        finally:
            if self.elm is not None:
                self.elm.close()
            self.disconnected.emit(reason)


class ExperimentalMainWindow(app.MainWindow):
    """Integrate the verified X16XEL profile into the existing application UI."""

    def __init__(self):
        self.kw82_probe_active = False
        super().__init__()
        if self.protocol_combo.findData(KW82_PROTOCOL_TOKEN) < 0:
            self.protocol_combo.addItem(KW82_PROTOCOL_LABEL, KW82_PROTOCOL_TOKEN)
        if hasattr(self, "pid_presets"):
            self.pid_presets.setdefault("Opel X16XEL live", list(profile.DEFAULT_SENSOR_KEYS))
            self._refresh_pid_combo(self.pid_preset_combo.currentText())
        saved = str(self.settings.value("connection/protocol", "ATSP0"))
        if saved == KW82_PROTOCOL_TOKEN:
            index = self.protocol_combo.findData(KW82_PROTOCOL_TOKEN)
            if index >= 0:
                self.protocol_combo.setCurrentIndex(index)
        self.protocol_combo.currentIndexChanged.connect(self._kw82_selection_changed)
        self._kw82_selection_changed()

    def _kw82_selection_changed(self, *_args) -> None:
        selected = self.protocol_combo.currentData() == KW82_PROTOCOL_TOKEN
        if selected and not self.connected_state:
            self.connection_detail_label.setToolTip(
                "Verified KWP2000 Fast-Init profile for Astra-G X16XEL / Multec-H on DLC pin 7."
            )
        else:
            self.connection_detail_label.setToolTip("")

    def _effective_worker_keys(self) -> list[str]:
        if self.kw82_probe_active:
            return sorted(self.enabled_keys & profile.SUPPORTED_SENSOR_KEYS)
        return super()._effective_worker_keys()

    def _apply_supported_state(self) -> None:
        if not self.kw82_probe_active:
            super()._apply_supported_state()
            return
        for sensor in core.SENSORS:
            row = self.pid_row_by_key[sensor.key]
            mapped = sensor.key in profile.SUPPORTED_SENSOR_KEYS
            status_item = self.pid_table.item(row, 4)
            status_item.setText("Multec-H 2101" if mapped else "Not mapped in profile")
            status_item.setToolTip(
                "Decoded from the X16XEL ReadDataByLocalIdentifier 0x2101 block."
                if mapped
                else "This generic OBD-II measurement is not mapped for the X16XEL profile yet."
            )
            command_item = self.value_table.item(self.dashboard_row_by_key[sensor.key], 3)
            command_item.setText(profile.LIVE_COMMAND_LABELS.get(sensor.key, "not mapped"))

    def _toggle_connection(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            super()._toggle_connection()
            return

        if self.protocol_combo.currentData() != KW82_PROTOCOL_TOKEN:
            self.kw82_probe_active = False
            super()._toggle_connection()
            return

        port = self.port_combo.currentData()
        if not port:
            QMessageBox.warning(self, "No serial port", "Select a serial port on the Settings tab.")
            self.tabs.setCurrentWidget(self.settings_tab)
            return

        if not (self.enabled_keys & profile.SUPPORTED_SENSOR_KEYS):
            self.enabled_keys = set(profile.DEFAULT_SENSOR_KEYS)
            self._apply_pid_visibility()

        self._save_settings()
        self.kw82_probe_active = True
        self.offline_mode = False
        self.connect_button.setText("Disconnect")
        self.connect_button.setEnabled(True)
        self._set_connection_controls(False)
        self.connection_status_label.setText("● Connecting to X16XEL…")
        self.connection_status_label.setStyleSheet("color: #d38b00;")

        worker = OpelKW82ProbeWorker(
            port=port,
            baudrate=int(self.baud_combo.currentText()),
            enabled_keys=sorted(self.enabled_keys & profile.SUPPORTED_SENSOR_KEYS),
            poll_pause_ms=self.poll_pause_spin.value(),
            parent=self,
        )
        worker.command_timeout = self.command_timeout_spin.value()
        self.worker = worker
        worker.connected.connect(self._on_connected)
        worker.disconnected.connect(self._on_disconnected)
        worker.status.connect(self.statusBar().showMessage)
        worker.raw_log.connect(self._append_raw)
        worker.sample.connect(self._on_sample)
        worker.dtcs_ready.connect(self._show_dtcs)
        worker.mode06_ready.connect(self._show_mode06)
        worker.custom_ready.connect(self._show_custom_response)
        worker.probe_ready.connect(self._show_kw82_probe)
        worker.start()

    @Slot(str, object)
    def _on_connected(self, identity: str, supported: object) -> None:
        super()._on_connected(identity, supported)
        if not self.kw82_probe_active:
            return
        self.plot_start_button.setEnabled(True)
        self.polling_pause_button.setEnabled(True)
        self.read_dtcs_button.setEnabled(True)
        self.clear_dtcs_button.setEnabled(True)
        self.mode06_button.setEnabled(False)
        # Guided/RPM test integration comes later; phase 1 is live plotting + DTCs.
        self.single_test_button.setEnabled(False)
        self.preset_start_button.setEnabled(False)
        self.connection_status_label.setText("● Opel X16XEL connected")
        self.connection_status_label.setStyleSheet("color: #27964b;")
        self.statusBar().showMessage(
            "X16XEL / Multec-H connected; live 0x2101 polling and DTC functions are active."
        )

    def _read_dtcs(self) -> None:
        if not self.kw82_probe_active:
            super()._read_dtcs()
            return
        worker = self._require_worker()
        if worker is not None:
            self.dtc_output.setPlainText("Reading X16XEL fault memory…")
            worker.request_dtcs()

    def _clear_dtcs(self) -> None:
        if not self.kw82_probe_active:
            super()._clear_dtcs()
            return
        worker = self._require_worker()
        if worker is None:
            return
        answer = QMessageBox.warning(
            self,
            "Clear X16XEL DTCs",
            "Clear the stored DTCs in the X16XEL engine ECU? The application will read the fault memory again immediately afterwards to verify the result.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            worker.request_clear_dtcs()

    @Slot(object)
    def _show_dtcs(self, dtcs: object) -> None:
        if not self.kw82_probe_active:
            super()._show_dtcs(dtcs)
            return
        records = list(dtcs)
        if not records:
            self.dtc_output.setPlainText("No stored DTCs.")
            return
        lines = ["DTC      Meaning", "------------------------------"]
        for record in records:
            code = getattr(record, "code", str(record))
            description = getattr(record, "description", "")
            lines.append(f"{code:<8} {description}")
        self.dtc_output.setPlainText("\n".join(lines))

    @Slot(str)
    def _show_kw82_probe(self, report: str) -> None:
        self.raw_output.append("\n=== Opel X16XEL / Multec-H session report ===\n" + report)
        self.dtc_output.setPlainText(
            "X16XEL / Multec-H session established.\n\nUse Read DTCs for the fault memory; live values are available on Dashboard and Plot."
        )

    @Slot(str)
    def _on_disconnected(self, reason: str) -> None:
        was_kw82 = self.kw82_probe_active
        super()._on_disconnected(reason)
        if was_kw82:
            self.read_dtcs_button.setEnabled(True)
            self.clear_dtcs_button.setEnabled(True)
            self.mode06_button.setEnabled(True)
            self.single_test_button.setEnabled(True)
            self.preset_start_button.setEnabled(True)
            self.kw82_probe_active = False


def install() -> None:
    app.MainWindow = ExperimentalMainWindow

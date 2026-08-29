#!/usr/bin/env python3
"""Experimental Opel Astra-G X16XEL / Multec-H K-line probing.

The 1999 Astra-G X16XEL is supported by Opel-specific diagnostic software that
uses KWP2000-style communication even though the ECU does not necessarily offer
standard EOBD Mode 01 discovery.  The ELM327 can perform the ISO 14230 slow
(5-baud) initialization, so this module first tests the physical/session layer
without sending standard SAE PID, clear-DTC or actuator commands.

The first attempt deliberately uses the ELM327/ISO defaults: KWP slow init,
address 0x33 and 10400 bit/s.  Only if that fails do we try conservative
fallbacks.  The raw log is the primary diagnostic result.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import serial
from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import QMessageBox

import elm327_twingo_gui as core
import elm327_app as app


# Keep the original token so existing settings continue to select this mode.
KW82_PROTOCOL_TOKEN = "OPEL_KW82_9600"
KW82_PROTOCOL_LABEL = "Opel Astra G X16XEL / Multec-H legacy KWP probe (experimental)"
KW82_ENGINE_INIT_ADDRESS = 0x33


@dataclass(frozen=True)
class ProbeStep:
    command: str
    response: str
    ok: bool


@dataclass(frozen=True)
class ProbeAttempt:
    name: str
    protocol_command: str
    baud_command: str
    init_address: int


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
    """Reset only the adapter; intentionally do not send normal OBD command 0100."""
    identity = "ELM327-compatible adapter"
    for command, timeout in (
        ("ATZ", 3.5),
        ("ATE0", 1.0),
        ("ATL0", 1.0),
        ("ATS1", 1.0),
        ("ATH1", 1.0),
        ("ATM0", 1.0),
    ):
        step = _run_step(elm, command, timeout, log)
        if command == "ATZ" and step.response:
            lines = core.ELM327.clean_lines(step.response, command)
            candidate = " ".join(
                line for line in lines if line not in {"OK", "STOPPED"}
            ).strip()
            if candidate:
                identity = candidate
    return identity


def _valid_buffer_bytes(response: str) -> str:
    """Decode ATBD's length byte so stale buffer bytes are not presented as ECU data."""
    rows = core.ELM327.extract_hex_bytes(response, "ATBD")
    if not rows or not rows[0]:
        return "none"
    row = rows[0]
    length = row[0]
    valid = row[1:1 + min(length, max(0, len(row) - 1))]
    if not valid:
        return f"length={length}, no captured bytes"
    return f"length={length}, valid=" + " ".join(f"{value:02X}" for value in valid)


def probe_kw82_engine(
    elm: core.ELM327,
    log: Callable[[str], None],
    init_address: int = KW82_ENGINE_INIT_ADDRESS,
) -> tuple[bool, str]:
    """Probe the X16XEL using KWP slow-init defaults before legacy fallbacks."""
    address = init_address & 0xFF
    steps: list[ProbeStep] = []

    def step(command: str, timeout: float = 1.0) -> ProbeStep:
        result = _run_step(elm, command, timeout, log)
        steps.append(result)
        return result

    attempts = [
        ProbeAttempt("KWP slow init / ISO default", "ATSP4", "ATIB10", address),
        ProbeAttempt("KWP slow init / Opel 9600 fallback", "ATSP4", "ATIB96", address),
        ProbeAttempt("ISO 9141 / 9600 fallback", "ATSP3", "ATIB96", address),
    ]

    success = False
    successful_attempt: ProbeAttempt | None = None
    attempt_reports: list[str] = []

    for attempt in attempts:
        step("ATPC")
        step(attempt.protocol_command)
        step("ATKW0")
        baud = step(attempt.baud_command)
        step("ATAT0")
        step("ATSTFF")
        step(f"ATIIA{attempt.init_address:02X}")

        if not baud.ok:
            init_result = ProbeStep("ATSI", f"{attempt.baud_command} unsupported", False)
            steps.append(init_result)
            log(f"> ATSI\nSkipped: {attempt.baud_command} unsupported")
        else:
            init_result = step("ATSI", 8.0)

        keyword = step("ATKW", 1.5)
        buffer_dump = step("ATBD", 1.5)
        attempt_reports.append(
            "\n".join(
                (
                    f"- {attempt.name}",
                    f"  protocol: {attempt.protocol_command}",
                    f"  baud command: {attempt.baud_command}",
                    f"  init address: 0x{attempt.init_address:02X}",
                    f"  ATSI: {init_result.response}",
                    f"  keywords: {keyword.response}",
                    f"  buffer: {_valid_buffer_bytes(buffer_dump.response)}",
                )
            )
        )

        if init_result.ok:
            success = True
            successful_attempt = attempt
            break

    protocol = step("ATDP", 1.0)
    protocol_number = step("ATDPN", 1.0)

    unsupported = sorted(
        {
            item.command
            for item in steps
            if _response_without_prompt(item.response) == "?"
            or "unsupported" in item.response.lower()
        }
    )

    lines = [
        "Experimental Opel Astra G X16XEL / Multec-H legacy KWP probe",
        "==============================================================",
        "",
        "Target: engine ECU on vehicle DLC pin 7",
        "No standard OBD-II 0100 request was sent.",
        "",
        "Probe attempts:",
        *attempt_reports,
        "",
        f"Slow initialization: {'SUCCESS' if success else 'NO SUCCESSFUL INITIALIZATION'}",
        f"ELM active protocol: {protocol.response}",
        f"ELM protocol number: {protocol_number.response}",
    ]

    if successful_attempt is not None:
        lines.extend(
            (
                "",
                "Interpretation:",
                f"The ECU completed {successful_attempt.name}. The next step is a read-only "
                "Opel/Multec-H KWP identification request rather than SAE Mode 01 discovery.",
            )
        )
    else:
        lines.extend(
            (
                "",
                "Interpretation:",
                "No complete ISO/KWP slow-init handshake was seen at address 0x33. The first "
                "attempt used the ELM327 standard 10400 bit/s setting; 9600 bit/s was tried "
                "only as a fallback. The raw ATSI/ATKW results are the useful evidence.",
            )
        )

    if unsupported:
        lines.extend(("", "Adapter commands not supported:", "  " + ", ".join(unsupported)))

    lines.extend(
        (
            "",
            "Safety: this probe only configures the interface and performs session initialization.",
        )
    )
    return success, "\n".join(lines)


class OpelKW82ProbeWorker(core.OBDWorker):
    """Connection worker that never starts standard SAE PID polling."""

    probe_ready = Signal(str)

    def run(self) -> None:
        reason = "Connection closed."
        try:
            self.status.emit(f"Opening {self.port} at {self.baudrate} baud for Opel legacy KWP probe…")
            self.elm = core.ELM327(
                port=self.port,
                baudrate=self.baudrate,
                stop_event=self.stop_event,
                timeout=float(getattr(self, "command_timeout", 2.0)),
                protocol_command="ATSP4",
            )
            self.elm.open()
            identity = initialize_adapter_for_kw82_probe(self.elm, self.raw_log.emit)
            success, report = probe_kw82_engine(self.elm, self.raw_log.emit)

            self.connected.emit(f"{identity} · Opel legacy KWP probe", set())
            self.probe_ready.emit(report)
            self.status.emit(
                "Multec-H KWP slow-init response received; inspect the probe report and raw log."
                if success
                else "Multec-H KWP probe finished without successful slow initialization; inspect the raw log."
            )

            while not self.stop_event.is_set():
                self._process_requests(limit=5)
                self.stop_event.wait(0.03)

        except (serial.SerialException, core.ELM327Error, OSError) as exc:
            reason = str(exc)
            if not self.stop_event.is_set():
                self.status.emit(f"Opel legacy KWP probe error: {exc}")
        except Exception as exc:
            reason = f"Unexpected Opel legacy KWP probe error: {exc}"
            if not self.stop_event.is_set():
                self.status.emit(reason)
        finally:
            if self.elm is not None:
                self.elm.close()
            self.disconnected.emit(reason)


class ExperimentalMainWindow(app.MainWindow):
    """Add the X16XEL legacy KWP probe without disturbing normal OBD-II."""

    def __init__(self):
        self.kw82_probe_active = False
        super().__init__()
        if self.protocol_combo.findData(KW82_PROTOCOL_TOKEN) < 0:
            self.protocol_combo.addItem(KW82_PROTOCOL_LABEL, KW82_PROTOCOL_TOKEN)
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
                "Experimental read-only slow-init probe for the Astra-G X16XEL / Multec-H K-line ECU."
            )
        else:
            self.connection_detail_label.setToolTip("")

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

        self._save_settings()
        self.kw82_probe_active = True
        self.offline_mode = False
        self.connect_button.setText("Disconnect")
        self.connect_button.setEnabled(True)
        self._set_connection_controls(False)
        self.connection_status_label.setText("● Probing Multec-H KWP…")
        self.connection_status_label.setStyleSheet("color: #d38b00;")

        worker = OpelKW82ProbeWorker(
            port=port,
            baudrate=int(self.baud_combo.currentText()),
            enabled_keys=[],
            poll_pause_ms=0,
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
        self.plot_start_button.setEnabled(False)
        self.polling_pause_button.setEnabled(False)
        self.read_dtcs_button.setEnabled(False)
        self.clear_dtcs_button.setEnabled(False)
        self.mode06_button.setEnabled(False)
        self.single_test_button.setEnabled(False)
        self.preset_start_button.setEnabled(False)
        self.connection_status_label.setText("● Opel legacy KWP probe connected")
        self.connection_status_label.setStyleSheet("color: #8c6bc4;")
        self.statusBar().showMessage("Experimental Multec-H probe connected; no standard OBD-II polling is active.")

    @Slot(str)
    def _show_kw82_probe(self, report: str) -> None:
        self.dtc_output.setPlainText(report)
        self.raw_output.append("\n=== Opel legacy KWP probe report ===\n" + report)
        self.tabs.setCurrentWidget(self.dtc_output.parentWidget())

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

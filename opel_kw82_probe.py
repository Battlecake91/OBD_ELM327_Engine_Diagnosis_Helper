#!/usr/bin/env python3
"""Experimental Opel Astra-G X16XEL / Multec-H KWP2000 probing.

The 1999 Astra-G X16XEL uses a Delco HSFI-C / Multec-H ECU on K-line. Public
Opel KWP2000 traces show the engine controller addressed as 0x11 from tester
address 0xF1, with a Fast-Init followed by StartCommunication (service 0x81).

This module therefore probes only that session-establishment path. It does not
send SAE Mode 01 discovery, clear-DTC commands, coding, actuator commands or
memory writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import serial
from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import QMessageBox

import elm327_twingo_gui as core
import elm327_app as app


# Preserve the original settings token so existing installations stay selected.
KW82_PROTOCOL_TOKEN = "OPEL_KW82_9600"
KW82_PROTOCOL_LABEL = "Opel Astra G X16XEL / Multec-H KWP2000 Fast-Init probe"
OPel_TESTER_ADDRESS = 0xF1
OPEL_ENGINE_TARGETS = (0x11, 0x10)


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


def _kwp_start_accepted(response: str) -> bool:
    """Positive response to StartCommunication service 0x81 is service 0xC1."""
    for row in _hex_rows(response, "81"):
        if 0xC1 in row:
            return True
    return False


def _valid_buffer_bytes(response: str) -> str:
    """Decode ATBD's leading length byte and hide stale bytes after that length."""
    rows = _hex_rows(response, "ATBD")
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
    targets: tuple[int, ...] = OPEL_ENGINE_TARGETS,
) -> tuple[bool, str]:
    """Probe Opel KWP2000 Fast Init and StartCommunication on the engine K-line."""
    steps: list[ProbeStep] = []
    attempts: list[FastInitAttempt] = []

    def step(command: str, timeout: float = 1.0) -> ProbeStep:
        result = _run_step(elm, command, timeout, log)
        steps.append(result)
        return result

    success = False
    successful_target: int | None = None

    for raw_target in targets:
        target = raw_target & 0xFF
        header = f"81{target:02X}{OPel_TESTER_ADDRESS:02X}"

        # Protocol 5 is ISO 14230-4 KWP with Fast Init.  ATFI emits the 25/25 ms
        # wake-up pulse.  With header 81 11 F1, sending service 81 produces the
        # documented Opel frame 81 11 F1 81 <checksum>.
        step("ATPC")
        step("ATSP5")
        step("ATKW0")
        step("ATIB10")
        step("ATAT0")
        step("ATSTFF")
        step(f"ATSH{header}")
        fast_init = step("ATFI", 3.0)
        start_response = step("81", 4.0)
        buffer_response = step("ATBD", 1.5)

        attempt = FastInitAttempt(
            target=target,
            header=header,
            fast_init=fast_init,
            start_response=start_response,
            buffer_response=buffer_response,
        )
        attempts.append(attempt)

        if _kwp_start_accepted(start_response.response):
            success = True
            successful_target = target
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
        "Experimental Opel Astra G X16XEL / Multec-H KWP2000 Fast-Init probe",
        "====================================================================",
        "",
        "Target: engine ECU on vehicle DLC pin 7",
        "Tester address: 0xF1",
        "No standard OBD-II 0100 request was sent.",
        "",
        "Probe attempts:",
        *attempt_reports,
        "",
        f"KWP StartCommunication: {'SUCCESS' if success else 'NO POSITIVE C1 RESPONSE'}",
        f"ELM active protocol: {protocol.response}",
        f"ELM protocol number: {protocol_number.response}",
        f"ELM keywords: {keyword.response}",
    ]

    if successful_target is not None:
        lines.extend(
            (
                "",
                "Interpretation:",
                f"The ECU at target 0x{successful_target:02X} returned a positive KWP2000 "
                "StartCommunication response (0xC1). The physical/session layer is established; "
                "the next safe request is read-only ECU identification (service 0x1A).",
            )
        )
    else:
        lines.extend(
            (
                "",
                "Interpretation:",
                "No positive KWP2000 StartCommunication response (0xC1) was received after "
                "Fast Init. Target 0x11 is the documented Opel engine-ECU address used first; "
                "0x10 is tried only as a conservative fallback. Check the raw response to ATFI "
                "and command 81 before changing any further timing or addressing.",
            )
        )

    if unsupported:
        lines.extend(("", "Adapter commands not supported:", "  " + ", ".join(unsupported)))

    lines.extend(
        (
            "",
            "Safety: this probe performs interface/session initialization only; no write or clear command is sent.",
        )
    )
    return success, "\n".join(lines)


class OpelKW82ProbeWorker(core.OBDWorker):
    """Connection worker that does not start standard SAE PID polling."""

    probe_ready = Signal(str)

    def run(self) -> None:
        reason = "Connection closed."
        try:
            self.status.emit(
                f"Opening {self.port} at {self.baudrate} baud for Opel Multec-H KWP Fast-Init probe…"
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

            self.connected.emit(f"{identity} · Opel Multec-H KWP probe", set())
            self.probe_ready.emit(report)
            self.status.emit(
                "Multec-H KWP StartCommunication succeeded; inspect the report."
                if success
                else "Multec-H Fast-Init probe finished without a C1 response; inspect the raw log."
            )

            while not self.stop_event.is_set():
                self._process_requests(limit=5)
                self.stop_event.wait(0.03)

        except (serial.SerialException, core.ELM327Error, OSError) as exc:
            reason = str(exc)
            if not self.stop_event.is_set():
                self.status.emit(f"Opel Multec-H probe error: {exc}")
        except Exception as exc:
            reason = f"Unexpected Opel Multec-H probe error: {exc}"
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
                "Experimental read-only Fast-Init probe for the Astra-G X16XEL / Multec-H KWP2000 ECU."
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
        self.connection_status_label.setText("● Probing Multec-H KWP Fast Init…")
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
        self.connection_status_label.setText("● Opel Multec-H probe connected")
        self.connection_status_label.setStyleSheet("color: #8c6bc4;")
        self.statusBar().showMessage(
            "Experimental Multec-H probe connected; no standard OBD-II polling is active."
        )

    @Slot(str)
    def _show_kw82_probe(self, report: str) -> None:
        self.dtc_output.setPlainText(report)
        self.raw_output.append("\n=== Opel Multec-H KWP probe report ===\n" + report)
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

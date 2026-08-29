#!/usr/bin/env python3
"""Experimental Opel KW82 probing through an ELM327-compatible adapter.

This module deliberately does *not* claim full KW82 support.  Genuine ELM327
firmware exposes enough ISO/K-line controls to try a 5-baud wake-up at a custom
address and at 9600 baud, but KW82's application-layer framing/timing is not an
ELM327 protocol.  The probe therefore answers one useful question first:

    Can this specific adapter complete a slow K-line initialization with the
    Astra-G engine ECU and show any keyword/buffer evidence afterwards?

The experiment is read-only.  Standard OBD-II DTC, Mode 06, PID polling and
clear commands are disabled while the probe connection is active.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

import serial
from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import QMessageBox

import elm327_twingo_gui as core
import elm327_app as app


KW82_PROTOCOL_TOKEN = "OPEL_KW82_9600"
KW82_PROTOCOL_LABEL = "Opel Astra G KW82 probe (experimental, 9600 baud)"
KW82_ENGINE_INIT_ADDRESS = 0x01


@dataclass(frozen=True)
class ProbeStep:
    command: str
    response: str
    ok: bool


def _response_without_prompt(response: str) -> str:
    return response.upper().replace(">", "").strip()


def _response_ok(response: str) -> bool:
    upper = _response_without_prompt(response)
    if not upper:
        return False
    if upper == "?":
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
    except Exception as exc:  # The report must survive clone-specific command failures.
        response = f"{type(exc).__name__}: {exc}"
        ok = False
    log(f"> {command}\n{response}")
    return ProbeStep(command=command, response=response, ok=ok)


def initialize_adapter_for_kw82_probe(
    elm: core.ELM327,
    log: Callable[[str], None],
) -> str:
    """Reset only the adapter; intentionally do not send the normal 0100 probe."""
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


def probe_kw82_engine(
    elm: core.ELM327,
    log: Callable[[str], None],
    init_address: int = KW82_ENGINE_INIT_ADDRESS,
) -> tuple[bool, str]:
    """Try the ELM327 ISO controls that are useful for a KW82 wake-up experiment.

    We first use protocol 3 (ISO 9141-2) because it exposes a 5-baud slow init
    without imposing KWP2000 application semantics.  Some clone firmwares behave
    differently on protocol 4, so a second attempt is made there if protocol 3
    does not complete initialization.
    """
    address = init_address & 0xFF
    steps: list[ProbeStep] = []

    def step(command: str, timeout: float = 1.0) -> ProbeStep:
        result = _run_step(elm, command, timeout, log)
        steps.append(result)
        return result

    # Close any automatically selected OBD protocol from an earlier session.
    step("ATPC")

    init_result: ProbeStep | None = None
    selected_protocol = ""
    for protocol in ("ATSP3", "ATSP4"):
        selected_protocol = protocol
        step(protocol)
        step("ATKW0")            # Accept non-standard keyword bytes from old Opel ECUs.
        baud = step("ATIB96")    # KW82 commonly runs at 9600 baud.
        step("ATAT0")            # Fixed timing makes the experiment reproducible.
        step("ATSTFF")           # Give the old ECU plenty of time to answer.
        step(f"ATIIA{address:02X}")

        if not baud.ok:
            init_result = ProbeStep("ATSI", "ATIB96 is unsupported by this adapter", False)
            steps.append(init_result)
            log("> ATSI\nSkipped: ATIB96 is unsupported by this adapter")
        else:
            init_result = step("ATSI", 8.0)

        if init_result.ok:
            break

        # Start the second attempt from a clean protocol state.
        step("ATPC")

    success = bool(init_result and init_result.ok)

    # These commands are read-only and provide useful evidence even when the ECU
    # does not progress to normal ELM message handling.
    keyword = step("ATKW", 1.5)
    protocol = step("ATDP", 1.0)
    protocol_number = step("ATDPN", 1.0)
    buffer_dump = step("ATBD", 1.5)

    unsupported = [
        item.command
        for item in steps
        if _response_without_prompt(item.response) == "?"
        or "unsupported" in item.response.lower()
    ]

    lines = [
        "Experimental Opel KW82 probe",
        "================================",
        "",
        "Target: Astra G engine ECU on vehicle DLC pin 7",
        f"Slow-init address tried: 0x{address:02X}",
        "Bus baud rate requested: 9600 bit/s",
        f"Last ELM protocol attempt: {selected_protocol}",
        "",
        f"Slow initialization: {'POSSIBLE RESPONSE / SUCCESS' if success else 'NO SUCCESSFUL INITIALIZATION'}",
        "",
        "ELM evidence:",
        f"  ATKW  : {keyword.response}",
        f"  ATDP  : {protocol.response}",
        f"  ATDPN : {protocol_number.response}",
        f"  ATBD  : {buffer_dump.response}",
    ]
    if unsupported:
        lines.extend(("", "Adapter commands not supported:", "  " + ", ".join(sorted(set(unsupported)))))

    lines.extend(
        (
            "",
            "Interpretation:",
            (
                "The adapter completed an ISO-style slow initialization at the requested "
                "address/baud rate. This is encouraging, but it does NOT yet prove that the "
                "ELM327 can exchange KW82 application-layer blocks. Save the raw log; the "
                "next step is to identify the returned keyword/initial bytes and derive the "
                "first read-only KW82 request."
                if success
                else
                "The ELM327 did not complete the experimental slow initialization. This can "
                "mean a clone lacks ATIB96/ATSI support, the init address is different, the "
                "ECU expects a different wake-up sequence, or the ECU is not using KW82. "
                "The raw log is the useful result; no write/clear command was sent."
            ),
            "",
            "Safety: this probe only configures the ELM interface and performs read-only initialization.",
        )
    )
    return success, "\n".join(lines)


class OpelKW82ProbeWorker(core.OBDWorker):
    """Connection worker that never starts standard SAE PID polling."""

    probe_ready = Signal(str)

    def run(self) -> None:
        reason = "Connection closed."
        try:
            self.status.emit(f"Opening {self.port} at {self.baudrate} baud for KW82 probe…")
            self.elm = core.ELM327(
                port=self.port,
                baudrate=self.baudrate,
                stop_event=self.stop_event,
                timeout=float(getattr(self, "command_timeout", 2.0)),
                protocol_command="ATSP3",
            )
            self.elm.open()
            identity = initialize_adapter_for_kw82_probe(self.elm, self.raw_log.emit)
            success, report = probe_kw82_engine(self.elm, self.raw_log.emit)

            self.connected.emit(f"{identity} · KW82 probe", set())
            self.probe_ready.emit(report)
            self.status.emit(
                "KW82 slow-init response received; inspect the probe report and raw log."
                if success
                else "KW82 probe finished without successful slow initialization; inspect the raw log."
            )

            # Keep the serial connection open for harmless manual AT/raw experiments.
            # No automatic OBD-II PID request is sent in this mode.
            while not self.stop_event.is_set():
                self._process_requests(limit=5)
                self.stop_event.wait(0.03)

        except (serial.SerialException, core.ELM327Error, OSError) as exc:
            reason = str(exc)
            if not self.stop_event.is_set():
                self.status.emit(f"KW82 probe error: {exc}")
        except Exception as exc:
            reason = f"Unexpected KW82 probe error: {exc}"
            if not self.stop_event.is_set():
                self.status.emit(reason)
        finally:
            if self.elm is not None:
                self.elm.close()
            self.disconnected.emit(reason)


class ExperimentalMainWindow(app.MainWindow):
    """Add the KW82 probe as a connection mode without disturbing normal OBD-II."""

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
                "Experimental read-only 5-baud/9600-baud probe for older Opel KW82-style K-line ECUs."
            )
        else:
            self.connection_detail_label.setToolTip("")

    def _toggle_connection(self) -> None:
        # Reuse the normal disconnect path regardless of connection mode.
        if self.worker is not None and self.worker.isRunning():
            super()._toggle_connection()
            return

        if self.protocol_combo.currentData() != KW82_PROTOCOL_TOKEN:
            self.kw82_probe_active = False
            super()._toggle_connection()
            return

        port = self.port_combo.currentData()
        if not port:
            QMessageBox.warning(
                self,
                "No serial port",
                "Select a serial port on the Settings tab.",
            )
            self.tabs.setCurrentWidget(self.settings_tab)
            return

        self._save_settings()
        self.kw82_probe_active = True
        self.offline_mode = False
        self.connect_button.setText("Disconnect")
        self.connect_button.setEnabled(True)
        self._set_connection_controls(False)
        self.connection_status_label.setText("● Probing KW82…")
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
        self.connection_status_label.setText("● KW82 probe connected")
        self.connection_status_label.setStyleSheet("color: #8c6bc4;")
        self.statusBar().showMessage("Experimental KW82 probe connected; no standard OBD-II polling is active.")

    @Slot(str)
    def _show_kw82_probe(self, report: str) -> None:
        self.dtc_output.setPlainText(report)
        self.raw_output.append("\n=== KW82 probe report ===\n" + report)
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
    """Install the extended window class before ``elm327_app.main()`` runs."""
    app.MainWindow = ExperimentalMainWindow

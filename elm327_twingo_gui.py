#!/usr/bin/env python3
"""
ELM327 Live Diagnostic v3
==========================

Professional PySide6 application for standard OBD-II live data, plots,
temporary CSV acquisition, range exports, markers, saved recordings and
guided multi-stage tests using a serial ELM327 adapter.

Plot acquisition is deliberately started by the user. Every active plot
session is written to a temporary CSV file and can be exported in full or
as a selected time range.
"""

from __future__ import annotations

import csv
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pyqtgraph as pg
import serial
from serial.tools import list_ports

from PySide6.QtCore import (
    QThread,
    QTimer,
    Qt,
    Signal,
    Slot,
    QRectF,
    QSettings,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QCloseEvent,
    QFont,
    QPainter,
    QPen,
    QIcon,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStatusBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QStyle,
)


APP_NAME = "ELM327 Live Diagnostic"
APP_VERSION = "3.0"
ORGANIZATION_NAME = "Open Diagnostics"
DESKTOP_FILE_ID = "io.github.open-diagnostics.elm327-live-diagnostic"


# ---------------------------------------------------------------------------
# Sensor definitions
# ---------------------------------------------------------------------------

Decoder = Callable[[list[int]], Optional[float]]


@dataclass(frozen=True)
class SensorDefinition:
    key: str
    name: str
    command: str
    pid: Optional[int]
    unit: str
    decimals: int
    decoder: Decoder
    group: str
    default_enabled: bool = True


@dataclass(frozen=True)
class Marker:
    elapsed: float
    text: str
    timestamp: str


@dataclass(frozen=True)
class TestStage:
    name: str
    instruction: str
    duration_s: float = 0.0
    target_rpm: Optional[int] = None
    tolerance_rpm: int = 100
    manual: bool = False


def need(data: list[int], count: int) -> bool:
    return len(data) >= count


def dec_percent_a(data: list[int]) -> Optional[float]:
    return data[0] * 100.0 / 255.0 if need(data, 1) else None


def dec_temp_a(data: list[int]) -> Optional[float]:
    return float(data[0] - 40) if need(data, 1) else None


def dec_trim_a(data: list[int]) -> Optional[float]:
    return (data[0] - 128) * 100.0 / 128.0 if need(data, 1) else None


def dec_fuel_pressure(data: list[int]) -> Optional[float]:
    return float(data[0] * 3) if need(data, 1) else None


def dec_map(data: list[int]) -> Optional[float]:
    return float(data[0]) if need(data, 1) else None


def dec_rpm(data: list[int]) -> Optional[float]:
    return ((data[0] << 8) | data[1]) / 4.0 if need(data, 2) else None


def dec_speed(data: list[int]) -> Optional[float]:
    return float(data[0]) if need(data, 1) else None


def dec_timing(data: list[int]) -> Optional[float]:
    return data[0] / 2.0 - 64.0 if need(data, 1) else None


def dec_maf(data: list[int]) -> Optional[float]:
    return ((data[0] << 8) | data[1]) / 100.0 if need(data, 2) else None


def dec_o2_voltage(data: list[int]) -> Optional[float]:
    return data[0] / 200.0 if need(data, 1) else None


def dec_runtime(data: list[int]) -> Optional[float]:
    return float((data[0] << 8) | data[1]) if need(data, 2) else None


def dec_fuel_level(data: list[int]) -> Optional[float]:
    return data[0] * 100.0 / 255.0 if need(data, 1) else None


def dec_baro(data: list[int]) -> Optional[float]:
    return float(data[0]) if need(data, 1) else None


def dec_voltage(data: list[int]) -> Optional[float]:
    return ((data[0] << 8) | data[1]) / 1000.0 if need(data, 2) else None


def dec_abs_load(data: list[int]) -> Optional[float]:
    return ((data[0] << 8) | data[1]) * 100.0 / 255.0 if need(data, 2) else None


def dec_equivalence(data: list[int]) -> Optional[float]:
    return ((data[0] << 8) | data[1]) / 32768.0 if need(data, 2) else None


SENSORS: list[SensorDefinition] = [
    SensorDefinition("rpm", "Engine speed", "010C", 0x0C, "rpm", 0, dec_rpm, "Engine"),
    SensorDefinition("coolant", "Coolant temperature", "0105", 0x05, "°C", 0, dec_temp_a, "Temperature"),
    SensorDefinition("iat", "Intake air temperature", "010F", 0x0F, "°C", 0, dec_temp_a, "Temperature"),
    SensorDefinition("stft1", "Short-term fuel trim B1", "0106", 0x06, "%", 1, dec_trim_a, "Fuel mixture"),
    SensorDefinition("ltft1", "Long-term fuel trim B1", "0107", 0x07, "%", 1, dec_trim_a, "Fuel mixture"),
    SensorDefinition("map", "Intake manifold pressure", "010B", 0x0B, "kPa", 0, dec_map, "Intake"),
    SensorDefinition("baro", "Barometric pressure", "0133", 0x33, "kPa", 0, dec_baro, "Intake", False),
    SensorDefinition("load", "Calculated engine load", "0104", 0x04, "%", 1, dec_percent_a, "Engine"),
    SensorDefinition("abs_load", "Absolute engine load", "0143", 0x43, "%", 1, dec_abs_load, "Engine", False),
    SensorDefinition("throttle", "Throttle position", "0111", 0x11, "%", 1, dec_percent_a, "Intake"),
    SensorDefinition("timing", "Ignition timing advance", "010E", 0x0E, "°", 1, dec_timing, "Engine"),
    SensorDefinition("maf", "Mass air flow", "0110", 0x10, "g/s", 2, dec_maf, "Intake", False),
    SensorDefinition("o2_b1s1", "Oxygen sensor B1S1", "0114", 0x14, "V", 3, dec_o2_voltage, "Fuel mixture"),
    SensorDefinition("equiv", "Commanded equivalence ratio", "0144", 0x44, "λ", 3, dec_equivalence, "Fuel mixture", False),
    SensorDefinition("fuel_pressure", "Fuel pressure", "010A", 0x0A, "kPa", 0, dec_fuel_pressure, "Intake", False),
    SensorDefinition("speed", "Vehicle speed", "010D", 0x0D, "km/h", 0, dec_speed, "Engine", False),
    SensorDefinition("runtime", "Engine runtime", "011F", 0x1F, "s", 0, dec_runtime, "Engine", False),
    SensorDefinition("fuel_level", "Fuel level", "012F", 0x2F, "%", 1, dec_fuel_level, "Other", False),
    SensorDefinition("ecu_voltage", "Control module voltage", "0142", 0x42, "V", 2, dec_voltage, "Temperature"),
]

SENSOR_BY_KEY = {sensor.key: sensor for sensor in SENSORS}


# ---------------------------------------------------------------------------
# ELM327 communication
# ---------------------------------------------------------------------------

class ELM327Error(RuntimeError):
    pass


class ELM327:
    def __init__(
        self,
        port: str,
        baudrate: int,
        stop_event: threading.Event,
        timeout: float = 2.0,
        protocol_command: str = "ATSP0",
    ):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.protocol_command = protocol_command
        self.stop_event = stop_event
        self.serial: Optional[serial.Serial] = None
        self.lock = threading.Lock()

    def open(self) -> None:
        self.serial = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            timeout=0.05,
            write_timeout=0.5,
        )
        time.sleep(0.15)
        self.serial.reset_input_buffer()
        self.serial.reset_output_buffer()

    def abort_io(self) -> None:
        serial_port = self.serial
        if serial_port is None:
            return

        try:
            cancel_read = getattr(serial_port, "cancel_read", None)
            if callable(cancel_read):
                cancel_read()
        except Exception:
            pass

        try:
            cancel_write = getattr(serial_port, "cancel_write", None)
            if callable(cancel_write):
                cancel_write()
        except Exception:
            pass

        try:
            serial_port.close()
        except Exception:
            pass

    def close(self) -> None:
        serial_port = self.serial
        self.serial = None
        if serial_port is not None:
            try:
                serial_port.close()
            except Exception:
                pass

    def _check_cancelled(self) -> None:
        if self.stop_event.is_set():
            raise ELM327Error("Communication cancelled.")

    def command(self, command: str, timeout: Optional[float] = None) -> str:
        self._check_cancelled()

        serial_port = self.serial
        if serial_port is None or not serial_port.is_open:
            raise ELM327Error("Serial port is not open.")

        cmd = command.strip().upper()
        deadline = time.monotonic() + (timeout if timeout is not None else self.timeout)

        with self.lock:
            self._check_cancelled()
            serial_port.reset_input_buffer()
            serial_port.write((cmd + "\r").encode("ascii"))
            serial_port.flush()

            buffer = bytearray()
            while time.monotonic() < deadline:
                self._check_cancelled()

                try:
                    chunk = serial_port.read(serial_port.in_waiting or 1)
                except (serial.SerialException, OSError) as exc:
                    if self.stop_event.is_set():
                        raise ELM327Error("Communication cancelled.") from exc
                    raise

                if chunk:
                    buffer.extend(chunk)
                    if b">" in buffer:
                        break
                else:
                    time.sleep(0.005)

        text = buffer.decode("ascii", errors="replace")
        if not text.strip():
            raise ELM327Error(f"No response to {cmd}")
        return text

    @staticmethod
    def clean_lines(raw: str, command: str = "") -> list[str]:
        cmd = re.sub(r"\s+", "", command.upper())
        cleaned: list[str] = []

        text = raw.replace("\x00", "").replace(">", "\n")
        for raw_line in re.split(r"[\r\n]+", text):
            line = raw_line.strip().upper()
            compact = re.sub(r"\s+", "", line)

            if not line:
                continue
            if compact == cmd:
                continue
            if line.startswith("SEARCHING"):
                continue
            if line.startswith("BUS INIT"):
                continue
            cleaned.append(line)

        return cleaned

    @staticmethod
    def extract_hex_bytes(raw: str, command: str = "") -> list[list[int]]:
        rows: list[list[int]] = []

        for line in ELM327.clean_lines(raw, command):
            if any(token in line for token in ("NO DATA", "UNABLE TO CONNECT", "ERROR", "?")):
                continue

            line = re.sub(r"^\s*[0-9A-F]+\s*:\s*", "", line)
            tokens = re.findall(r"(?<![0-9A-F])[0-9A-F]{2}(?![0-9A-F])", line)

            if tokens:
                rows.append([int(token, 16) for token in tokens])
                continue

            compact = re.sub(r"[^0-9A-F]", "", line)
            if len(compact) >= 4 and len(compact) % 2 == 0:
                rows.append(
                    [int(compact[i:i + 2], 16) for i in range(0, len(compact), 2)]
                )

        return rows

    def initialize(self, log: Callable[[str], None]) -> str:
        init_commands = [
            ("ATZ", 3.5),
            ("ATE0", 1.0),
            ("ATL0", 1.0),
            ("ATS0", 1.0),
            ("ATH0", 1.0),
            (self.protocol_command, 1.0),
            ("ATAT2", 1.0),
            ("ATST64", 1.0),
        ]

        identity = ""
        for cmd, timeout in init_commands:
            self._check_cancelled()
            raw = self.command(cmd, timeout)
            log(f"> {cmd}\n{raw.strip()}")

            if cmd == "ATZ":
                lines = self.clean_lines(raw, cmd)
                identity = " ".join(
                    line for line in lines if line not in {"OK", "STOPPED"}
                )

        raw = self.command("0100", 8.0)
        log(f"> 0100\n{raw.strip()}")
        upper = raw.upper()

        if "UNABLE TO CONNECT" in upper or "NO DATA" in upper:
            raise ELM327Error(
                "ELM327 detected, but the engine control unit did not respond."
            )
        if not self.extract_hex_bytes(raw, "0100"):
            raise ELM327Error(
                "The engine control unit did not return usable OBD data."
            )

        return identity or "ELM327"

    def read_pid(self, sensor: SensorDefinition) -> Optional[float]:
        raw = self.command(sensor.command)
        rows = self.extract_hex_bytes(raw, sensor.command)

        if sensor.pid is None:
            return None

        for row in rows:
            for index in range(max(0, len(row) - 1)):
                if row[index] == 0x41 and row[index + 1] == sensor.pid:
                    return sensor.decoder(row[index + 2:])

        return None

    def read_adapter_voltage(self) -> Optional[float]:
        raw = self.command("ATRV")
        match = re.search(r"([0-9]+(?:[.,][0-9]+)?)\s*V", raw.upper())
        if not match:
            return None
        return float(match.group(1).replace(",", "."))

    def supported_pids(self) -> set[int]:
        supported: set[int] = set()
        base = 0x00

        while base <= 0xC0:
            self._check_cancelled()
            command = f"01{base:02X}"
            raw = self.command(command)
            rows = self.extract_hex_bytes(raw, command)
            found_mask = None

            for row in rows:
                for index in range(max(0, len(row) - 5)):
                    if row[index] == 0x41 and row[index + 1] == base:
                        found_mask = (
                            (row[index + 2] << 24)
                            | (row[index + 3] << 16)
                            | (row[index + 4] << 8)
                            | row[index + 5]
                        )
                        break
                if found_mask is not None:
                    break

            if found_mask is None:
                break

            for offset in range(1, 33):
                if found_mask & (1 << (32 - offset)):
                    supported.add(base + offset)

            if not (found_mask & 1):
                break
            base += 0x20

        return supported

    def read_dtcs(self) -> list[str]:
        raw = self.command("03", 4.0)
        rows = self.extract_hex_bytes(raw, "03")
        dtcs: list[str] = []

        for row in rows:
            try:
                start = row.index(0x43) + 1
            except ValueError:
                continue

            payload = row[start:]
            for index in range(0, len(payload) - 1, 2):
                a, b = payload[index], payload[index + 1]
                if a == 0 and b == 0:
                    continue

                family = "PCBU"[(a >> 6) & 0x03]
                code = (
                    f"{family}{(a >> 4) & 0x03:X}{a & 0x0F:X}"
                    f"{(b >> 4) & 0x0F:X}{b & 0x0F:X}"
                )
                if code not in dtcs:
                    dtcs.append(code)

        return dtcs

    def clear_dtcs(self) -> str:
        return self.command("04", 5.0)

    def read_mode06_raw(self) -> str:
        blocks: list[str] = []

        for command in ("0600", "0620", "0640", "0660", "0680", "06A0"):
            self._check_cancelled()
            try:
                raw = self.command(command, 4.0)
            except ELM327Error as exc:
                raw = str(exc)

            blocks.append(f"> {command}\n{raw.strip()}")
            if "NO DATA" in raw.upper() and command != "0600":
                break

        return "\n\n".join(blocks)


# ---------------------------------------------------------------------------
# Background threads
# ---------------------------------------------------------------------------

class OBDWorker(QThread):
    connected = Signal(str, object)
    disconnected = Signal(str)
    status = Signal(str)
    raw_log = Signal(str)
    sample = Signal(str, float, float)
    dtcs_ready = Signal(object)
    mode06_ready = Signal(str)
    custom_ready = Signal(str, str)

    def __init__(
        self,
        port: str,
        baudrate: int,
        enabled_keys: list[str],
        poll_pause_ms: int,
        parent=None,
    ):
        super().__init__(parent)
        self.port = port
        self.baudrate = baudrate
        self.enabled_keys = list(enabled_keys)
        self.poll_pause_ms = poll_pause_ms
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.requests: queue.Queue[tuple[str, Optional[str]]] = queue.Queue()
        self.elm: Optional[ELM327] = None
        self.keys_lock = threading.Lock()

    def stop(self) -> None:
        self.stop_event.set()
        self.pause_event.clear()
        elm = self.elm
        if elm is not None:
            elm.abort_io()

    def set_polling_paused(self, paused: bool) -> None:
        if paused:
            self.pause_event.set()
        else:
            self.pause_event.clear()

    def request_dtcs(self) -> None:
        self.requests.put(("read_dtcs", None))

    def request_clear_dtcs(self) -> None:
        self.requests.put(("clear_dtcs", None))

    def request_mode06(self) -> None:
        self.requests.put(("mode06", None))

    def request_custom(self, command: str) -> None:
        self.requests.put(("custom", command))

    def update_enabled_keys(self, keys: list[str]) -> None:
        with self.keys_lock:
            self.enabled_keys = list(keys)

    def _get_enabled_keys(self) -> list[str]:
        with self.keys_lock:
            return list(self.enabled_keys)

    def run(self) -> None:
        reason = "Connection closed."

        try:
            self.status.emit(f"Opening {self.port} at {self.baudrate} baud…")
            self.elm = ELM327(
                port=self.port,
                baudrate=self.baudrate,
                stop_event=self.stop_event,
                timeout=float(getattr(self, "command_timeout", 2.0)),
                protocol_command=str(getattr(self, "protocol_command", "ATSP0")),
            )
            self.elm.open()

            identity = self.elm.initialize(self.raw_log.emit)
            supported = self.elm.supported_pids()
            with self.keys_lock:
                self.enabled_keys = [
                    key for key in self.enabled_keys
                    if key in SENSOR_BY_KEY
                    and (SENSOR_BY_KEY[key].pid is None or SENSOR_BY_KEY[key].pid in supported)
                ]
            self.connected.emit(identity, supported)
            self.status.emit(f"Connected: {identity}")

            adapter_voltage_due = 0.0

            while not self.stop_event.is_set():
                self._process_requests(limit=5)

                if self.pause_event.is_set():
                    time.sleep(0.03)
                    continue

                keys = self._get_enabled_keys()
                if not keys:
                    time.sleep(0.05)
                    continue

                for key in keys:
                    if self.stop_event.is_set() or self.pause_event.is_set():
                        break

                    self._process_requests(limit=1)
                    sensor = SENSOR_BY_KEY.get(key)
                    if sensor is None:
                        continue

                    try:
                        value = self.elm.read_pid(sensor)
                    except ELM327Error as exc:
                        if self.stop_event.is_set():
                            break
                        self.raw_log.emit(f"{sensor.command}: {exc}")
                        value = None
                    except (serial.SerialException, OSError) as exc:
                        if self.stop_event.is_set():
                            break
                        raise ELM327Error(str(exc)) from exc

                    if value is not None:
                        self.sample.emit(sensor.key, float(value), time.monotonic())

                    if self.poll_pause_ms > 0:
                        self.stop_event.wait(self.poll_pause_ms / 1000.0)

                now = time.monotonic()
                if (
                    not self.stop_event.is_set()
                    and not self.pause_event.is_set()
                    and now >= adapter_voltage_due
                ):
                    try:
                        voltage = self.elm.read_adapter_voltage()
                        if voltage is not None:
                            self.sample.emit("adapter_voltage", voltage, now)
                    except ELM327Error as exc:
                        if not self.stop_event.is_set():
                            self.raw_log.emit(f"ATRV: {exc}")
                    adapter_voltage_due = now + 2.0

        except (serial.SerialException, ELM327Error, OSError) as exc:
            reason = str(exc)
            if not self.stop_event.is_set():
                self.status.emit(f"Error: {exc}")
        except Exception as exc:
            reason = f"Unexpected error: {exc}"
            self.status.emit(reason)
        finally:
            if self.elm is not None:
                self.elm.close()
            self.disconnected.emit(reason)

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
                    self.dtcs_ready.emit(self.elm.read_dtcs())
                elif request == "clear_dtcs":
                    response = self.elm.clear_dtcs()
                    self.raw_log.emit(f"> 04\n{response.strip()}")
                    self.status.emit(
                        "Clear command sent. Do not switch off the ignition."
                    )
                elif request == "mode06":
                    self.mode06_ready.emit(self.elm.read_mode06_raw())
                elif request == "custom" and payload:
                    response = self.elm.command(payload, 5.0)
                    self.custom_ready.emit(payload, response)
            except Exception as exc:
                if not self.stop_event.is_set():
                    self.status.emit(f"Diagnostic command failed: {exc}")


class CsvWriterThread(QThread):
    error = Signal(str)
    closed = Signal(str)

    HEADER = [
        "Timestamp",
        "Elapsed_s",
        "Key",
        "Measurement",
        "Value",
        "Unit",
        "Comment",
    ]

    def __init__(self, path: Path, parent=None):
        super().__init__(parent)
        self.path = path
        self.rows: queue.Queue[Optional[list[str]]] = queue.Queue()
        self.stop_event = threading.Event()

    def enqueue_sample(
        self,
        timestamp: str,
        elapsed: float,
        key: str,
        name: str,
        value: float,
        unit: str,
    ) -> None:
        if not self.stop_event.is_set():
            self.rows.put(
                [
                    timestamp,
                    f"{elapsed:.3f}",
                    key,
                    name,
                    f"{value:.6f}",
                    unit,
                    "",
                ]
            )

    def enqueue_marker(self, marker: Marker) -> None:
        if not self.stop_event.is_set():
            self.rows.put(
                [
                    marker.timestamp,
                    f"{marker.elapsed:.3f}",
                    "__marker__",
                    "Marker",
                    "",
                    "",
                    marker.text,
                ]
            )

    def stop_writer(self) -> None:
        if not self.stop_event.is_set():
            self.stop_event.set()
            self.rows.put(None)

    def run(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.writer(handle, delimiter=";")
                writer.writerow(self.HEADER)

                buffered = 0
                last_flush = time.monotonic()

                while True:
                    try:
                        row = self.rows.get(timeout=0.25)
                    except queue.Empty:
                        row = None if self.stop_event.is_set() else []

                    if row is None:
                        break
                    if row:
                        writer.writerow(row)
                        buffered += 1

                    now = time.monotonic()
                    if buffered >= 100 or now - last_flush >= 1.0:
                        handle.flush()
                        buffered = 0
                        last_flush = now

                while True:
                    try:
                        row = self.rows.get_nowait()
                    except queue.Empty:
                        break
                    if row:
                        writer.writerow(row)

                handle.flush()

            self.closed.emit(str(self.path))
        except Exception as exc:
            self.error.emit(str(exc))


# ---------------------------------------------------------------------------
# Target RPM display
# ---------------------------------------------------------------------------

class RpmTargetGauge(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_rpm: Optional[float] = None
        self.target_rpm: Optional[int] = None
        self.tolerance_rpm = 100
        self.setMinimumHeight(170)

    def set_values(
        self,
        current_rpm: Optional[float],
        target_rpm: Optional[int],
        tolerance_rpm: int,
    ) -> None:
        self.current_rpm = current_rpm
        self.target_rpm = target_rpm
        self.tolerance_rpm = tolerance_rpm
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        palette = self.palette()
        background = palette.color(palette.ColorRole.Base)
        text_color = palette.color(palette.ColorRole.Text)
        muted = palette.color(palette.ColorRole.Mid)

        outer = QRectF(8, 8, self.width() - 16, self.height() - 16)
        painter.setPen(QPen(muted, 1))
        painter.setBrush(background)
        painter.drawRoundedRect(outer, 12, 12)

        title_font = QFont(self.font())
        title_font.setPointSize(10)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(text_color)

        if self.target_rpm is None:
            painter.drawText(
                outer,
                Qt.AlignmentFlag.AlignCenter,
                "No target active\n"
                + (
                    f"Current: {self.current_rpm:.0f} rpm"
                    if self.current_rpm is not None
                    else "No engine-speed data received"
                ),
            )
            return

        current_text = "–" if self.current_rpm is None else f"{self.current_rpm:.0f}"
        delta = (
            None
            if self.current_rpm is None
            else self.current_rpm - float(self.target_rpm)
        )
        delta_text = "–" if delta is None else f"{delta:+.0f}"

        big_font = QFont(self.font())
        big_font.setPointSize(22)
        big_font.setBold(True)
        painter.setFont(big_font)
        painter.drawText(
            QRectF(20, 18, self.width() - 40, 42),
            Qt.AlignmentFlag.AlignCenter,
            f"{current_text} rpm",
        )

        painter.setFont(title_font)
        painter.drawText(
            QRectF(20, 58, self.width() - 40, 26),
            Qt.AlignmentFlag.AlignCenter,
            f"Target {self.target_rpm} ± {self.tolerance_rpm} rpm   |   "
            f"Deviation {delta_text} rpm",
        )

        bar = QRectF(28, 105, self.width() - 56, 28)
        painter.setPen(QPen(muted, 1))
        painter.setBrush(palette.color(palette.ColorRole.AlternateBase))
        painter.drawRoundedRect(bar, 7, 7)

        scale = max(500.0, self.target_rpm * 0.45)
        low = self.target_rpm - scale
        high = self.target_rpm + scale

        def map_rpm(value: float) -> float:
            ratio = (value - low) / (high - low)
            ratio = max(0.0, min(1.0, ratio))
            return bar.left() + ratio * bar.width()

        tolerance_left = map_rpm(self.target_rpm - self.tolerance_rpm)
        tolerance_right = map_rpm(self.target_rpm + self.tolerance_rpm)
        tolerance_rect = QRectF(
            tolerance_left,
            bar.top(),
            max(2.0, tolerance_right - tolerance_left),
            bar.height(),
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(70, 150, 90, 110))
        painter.drawRoundedRect(tolerance_rect, 6, 6)

        target_x = map_rpm(float(self.target_rpm))
        painter.setPen(QPen(QColor(80, 160, 230), 2))
        painter.drawLine(
            int(target_x),
            int(bar.top() - 5),
            int(target_x),
            int(bar.bottom() + 5),
        )

        if self.current_rpm is not None:
            current_x = map_rpm(self.current_rpm)
            in_range = abs(self.current_rpm - self.target_rpm) <= self.tolerance_rpm
            pointer_color = (
                QColor(50, 190, 90) if in_range else QColor(220, 145, 45)
            )
            painter.setPen(QPen(pointer_color, 3))
            painter.drawLine(
                int(current_x),
                int(bar.top() - 12),
                int(current_x),
                int(bar.bottom() + 12),
            )

        painter.setPen(text_color)
        painter.setFont(self.font())
        painter.drawText(
            QRectF(20, 138, self.width() - 40, 22),
            Qt.AlignmentFlag.AlignCenter,
            "Left: too low     Centre: target range     Right: too high",
        )


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------


class BluetoothSerialWorker(QThread):
    """Create or release a Linux RFCOMM serial device without blocking the GUI."""

    succeeded = Signal(str)
    failed = Signal(str)
    status = Signal(str)

    def __init__(
        self,
        action: str,
        address: str,
        channel: int,
        device: str,
        parent=None,
    ):
        super().__init__(parent)
        self.action = action
        self.address = address.strip().upper()
        self.channel = channel
        self.device = device.strip()

    @staticmethod
    def _run(command: list[str], timeout: float = 20.0) -> subprocess.CompletedProcess:
        return subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )

    def _privileged(self, command: list[str]) -> subprocess.CompletedProcess:
        if os.geteuid() == 0:
            return self._run(command)
        pkexec = shutil.which("pkexec")
        if not pkexec:
            raise RuntimeError(
                "Administrative privileges are required, but pkexec is not installed."
            )
        return self._run([pkexec, *command], timeout=60.0)

    def run(self) -> None:
        if sys.platform != "linux":
            self.failed.emit("Automatic RFCOMM setup is available on Linux only.")
            return

        rfcomm = shutil.which("rfcomm")
        if not rfcomm:
            self.failed.emit(
                "The rfcomm utility was not found. Install the BlueZ package first."
            )
            return

        try:
            rfcomm_dev = Path(self.device).name
            if self.action == "release":
                self.status.emit(f"Releasing {self.device}…")
                result = self._privileged([rfcomm, "release", rfcomm_dev])
                if result.returncode not in (0, 1):
                    raise RuntimeError(result.stdout.strip() or "rfcomm release failed")
                self.succeeded.emit(f"Released {self.device}")
                return

            if not re.fullmatch(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}", self.address):
                raise ValueError("Enter a valid Bluetooth address such as 00:11:22:33:44:55.")
            if not re.fullmatch(r"/dev/rfcomm\d+", self.device):
                raise ValueError("The RFCOMM device must look like /dev/rfcomm0.")

            bluetoothctl = shutil.which("bluetoothctl")
            if bluetoothctl:
                self.status.emit(f"Connecting to {self.address}…")
                result = self._run([bluetoothctl, "connect", self.address], timeout=25.0)
                output = result.stdout.lower()
                if result.returncode != 0 and "already connected" not in output:
                    self.status.emit(
                        "Bluetooth connection was not confirmed; attempting RFCOMM binding anyway."
                    )

            self.status.emit(f"Creating {self.device} on channel {self.channel}…")
            self._privileged([rfcomm, "release", rfcomm_dev])
            result = self._privileged(
                [rfcomm, "bind", rfcomm_dev, self.address, str(self.channel)]
            )
            if result.returncode != 0:
                raise RuntimeError(result.stdout.strip() or "rfcomm bind failed")

            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline and not Path(self.device).exists():
                time.sleep(0.1)

            if not Path(self.device).exists():
                raise RuntimeError(
                    f"RFCOMM reported success, but {self.device} was not created."
                )
            self.succeeded.emit(self.device)
        except subprocess.TimeoutExpired:
            self.failed.emit("Bluetooth/RFCOMM command timed out.")
        except Exception as exc:
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    HISTORY_LIMIT = 250_000

    PID_PRESETS = {
        "Lean diagnostics": [
            "rpm",
            "coolant",
            "stft1",
            "ltft1",
            "map",
            "throttle",
            "o2_b1s1",
        ],
        "Balanced": [sensor.key for sensor in SENSORS if sensor.default_enabled],
        "Full scan": [sensor.key for sensor in SENSORS],
    }

    TEST_PRESETS = {
        "RPM step test": [
            TestStage("Idle baseline", "Release the accelerator and stabilise at idle.", 10),
            TestStage("1500 rpm", "Hold 1500 ±100 rpm.", 20, 1500, 100),
            TestStage("Intermediate idle", "Release the accelerator and return to idle.", 20),
            TestStage("2500 rpm", "Hold 2500 ±120 rpm.", 20, 2500, 120),
            TestStage("Final idle", "Release the accelerator and remain at idle.", 20),
        ],
        "Extended fuel-trim test": [
            TestStage("Idle baseline", "All electrical loads off; release the accelerator.", 30),
            TestStage("1500 rpm", "Hold 1500 ±100 rpm.", 20, 1500, 100),
            TestStage("Intermediate idle", "Release the accelerator.", 30),
            TestStage("2500 rpm", "Hold 2500 ±120 rpm.", 20, 2500, 120),
            TestStage("Idle recovery", "Release the accelerator and keep the engine running.", 60),
        ],
        "Electrical load test": [
            TestStage("Loads off", "Switch off blower, lights and rear-window heater.", 30),
            TestStage(
                "Enable loads",
                "Set the blower to maximum, switch on lights and rear-window heater, then click Next.",
                manual=True,
            ),
            TestStage("Loaded idle", "Keep all selected loads enabled and remain at idle.", 30),
            TestStage("Loaded 2500 rpm", "Hold 2500 ±120 rpm with the loads enabled.", 20, 2500, 120),
            TestStage("Final loaded idle", "Release the accelerator and keep the loads enabled.", 30),
        ],
        "Oxygen-sensor response": [
            TestStage("Idle baseline", "Release the accelerator and stabilise at idle.", 30),
            TestStage("2500 rpm", "Hold 2500 ±120 rpm.", 30, 2500, 120),
            TestStage("Idle recovery", "Release the accelerator and return to idle.", 30),
        ],
    }

    def __init__(self):
        super().__init__()
        self.settings = QSettings(ORGANIZATION_NAME, APP_NAME)
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.resize(1600, 980)

        icon_path = Path(__file__).resolve().parent / "assets" / f"{DESKTOP_FILE_ID}.svg"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.worker: Optional[OBDWorker] = None
        self.bluetooth_worker: Optional[BluetoothSerialWorker] = None
        self.csv_writer: Optional[CsvWriterThread] = None
        self.temp_csv_path: Optional[Path] = None

        self.connected_state = False
        self.closing = False
        self.capture_active = False
        self.plot_paused = False
        self.polling_paused = False
        self.offline_mode = False

        self.capture_start_monotonic = time.monotonic()
        self.capture_start_wallclock = datetime.now()
        self.plot_time = 0.0
        self.history: dict[str, deque[tuple[float, float]]] = defaultdict(
            lambda: deque(maxlen=self.HISTORY_LIMIT)
        )
        self.latest_values: dict[str, float] = {}
        self.supported_pids: set[int] = set()
        self.markers: list[Marker] = []
        self.marker_graphics: list[tuple[pg.PlotWidget, object]] = []

        saved_keys = self.settings.value("pids/enabled", None)
        if isinstance(saved_keys, str):
            saved_keys = [part for part in saved_keys.split(",") if part]
        valid_keys = {sensor.key for sensor in SENSORS}
        self.enabled_keys = {
            key for key in (saved_keys or self.PID_PRESETS["Balanced"]) if key in valid_keys
        }
        if not self.enabled_keys:
            self.enabled_keys = set(self.PID_PRESETS["Lean diagnostics"])

        self.test_active = False
        self.test_stages: list[TestStage] = []
        self.test_stage_index = -1
        self.test_stage_elapsed = 0.0
        self.test_last_tick = time.monotonic()
        self.test_capture_start: Optional[float] = None
        self.last_test_range: Optional[tuple[float, float]] = None
        self.last_test_title = ""

        pg.setConfigOptions(antialias=False)
        self._cleanup_stale_temp_files()
        self._build_ui()
        self._refresh_ports()
        self._build_plots()
        self._apply_pid_visibility()
        self._update_test_gauge()
        self._apply_style()

        self.plot_timer = QTimer(self)
        self.plot_timer.timeout.connect(self._refresh_plots)
        self.plot_timer.start(400)

        self.test_timer = QTimer(self)
        self.test_timer.timeout.connect(self._test_tick)
        self.test_timer.start(100)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QGroupBox { font-weight: 600; margin-top: 10px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
            QPushButton { min-height: 28px; padding: 3px 10px; }
            QPushButton#primaryButton { font-weight: 700; }
            QLabel#connectionStatus { font-size: 13px; font-weight: 600; }
            QLabel#sectionHint { color: palette(mid); }
            QTabWidget::pane { border: 1px solid palette(midlight); }
            """
        )

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QVBoxLayout(root)

        connection_box = QGroupBox("Connection")
        connection_layout = QHBoxLayout(connection_box)
        self.connection_status_label = QLabel("● Disconnected")
        self.connection_status_label.setObjectName("connectionStatus")
        self.connection_status_label.setStyleSheet("color: #b33a3a;")
        self.connection_detail_label = QLabel("Configure the serial connection on the Settings tab.")
        self.connection_detail_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.connect_button = QPushButton("Connect")
        self.connect_button.setObjectName("primaryButton")
        self.connect_button.clicked.connect(self._toggle_connection)
        connection_layout.addWidget(self.connection_status_label)
        connection_layout.addWidget(self.connection_detail_label, 1)
        connection_layout.addWidget(self.connect_button)
        root_layout.addWidget(connection_box)

        self.tabs = QTabWidget()
        root_layout.addWidget(self.tabs, 1)
        self._build_dashboard_tab()
        self._build_plot_tab()
        self._build_test_tab()
        self._build_diagnostic_tab()
        self._build_raw_tab()
        self._build_settings_tab()

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Disconnected")

        file_menu = self.menuBar().addMenu("File")
        load_action = QAction("Open CSV recording…", self)
        load_action.triggered.connect(self._load_csv)
        file_menu.addAction(load_action)
        export_range_action = QAction("Export selected range…", self)
        export_range_action.triggered.connect(self._export_selected_range)
        file_menu.addAction(export_range_action)
        export_all_action = QAction("Export complete session…", self)
        export_all_action.triggered.connect(self._export_complete_session)
        file_menu.addAction(export_all_action)
        file_menu.addSeparator()
        snapshot_action = QAction("Export current values…", self)
        snapshot_action.triggered.connect(self._export_snapshot)
        file_menu.addAction(snapshot_action)

    def _build_dashboard_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        hint = QLabel(
            "Live values continue to update while connected. Plot history is collected only after Start is pressed on the Plot tab."
        )
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.value_table = QTableWidget(len(SENSORS) + 1, 4)
        self.value_table.setHorizontalHeaderLabels(["Measurement", "Value", "Unit", "OBD command"])
        self.value_table.verticalHeader().setVisible(False)
        self.value_table.setAlternatingRowColors(True)
        self.value_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.value_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.value_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3):
            self.value_table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        self.dashboard_row_by_key: dict[str, int] = {}
        for row, sensor in enumerate(SENSORS):
            self.dashboard_row_by_key[sensor.key] = row
            self.value_table.setItem(row, 0, QTableWidgetItem(sensor.name))
            value_item = QTableWidgetItem("–")
            value_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.value_table.setItem(row, 1, value_item)
            self.value_table.setItem(row, 2, QTableWidgetItem(sensor.unit))
            self.value_table.setItem(row, 3, QTableWidgetItem(sensor.command))

        adapter_row = len(SENSORS)
        self.dashboard_row_by_key["adapter_voltage"] = adapter_row
        for column, text in enumerate(["ELM supply voltage", "–", "V", "ATRV"]):
            item = QTableWidgetItem(text)
            if column == 1:
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.value_table.setItem(adapter_row, column, item)
        layout.addWidget(self.value_table, 1)
        self.tabs.addTab(tab, "Dashboard")

    def _build_plot_tab(self) -> None:
        self.plot_tab = QWidget()
        self.plot_layout = QVBoxLayout(self.plot_tab)
        controls = QGridLayout()

        self.plot_start_button = QPushButton("Start")
        self.plot_start_button.setEnabled(False)
        self.plot_start_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.plot_start_button.clicked.connect(self._start_plot_capture)
        self.plot_pause_button = QPushButton("Pause")
        self.plot_pause_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))
        self.plot_pause_button.setCheckable(True)
        self.plot_pause_button.setEnabled(False)
        self.plot_pause_button.toggled.connect(self._toggle_plot_pause)
        self.plot_reset_button = QPushButton("Reset")
        self.plot_reset_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        self.plot_reset_button.clicked.connect(self._reset_plot_session)

        self.history_combo = QComboBox()
        for label, seconds in [
            ("1 minute", 60), ("2 minutes", 120), ("5 minutes", 300),
            ("10 minutes", 600), ("20 minutes", 1200), ("30 minutes", 1800),
            ("60 minutes", 3600), ("2 hours", 7200), ("Complete session", 0),
        ]:
            self.history_combo.addItem(label, seconds)
        self.history_combo.setCurrentText("10 minutes")
        self.history_combo.currentIndexChanged.connect(self._update_visible_export_range)

        self.load_csv_button = QPushButton("Open CSV…")
        self.load_csv_button.clicked.connect(self._load_csv)
        self.source_label = QLabel("Source: no plot session")
        self.source_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        controls.addWidget(self.plot_start_button, 0, 0)
        controls.addWidget(self.plot_pause_button, 0, 1)
        controls.addWidget(self.plot_reset_button, 0, 2)
        controls.addWidget(QLabel("Display window:"), 0, 3)
        controls.addWidget(self.history_combo, 0, 4)
        controls.addWidget(self.load_csv_button, 0, 5)
        controls.addWidget(self.source_label, 0, 6, 1, 2)

        self.marker_edit = QLineEdit()
        self.marker_edit.setPlaceholderText("Marker comment, for example: EVAP valve disconnected")
        self.marker_edit.returnPressed.connect(self._add_manual_marker)
        self.marker_button = QPushButton("Add marker")
        self.marker_button.setEnabled(False)
        self.marker_button.clicked.connect(self._add_manual_marker)
        controls.addWidget(QLabel("Marker:"), 1, 0)
        controls.addWidget(self.marker_edit, 1, 1, 1, 6)
        controls.addWidget(self.marker_button, 1, 7)

        self.export_start_spin = QDoubleSpinBox()
        self.export_start_spin.setRange(0.0, 999999.0)
        self.export_start_spin.setDecimals(2)
        self.export_start_spin.setSuffix(" s")
        self.export_end_spin = QDoubleSpinBox()
        self.export_end_spin.setRange(0.0, 999999.0)
        self.export_end_spin.setDecimals(2)
        self.export_end_spin.setSuffix(" s")
        self.visible_range_button = QPushButton("Use visible range")
        self.visible_range_button.clicked.connect(self._update_visible_export_range)
        self.export_range_button = QPushButton("Export range…")
        self.export_range_button.clicked.connect(self._export_selected_range)
        self.export_all_button = QPushButton("Export all…")
        self.export_all_button.clicked.connect(self._export_complete_session)
        controls.addWidget(QLabel("Export from:"), 2, 0)
        controls.addWidget(self.export_start_spin, 2, 1)
        controls.addWidget(QLabel("to:"), 2, 2)
        controls.addWidget(self.export_end_spin, 2, 3)
        controls.addWidget(self.visible_range_button, 2, 4)
        controls.addWidget(self.export_range_button, 2, 5)
        controls.addWidget(self.export_all_button, 2, 6)

        self.temp_file_label = QLabel("Temporary recording: inactive")
        self.temp_file_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        controls.addWidget(self.temp_file_label, 3, 0, 1, 8)
        self.plot_layout.addLayout(controls)
        self.tabs.addTab(self.plot_tab, "Plot")

    def _build_test_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.rpm_gauge = RpmTargetGauge()
        layout.addWidget(self.rpm_gauge)

        single_box = QGroupBox("Single RPM test")
        single_layout = QGridLayout(single_box)
        self.target_rpm_spin = QSpinBox()
        self.target_rpm_spin.setRange(700, 5000)
        self.target_rpm_spin.setSingleStep(50)
        self.target_rpm_spin.setValue(1500)
        self.target_rpm_spin.valueChanged.connect(self._update_test_gauge)
        self.tolerance_spin = QSpinBox()
        self.tolerance_spin.setRange(25, 500)
        self.tolerance_spin.setSingleStep(25)
        self.tolerance_spin.setValue(100)
        self.tolerance_spin.setSuffix(" rpm")
        self.tolerance_spin.valueChanged.connect(self._update_test_gauge)
        self.hold_time_spin = QSpinBox()
        self.hold_time_spin.setRange(5, 300)
        self.hold_time_spin.setValue(20)
        self.hold_time_spin.setSuffix(" s")
        self.single_test_button = QPushButton("Start single test")
        self.single_test_button.clicked.connect(self._start_single_rpm_test)
        single_layout.addWidget(QLabel("Target:"), 0, 0)
        single_layout.addWidget(self.target_rpm_spin, 0, 1)
        single_layout.addWidget(QLabel("Tolerance:"), 0, 2)
        single_layout.addWidget(self.tolerance_spin, 0, 3)
        single_layout.addWidget(QLabel("Hold time:"), 0, 4)
        single_layout.addWidget(self.hold_time_spin, 0, 5)
        single_layout.addWidget(self.single_test_button, 0, 6)
        layout.addWidget(single_box)

        preset_box = QGroupBox("Multi-stage test assistant")
        preset_layout = QGridLayout(preset_box)
        self.test_preset_combo = QComboBox()
        self.test_preset_combo.addItems(self.TEST_PRESETS.keys())
        self.preset_start_button = QPushButton("Start preset")
        self.preset_start_button.clicked.connect(self._start_selected_preset)
        self.test_next_button = QPushButton("Next")
        self.test_next_button.clicked.connect(self._manual_stage_next)
        self.test_next_button.setEnabled(False)
        self.test_abort_button = QPushButton("Abort")
        self.test_abort_button.clicked.connect(self._abort_test)
        self.test_abort_button.setEnabled(False)
        self.export_test_button = QPushButton("Export last test…")
        self.export_test_button.clicked.connect(self._export_last_test)
        self.export_test_button.setEnabled(False)
        preset_layout.addWidget(QLabel("Preset:"), 0, 0)
        preset_layout.addWidget(self.test_preset_combo, 0, 1, 1, 3)
        preset_layout.addWidget(self.preset_start_button, 0, 4)
        preset_layout.addWidget(self.test_next_button, 0, 5)
        preset_layout.addWidget(self.test_abort_button, 0, 6)
        preset_layout.addWidget(self.export_test_button, 0, 7)
        layout.addWidget(preset_box)

        self.test_stage_label = QLabel("No test active")
        font = QFont(self.test_stage_label.font())
        font.setPointSize(15)
        font.setBold(True)
        self.test_stage_label.setFont(font)
        self.test_stage_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.test_stage_label)
        self.test_instruction_label = QLabel("Configure a single test or select a preset.")
        self.test_instruction_label.setWordWrap(True)
        self.test_instruction_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.test_instruction_label)
        self.test_countdown_label = QLabel("–")
        font = QFont(self.test_countdown_label.font())
        font.setPointSize(24)
        font.setBold(True)
        self.test_countdown_label.setFont(font)
        self.test_countdown_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.test_countdown_label)

        marker_box = QGroupBox("Test and session markers")
        marker_layout = QVBoxLayout(marker_box)
        self.marker_table = QTableWidget(0, 2)
        self.marker_table.setHorizontalHeaderLabels(["Time", "Comment"])
        self.marker_table.verticalHeader().setVisible(False)
        self.marker_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.marker_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.marker_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        marker_layout.addWidget(self.marker_table)
        layout.addWidget(marker_box, 1)
        self.tabs.addTab(tab, "Test assistant")

    def _build_diagnostic_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        buttons = QHBoxLayout()
        self.read_dtcs_button = QPushButton("Read DTCs")
        self.read_dtcs_button.clicked.connect(self._read_dtcs)
        self.clear_dtcs_button = QPushButton("Clear DTCs")
        self.clear_dtcs_button.clicked.connect(self._clear_dtcs)
        self.mode06_button = QPushButton("Read raw Mode 06")
        self.mode06_button.clicked.connect(self._read_mode06)
        self.polling_pause_button = QPushButton("Pause polling")
        self.polling_pause_button.setCheckable(True)
        self.polling_pause_button.setEnabled(False)
        self.polling_pause_button.toggled.connect(self._toggle_polling_pause)
        for button in (
            self.read_dtcs_button, self.clear_dtcs_button,
            self.mode06_button, self.polling_pause_button,
        ):
            buttons.addWidget(button)
        buttons.addStretch()
        layout.addLayout(buttons)
        self.dtc_output = QTextEdit()
        self.dtc_output.setReadOnly(True)
        self.dtc_output.setPlaceholderText("DTC and Mode 06 output appears here.")
        self.dtc_output.document().setMaximumBlockCount(3000)
        layout.addWidget(self.dtc_output, 1)
        custom_box = QGroupBox("Custom ELM/OBD command")
        custom_layout = QHBoxLayout(custom_box)
        self.custom_command = QLineEdit()
        self.custom_command.setPlaceholderText("For example: 0100, 03, 0600, or a manufacturer-specific command")
        self.custom_command.returnPressed.connect(self._send_custom)
        self.custom_send_button = QPushButton("Send")
        self.custom_send_button.clicked.connect(self._send_custom)
        custom_layout.addWidget(self.custom_command, 1)
        custom_layout.addWidget(self.custom_send_button)
        layout.addWidget(custom_box)
        self.tabs.addTab(tab, "Diagnostics")

    def _build_raw_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.raw_output = QTextEdit()
        self.raw_output.setReadOnly(True)
        self.raw_output.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.raw_output.document().setMaximumBlockCount(3000)
        layout.addWidget(self.raw_output, 1)
        clear_button = QPushButton("Clear raw log")
        clear_button.clicked.connect(self.raw_output.clear)
        layout.addWidget(clear_button)
        self.tabs.addTab(tab, "ELM raw log")

    def _build_settings_tab(self) -> None:
        tab = QWidget()
        self.settings_tab = tab
        layout = QVBoxLayout(tab)

        connection_box = QGroupBox("Serial connection")
        form = QFormLayout(connection_box)
        port_row = QHBoxLayout()
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(340)
        self.port_combo.currentIndexChanged.connect(self._update_connection_detail)
        self.refresh_button = QPushButton("Refresh ports")
        self.refresh_button.clicked.connect(self._refresh_ports)
        port_row.addWidget(self.port_combo, 1)
        port_row.addWidget(self.refresh_button)
        form.addRow("Serial port:", port_row)
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["38400", "115200", "9600", "57600"])
        self.baud_combo.setCurrentText(str(self.settings.value("connection/baud", "38400")))
        self.baud_combo.currentTextChanged.connect(self._update_connection_detail)
        form.addRow("Baud rate:", self.baud_combo)
        self.protocol_combo = QComboBox()
        for label, command in [
            ("Automatic", "ATSP0"),
            ("ISO 9141-2", "ATSP3"),
            ("ISO 14230-4 KWP (5 baud init)", "ATSP4"),
            ("ISO 14230-4 KWP (fast init)", "ATSP5"),
            ("ISO 15765-4 CAN 11 bit / 500 kbit", "ATSP6"),
        ]:
            self.protocol_combo.addItem(label, command)
        saved_protocol = str(self.settings.value("connection/protocol", "ATSP0"))
        index = self.protocol_combo.findData(saved_protocol)
        self.protocol_combo.setCurrentIndex(max(0, index))
        form.addRow("OBD protocol:", self.protocol_combo)
        self.poll_pause_spin = QSpinBox()
        self.poll_pause_spin.setRange(0, 500)
        self.poll_pause_spin.setValue(int(self.settings.value("connection/poll_pause_ms", 25)))
        self.poll_pause_spin.setSuffix(" ms")
        form.addRow("Delay after each PID:", self.poll_pause_spin)
        self.command_timeout_spin = QDoubleSpinBox()
        self.command_timeout_spin.setRange(0.3, 10.0)
        self.command_timeout_spin.setDecimals(1)
        self.command_timeout_spin.setSingleStep(0.1)
        self.command_timeout_spin.setValue(float(self.settings.value("connection/timeout_s", 2.0)))
        self.command_timeout_spin.setSuffix(" s")
        form.addRow("Command timeout:", self.command_timeout_spin)
        layout.addWidget(connection_box)

        bluetooth_box = QGroupBox("Bluetooth serial helper (Linux)")
        bluetooth_layout = QGridLayout(bluetooth_box)
        self.bluetooth_address_edit = QLineEdit(str(self.settings.value("bluetooth/address", "")))
        self.bluetooth_address_edit.setPlaceholderText("00:11:22:33:44:55")
        self.bluetooth_channel_spin = QSpinBox()
        self.bluetooth_channel_spin.setRange(1, 30)
        self.bluetooth_channel_spin.setValue(int(self.settings.value("bluetooth/channel", 1)))
        self.rfcomm_device_edit = QLineEdit(str(self.settings.value("bluetooth/device", "/dev/rfcomm0")))
        self.bluetooth_create_button = QPushButton("Create serial port")
        self.bluetooth_create_button.clicked.connect(self._create_bluetooth_serial)
        self.bluetooth_release_button = QPushButton("Release serial port")
        self.bluetooth_release_button.clicked.connect(self._release_bluetooth_serial)
        self.bluetooth_status_label = QLabel(
            "Pairs/connects with bluetoothctl and binds an RFCOMM device. Administrative authentication may be requested."
        )
        self.bluetooth_status_label.setWordWrap(True)
        bluetooth_layout.addWidget(QLabel("Adapter address:"), 0, 0)
        bluetooth_layout.addWidget(self.bluetooth_address_edit, 0, 1)
        bluetooth_layout.addWidget(QLabel("SPP channel:"), 0, 2)
        bluetooth_layout.addWidget(self.bluetooth_channel_spin, 0, 3)
        bluetooth_layout.addWidget(QLabel("Device:"), 1, 0)
        bluetooth_layout.addWidget(self.rfcomm_device_edit, 1, 1)
        bluetooth_layout.addWidget(self.bluetooth_create_button, 1, 2)
        bluetooth_layout.addWidget(self.bluetooth_release_button, 1, 3)
        bluetooth_layout.addWidget(self.bluetooth_status_label, 2, 0, 1, 4)
        if sys.platform != "linux":
            self.bluetooth_create_button.setEnabled(False)
            self.bluetooth_release_button.setEnabled(False)
            self.bluetooth_status_label.setText(
                "On Windows, pair the adapter in system settings and select the resulting COM port above."
            )
        layout.addWidget(bluetooth_box)

        pid_box = QGroupBox("Displayed and recorded PIDs")
        pid_layout = QVBoxLayout(pid_box)
        preset_row = QHBoxLayout()
        self.pid_preset_combo = QComboBox()
        self.pid_preset_combo.addItems([*self.PID_PRESETS.keys(), "Custom"])
        self.pid_preset_combo.setCurrentText("Custom")
        self.apply_pid_preset_button = QPushButton("Apply preset")
        self.apply_pid_preset_button.clicked.connect(self._apply_selected_pid_preset)
        preset_row.addWidget(QLabel("PID preset:"))
        preset_row.addWidget(self.pid_preset_combo)
        preset_row.addWidget(self.apply_pid_preset_button)
        preset_row.addStretch()
        pid_layout.addLayout(preset_row)

        self.pid_table = QTableWidget(len(SENSORS), 5)
        self.pid_table.setHorizontalHeaderLabels(["Enabled", "Measurement", "PID", "Unit", "ECU support"])
        self.pid_table.verticalHeader().setVisible(False)
        self.pid_table.setAlternatingRowColors(True)
        self.pid_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.pid_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in (2, 3, 4):
            self.pid_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.pid_row_by_key: dict[str, int] = {}
        for row, sensor in enumerate(SENSORS):
            self.pid_row_by_key[sensor.key] = row
            enabled_item = QTableWidgetItem()
            enabled_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable
            )
            enabled_item.setCheckState(
                Qt.CheckState.Checked if sensor.key in self.enabled_keys else Qt.CheckState.Unchecked
            )
            enabled_item.setData(Qt.ItemDataRole.UserRole, sensor.key)
            self.pid_table.setItem(row, 0, enabled_item)
            for column, text in enumerate([sensor.name, sensor.command, sensor.unit, "Unknown"], start=1):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.pid_table.setItem(row, column, item)
        self.pid_table.itemChanged.connect(self._pid_selection_changed)
        pid_layout.addWidget(self.pid_table)
        layout.addWidget(pid_box, 1)
        self.tabs.addTab(tab, "Settings")

    def _build_plots(self) -> None:
        self.plot_widgets: dict[str, pg.PlotWidget] = {}
        self.curves: dict[str, object] = {}
        groups = [
            ("Fuel mixture", ["stft1", "ltft1", "o2_b1s1", "equiv"]),
            ("Intake", ["map", "baro", "throttle", "maf", "fuel_pressure"]),
            ("Engine", ["rpm", "load", "abs_load", "timing", "speed"]),
            ("Temperature / voltage", ["coolant", "iat", "ecu_voltage", "adapter_voltage"]),
        ]
        for group_name, keys in groups:
            plot = pg.PlotWidget()
            plot.setTitle(group_name)
            plot.setLabel("bottom", "Time", units="s")
            plot.showGrid(x=True, y=True, alpha=0.25)
            plot.addLegend(offset=(10, 10))
            plot.setDownsampling(auto=True, mode="peak")
            plot.setClipToView(True)
            self.plot_layout.addWidget(plot, 1)
            self.plot_widgets[group_name] = plot
            for index, key in enumerate(keys):
                if key == "adapter_voltage":
                    name = "ELM supply [V]"
                else:
                    sensor = SENSOR_BY_KEY[key]
                    name = f"{sensor.name} [{sensor.unit}]"
                curve = plot.plot(
                    [], [], pen=pg.mkPen(pg.intColor(index, hues=max(6, len(keys))), width=1), name=name
                )
                curve.setDownsampling(auto=True, method="peak")
                curve.setClipToView(True)
                self.curves[key] = curve

    def _refresh_ports(self) -> None:
        current = self.port_combo.currentData() or self.settings.value("connection/port", "")
        self.port_combo.blockSignals(True)
        self.port_combo.clear()
        ports = sorted(list_ports.comports(), key=lambda port: port.device)
        for port in ports:
            description = port.description or "Serial port"
            self.port_combo.addItem(f"{port.device} — {description}", port.device)
        configured_rfcomm = self.rfcomm_device_edit.text().strip() if hasattr(self, "rfcomm_device_edit") else ""
        if configured_rfcomm and Path(configured_rfcomm).exists() and all(
            self.port_combo.itemData(i) != configured_rfcomm for i in range(self.port_combo.count())
        ):
            self.port_combo.addItem(f"{configured_rfcomm} — Bluetooth RFCOMM", configured_rfcomm)
        if not ports and self.port_combo.count() == 0:
            self.port_combo.addItem("No serial port found", "")
        chosen = False
        for index in range(self.port_combo.count()):
            if self.port_combo.itemData(index) == current:
                self.port_combo.setCurrentIndex(index)
                chosen = True
                break
        if not chosen and self.port_combo.count():
            self.port_combo.setCurrentIndex(0)
        self.port_combo.blockSignals(False)
        self._update_connection_detail()

    def _save_settings(self) -> None:
        self.settings.setValue("connection/port", self.port_combo.currentData() or "")
        self.settings.setValue("connection/baud", self.baud_combo.currentText())
        self.settings.setValue("connection/protocol", self.protocol_combo.currentData())
        self.settings.setValue("connection/poll_pause_ms", self.poll_pause_spin.value())
        self.settings.setValue("connection/timeout_s", self.command_timeout_spin.value())
        self.settings.setValue("pids/enabled", sorted(self.enabled_keys))
        self.settings.setValue("bluetooth/address", self.bluetooth_address_edit.text().strip())
        self.settings.setValue("bluetooth/channel", self.bluetooth_channel_spin.value())
        self.settings.setValue("bluetooth/device", self.rfcomm_device_edit.text().strip())
        self.settings.sync()

    def _update_connection_detail(self) -> None:
        if not hasattr(self, "port_combo"):
            return
        port = self.port_combo.currentData() or "no port selected"
        baud = self.baud_combo.currentText() if hasattr(self, "baud_combo") else ""
        self.connection_detail_label.setText(f"{port} · {baud} baud")

    def _effective_worker_keys(self) -> list[str]:
        if not self.connected_state or not self.supported_pids:
            return sorted(self.enabled_keys)
        return [
            sensor.key for sensor in SENSORS
            if sensor.key in self.enabled_keys and (sensor.pid is None or sensor.pid in self.supported_pids)
        ]

    def _toggle_connection(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.connect_button.setEnabled(False)
            self.statusBar().showMessage("Disconnecting…")
            self.worker.stop()
            return
        port = self.port_combo.currentData()
        if not port:
            QMessageBox.warning(self, "No serial port", "Select a serial port on the Settings tab.")
            self.tabs.setCurrentWidget(self.settings_tab if hasattr(self, "settings_tab") else self.tabs.widget(5))
            return
        if not self.enabled_keys:
            QMessageBox.warning(self, "No PIDs selected", "Enable at least one PID on the Settings tab.")
            return
        self._save_settings()
        self.offline_mode = False
        self.connect_button.setText("Disconnect")
        self.connect_button.setEnabled(True)
        self._set_connection_controls(False)
        self.connection_status_label.setText("● Connecting…")
        self.connection_status_label.setStyleSheet("color: #d38b00;")
        self.worker = OBDWorker(
            port=port,
            baudrate=int(self.baud_combo.currentText()),
            enabled_keys=sorted(self.enabled_keys),
            poll_pause_ms=self.poll_pause_spin.value(),
            parent=self,
        )
        # Worker attributes are assigned here to keep backward compatibility with the v2 class.
        self.worker.command_timeout = self.command_timeout_spin.value()
        self.worker.protocol_command = str(self.protocol_combo.currentData())
        self.worker.connected.connect(self._on_connected)
        self.worker.disconnected.connect(self._on_disconnected)
        self.worker.status.connect(self.statusBar().showMessage)
        self.worker.raw_log.connect(self._append_raw)
        self.worker.sample.connect(self._on_sample)
        self.worker.dtcs_ready.connect(self._show_dtcs)
        self.worker.mode06_ready.connect(self._show_mode06)
        self.worker.custom_ready.connect(self._show_custom_response)
        self.worker.start()

    @Slot(str, object)
    def _on_connected(self, identity: str, supported: object) -> None:
        if self.closing:
            return
        self.connected_state = True
        self.supported_pids = set(supported)
        self._apply_supported_state()
        if self.worker is not None:
            self.worker.update_enabled_keys(self._effective_worker_keys())
        self.polling_pause_button.setEnabled(True)
        self.plot_start_button.setEnabled(True)
        self.connection_status_label.setText("● Connected")
        self.connection_status_label.setStyleSheet("color: #27964b;")
        self.statusBar().showMessage(
            f"Connected: {identity}; ECU reported {len(self.supported_pids)} standard PIDs"
        )

    @Slot(str)
    def _on_disconnected(self, reason: str) -> None:
        self.connected_state = False
        self.polling_paused = False
        if self.test_active:
            self._abort_test(silent=False)
        if self.capture_active:
            self._stop_capture_writer()
        if not self.closing:
            self.connect_button.setText("Connect")
            self.connect_button.setEnabled(True)
            self.plot_start_button.setEnabled(False)
            self.polling_pause_button.blockSignals(True)
            self.polling_pause_button.setChecked(False)
            self.polling_pause_button.blockSignals(False)
            self.polling_pause_button.setEnabled(False)
            self._set_connection_controls(True)
            self.connection_status_label.setText("● Disconnected")
            self.connection_status_label.setStyleSheet("color: #b33a3a;")
            self.statusBar().showMessage(f"Disconnected: {reason}")
        sender = self.sender()
        if sender is self.worker:
            self.worker = None

    def _set_connection_controls(self, enabled: bool) -> None:
        for widget in (
            self.port_combo, self.refresh_button, self.baud_combo, self.protocol_combo,
            self.poll_pause_spin, self.command_timeout_spin,
            self.bluetooth_create_button, self.bluetooth_release_button,
        ):
            widget.setEnabled(enabled and (sys.platform == "linux" or widget not in (self.bluetooth_create_button, self.bluetooth_release_button)))

    @Slot(bool)
    def _toggle_polling_pause(self, paused: bool) -> None:
        self.polling_paused = paused
        if self.worker is not None:
            self.worker.set_polling_paused(paused)
        self.polling_pause_button.setText("Resume polling" if paused else "Pause polling")
        self.statusBar().showMessage("ECU polling paused." if paused else "ECU polling resumed.")

    def _apply_supported_state(self) -> None:
        for sensor in SENSORS:
            row = self.pid_row_by_key[sensor.key]
            supported = sensor.pid is None or sensor.pid in self.supported_pids
            status_item = self.pid_table.item(row, 4)
            status_item.setText("Supported" if supported else "Not reported")
            status_item.setToolTip(
                "" if supported else "The ECU did not advertise this standard OBD-II PID."
            )
            command_item = self.value_table.item(self.dashboard_row_by_key[sensor.key], 3)
            command_item.setText(sensor.command if supported else f"{sensor.command} (not reported)")

    @Slot(QTableWidgetItem)
    def _pid_selection_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 0:
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        if not key:
            return
        if item.checkState() == Qt.CheckState.Checked:
            self.enabled_keys.add(str(key))
        else:
            self.enabled_keys.discard(str(key))
        self.pid_preset_combo.setCurrentText("Custom")
        self._apply_pid_visibility()
        self._save_settings()
        if self.worker is not None:
            self.worker.update_enabled_keys(self._effective_worker_keys())

    def _apply_selected_pid_preset(self) -> None:
        name = self.pid_preset_combo.currentText()
        if name not in self.PID_PRESETS:
            return
        self.enabled_keys = set(self.PID_PRESETS[name])
        self.pid_table.blockSignals(True)
        try:
            for sensor in SENSORS:
                self.pid_table.item(self.pid_row_by_key[sensor.key], 0).setCheckState(
                    Qt.CheckState.Checked if sensor.key in self.enabled_keys else Qt.CheckState.Unchecked
                )
        finally:
            self.pid_table.blockSignals(False)
        self._apply_pid_visibility()
        self._save_settings()
        if self.worker is not None:
            self.worker.update_enabled_keys(self._effective_worker_keys())
        self.statusBar().showMessage(f"PID preset applied: {name}")

    def _apply_pid_visibility(self) -> None:
        for sensor in SENSORS:
            self.value_table.setRowHidden(
                self.dashboard_row_by_key[sensor.key], sensor.key not in self.enabled_keys
            )
        for key, curve in getattr(self, "curves", {}).items():
            curve.setVisible(key == "adapter_voltage" or key in self.enabled_keys)

    @Slot(str, float, float)
    def _on_sample(self, key: str, value: float, timestamp: float) -> None:
        self.latest_values[key] = value
        row = self.dashboard_row_by_key.get(key)
        if row is not None:
            decimals = 2 if key == "adapter_voltage" else SENSOR_BY_KEY[key].decimals
            self.value_table.item(row, 1).setText(f"{value:.{decimals}f}")
        if key == "rpm":
            self._update_test_gauge()
        if not self.capture_active:
            return
        elapsed = max(0.0, timestamp - self.capture_start_monotonic)
        self.plot_time = max(self.plot_time, elapsed)
        self.history[key].append((elapsed, value))
        self.export_end_spin.setMaximum(max(0.0, self.plot_time))
        self.export_end_spin.setValue(self.plot_time)
        writer = self.csv_writer
        if writer is not None:
            if key == "adapter_voltage":
                name, unit = "ELM supply voltage", "V"
            else:
                sensor = SENSOR_BY_KEY[key]
                name, unit = sensor.name, sensor.unit
            writer.enqueue_sample(
                timestamp=datetime.now().isoformat(timespec="milliseconds"),
                elapsed=elapsed,
                key=key,
                name=name,
                value=value,
                unit=unit,
            )

    def _start_plot_capture(self) -> None:
        if self.offline_mode:
            QMessageBox.information(self, "Offline recording", "Reset the loaded recording before starting a live plot session.")
            return
        if not self.connected_state:
            QMessageBox.information(self, "Not connected", "Connect to the ELM327 before starting a plot session.")
            return
        if self.capture_active:
            if self.plot_paused:
                self.plot_pause_button.setChecked(False)
            return
        if self.history:
            answer = QMessageBox.question(
                self,
                "Start a new plot session",
                "Starting a new session discards the current in-memory plot history and temporary file. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._delete_temp_file()
        self._clear_history_internal()
        self.capture_start_monotonic = time.monotonic()
        self.capture_start_wallclock = datetime.now()
        temp_dir = Path(tempfile.gettempdir()) / "elm327-live-diagnostic"
        temp_dir.mkdir(parents=True, exist_ok=True)
        self.temp_csv_path = temp_dir / f"session_{datetime.now():%Y%m%d_%H%M%S_%f}.csv"
        writer = CsvWriterThread(self.temp_csv_path, parent=self)
        writer.error.connect(self._csv_error)
        writer.closed.connect(self._csv_closed)
        self.csv_writer = writer
        writer.start()
        self.capture_active = True
        self.plot_paused = False
        self.plot_pause_button.blockSignals(True)
        self.plot_pause_button.setChecked(False)
        self.plot_pause_button.blockSignals(False)
        self.plot_pause_button.setEnabled(True)
        self.plot_start_button.setEnabled(False)
        self.marker_button.setEnabled(True)
        self.source_label.setText("Source: live plot session")
        self.temp_file_label.setText(f"Temporary recording: {self.temp_csv_path}")
        self.statusBar().showMessage("Plot session started; all received data is being written to a temporary CSV file.")

    def _stop_capture_writer(self) -> None:
        writer = self.csv_writer
        self.capture_active = False
        self.csv_writer = None
        if writer is not None:
            writer.stop_writer()
            writer.wait(2500)
            if writer.isRunning():
                writer.terminate()
                writer.wait(500)
        self.plot_start_button.setEnabled(self.connected_state and not self.offline_mode)
        self.plot_pause_button.setEnabled(bool(self.history) or self.offline_mode)
        self.marker_button.setEnabled(False)

    @Slot(bool)
    def _toggle_plot_pause(self, paused: bool) -> None:
        self.plot_paused = paused
        self.plot_pause_button.setText("Resume" if paused else "Pause")
        self.plot_pause_button.setIcon(
            self.style().standardIcon(
                QStyle.StandardPixmap.SP_MediaPlay if paused else QStyle.StandardPixmap.SP_MediaPause
            )
        )
        if paused:
            self.statusBar().showMessage("Plot display paused; acquisition and temporary CSV recording continue.")
        else:
            self.statusBar().showMessage("Plot display resumed.")
            self._refresh_plots()

    def _reset_plot_session(self) -> None:
        if self.test_active:
            QMessageBox.warning(self, "Test active", "Abort the running test before resetting the plot session.")
            return
        if self.history or self.markers:
            answer = QMessageBox.question(
                self,
                "Reset plot session",
                "Discard the current plot history and markers? Exported CSV files are not affected.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        restart = self.capture_active
        if self.capture_active:
            self._stop_capture_writer()
        self._delete_temp_file()
        self.offline_mode = False
        self._clear_history_internal()
        self.source_label.setText("Source: no plot session")
        self.temp_file_label.setText("Temporary recording: inactive")
        self.plot_start_button.setEnabled(self.connected_state)
        if restart and self.connected_state:
            self._start_plot_capture()

    def _clear_history_internal(self) -> None:
        self.history.clear()
        self.markers.clear()
        self.plot_time = 0.0
        self.last_test_range = None
        self.last_test_title = ""
        self.export_test_button.setEnabled(False)
        self._clear_marker_graphics()
        self._refresh_marker_table()
        for curve in getattr(self, "curves", {}).values():
            curve.setData([], [])
        for plot in getattr(self, "plot_widgets", {}).values():
            plot.setXRange(0, 10, padding=0.01)
        self.export_start_spin.setValue(0.0)
        self.export_end_spin.setMaximum(0.0)
        self.export_end_spin.setValue(0.0)
        self._update_test_gauge()

    def _refresh_plots(self) -> None:
        if self.plot_paused or not (self.capture_active or self.offline_mode or self.history):
            return
        window_seconds = int(self.history_combo.currentData())
        display_end = max(10.0, self.plot_time)
        minimum_time = 0.0 if window_seconds == 0 else max(0.0, display_end - window_seconds)
        for key, curve in self.curves.items():
            if key != "adapter_voltage" and key not in self.enabled_keys and not self.offline_mode:
                curve.setData([], [])
                continue
            data = self.history.get(key)
            if not data:
                curve.setData([], [])
                continue
            array = np.asarray(data, dtype=np.float64)
            start_index = int(np.searchsorted(array[:, 0], minimum_time, side="left")) if minimum_time > 0 else 0
            visible = array[start_index:]
            if visible.size:
                curve.setData(visible[:, 0], visible[:, 1])
            else:
                curve.setData([], [])
        for plot in self.plot_widgets.values():
            plot.setXRange(minimum_time, display_end, padding=0.01)

    def _update_visible_export_range(self) -> None:
        window_seconds = int(self.history_combo.currentData())
        end = self.plot_time
        start = 0.0 if window_seconds == 0 else max(0.0, end - window_seconds)
        self.export_start_spin.setValue(start)
        self.export_end_spin.setValue(end)

    def _add_manual_marker(self) -> None:
        text = self.marker_edit.text().strip()
        if not text:
            QMessageBox.information(self, "Empty marker", "Enter a comment for the marker.")
            return
        if not self.capture_active:
            QMessageBox.information(self, "No active plot session", "Start the plot before adding markers.")
            return
        self._add_marker(text)
        self.marker_edit.clear()

    def _add_marker(self, text: str) -> None:
        marker = Marker(
            elapsed=self.plot_time,
            text=text.strip(),
            timestamp=datetime.now().isoformat(timespec="milliseconds"),
        )
        self.markers.append(marker)
        self.markers.sort(key=lambda item: item.elapsed)
        self._rebuild_marker_graphics()
        self._refresh_marker_table()
        if self.csv_writer is not None:
            self.csv_writer.enqueue_marker(marker)

    def _clear_marker_graphics(self) -> None:
        for plot, item in self.marker_graphics:
            try:
                plot.removeItem(item)
            except Exception:
                pass
        self.marker_graphics.clear()

    def _rebuild_marker_graphics(self) -> None:
        self._clear_marker_graphics()
        for marker in self.markers:
            label = marker.text if len(marker.text) <= 32 else marker.text[:29] + "…"
            for plot in self.plot_widgets.values():
                line = pg.InfiniteLine(
                    pos=marker.elapsed,
                    angle=90,
                    movable=False,
                    pen=pg.mkPen((180, 120, 40, 180), width=1),
                    label=label,
                    labelOpts={"position": 0.92, "rotateAxis": (1, 0), "anchors": [(0, 0), (0, 0)]},
                )
                plot.addItem(line)
                self.marker_graphics.append((plot, line))

    def _refresh_marker_table(self) -> None:
        self.marker_table.setRowCount(len(self.markers))
        for row, marker in enumerate(self.markers):
            self.marker_table.setItem(row, 0, QTableWidgetItem(self._format_elapsed(marker.elapsed)))
            self.marker_table.setItem(row, 1, QTableWidgetItem(marker.text))
        if self.markers:
            self.marker_table.scrollToBottom()

    @staticmethod
    def _format_elapsed(seconds: float) -> str:
        seconds = max(0.0, seconds)
        minutes, remaining = divmod(seconds, 60)
        hours, minutes = divmod(int(minutes), 60)
        return f"{hours:02d}:{minutes:02d}:{remaining:05.2f}" if hours else f"{minutes:02d}:{remaining:05.2f}"

    def _write_csv_range(self, path: Path, start: float, end: float) -> None:
        if end < start:
            raise ValueError("The export end must not be earlier than the start.")
        rows: list[tuple[float, list[str]]] = []
        for key, points in self.history.items():
            if key == "adapter_voltage":
                name, unit = "ELM supply voltage", "V"
            elif key in SENSOR_BY_KEY:
                sensor = SENSOR_BY_KEY[key]
                name, unit = sensor.name, sensor.unit
            else:
                continue
            for elapsed, value in points:
                if start <= elapsed <= end:
                    timestamp = (self.capture_start_wallclock + timedelta(seconds=elapsed)).isoformat(timespec="milliseconds")
                    rows.append((elapsed, [timestamp, f"{elapsed:.3f}", key, name, f"{value:.6f}", unit, ""]))
        for marker in self.markers:
            if start <= marker.elapsed <= end:
                rows.append((marker.elapsed, [marker.timestamp, f"{marker.elapsed:.3f}", "__marker__", "Marker", "", "", marker.text]))
        rows.sort(key=lambda item: item[0])
        if not rows:
            raise ValueError("The selected range contains no samples.")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow(CsvWriterThread.HEADER)
            writer.writerows(row for _, row in rows)

    def _choose_export_path(self, stem: str) -> Optional[Path]:
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Export CSV",
            str(Path.home() / f"{stem}_{datetime.now():%Y%m%d_%H%M%S}.csv"),
            "CSV files (*.csv)",
        )
        if not filename:
            return None
        path = Path(filename)
        return path if path.suffix.lower() == ".csv" else path.with_suffix(".csv")

    def _export_selected_range(self) -> None:
        path = self._choose_export_path("elm327_range")
        if path is None:
            return
        try:
            self._write_csv_range(path, self.export_start_spin.value(), self.export_end_spin.value())
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        self.statusBar().showMessage(f"Exported CSV range: {path}")

    def _export_complete_session(self) -> None:
        if not self.history:
            QMessageBox.information(self, "No plot data", "There is no plot session to export.")
            return
        path = self._choose_export_path("elm327_session")
        if path is None:
            return
        try:
            self._write_csv_range(path, 0.0, self.plot_time)
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        self.statusBar().showMessage(f"Exported complete session: {path}")

    def _export_last_test(self) -> None:
        if not self.last_test_range:
            QMessageBox.information(self, "No completed test", "Complete or abort a test before exporting it.")
            return
        stem = re.sub(r"[^A-Za-z0-9_-]+", "_", self.last_test_title.strip()).strip("_").lower() or "test"
        path = self._choose_export_path(f"elm327_{stem}")
        if path is None:
            return
        try:
            self._write_csv_range(path, *self.last_test_range)
        except Exception as exc:
            QMessageBox.critical(self, "Test export failed", str(exc))
            return
        self.statusBar().showMessage(f"Exported test recording: {path}")

    def _load_csv(self) -> None:
        if self.connected_state or self.capture_active:
            QMessageBox.information(self, "Disconnect first", "Disconnect from the ECU before opening a saved recording.")
            return
        filename, _ = QFileDialog.getOpenFileName(
            self, "Open ELM327 recording", str(Path.home()), "CSV files (*.csv);;All files (*)"
        )
        if not filename:
            return
        try:
            loaded_history, loaded_markers, max_time, start_wallclock = self._parse_csv(Path(filename))
        except Exception as exc:
            QMessageBox.critical(self, "CSV could not be opened", str(exc))
            return
        self._delete_temp_file()
        self._clear_history_internal()
        self.latest_values.clear()
        for row in self.dashboard_row_by_key.values():
            self.value_table.item(row, 1).setText("–")
        self.offline_mode = True
        self.capture_start_wallclock = start_wallclock
        for key, points in loaded_history.items():
            self.history[key].extend(points)
            if points:
                self.latest_values[key] = points[-1][1]
                row = self.dashboard_row_by_key.get(key)
                if row is not None:
                    decimals = 2 if key == "adapter_voltage" else SENSOR_BY_KEY[key].decimals
                    self.value_table.item(row, 1).setText(f"{points[-1][1]:.{decimals}f}")
        self.markers.extend(loaded_markers)
        self.plot_time = max_time
        self.export_end_spin.setMaximum(max_time)
        self.export_end_spin.setValue(max_time)
        self._rebuild_marker_graphics()
        self._refresh_marker_table()
        self.history_combo.setCurrentText("Complete session")
        self.source_label.setText(f"Source: {filename}")
        self.temp_file_label.setText("Temporary recording: not used for opened files")
        self.plot_start_button.setEnabled(False)
        self.plot_pause_button.setEnabled(True)
        self._refresh_plots()
        self.statusBar().showMessage(f"Opened recording: {filename} ({self._format_elapsed(max_time)})")

    @staticmethod
    def _parse_float(text: str) -> float:
        return float(text.strip().replace(",", "."))

    def _parse_csv(self, path: Path) -> tuple[dict[str, list[tuple[float, float]]], list[Marker], float, datetime]:
        history: dict[str, list[tuple[float, float]]] = defaultdict(list)
        markers: list[Marker] = []
        max_time = 0.0
        start_wallclock: Optional[datetime] = None
        with path.open("r", newline="", encoding="utf-8-sig") as handle:
            sample = handle.read(4096)
            handle.seek(0)
            delimiter = "," if sample.count(",") > sample.count(";") * 2 else ";"
            reader = csv.DictReader(handle, delimiter=delimiter)
            if reader.fieldnames is None:
                raise ValueError("The CSV file has no header.")
            fields = set(reader.fieldnames)
            elapsed_field = "Elapsed_s" if "Elapsed_s" in fields else "Laufzeit_s"
            key_field = "Key" if "Key" in fields else "Schlüssel"
            value_field = "Value" if "Value" in fields else "Wert"
            comment_field = "Comment" if "Comment" in fields else "Kommentar"
            measurement_field = "Measurement" if "Measurement" in fields else "Messwert"
            timestamp_field = "Timestamp" if "Timestamp" in fields else "Zeitstempel"
            if elapsed_field not in fields or key_field not in fields:
                raise ValueError("Unknown CSV format. Expected Elapsed_s/Key or Laufzeit_s/Schlüssel columns.")
            for row in reader:
                elapsed_text = (row.get(elapsed_field) or "").strip()
                key = (row.get(key_field) or "").strip()
                if not elapsed_text or not key:
                    continue
                try:
                    elapsed = self._parse_float(elapsed_text)
                except ValueError:
                    continue
                max_time = max(max_time, elapsed)
                timestamp_text = (row.get(timestamp_field) or "").strip()
                if timestamp_text and start_wallclock is None:
                    try:
                        start_wallclock = datetime.fromisoformat(timestamp_text) - timedelta(seconds=elapsed)
                    except ValueError:
                        pass
                if key == "__marker__":
                    comment = (row.get(comment_field) or row.get(measurement_field) or "Marker").strip()
                    markers.append(Marker(elapsed, comment or "Marker", timestamp_text or datetime.now().isoformat(timespec="milliseconds")))
                    continue
                value_text = (row.get(value_field) or "").strip()
                if not value_text:
                    continue
                try:
                    value = self._parse_float(value_text)
                except ValueError:
                    continue
                if key in SENSOR_BY_KEY or key == "adapter_voltage":
                    history[key].append((elapsed, value))
        if not history:
            raise ValueError("The CSV file contains no recognised measurements.")
        for points in history.values():
            points.sort(key=lambda item: item[0])
        markers.sort(key=lambda item: item.elapsed)
        return dict(history), markers, max_time, start_wallclock or datetime.now()

    def _export_snapshot(self) -> None:
        if not self.latest_values:
            QMessageBox.information(self, "No values", "No current measurements are available.")
            return
        path = self._choose_export_path("elm327_snapshot")
        if path is None:
            return
        with path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow(["Measurement", "Value", "Unit", "Command"])
            for sensor in SENSORS:
                value = self.latest_values.get(sensor.key)
                writer.writerow([
                    sensor.name,
                    "" if value is None else f"{value:.{sensor.decimals}f}",
                    sensor.unit,
                    sensor.command,
                ])
            value = self.latest_values.get("adapter_voltage")
            writer.writerow(["ELM supply voltage", "" if value is None else f"{value:.2f}", "V", "ATRV"])
        self.statusBar().showMessage(f"Exported current values: {path}")

    def _update_test_gauge(self) -> None:
        current = self.latest_values.get("rpm")
        if self.test_active and 0 <= self.test_stage_index < len(self.test_stages):
            stage = self.test_stages[self.test_stage_index]
            target, tolerance = stage.target_rpm, stage.tolerance_rpm
        else:
            target, tolerance = self.target_rpm_spin.value(), self.tolerance_spin.value()
        self.rpm_gauge.set_values(current, target, tolerance)

    def _ensure_rpm_for_test(self) -> bool:
        if not self.connected_state:
            QMessageBox.information(self, "No ECU connection", "The test assistant requires an active ECU connection.")
            return False
        if "rpm" not in self.enabled_keys:
            self.enabled_keys.add("rpm")
            self.pid_table.blockSignals(True)
            self.pid_table.item(self.pid_row_by_key["rpm"], 0).setCheckState(Qt.CheckState.Checked)
            self.pid_table.blockSignals(False)
            self._apply_pid_visibility()
            if self.worker is not None:
                self.worker.update_enabled_keys(self._effective_worker_keys())
        if not self.capture_active:
            self._start_plot_capture()
        return self.capture_active

    def _start_single_rpm_test(self) -> None:
        if not self._ensure_rpm_for_test():
            return
        target = self.target_rpm_spin.value()
        tolerance = self.tolerance_spin.value()
        duration = self.hold_time_spin.value()
        stages = [
            TestStage("Idle preparation", "Release the accelerator and stabilise at idle.", 10),
            TestStage(f"Hold {target} rpm", f"Hold {target} ±{tolerance} rpm. The countdown runs only inside the target range.", duration, target, tolerance),
            TestStage("Idle recovery", "Release the accelerator and record idle operation.", 20),
        ]
        self._start_test(stages, f"Single RPM test {target}")

    def _start_selected_preset(self) -> None:
        if not self._ensure_rpm_for_test():
            return
        title = self.test_preset_combo.currentText()
        self._start_test(list(self.TEST_PRESETS[title]), title)

    def _start_test(self, stages: list[TestStage], title: str) -> None:
        self._abort_test(silent=True)
        self.test_active = True
        self.test_stages = stages
        self.test_stage_index = -1
        self.test_stage_elapsed = 0.0
        self.test_capture_start = self.plot_time
        self.last_test_range = None
        self.last_test_title = title
        self.export_test_button.setEnabled(False)
        self.test_abort_button.setEnabled(True)
        self.preset_start_button.setEnabled(False)
        self.single_test_button.setEnabled(False)
        self._add_marker(f"TEST START: {title}")
        self._advance_test_stage()

    def _advance_test_stage(self) -> None:
        if not self.test_active:
            return
        self.test_stage_index += 1
        self.test_stage_elapsed = 0.0
        self.test_last_tick = time.monotonic()
        if self.test_stage_index >= len(self.test_stages):
            self._add_marker("TEST END")
            self.last_test_range = (self.test_capture_start or 0.0, self.plot_time)
            self.export_test_button.setEnabled(True)
            QApplication.beep()
            self.test_stage_label.setText("Test completed")
            self.test_instruction_label.setText("All test stages were recorded and can be exported separately.")
            self.test_countdown_label.setText("Complete")
            self._finish_test_state()
            return
        stage = self.test_stages[self.test_stage_index]
        self.test_stage_label.setText(f"Stage {self.test_stage_index + 1}/{len(self.test_stages)}: {stage.name}")
        self.test_instruction_label.setText(stage.instruction)
        self.test_next_button.setEnabled(stage.manual)
        self.test_countdown_label.setText("Waiting for Next" if stage.manual else f"{stage.duration_s:.1f} s")
        self._add_marker(f"STAGE: {stage.name}")
        self._update_test_gauge()
        QApplication.beep()

    @Slot()
    def _test_tick(self) -> None:
        if not self.test_active or not (0 <= self.test_stage_index < len(self.test_stages)):
            return
        now = time.monotonic()
        delta = max(0.0, min(0.5, now - self.test_last_tick))
        self.test_last_tick = now
        stage = self.test_stages[self.test_stage_index]
        current_rpm = self.latest_values.get("rpm")
        if stage.manual:
            self.test_countdown_label.setText("Waiting for Next")
            self._update_test_gauge()
            return
        in_range = stage.target_rpm is None or (
            current_rpm is not None and abs(current_rpm - stage.target_rpm) <= stage.tolerance_rpm
        )
        if in_range:
            self.test_stage_elapsed += delta
        remaining = max(0.0, stage.duration_s - self.test_stage_elapsed)
        if stage.target_rpm is None:
            text = f"{remaining:05.1f} s"
        elif current_rpm is None:
            text = f"{remaining:05.1f} s · no RPM data"
        elif in_range:
            text = f"{remaining:05.1f} s · in target range"
        else:
            difference = current_rpm - stage.target_rpm
            direction = "high" if difference > 0 else "low"
            text = f"{remaining:05.1f} s · {abs(difference):.0f} rpm too {direction}"
        self.test_countdown_label.setText(text)
        self._update_test_gauge()
        if remaining <= 0:
            self._add_marker(f"STAGE END: {stage.name}")
            self._advance_test_stage()

    def _manual_stage_next(self) -> None:
        if not self.test_active or not (0 <= self.test_stage_index < len(self.test_stages)):
            return
        stage = self.test_stages[self.test_stage_index]
        if stage.manual:
            self._add_marker(f"STAGE END: {stage.name}")
            self._advance_test_stage()

    @Slot()
    def _abort_test(self, silent: bool = False) -> None:
        if not self.test_active:
            return
        if not silent:
            self._add_marker("TEST ABORTED")
            self.last_test_range = (self.test_capture_start or 0.0, self.plot_time)
            self.export_test_button.setEnabled(True)
            self.test_stage_label.setText("Test aborted")
            self.test_instruction_label.setText("The recorded part remains available for export.")
            self.test_countdown_label.setText("Aborted")
        self._finish_test_state()

    def _finish_test_state(self) -> None:
        self.test_active = False
        self.test_stages = []
        self.test_stage_index = -1
        self.test_stage_elapsed = 0.0
        self.test_next_button.setEnabled(False)
        self.test_abort_button.setEnabled(False)
        self.preset_start_button.setEnabled(True)
        self.single_test_button.setEnabled(True)
        self._update_test_gauge()

    def _require_worker(self) -> Optional[OBDWorker]:
        if self.worker is None or not self.worker.isRunning():
            QMessageBox.information(self, "Not connected", "Connect to the ELM327 first.")
            return None
        return self.worker

    def _read_dtcs(self) -> None:
        worker = self._require_worker()
        if worker is not None:
            self.dtc_output.append("Reading generic DTCs…")
            worker.request_dtcs()

    def _clear_dtcs(self) -> None:
        worker = self._require_worker()
        if worker is None:
            return
        answer = QMessageBox.warning(
            self,
            "Clear DTCs",
            "Service 04 clears DTCs, freeze frames and readiness information. Send the command?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            worker.request_clear_dtcs()

    def _read_mode06(self) -> None:
        worker = self._require_worker()
        if worker is not None:
            self.dtc_output.append("Reading raw Mode 06 data…")
            worker.request_mode06()

    def _send_custom(self) -> None:
        worker = self._require_worker()
        if worker is None:
            return
        command = re.sub(r"\s+", "", self.custom_command.text()).upper()
        if not command:
            return
        if not re.fullmatch(r"[0-9A-Z]+", command):
            QMessageBox.warning(self, "Invalid command", "Use only letters and hexadecimal digits without punctuation.")
            return
        worker.request_custom(command)

    @Slot(object)
    def _show_dtcs(self, dtcs: object) -> None:
        codes = list(dtcs)
        self.dtc_output.append(
            "Stored generic DTCs:\n  " + "\n  ".join(codes)
            if codes else "No generic DTCs reported."
        )

    @Slot(str)
    def _show_mode06(self, text: str) -> None:
        self.dtc_output.append("\nMode 06:\n" + text)

    @Slot(str, str)
    def _show_custom_response(self, command: str, response: str) -> None:
        self.dtc_output.append(f"\n> {command}\n{response.strip()}")

    @Slot(str)
    def _append_raw(self, text: str) -> None:
        self.raw_output.append(text)

    def _create_bluetooth_serial(self) -> None:
        self._start_bluetooth_worker("create")

    def _release_bluetooth_serial(self) -> None:
        self._start_bluetooth_worker("release")

    def _start_bluetooth_worker(self, action: str) -> None:
        if self.bluetooth_worker is not None and self.bluetooth_worker.isRunning():
            return
        self._save_settings()
        worker = BluetoothSerialWorker(
            action,
            self.bluetooth_address_edit.text(),
            self.bluetooth_channel_spin.value(),
            self.rfcomm_device_edit.text(),
            self,
        )
        self.bluetooth_worker = worker
        self.bluetooth_create_button.setEnabled(False)
        self.bluetooth_release_button.setEnabled(False)
        worker.status.connect(self.bluetooth_status_label.setText)
        worker.succeeded.connect(self._bluetooth_succeeded)
        worker.failed.connect(self._bluetooth_failed)
        worker.finished.connect(self._bluetooth_finished)
        worker.start()

    @Slot(str)
    def _bluetooth_succeeded(self, message: str) -> None:
        self.bluetooth_status_label.setText(message)
        self._refresh_ports()
        device = self.rfcomm_device_edit.text().strip()
        for index in range(self.port_combo.count()):
            if self.port_combo.itemData(index) == device:
                self.port_combo.setCurrentIndex(index)
                break
        self.statusBar().showMessage(message)

    @Slot(str)
    def _bluetooth_failed(self, message: str) -> None:
        self.bluetooth_status_label.setText(f"Bluetooth setup failed: {message}")
        QMessageBox.warning(self, "Bluetooth serial setup failed", message)

    def _bluetooth_finished(self) -> None:
        self.bluetooth_worker = None
        enabled = not self.connected_state and sys.platform == "linux"
        self.bluetooth_create_button.setEnabled(enabled)
        self.bluetooth_release_button.setEnabled(enabled)

    @Slot(str)
    def _csv_error(self, message: str) -> None:
        QMessageBox.critical(self, "Temporary CSV recording failed", message)
        self.csv_writer = None
        self.capture_active = False
        self.plot_start_button.setEnabled(self.connected_state)

    @Slot(str)
    def _csv_closed(self, path: str) -> None:
        if not self.closing:
            self.statusBar().showMessage(f"Temporary CSV writer closed: {path}")

    def _cleanup_stale_temp_files(self) -> None:
        temp_dir = Path(tempfile.gettempdir()) / "elm327-live-diagnostic"
        if not temp_dir.exists():
            return
        cutoff = time.time() - 7 * 24 * 3600
        for path in temp_dir.glob("session_*.csv"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                pass

    def _delete_temp_file(self) -> None:
        path = self.temp_csv_path
        self.temp_csv_path = None
        if path is not None:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    def closeEvent(self, event: QCloseEvent) -> None:
        self.closing = True
        self._save_settings()
        self.plot_timer.stop()
        self.test_timer.stop()
        self._abort_test(silent=True)
        if self.capture_active or self.csv_writer is not None:
            self._stop_capture_writer()
        worker = self.worker
        if worker is not None and worker.isRunning():
            worker.stop()
            if not worker.wait(3000):
                worker.terminate()
                worker.wait(800)
        bluetooth_worker = self.bluetooth_worker
        if bluetooth_worker is not None and bluetooth_worker.isRunning():
            bluetooth_worker.requestInterruption()
            bluetooth_worker.wait(1000)
        self.worker = None
        self._delete_temp_file()
        event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    app.setOrganizationName(ORGANIZATION_NAME)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    if hasattr(app, "setDesktopFileName"):
        app.setDesktopFileName(DESKTOP_FILE_ID)
    icon_path = Path(__file__).resolve().parent / "assets" / f"{DESKTOP_FILE_ID}.svg"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Verified/curated diagnostic data for Opel Astra-G X16XEL Multec-H.

This module deliberately contains vehicle/profile knowledge only. Transport,
ELM327 timing and GUI code live elsewhere so the profile can later be replaced
or extended by JSON-backed vehicle/PID definitions.
"""

from __future__ import annotations

from dataclasses import dataclass

import elm327_twingo_gui as core


OPEL_LIVE_REQUEST = "2101"
OPEL_READ_DTCS = "1800FF00"
OPEL_CLEAR_DTCS = "14FF00"


@dataclass(frozen=True)
class LocalDataBlock:
    response_ok: bool
    payload_length: int
    data: tuple[int, ...]
    checksum_ok: bool | None
    frame: tuple[int, ...]


@dataclass(frozen=True)
class DTCRecord:
    code: str
    description: str
    status: int


# Curated for the X16XEL / Multec-H family. Unknown codes are still returned
# verbatim so the UI never hides diagnostic information just because our table
# is incomplete.
DTC_DESCRIPTIONS: dict[str, str] = {
    "P0105": "Manifold absolute pressure (MAP) sensor signal fault",
    "P0110": "Intake air temperature sensor circuit fault",
    "P0115": "Engine coolant temperature sensor circuit fault",
    "P0120": "Throttle position sensor circuit fault",
    "P0130": "Oxygen sensor circuit fault",
    "P0135": "Oxygen sensor heater circuit fault",
    "P0170": "Fuel trim malfunction / mixture adaptation out of range",
    "P0200": "Injector circuit malfunction",
    "P0230": "Fuel pump relay primary circuit fault",
    "P0325": "Knock sensor circuit fault",
    "P0335": "Crankshaft position / engine speed signal fault",
    "P0340": "Camshaft position sensor circuit fault",
    "P0351": "Ignition coil circuit, cylinders 1 and 4",
    "P0352": "Ignition coil circuit, cylinders 2 and 3",
    "P0400": "EGR system flow/function fault",
    "P0443": "EVAP purge valve circuit fault",
    "P0480": "Cooling fan relay/control circuit fault, low stage",
    "P0481": "Cooling fan relay/control circuit fault, high stage",
    "P0500": "Vehicle speed signal fault",
    "P0505": "Idle speed control / idle air control fault",
    "P0530": "A/C refrigerant pressure sensor circuit fault",
    "P0560": "System voltage malfunction",
    "P0602": "Control module programming/configuration fault",
    "P0650": "Malfunction indicator lamp (MIL) control circuit fault",
    "P0660": "Coolant warning output/control circuit fault",
    "P1231": "Fuel pump relay/contact fault",
    "P1405": "EGR valve position/control fault",
    "P1484": "Cooling fan relay/control fault",
    "P1530": "A/C compressor relay/control circuit fault",
    "P1540": "A/C pressure signal fault",
    "P1604": "Engine control module internal fault",
    "P1605": "Engine control module programming/internal fault",
    "P1610": "Immobilizer not programmed / immobilizer fault",
    "P1611": "Incorrect immobilizer/security code",
    "P1612": "Immobilizer signal missing or incorrect",
    "P1613": "Immobilizer signal missing or incorrect",
    "P1614": "Incorrect immobilizer transponder/key",
    "P1622": "Fuel pump relay/contact fault",
    "P1640": "Quad driver module / output driver fault",
    "P1813": "Torque control signal incorrect (automatic transmission)",
}


# Sensor keys intentionally reuse the application's existing generic names.
# That lets the current dashboard/CSV/plot pipeline work unchanged while the
# future PID editor and modular plot UI are being designed.
LIVE_COMMAND_LABELS: dict[str, str] = {
    "map": "2101 byte 13",
    "ecu_voltage": "2101 byte 14",
    "iat": "2101 byte 16",
    "coolant": "2101 byte 18",
    "timing": "2101 byte 19",
    "load": "2101 byte 20",
    "throttle": "2101 byte 28",
    "speed": "2101 byte 29",
    "rpm": "2101 byte 30",
    "o2_b1s1": "2101 byte 35",
}

DEFAULT_SENSOR_KEYS: tuple[str, ...] = (
    "rpm",
    "map",
    "ecu_voltage",
    "coolant",
    "iat",
    "throttle",
    "load",
    "timing",
    "speed",
    "o2_b1s1",
)
SUPPORTED_SENSOR_KEYS = frozenset(DEFAULT_SENSOR_KEYS)


def _hex_rows(response: str, command: str = "") -> list[list[int]]:
    try:
        return core.ELM327.extract_hex_bytes(response, command)
    except Exception:
        return []


def parse_local_identifier_01(response: str) -> LocalDataBlock:
    """Parse the verified X16XEL KWP response to ReadDataByLocalIdentifier 0x01."""
    rows = _hex_rows(response, OPEL_LIVE_REQUEST)
    if not rows:
        return LocalDataBlock(False, 0, (), None, ())

    for raw_row in rows:
        row = list(raw_row)
        if len(row) >= 4 and (row[0] & 0x80):
            payload_length = row[0] & 0x3F
            payload_start = 3
            payload_end = payload_start + payload_length
            if payload_length >= 2 and len(row) >= payload_end:
                payload = row[payload_start:payload_end]
                if payload[:2] != [0x61, 0x01]:
                    continue
                checksum_ok: bool | None = None
                if len(row) > payload_end:
                    checksum_ok = (sum(row[:payload_end]) & 0xFF) == row[payload_end]
                return LocalDataBlock(
                    True,
                    payload_length,
                    tuple(payload[2:]),
                    checksum_ok,
                    tuple(row[: payload_end + (1 if len(row) > payload_end else 0)]),
                )

        for index in range(max(0, len(row) - 1)):
            if row[index:index + 2] == [0x61, 0x01]:
                data = tuple(row[index + 2:])
                return LocalDataBlock(True, 2 + len(data), data, None, tuple(row))

    return LocalDataBlock(False, 0, (), None, tuple(rows[0]))


def format_indexed_data(data: tuple[int, ...]) -> str:
    if not data:
        return "  none"
    lines: list[str] = []
    for start in range(0, len(data), 8):
        chunk = data[start:start + 8]
        lines.append(f"  {start:02d}: " + " ".join(f"{value:02X}" for value in chunk))
    return "\n".join(lines)


def decode_live_values(response: str) -> dict[str, float]:
    """Decode only values already verified or strongly cross-checked on X16XEL.

    Offsets below are zero-based relative to the first data byte after ``61 01``.
    The source reverse-engineering numbers bytes from the start of the complete
    KWP frame, hence e.g. frame byte 30 is data offset 24.
    """
    block = parse_local_identifier_01(response)
    if not block.response_ok or len(block.data) < 30:
        return {}
    d = block.data
    return {
        # 0xF9 with engine off evaluates to about 101.6 kPa, matching ambient.
        "map": d[7] * 104.0 / 255.0,
        # Real captures: 0x74 -> 11.6 V, 0x8B -> 13.9 V, 0x8C -> 14.0 V.
        "ecu_voltage": d[8] / 10.0,
        "iat": d[10] * 191.0 / 255.0 - 40.0,
        "coolant": d[12] * 191.0 / 255.0 - 40.0,
        "timing": d[13] * 180.0 / 255.0 - 90.0,
        "load": d[14] * 100.0 / 255.0,
        "throttle": d[22] * 100.0 / 255.0,
        "speed": float(d[23]),
        # Verified against the user's ~3000 rpm capture: 0x7A * 25 = 3050 rpm.
        "rpm": float(d[24] * 25),
        "o2_b1s1": d[29] * 1.127 / 255.0,
    }


def _decode_dtc_word(high: int, low: int) -> str:
    word = ((high & 0xFF) << 8) | (low & 0xFF)
    family = "PCBU"[(word >> 14) & 0x03]
    first_digit = (word >> 12) & 0x03
    return f"{family}{first_digit:X}{word & 0x0FFF:03X}"


def parse_dtc_response(response: str) -> list[DTCRecord]:
    """Parse KWP service 0x18 response ``58 count (DTC_hi DTC_lo status)*``."""
    for row in _hex_rows(response, OPEL_READ_DTCS):
        try:
            index = row.index(0x58)
        except ValueError:
            continue
        if index + 1 >= len(row):
            continue
        count = row[index + 1]
        cursor = index + 2
        records: list[DTCRecord] = []
        for _ in range(count):
            if cursor + 2 >= len(row):
                break
            code = _decode_dtc_word(row[cursor], row[cursor + 1])
            status = row[cursor + 2]
            records.append(
                DTCRecord(
                    code=code,
                    description=DTC_DESCRIPTIONS.get(
                        code, "No description stored in the X16XEL/Multec-H profile"
                    ),
                    status=status,
                )
            )
            cursor += 3
        return records
    return []


def clear_dtc_response_ok(response: str) -> bool:
    for row in _hex_rows(response, OPEL_CLEAR_DTCS):
        for index in range(max(0, len(row) - 2)):
            if row[index:index + 3] == [0x54, 0xFF, 0x00]:
                return True
    return False

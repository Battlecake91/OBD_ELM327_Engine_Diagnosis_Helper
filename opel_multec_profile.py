#!/usr/bin/env python3
"""Verified/curated diagnostic data for Opel Astra-G X16XEL Multec-H.

This module deliberately contains vehicle/profile knowledge only. Transport,
ELM327 timing and GUI code live elsewhere so the profile can later be replaced
or extended by JSON-backed vehicle/PID definitions.
"""

from __future__ import annotations

from dataclasses import dataclass

import elm327_twingo_gui as core
from diagnostic_data import dtc_database


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


# Human-readable DTC texts live in data/dtc_codes.json so they can be translated
# and updated independently of the protocol parser.
def _load_opel_dtc_descriptions() -> dict[str, str]:
    manufacturers = dtc_database().get("manufacturers", {})
    opel = manufacturers.get("opel", {}) if isinstance(manufacturers, dict) else {}
    codes = opel.get("codes", {}) if isinstance(opel, dict) else {}
    result: dict[str, str] = {}
    if isinstance(codes, dict):
        for code, value in codes.items():
            if isinstance(value, dict):
                result[str(code).upper()] = str(value.get("en") or value.get("de") or "")
    return result


DTC_DESCRIPTIONS = _load_opel_dtc_descriptions()


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

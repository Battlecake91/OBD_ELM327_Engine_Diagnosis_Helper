#!/usr/bin/env python3
"""Read-only X16XEL / Multec-H local-data probing.

This extension is intentionally conservative.  After the existing Opel
KWP2000 Fast-Init/StartCommunication/ECU-identification probe succeeds, it
requests local identifier 0x01 with KWP service 0x21.  The response is captured
and indexed as raw bytes, but sensor formulas are not guessed until they have
been verified against measurements from the real vehicle.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import elm327_twingo_gui as core
import opel_kw82_probe as opel_probe


OPEL_LIVE_REQUEST = "2101"


@dataclass(frozen=True)
class LocalDataBlock:
    response_ok: bool
    payload_length: int
    data: tuple[int, ...]
    checksum_ok: bool | None
    frame: tuple[int, ...]


def _hex_rows(response: str, command: str = "") -> list[list[int]]:
    try:
        return core.ELM327.extract_hex_bytes(response, command)
    except Exception:
        return []


def parse_local_identifier_01(response: str) -> LocalDataBlock:
    """Parse a positive KWP 0x21/0x01 response without assigning sensor meanings.

    A normal physical KWP frame from this ECU looks like::

        B2 F1 11 61 01 <48 data bytes> <checksum>

    ``B2 & 0x3f == 0x32`` means 50 payload bytes: the positive service 0x61,
    local identifier 0x01 and 48 measurement bytes.
    """
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

        # Some ELM clones or header settings can return only the KWP payload.
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


def append_live_data_probe(
    elm: core.ELM327,
    log: Callable[[str], None],
    report: str,
) -> str:
    try:
        raw = elm.command(OPEL_LIVE_REQUEST, 5.0)
        response = raw.strip()
    except Exception as exc:
        response = f"{type(exc).__name__}: {exc}"
    log(f"> {OPEL_LIVE_REQUEST}\n{response}")

    block = parse_local_identifier_01(response)
    lines = [
        report,
        "",
        "ReadDataByLocalIdentifier 0x21 / local identifier 0x01:",
        response,
        f"Local-data response: {'POSITIVE 0x61 0x01' if block.response_ok else 'no positive 0x61 0x01 response'}",
    ]
    if block.response_ok:
        checksum_text = (
            "OK" if block.checksum_ok is True
            else "FAILED" if block.checksum_ok is False
            else "not available"
        )
        lines.extend(
            (
                f"KWP payload length: {block.payload_length} byte(s)",
                f"Measurement data bytes after 61 01: {len(block.data)}",
                f"Frame checksum: {checksum_text}",
                "Indexed raw measurement bytes (offset is relative to the first byte after 61 01):",
                format_indexed_data(block.data),
                "",
                "Interpretation:",
                "Local identifier 0x01 is readable on this Multec-H ECU. Sensor meanings and scaling are intentionally not assigned yet; compare indexed bytes across known engine states before promoting them to live values.",
            )
        )
    return "\n".join(lines)


_BASE_PROBE = opel_probe.probe_kw82_engine


def enhanced_probe_kw82_engine(
    elm: core.ELM327,
    log: Callable[[str], None],
    targets: tuple[int, ...] = opel_probe.OPEL_ENGINE_TARGETS,
) -> tuple[bool, str]:
    success, report = _BASE_PROBE(elm, log, targets)
    if not success:
        return success, report
    return success, append_live_data_probe(elm, log, report)


def install_live_extension() -> None:
    """Attach the read-only 0x2101 capture to the existing Opel probe worker."""
    opel_probe.probe_kw82_engine = enhanced_probe_kw82_engine

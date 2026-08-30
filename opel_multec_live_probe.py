#!/usr/bin/env python3
"""Read-only X16XEL / Multec-H local-data probe extension."""

from __future__ import annotations

from typing import Callable

import elm327_twingo_gui as core
import opel_kw82_probe as opel_probe
from opel_multec_profile import (
    OPEL_LIVE_REQUEST,
    LocalDataBlock,
    format_indexed_data,
    parse_local_identifier_01,
)


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
                "Local identifier 0x01 is readable on this Multec-H ECU. Verified live-value mappings are now used by the normal dashboard/plot worker; unmapped bytes remain available here for future reverse engineering.",
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

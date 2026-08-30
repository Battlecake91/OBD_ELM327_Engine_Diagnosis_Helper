from __future__ import annotations

import pytest

from opel_multec_profile import (
    clear_dtc_response_ok,
    decode_live_values,
    parse_dtc_response,
    parse_local_identifier_01,
)


FRAME_3000_RPM = (
    "B2 F1 11 61 01 03 14 05 20 04 00 30 3B 8C 00 58 38 6C 98 19 09 0C "
    "00 00 00 00 23 03 00 7A 2B 7F EB EA B4 80 07 7F 02 00 95 00 00 82 08 "
    "80 D4 A2 00 00 00 00 27 26\r>"
)


def test_parse_real_2101_frame_and_checksum():
    block = parse_local_identifier_01(FRAME_3000_RPM)

    assert block.response_ok is True
    assert block.payload_length == 50
    assert len(block.data) == 48
    assert block.checksum_ok is True


def test_decode_real_3000_rpm_capture():
    values = decode_live_values(FRAME_3000_RPM)

    assert values["rpm"] == 3050.0
    assert values["ecu_voltage"] == 14.0
    assert values["map"] == pytest.approx(0x3B * 104.0 / 255.0)
    assert values["speed"] == 0.0
    assert values["throttle"] == pytest.approx(0x03 * 100.0 / 255.0)
    assert values["o2_b1s1"] == pytest.approx(0xB4 * 1.127 / 255.0)


def test_parse_real_x16xel_dtc_response():
    records = parse_dtc_response(
        "8B F1 11 58 03 14 05 20 04 00 30 18 13 38 B8\r>"
    )

    assert [(item.code, item.status) for item in records] == [
        ("P1405", 0x20),
        ("P0400", 0x30),
        ("P1813", 0x38),
    ]
    assert "EGR" in records[0].description
    assert "Torque control" in records[2].description


def test_parse_empty_dtc_memory():
    assert parse_dtc_response("82 F1 11 58 00 DC\r>") == []


def test_clear_dtc_positive_response():
    assert clear_dtc_response_ok("83 F1 11 54 FF 00 D8\r>") is True

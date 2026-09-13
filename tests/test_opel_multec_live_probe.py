from __future__ import annotations

from opel_multec_live_probe import append_live_data_probe, parse_local_identifier_01


REAL_X16XEL_2101 = (
    "B2 F1 11 61 01 03 14 05 E0 04 00 30 F9 74 00 5C 4D 5C 8A 0E 09 "
    "00 00 00 00 00 20 00 00 02 35 4D 59 50 69 80 14 7B 00 00 3F 00 "
    "00 80 00 80 F0 A2 00 00 00 00 00 EF\r>"
)


class FakeELM:
    def __init__(self, response: str):
        self.response = response
        self.commands = []

    def command(self, command, timeout=None):
        self.commands.append((command, timeout))
        return self.response


def test_parse_real_x16xel_2101_frame():
    block = parse_local_identifier_01(REAL_X16XEL_2101)

    assert block.response_ok is True
    assert block.payload_length == 0x32
    assert len(block.data) == 48
    assert block.data[:8] == (0x03, 0x14, 0x05, 0xE0, 0x04, 0x00, 0x30, 0xF9)
    assert block.data[-6:] == (0xA2, 0x00, 0x00, 0x00, 0x00, 0x00)
    assert block.checksum_ok is True


def test_append_live_probe_reports_indexed_raw_bytes():
    elm = FakeELM(REAL_X16XEL_2101)
    log = []

    report = append_live_data_probe(elm, log.append, "base report")

    assert elm.commands == [("2101", 5.0)]
    assert "POSITIVE 0x61 0x01" in report
    assert "KWP payload length: 50 byte(s)" in report
    assert "Measurement data bytes after 61 01: 48" in report
    assert "Frame checksum: OK" in report
    assert "00: 03 14 05 E0 04 00 30 F9" in report
    assert any("> 2101" in entry for entry in log)

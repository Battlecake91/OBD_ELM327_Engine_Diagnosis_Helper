from __future__ import annotations

from opel_kw82_probe import probe_kw82_engine


class FakeELM:
    def __init__(self, responses):
        self.responses = {key: list(value) for key, value in responses.items()}
        self.commands = []

    def command(self, command, timeout=None):
        del timeout
        self.commands.append(command)
        values = self.responses.get(command)
        if not values:
            return "OK\r>"
        return values.pop(0)


def test_opel_probe_uses_fast_init_target_11_and_accepts_c1():
    elm = FakeELM(
        {
            "ATFI": ["OK\r>"],
            "81": ["83 F1 11 C1 EF 8F C4\r>"],
            "ATBD": ["07 83 F1 11 C1 EF 8F C4 00 00 00 00 00\r>"],
            "ATDP": ["ISO 14230-4 (KWP FAST)\r>"],
            "ATDPN": ["5\r>"],
            "ATKW": ["1:EF 2:8F\r>"],
        }
    )
    log = []

    success, report = probe_kw82_engine(elm, log.append)

    assert success is True
    assert "ATSP5" in elm.commands
    assert "ATIB10" in elm.commands
    assert "ATSH8111F1" in elm.commands
    assert "ATFI" in elm.commands
    assert "81" in elm.commands
    assert "ATSH8110F1" not in elm.commands
    assert "KWP StartCommunication: SUCCESS" in report
    assert "target ECU 0x11" in report
    assert "length=7, valid=83 F1 11 C1 EF 8F C4" in report
    assert any("> 81" in entry for entry in log)


def test_opel_probe_falls_back_to_target_10_after_no_data_on_11():
    elm = FakeELM(
        {
            "ATFI": ["OK\r>", "OK\r>"],
            "81": ["NO DATA\r>", "83 F1 10 C1 EF 8F C3\r>"],
            "ATBD": [
                "00 00 00 00 00 00 00 00 00 00 00 00 00\r>",
                "07 83 F1 10 C1 EF 8F C3 00 00 00 00 00\r>",
            ],
        }
    )

    success, report = probe_kw82_engine(elm, lambda _entry: None)

    assert success is True
    assert elm.commands.index("ATSH8111F1") < elm.commands.index("ATSH8110F1")
    assert elm.commands.count("ATFI") == 2
    assert elm.commands.count("81") == 2
    assert "target ECU 0x10" in report
    assert "KWP StartCommunication: SUCCESS" in report


def test_opel_probe_reports_no_positive_response_when_fast_init_fails():
    elm = FakeELM(
        {
            "ATFI": ["?\r>", "?\r>"],
            "81": ["NO DATA\r>", "NO DATA\r>"],
            "ATBD": ["00\r>", "00\r>"],
        }
    )

    success, report = probe_kw82_engine(elm, lambda _entry: None)

    assert success is False
    assert elm.commands.count("ATSP5") == 2
    assert elm.commands.count("ATFI") == 2
    assert "ATFI" in report
    assert "NO POSITIVE C1 RESPONSE" in report

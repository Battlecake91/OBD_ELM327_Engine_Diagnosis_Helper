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


def test_kw82_probe_uses_9600_custom_slow_init_and_reports_success():
    elm = FakeELM(
        {
            "ATSI": ["BUS INIT: OK\r>"],
            "ATKW": ["KW1: 12 KW2: 34\r>"],
            "ATDP": ["ISO 9141-2\r>"],
            "ATDPN": ["3\r>"],
            "ATBD": ["55 12 34\r>"],
        }
    )
    log = []

    success, report = probe_kw82_engine(elm, log.append)

    assert success is True
    assert "ATSP3" in elm.commands
    assert "ATIB96" in elm.commands
    assert "ATIIA01" in elm.commands
    assert "ATSI" in elm.commands
    assert "POSSIBLE RESPONSE / SUCCESS" in report
    assert "55 12 34" in report
    assert any("> ATSI" in entry for entry in log)


def test_kw82_probe_falls_back_to_protocol4_after_failed_protocol3_init():
    elm = FakeELM(
        {
            "ATSI": ["BUS INIT: ...ERROR\r>", "BUS INIT: OK\r>"],
            "ATKW": ["KW1: AA KW2: BB\r>"],
        }
    )

    success, report = probe_kw82_engine(elm, lambda _entry: None)

    assert success is True
    assert elm.commands.index("ATSP4") > elm.commands.index("ATSP3")
    assert elm.commands.count("ATSI") == 2
    assert "POSSIBLE RESPONSE / SUCCESS" in report


def test_kw82_probe_reports_missing_9600_support():
    elm = FakeELM(
        {
            "ATIB96": ["?\r>", "?\r>"],
            "ATKW": ["?\r>"],
        }
    )

    success, report = probe_kw82_engine(elm, lambda _entry: None)

    assert success is False
    assert "ATIB96" in report
    assert "NO SUCCESSFUL INITIALIZATION" in report

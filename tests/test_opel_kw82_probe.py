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


def test_opel_probe_uses_kwp_default_address_and_10400_first():
    elm = FakeELM(
        {
            "ATSI": ["BUS INIT: OK\r>"],
            "ATKW": ["1:08 2:08\r>"],
            "ATDP": ["ISO 14230-4 (KWP 5BAUD)\r>"],
            "ATDPN": ["4\r>"],
            "ATBD": ["02 55 08 AA BB CC DD EE FF 00 11 22 33\r>"],
        }
    )
    log = []

    success, report = probe_kw82_engine(elm, log.append)

    assert success is True
    assert "ATSP4" in elm.commands
    assert "ATIB10" in elm.commands
    assert "ATIIA33" in elm.commands
    assert "ATIB96" not in elm.commands
    assert "ATSI" in elm.commands
    assert "Slow initialization: SUCCESS" in report
    assert "length=2, valid=55 08" in report
    assert any("> ATSI" in entry for entry in log)


def test_opel_probe_falls_back_to_9600_after_default_kwp_init_fails():
    elm = FakeELM(
        {
            "ATSI": ["BUS INIT: ...ERROR\r>", "BUS INIT: OK\r>"],
            "ATKW": ["1:-- 2:--\r>", "1:12 2:34\r>"],
            "ATBD": ["00 00 00 00 00 00 00 00 00 00 00 00 00\r>", "01 55 00 00 00 00 00 00 00 00 00 00 00\r>"],
        }
    )

    success, report = probe_kw82_engine(elm, lambda _entry: None)

    assert success is True
    assert elm.commands.index("ATIB10") < elm.commands.index("ATIB96")
    assert elm.commands.count("ATSI") == 2
    assert elm.commands.count("ATSP4") == 2
    assert "KWP slow init / Opel 9600 fallback" in report
    assert "Slow initialization: SUCCESS" in report


def test_opel_probe_reports_unsupported_iso_baud_commands():
    elm = FakeELM(
        {
            "ATIB10": ["?\r>"],
            "ATIB96": ["?\r>", "?\r>"],
        }
    )

    success, report = probe_kw82_engine(elm, lambda _entry: None)

    assert success is False
    assert "ATSI" not in elm.commands
    assert "ATIB10" in report
    assert "ATIB96" in report
    assert "NO SUCCESSFUL INITIALIZATION" in report

from __future__ import annotations

import diagnostic_data


def test_vehicle_profiles_are_json_backed_and_have_guided_presets():
    profiles = {item["id"]: item for item in diagnostic_data.all_vehicle_profiles()}

    assert "generic_obd2" in profiles
    assert "opel_astra_g_x16xel_multec_h" in profiles
    opel = profiles["opel_astra_g_x16xel_multec_h"]
    assert opel["interface"]["settings_token"] == "OPEL_KW82_9600"
    assert any(item["id"] == "forum_basic" for item in opel["live_presets"])


def test_bilingual_dtc_lookup_prefers_vehicle_manufacturer():
    assert "Drehmomentregelung" in diagnostic_data.dtc_description(
        "P1813", manufacturer="opel", language="de"
    )
    assert "Torque control" in diagnostic_data.dtc_description(
        "P1813", manufacturer="opel", language="en"
    )
    assert "mager" in diagnostic_data.dtc_description(
        "P0171", manufacturer="generic", language="de"
    )
    assert "too lean" in diagnostic_data.dtc_description(
        "P0171", manufacturer="generic", language="en"
    ).lower()


def test_language_detection_accepts_windows_locale_names(monkeypatch):
    monkeypatch.setattr(diagnostic_data.locale, "getlocale", lambda: ("German_Germany", "1252"))
    for key in ("LANG", "LC_ALL", "LC_MESSAGES"):
        monkeypatch.delenv(key, raising=False)
    assert diagnostic_data.language_code() == "de"

    monkeypatch.setattr(diagnostic_data.locale, "getlocale", lambda: ("English_United States", "1252"))
    assert diagnostic_data.language_code() == "en"

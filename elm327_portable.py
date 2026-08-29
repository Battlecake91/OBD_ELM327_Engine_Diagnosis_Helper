#!/usr/bin/env python3
"""Start ELM327 Live Diagnostic with portable JSON settings."""

from settings_store import JsonSettings

import elm327_twingo_gui as core

core.QSettings = JsonSettings

import elm327_app as app

app.QSettings = JsonSettings

from opel_kw82_probe import install as install_kw82_probe
from opel_multec_live_probe import install_live_extension

install_kw82_probe()
install_live_extension()


if __name__ == "__main__":
    raise SystemExit(app.main())

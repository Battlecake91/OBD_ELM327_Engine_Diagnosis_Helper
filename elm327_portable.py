#!/usr/bin/env python3
"""Start ELM327 Live Diagnostic with portable JSON settings."""

from settings_store import JsonSettings

import elm327_twingo_gui as core

core.QSettings = JsonSettings

import elm327_app as app

app.QSettings = JsonSettings

from opel_kw82_probe import install as install_kw82_probe

install_kw82_probe()


if __name__ == "__main__":
    raise SystemExit(app.main())

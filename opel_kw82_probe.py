#!/usr/bin/env python3
"""Backward-compatible imports for the former experimental KW82 module.

The Astra-G X16XEL implementation was verified to use ISO 14230-4 KWP2000
Fast Init. New code must import opel_kwp2000. This module remains so existing
settings, tests and third-party imports do not fail after the rename.
"""
from __future__ import annotations

from opel_kwp2000 import *  # noqa: F401,F403
from opel_kwp2000 import (
    OPEL_PROTOCOL_LABEL as KW82_PROTOCOL_LABEL,
    OPEL_PROTOCOL_TOKEN as KW82_PROTOCOL_TOKEN,
    OpelKwpMixin as ExperimentalMainWindow,
    OpelKwpWorker as OpelKW82ProbeWorker,
    initialize_opel_adapter as initialize_adapter_for_kw82_probe,
    probe_opel_engine as probe_kw82_engine,
)


def install() -> None:
    """Deprecated compatibility no-op.

    Opel support is integrated directly into elm327_app.MainWindow now.
    """
    return None

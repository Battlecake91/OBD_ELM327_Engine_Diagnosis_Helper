from __future__ import annotations

import update_service


def test_version_comparison_handles_release_tags():
    assert update_service.compare_versions("3.2.0", "3.1.9") == 1
    assert update_service.compare_versions("v3.1.0", "3.1") == 0
    assert update_service.compare_versions("3.0.9", "3.1.0") == -1


def test_release_asset_selection_is_platform_specific():
    release = {
        "assets": [
            {
                "name": "OBD_ELM327_Engine_Diagnosis_Helper-windows-x64.zip",
                "browser_download_url": "https://example.invalid/windows.zip",
                "size": 123,
            },
            {
                "name": "OBD_ELM327_Engine_Diagnosis_Helper-linux-x86_64.zip",
                "browser_download_url": "https://example.invalid/linux.zip",
                "size": 456,
            },
        ]
    }

    windows = update_service.find_release_asset(release, "win32")
    linux = update_service.find_release_asset(release, "linux")

    assert windows.name.endswith("windows-x64.zip")
    assert linux.name.endswith("linux-x86_64.zip")


def test_source_checkout_never_self_updates(monkeypatch):
    monkeypatch.setattr(update_service, "is_frozen_app", lambda: False)
    assert update_service.portable_update_available() is False

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

GITHUB_REPOSITORY = "Battlecake91/OBD_ELM327_Engine_Diagnosis_Helper"
APP_ASSET_TOKEN = "obd_elm327_engine_diagnosis_helper"

ProgressCallback = Callable[[int, int], None]


def platform_key(value: str | None = None) -> str:
    name = (value or sys.platform).lower()
    if name.startswith("win"):
        return "windows"
    if name.startswith("linux"):
        return "linux"
    if name == "darwin":
        return "macos"
    return name


def normalize_version(value: str) -> str:
    value = str(value or "").strip()
    return value[1:] if value.lower().startswith("v") else value


def version_key(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for part in normalize_version(value).replace("-", ".").split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        parts.append(int(digits or 0))
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def compare_versions(left: str, right: str) -> int:
    a, b = version_key(left), version_key(right)
    return 1 if a > b else -1 if a < b else 0


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    download_url: str
    size: int


@dataclass(frozen=True)
class UpdateInfo:
    current_version: str
    latest_version: str
    tag_name: str
    html_url: str
    asset: ReleaseAsset

    @property
    def is_newer(self) -> bool:
        return compare_versions(self.latest_version, self.current_version) > 0


def _json_request(url: str, current_version: str, timeout: int = 20) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"ELM327-Diagnosis-Helper/{current_version}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"GitHub returned HTTP {exc.code} while checking for updates.") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach GitHub: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("GitHub returned invalid release metadata.") from exc


def _platform_tokens(platform: str | None = None) -> tuple[str, ...]:
    key = platform_key(platform)
    if key == "windows":
        return ("windows", "win64", "win")
    if key == "linux":
        return ("linux", "x86_64", "amd64")
    return (key,)


def find_release_asset(release: dict, platform: str | None = None) -> ReleaseAsset:
    tokens = _platform_tokens(platform)
    candidates: list[ReleaseAsset] = []
    for raw in release.get("assets") or []:
        name = str(raw.get("name") or "")
        lower = name.lower()
        url = str(raw.get("browser_download_url") or "")
        if not url or not lower.endswith(".zip"):
            continue
        if not any(token in lower for token in tokens):
            continue
        if APP_ASSET_TOKEN not in lower and "elm327" not in lower:
            continue
        candidates.append(ReleaseAsset(name, url, int(raw.get("size") or 0)))
    if not candidates:
        raise RuntimeError(
            f"No {platform_key(platform)} update ZIP was found in the latest GitHub release."
        )
    candidates.sort(key=lambda item: item.name.lower())
    return candidates[0]


def check_for_update(current_version: str) -> UpdateInfo:
    release = _json_request(
        f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/latest",
        current_version,
    )
    tag = str(release.get("tag_name") or "").strip()
    if not tag:
        raise RuntimeError("Latest GitHub release has no tag.")
    return UpdateInfo(
        current_version=normalize_version(current_version),
        latest_version=normalize_version(tag),
        tag_name=tag,
        html_url=str(release.get("html_url") or ""),
        asset=find_release_asset(release),
    )


def is_frozen_app() -> bool:
    return bool(getattr(sys, "frozen", False))


def runtime_dir() -> Path:
    return Path(sys.executable).resolve().parent if is_frozen_app() else Path.cwd().resolve()


def updater_names() -> tuple[str, ...]:
    if platform_key() == "windows":
        return ("OBD_ELM327_Updater.exe", "updater.exe")
    return ("OBD_ELM327_Updater", "obd-elm327-updater", "updater")


def app_names() -> tuple[str, ...]:
    if platform_key() == "windows":
        return ("OBD_ELM327_Engine_Diagnosis_Helper.exe",)
    return ("OBD_ELM327_Engine_Diagnosis_Helper",)


def find_updater() -> Path:
    directory = runtime_dir()
    for name in updater_names():
        path = directory / name
        if path.exists():
            return path
    raise RuntimeError(
        "Portable self-update requires the packaged release folder with the updater "
        "next to the main application."
    )


def portable_update_available() -> bool:
    if not is_frozen_app():
        return False
    try:
        find_updater()
        return True
    except RuntimeError:
        return False


def updates_dir() -> Path:
    path = runtime_dir() / "updates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def download_update_asset(
    info: UpdateInfo,
    progress_callback: ProgressCallback | None = None,
) -> Path:
    target = updates_dir() / info.asset.name
    partial = target.with_suffix(target.suffix + ".part")
    request = urllib.request.Request(
        info.asset.download_url,
        headers={"User-Agent": f"ELM327-Diagnosis-Helper/{info.current_version}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            total = int(response.headers.get("Content-Length") or info.asset.size or 0)
            downloaded = 0
            with partial.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback is not None:
                        progress_callback(downloaded, total)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    target.unlink(missing_ok=True)
    partial.replace(target)
    return target


def restart_executable() -> Path:
    if is_frozen_app():
        return Path(sys.executable).resolve()
    return Path(sys.argv[0]).resolve()


def start_portable_update(zip_path: Path) -> None:
    updater = find_updater()
    runner = updater
    if platform_key() == "windows":
        runner_dir = updates_dir() / "runner"
        runner_dir.mkdir(parents=True, exist_ok=True)
        runner = runner_dir / updater.name
        shutil.copy2(updater, runner)

    command = [
        str(runner),
        "--zip", str(zip_path),
        "--target", str(runtime_dir()),
        "--restart", str(restart_executable()),
        "--pid", str(os.getpid()),
        "--log", str(updates_dir() / "updater.log"),
    ]
    kwargs = {
        "cwd": str(runtime_dir()),
        "close_fds": True,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if platform_key() == "windows":
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        flags |= getattr(subprocess, "DETACHED_PROCESS", 0)
        kwargs["creationflags"] = flags
    process = subprocess.Popen(command, **kwargs)
    if process.poll() is not None:
        raise RuntimeError("Updater exited immediately. See updates/updater.log.")

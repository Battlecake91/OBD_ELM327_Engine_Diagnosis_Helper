#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ctypes
import os
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path


PRESERVE_NAMES = {"settings.json", "updates", "logs"}
LOG_PATH: Path | None = None


class UpdateError(RuntimeError):
    pass


def log(message: str) -> None:
    line = f"[Updater] {message}"
    print(line, flush=True)
    if LOG_PATH is not None:
        try:
            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with LOG_PATH.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError:
            pass


def process_exists(pid: int) -> bool:
    if os.name == "nt":
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def wait_for_process(pid: int, timeout: int = 60) -> None:
    if pid <= 0:
        return
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not process_exists(pid):
            return
        time.sleep(0.4)
    raise UpdateError(f"Application process {pid} did not exit in time.")


def safe_extract(archive_path: Path, target: Path) -> None:
    root = target.resolve()
    with zipfile.ZipFile(archive_path, "r") as archive:
        for member in archive.infolist():
            resolved = (root / member.filename).resolve()
            try:
                resolved.relative_to(root)
            except ValueError as exc:
                raise UpdateError(f"Unsafe ZIP path blocked: {member.filename}") from exc
        archive.extractall(root)


def payload_root(extract_dir: Path) -> Path:
    entries = [entry for entry in extract_dir.iterdir() if entry.name != "__MACOSX"]
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return extract_dir


def preserve(relative: Path) -> bool:
    return any(part.lower() in PRESERVE_NAMES for part in relative.parts)


def replace_payload(source: Path, target: Path) -> None:
    top_entries = {item.name.lower() for item in source.iterdir()}
    for path in sorted(target.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        relative = path.relative_to(target)
        if preserve(relative) or not relative.parts:
            continue
        if relative.parts[0].lower() not in top_entries:
            continue
        if path.is_dir():
            try:
                path.rmdir()
            except OSError:
                pass
        else:
            path.unlink(missing_ok=True)

    for item in source.rglob("*"):
        relative = item.relative_to(source)
        if preserve(relative):
            continue
        destination = target / relative
        if item.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, destination)


def restart(path: Path | None) -> None:
    if path is None or not path.exists():
        return
    kwargs = {"cwd": str(path.parent), "close_fds": True}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([str(path)], **kwargs)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Portable updater for the ELM327 diagnosis helper.")
    parser.add_argument("--zip", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--restart", default="")
    parser.add_argument("--pid", type=int, default=0)
    parser.add_argument("--log", default="")
    return parser.parse_args()


def main() -> int:
    global LOG_PATH
    args = parse_args()
    archive = Path(args.zip).resolve()
    target = Path(args.target).resolve()
    restart_path = Path(args.restart).resolve() if args.restart else None
    LOG_PATH = Path(args.log).resolve() if args.log else None
    if LOG_PATH is not None:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        LOG_PATH.write_text("", encoding="utf-8")

    try:
        if not archive.exists():
            raise UpdateError(f"Archive not found: {archive}")
        if not target.exists():
            raise UpdateError(f"Target directory not found: {target}")
        log(f"Waiting for application PID {args.pid}")
        wait_for_process(args.pid)
        with tempfile.TemporaryDirectory(prefix="elm327_update_") as tmp:
            extract = Path(tmp) / "extract"
            extract.mkdir()
            safe_extract(archive, extract)
            source = payload_root(extract)
            log(f"Replacing program files from {source}")
            replace_payload(source, target)
        log("Update finished.")
        restart(restart_path)
        return 0
    except Exception as exc:
        log(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

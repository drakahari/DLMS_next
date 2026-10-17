"""Disposable Desktop identity and origin; never reads a normal DLMS profile."""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import shutil
import uuid

from .isolation import assert_safe_leaf
from .platform_files import lock, sync_directory, writer_path

MANIFEST = "desktop-profile.json"
TRANSITION = "synthetic-epoch-transition.json"


def atomic_json(path: Path, value: dict) -> None:
    """Publish one private JSON file with fsync and no planted output leaf."""
    assert_safe_leaf(path)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if os.environ.get("DLMS_DESKTOP_TEST_FAIL_MANIFEST") == "1" and path.name == MANIFEST:
            raise OSError("Synthetic manifest publication failure")
        assert_safe_leaf(path)
        if os.name == "nt":
            from .windows_files import replace
            replace(temporary, path)
        else:
            os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def read_manifest(paths: dict[str, Path], profile_name: str) -> dict | None:
    if (paths["root"] / TRANSITION).exists():
        raise RuntimeError("Synthetic epoch transition is incomplete; evidence needs manual inspection before launch")
    path = paths["root"] / MANIFEST
    assert_safe_leaf(path)
    if not path.exists():
        storage = paths["web_storage"]
        if (storage.exists() and any(storage.iterdir())) or (paths["root"] / "recovery-evidence.json").exists():
            raise RuntimeError("Browser evidence exists without a saved Desktop origin; leave this legacy profile untouched and use a new disposable profile")
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if (set(data) != {"version", "name", "uuid", "epoch", "port"}
            or data["version"] != 1 or data["name"] != profile_name
            or not isinstance(data["port"], int) or not 1024 <= data["port"] <= 65535):
        raise ValueError("Invalid Desktop profile identity or origin; no fallback port will be used")
    uuid.UUID(data["uuid"])
    uuid.UUID(data["epoch"])
    return data


def new_manifest(name: str, port: int) -> dict:
    return {"version": 1, "name": name, "uuid": str(uuid.uuid4()),
            "epoch": str(uuid.uuid4()), "port": port}


def publish_manifest(paths: dict[str, Path], manifest: dict) -> None:
    atomic_json(paths["root"] / MANIFEST, manifest)


def synthetic_epoch_change(paths: dict[str, Path], profile_name: str) -> dict:
    """Test-only closed-profile quarantine. This is not backup/restore adoption."""
    from PySide6.QtCore import QLockFile

    instance = QLockFile(str(paths["root"] / "instance.lock"))
    instance.setStaleLockTime(0)
    if not instance.tryLock(0):
        raise RuntimeError("Close the disposable Qt window before changing its synthetic epoch")
    writer_lock_path = writer_path(paths["root"] / "backend-writer.lock")
    assert_safe_leaf(writer_lock_path)
    fd = os.open(writer_lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        try:
            lock(fd)
        except BlockingIOError as exc:
            raise RuntimeError("Disposable backend is still running; synthetic epoch was not changed") from exc
        return _synthetic_epoch_change_locked(paths, profile_name)
    finally:
        os.close(fd)
        instance.unlock()


def _synthetic_epoch_change_locked(paths: dict[str, Path], profile_name: str) -> dict:
    old = read_manifest(paths, profile_name)
    if old is None:
        raise ValueError("Synthetic epoch change requires an existing disposable profile")
    quarantine = paths["root"] / "quarantine" / old["epoch"]
    if quarantine.exists() or quarantine.is_symlink():
        raise ValueError("Existing epoch quarantine requires inspection")
    marker = paths["root"] / TRANSITION
    atomic_json(marker, {"old_epoch": old["epoch"], "purpose": "synthetic demonstration"})
    quarantine.mkdir(mode=0o700, parents=True)
    storage = paths["web_storage"]
    if storage.exists():
        storage.rename(quarantine / "web_storage")
    storage.mkdir(mode=0o700)
    evidence = paths["root"] / "recovery-evidence.json"
    if evidence.exists():
        shutil.copy2(evidence, quarantine / evidence.name)
    updated = dict(old, epoch=str(uuid.uuid4()))
    publish_manifest(paths, updated)
    marker.unlink()
    return updated

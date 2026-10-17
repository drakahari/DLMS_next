"""Intentional removal of one exact disposable Desktop profile, with tombstone.

The external tombstone is checked before profile creation. The old root is
retained outside its active location for this synthetic acceptance phase.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import stat
import sys
import time

from .isolation import AREA, NAME, PROFILES, assert_safe_leaf, profile_paths
from .maintenance import (_copy_verified, _digest, _directory_inventory, _external_lock, _file_inventory,
                          _owned_dir, _recovery_dir, MaintenanceUnresolved)
from .profile_state import atomic_json, read_manifest
from .recovery import fsync_directory


def _abort(phase: str, root: Path) -> None:
    if (os.environ.get("DLMS_DESKTOP_AUTOMATED") == "1"
            and os.environ.get("DLMS_DESKTOP_TEST_REMOVE_ABORT") == phase
            and root.resolve().is_relative_to(AREA.resolve())):
        os._exit(75)


def _tombstone_path(name: str) -> Path:
    if not NAME.fullmatch(name):
        raise ValueError("Invalid disposable profile name")
    root = AREA / "removed"
    _owned_dir(AREA)
    _owned_dir(root, create=True)
    return root / f"{name}.json"


def read_tombstone(name: str) -> dict | None:
    path = _tombstone_path(name)
    assert_safe_leaf(path)
    if not path.exists():
        return None
    if path.stat().st_size > 8192:
        raise MaintenanceUnresolved("Removal tombstone is oversized")
    try:
        value = json.loads(path.read_text())
        if (value.get("version") != 1 or value.get("name") != name
                or value.get("phase") not in {"intent", "preimage_verified", "removed"}
                or len(value.get("operation_id", "")) != 32
                or any(c not in "0123456789abcdef" for c in value["operation_id"])
                or not isinstance(value.get("profile_uuid"), str)
                or not isinstance(value.get("epoch"), str)
                or value.get("target") != str(PROFILES / name)):
            raise ValueError("tombstone fields")
        return value
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise MaintenanceUnresolved("Removal tombstone requires inspection") from exc


def _write(name: str, value: dict) -> None:
    atomic_json(_tombstone_path(name), value)


def begin_intent(name: str, operation_id: str) -> dict:
    if len(operation_id) != 32 or any(c not in "0123456789abcdef" for c in operation_id):
        raise ValueError("Invalid removal operation ID")
    paths = profile_paths(name, create=False)
    manifest = read_manifest(paths, name)
    if manifest is None:
        raise MaintenanceUnresolved("Cannot remove a profile without verified Desktop identity")
    from .maintenance import read_marker, _ensure_no_pending
    from .transition import read_transition
    if read_marker(name) or read_transition(paths):
        raise MaintenanceUnresolved("Resolve existing data transition before profile removal")
    _ensure_no_pending(paths)
    with _external_lock(name):
        old = read_tombstone(name)
        if old:
            if old["operation_id"] == operation_id:
                return old
            raise MaintenanceUnresolved("A different profile-removal operation is recorded")
        value = {"version": 1, "name": name, "operation_id": operation_id,
                 "profile_uuid": manifest["uuid"], "epoch": manifest["epoch"],
                 "target": str(paths["root"]), "phase": "intent", "preimage_sha256": None,
                 "preimage_directories": None}
        _write(name, value)
        return value


def _owner_gone(paths: dict[str, Path]) -> None:
    descriptor = paths["root"] / "instance-owner.json"
    if descriptor.exists() or descriptor.is_symlink():
        assert_safe_leaf(descriptor)
        try:
            record = json.loads(descriptor.read_text())
            pid = record["pid"]
            ticks = record["start_ticks"]
            if (record["name"] != paths["root"].name or not isinstance(pid, int)
                    or pid <= 0 or not isinstance(ticks, int)):
                raise ValueError("owner descriptor identity")
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise MaintenanceUnresolved("Owner descriptor needs inspection") from exc
        from .ownership import process_start_ticks
        try:
            running_ticks = process_start_ticks(pid)
        except FileNotFoundError:
            running_ticks = None
        except (OSError, ValueError, IndexError) as exc:
            raise MaintenanceUnresolved("Recorded owner process cannot be verified") from exc
        if running_ticks == ticks:
            raise MaintenanceUnresolved("Owning window has not released its profile")
        # Only the exact recorded process is known to be gone. The external
        # removal lock excludes another reconciliation while this is retired.
        descriptor.unlink()
        fsync_directory(descriptor.parent)
    from PySide6.QtCore import QLockFile
    lock = QLockFile(str(paths["root"] / "instance.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        if not lock.removeStaleLockFile() or not lock.tryLock(0):
            raise MaintenanceUnresolved("Profile window lock is still held")
    lock.unlock()


def reconcile(name: str) -> dict | None:
    value = read_tombstone(name)
    if value is None:
        return None
    root = PROFILES / name
    recovery = _recovery_dir(name, value["operation_id"])
    _owned_dir(recovery, create=True)
    preimage = recovery / "profile"
    removed = recovery / "removed-profile"
    with _external_lock(name):
        writer = None
        if root.exists():
            from .backend import acquire_writer_lock
            writer = acquire_writer_lock(root / "backend-writer.lock")
        try:
            return _reconcile_locked(name, value, root, recovery, preimage, removed)
        finally:
            if writer is not None:
                writer.close()


def _reconcile_locked(name: str, value: dict, root: Path, recovery: Path,
                      preimage: Path, removed: Path) -> dict:
        def matches(path: Path) -> bool:
            return (_digest(_file_inventory(path)) == value["preimage_sha256"]
                    and (value.get("preimage_directories") is None
                         or _digest(_directory_inventory(path)) == value["preimage_directories"]))
        if root.is_symlink() or removed.is_symlink() or preimage.is_symlink():
            raise MaintenanceUnresolved("Removal path is a symlink")
        if value["phase"] == "removed":
            if root.exists() or not removed.exists() or not preimage.exists():
                raise MaintenanceUnresolved("Intentional-removal state is inconsistent")
            if not matches(removed):
                raise MaintenanceUnresolved("Retained removed profile differs from its verified preimage")
            return value
        if root.exists():
            paths = profile_paths(name, create=False)
            _owner_gone(paths)
            manifest = read_manifest(paths, name)
            if manifest is None or manifest["uuid"] != value["profile_uuid"] or manifest["epoch"] != value["epoch"]:
                raise MaintenanceUnresolved("Removal identity changed")
        elif not removed.exists():
            raise MaintenanceUnresolved("Removal target vanished without a retained outcome")
        if value["phase"] == "intent":
            if preimage.exists():
                digest = _digest(_file_inventory(preimage))
                if root.exists() and (_digest(_file_inventory(root)) != digest
                                      or _directory_inventory(root) != _directory_inventory(preimage)):
                    raise MaintenanceUnresolved("Partial removal preimage differs from active root")
            elif root.exists():
                digest = _copy_verified(root, preimage)
            else:
                raise MaintenanceUnresolved("Missing preimage before removal")
            value["preimage_sha256"] = digest
            value["preimage_directories"] = _digest(_directory_inventory(preimage))
            value["phase"] = "preimage_verified"
            _write(name, value)
            _abort("preimage_verified", PROFILES / name)
        if not matches(preimage):
            raise MaintenanceUnresolved("Verified removal preimage is damaged")
        if root.exists():
            if removed.exists():
                raise MaintenanceUnresolved("Active and removed profile roots both exist")
            if root.stat().st_dev != recovery.stat().st_dev:
                raise MaintenanceUnresolved("Removal requires same-filesystem atomic rename")
            if not matches(root):
                raise MaintenanceUnresolved("Active profile changed since removal preimage")
            os.rename(root, removed)
            fsync_directory(root.parent)
            fsync_directory(removed.parent)
            _abort("renamed", PROFILES / name)
        if not matches(removed):
            raise MaintenanceUnresolved("Removed profile verification failed")
        value["phase"] = "removed"
        _write(name, value)
        return value


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Intentional removal of one synthetic Desktop profile")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--operation-id")
    parser.add_argument("--reconcile", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.reconcile:
            result = reconcile(args.profile)
        else:
            secret = os.environ.get("DLMS_DESKTOP_REMOVE_OWNER_SECRET")
            parent_text = os.environ.get("DLMS_DESKTOP_REMOVE_PARENT_PID")
            pipe_text = os.environ.get("DLMS_DESKTOP_REMOVE_PARENT_PIPE")
            if not secret or not parent_text or not pipe_text or os.getppid() != int(parent_text):
                raise MaintenanceUnresolved("Removal must begin in the exact owning Qt window")
            from .ownership import process_start_ticks
            root = PROFILES / args.profile
            descriptor = json.loads((root / "instance-owner.json").read_text())
            if (descriptor.get("secret") != secret or descriptor.get("pid") != os.getppid()
                    or descriptor.get("start_ticks") != process_start_ticks(os.getppid())
                    or descriptor.get("name") != args.profile):
                raise MaintenanceUnresolved("Removal ownership descriptor differs")
            result = begin_intent(args.profile, args.operation_id or secrets.token_hex(16))
            _abort("intent", PROFILES / args.profile)
            progress = AREA / "removed" / f"{args.profile}.ready.json"
            atomic_json(progress, {"operation_id": result["operation_id"], "parent_pid": os.getppid()})
            # The parent closes its exact window and pipe, releasing the in-root
            # instance lock. The external intent prevents new profile creation.
            os.read(int(pipe_text), 1)
            os.close(int(pipe_text))
            deadline = time.monotonic() + 10
            while True:
                try:
                    result = reconcile(args.profile)
                    break
                except MaintenanceUnresolved as exc:
                    if ("Owning window has not released" not in str(exc)
                            and "window lock is still held" not in str(exc)) or time.monotonic() >= deadline:
                        raise
                    time.sleep(0.05)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"DLMS Desktop removal stopped: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Manual, exact-owned synthetic pilot code replacement; never changes profile data.

This module is deliberately not an automatic updater. The caller must supply a
reviewed archive/payload and explicitly run each operation. No host operation
is performed by importing it.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
from typing import Callable
import uuid

from .install_pilot import (PROFILE, VERSION, MARKER_NAME, _assert_home, _assert_parent_chain,
                            _pilot_marker, inventory, paths, sha256)

NEW_VERSION = "pilot-02"
RECEIPT = "pilot-replacement.json"
STAGE = "pilot-stage.json"
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_bytes(path: Path, data: bytes, mode: int = 0o600) -> None:
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        _fsync_dir(path.parent)
    finally:
        if temp.exists():
            temp.unlink()


def _json(value: dict) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def _pointer(path: Path, target: str) -> None:
    if target not in {f"versions/{VERSION}", f"versions/{NEW_VERSION}"}:
        raise ValueError("Unknown pilot pointer target")
    temp = path.with_name(f".current.{uuid.uuid4().hex}.tmp")
    os.symlink(target, temp)
    try:
        os.replace(temp, path)
        _fsync_dir(path.parent)
    finally:
        if temp.is_symlink():
            temp.unlink()


def _guarded_launcher(p: dict[str, Path]) -> bytes:
    # This guard remains pilot-02 even when the active pointer is rolled back
    # to v1, whose executable has no complete-state pointer check.
    guard = p["opt"] / "versions" / NEW_VERSION / "DLMS-Desktop" / "DLMS-Desktop"
    active = p["current"] / "DLMS-Desktop" / "DLMS-Desktop"
    for leaf in (guard, active, p["data"]):
        if re.search(r"[^A-Za-z0-9_./-]", str(leaf)):
            raise ValueError("Pilot launcher path is outside the reviewed shell layout")
    return ("#!/bin/sh\n"
            "# Manual synthetic pilot code gate; preserve graphical XDG_RUNTIME_DIR.\n"
            f"exec '{guard}' --pilot-launch --profile {PROFILE} --installed-pilot-root '{p['data']}'\n").encode()


def _regular_owned(path: Path, *, maximum: int | None = None) -> None:
    if path.is_symlink() or not path.is_file() or path.stat().st_uid != os.getuid():
        raise ValueError(f"Pilot file is missing, linked or not owned: {path}")
    if maximum is not None and path.stat().st_size > maximum:
        raise ValueError(f"Pilot file exceeds its bound: {path}")


def verify(home: Path, *, allow_receipt: bool = False,
           allow_updating: bool = False) -> tuple[dict, bytes]:
    """Verify the complete owned layout, not just the manifest's declaration."""
    _assert_home(home)
    p = paths(home)
    for key in ("opt", "manifest", "launcher", "entry", "data", "marker"):
        _assert_parent_chain(p[key], home)
    if p["opt"].is_symlink() or not p["opt"].is_dir() or p["opt"].stat().st_uid != os.getuid():
        raise ValueError("Pilot application root is not an owned directory")
    for version_path in (p["opt"] / "versions", p["opt"] / "versions" / VERSION):
        if (version_path.is_symlink() or not version_path.is_dir()
                or version_path.stat().st_uid != os.getuid()):
            raise ValueError("Pilot version path is not a plain owned directory")
    receipt = p["opt"] / RECEIPT
    if (receipt.exists() or receipt.is_symlink()) and not allow_receipt:
        raise ValueError("Pilot replacement receipt needs reconciliation")
    _regular_owned(p["manifest"], maximum=16384)
    raw = p["manifest"].read_bytes()
    manifest = json.loads(raw)
    if "manifest_format" in manifest:
        raise ValueError("Use manual_replace for versioned manifests; legacy tool refused")
    if (manifest.get("version") not in {1, 2}
            or manifest.get("phase") not in ({"complete", "updating"} if allow_updating else {"complete"})
            or manifest.get("home") != str(home)
            or not re.fullmatch(r"[0-9a-f]{32}", manifest.get("install_id", ""))
            or manifest.get("owned_paths") != {key: str(value) for key, value in p.items()}):
        raise ValueError("Pilot manifest identity or phase needs inspection")
    target = manifest.get("current_target")
    if target not in {f"versions/{VERSION}", f"versions/{NEW_VERSION}"}:
        raise ValueError("Pilot manifest has an unknown current target")
    if not p["current"].is_symlink() or os.readlink(p["current"]) != target:
        raise ValueError("Pilot pointer and manifest disagree")
    if p["data"].is_symlink() or not p["data"].is_dir() or p["data"].stat().st_uid != os.getuid():
        raise ValueError("Pilot data root is not an owned directory")
    _regular_owned(p["marker"], maximum=512)
    if json.loads(p["marker"].read_text()) != _pilot_marker(p["data"], manifest["install_id"]):
        raise ValueError("Pilot profile marker changed")
    required_files = {"launcher", "entry", "marker", *(f"icon_{size}" for size in (16, 24, 32, 48, 64))}
    if set(manifest.get("file_sha256", {})) != required_files:
        raise ValueError("Pilot manifest owned-file inventory is incomplete")
    for key, expected in manifest["file_sha256"].items():
        _regular_owned(p[key])
        if sha256(p[key]) != expected:
            raise ValueError(f"Pilot-owned file changed: {key}")
    active = target.rsplit("/", 1)[1]
    if manifest["version"] == 1:
        if active != VERSION:
            raise ValueError("v1 pilot cannot select a second version")
        recorded = {VERSION: manifest.get("payload_inventory_sha256")}
    else:
        recorded = manifest.get("version_inventories")
        if not isinstance(recorded, dict) or set(recorded) != {VERSION, NEW_VERSION}:
            raise ValueError("v2 pilot version inventory is incomplete")
        if recorded.get(active) != manifest.get("payload_inventory_sha256"):
            raise ValueError("Active pilot inventory does not match the manifest")
    for version, expected in recorded.items():
        if not isinstance(expected, str) or not _SHA.fullmatch(expected):
            raise ValueError("Pilot inventory digest is malformed")
        leaf = p["opt"] / "versions" / version / "DLMS-Desktop"
        parent = leaf.parent
        if parent.is_symlink() or not parent.is_dir() or parent.stat().st_uid != os.getuid():
            raise ValueError(f"Pilot version path is not a plain owned directory: {version}")
        if leaf.is_symlink() or inventory(leaf) != expected:
            raise ValueError(f"Pilot payload changed: {version}")
    return manifest, raw


def _exact_processes(home: Path, *, alternate_versions: Path | None = None) -> list[int]:
    """Only exact executable or launcher path identities; never a name match."""
    p = paths(home)
    # Derive identities only from plain owned directories inside this installation.
    versions = p["opt"] / "versions"
    if alternate_versions is not None:
        # Only a management-owned removed installation, never a manifest path.
        from desktop.management_state import state_root
        relative=alternate_versions.relative_to(state_root(home)/'operations')
        if len(relative.parts)!=3 or not _SHA.fullmatch(relative.parts[0]+'0'*32) or relative.parts[1:]!=('removed-opt','versions'):
            raise ValueError('Unknown removed-version evidence path')
        from desktop.install_manifest import owned_chain
        owned_chain(alternate_versions,home)
        if not versions.exists() and not versions.is_symlink():versions=alternate_versions
    if versions.is_symlink() or not versions.is_dir():
        raise ValueError("Pilot version path is unsafe")
    executables = set()
    payload_roots = []
    for leaf in versions.iterdir():
        if leaf.is_symlink() or not leaf.is_dir() or leaf.stat().st_uid != os.getuid():
            raise ValueError("Pilot version path is unsafe")
        payload_roots.append(leaf / "DLMS-Desktop")
        executables.add(leaf / "DLMS-Desktop/DLMS-Desktop")
    executable_args = {str(path).encode() for path in executables}
    launcher = str(p["launcher"]).encode()
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            exe = (entry / "exe").resolve(strict=True)
            cmdline = (entry / "cmdline").read_bytes().split(b"\0")
        except (OSError, PermissionError):
            continue
        if (exe in executables or any(exe.is_relative_to(root) for root in payload_roots)
                or launcher in cmdline or executable_args.intersection(cmdline)):
            found.append(int(entry.name))
    return sorted(found)


def _owner_paths(home: Path) -> tuple[Path, Path]:
    root = paths(home)["data"]
    return (root / "shell" / PROFILE / "instance-owner.json",
            root / "profiles" / PROFILE / "instance-owner.json")


def _data_fingerprint(home: Path) -> str:
    """Conservative data identity, omitting only transient ownership leaves."""
    root = paths(home)["data"]
    omitted = {"shell/pilot01/instance.lock", "profiles/pilot01/instance.lock",
               "shell/pilot01/instance-owner.json", "profiles/pilot01/instance-owner.json"}
    entries = []
    for leaf in sorted(root.rglob("*")):
        relative = leaf.relative_to(root).as_posix()
        if relative in omitted:
            continue
        if leaf.is_symlink():
            raise ValueError("Pilot data contains a symlink; rollback identity is ambiguous")
        if leaf.is_file():
            entries.append((relative, leaf.stat().st_size, sha256(leaf)))
        elif not leaf.is_dir():
            raise ValueError("Pilot data contains a special file")
    return hashlib.sha256(json.dumps(entries, separators=(",", ":")).encode()).hexdigest()


def _ensure_no_pending_data(home: Path) -> None:
    """Refuse code switching while a Desktop/source transaction needs recovery."""
    root = paths(home)["data"]
    # The extracted frozen manager has no window launch environment. Establish
    # its read-only inspection scope from the owned installation marker, never
    # from inherited environment variables or an arbitrary manifest path.
    from desktop.install_manifest import owned_chain
    owned_chain(root, home)
    marker = root / MARKER_NAME
    _regular_owned(marker, maximum=512)
    identity = json.loads(marker.read_bytes())
    from .install_pilot import _pilot_marker
    if (not re.fullmatch('[0-9a-f]{32}',str(identity.get('install_id','')))
            or identity != _pilot_marker(root, identity.get('install_id'))):
        raise ValueError('Pending-work inspection root identity differs')
    if getattr(sys, 'frozen', False):
        os.environ['DLMS_DESKTOP_DATA_ROOT'] = str(root)
        os.environ['DLMS_DESKTOP_ROOT_KIND'] = 'installed-pilot'
    from desktop.import_operations import unresolved_count as pending_imports
    from desktop.pack_operations import unresolved_count as pending_packs
    from desktop.profile_state import read_manifest

    profile = root / "profiles" / PROFILE
    for leaf in (root / "maintenance" / PROFILE / "active.json",
                 root / "removed" / f"{PROFILE}.json",
                 profile / "desktop-data-transition.json"):
        if leaf.exists() or leaf.is_symlink():
            raise ValueError(f"Pilot data transition needs reconciliation: {leaf.name}")
    for folder in (profile / "durable-actions", profile / "pending-requests",
                   profile / "backend/.restore_operations", profile / "backend/.quiz_publications"):
        if folder.is_symlink() or (folder.exists() and not folder.is_dir()):
            raise ValueError("Pilot action/publication evidence path is unsafe")
        if folder.exists() and any(folder.iterdir()):
            raise ValueError("Pilot accepted action or publication needs reconciliation")
    identity = read_manifest({"root": profile, "web_storage": profile / "web/storage"}, PROFILE)
    if identity and (pending_imports(profile, identity["epoch"])
                     or pending_packs(profile, identity["epoch"])):
        raise ValueError("Pilot portable import or pack installation needs reconciliation")
    if identity is None and any((profile / name).exists() for name in
                                ("portable-import-operations", "pack-install-receipts")):
        raise ValueError("Pilot operation records lack a profile identity")


def _lock_paths(home: Path) -> tuple[Path, Path, Path]:
    root = paths(home)["data"]
    return (root / "shell" / PROFILE / "instance.lock",
            root / "profiles" / PROFILE / "instance.lock",
            root / "profiles" / PROFILE / "backend-writer.lock")


@contextmanager
def _exclusive_window(home: Path, *, allow_descriptors: bool = False, alternate_versions: Path | None = None):
    from PySide6.QtCore import QLockFile

    shell, profile, writer = _lock_paths(home)
    for leaf in (shell, profile, writer):
        if leaf.parent.is_symlink() or not leaf.parent.is_dir() or leaf.parent.stat().st_uid != os.getuid():
            raise ValueError("Pilot lock parent is missing or unsafe")
    # QLockFile may delete a stale lock on acquisition. Never let it do so here.
    for leaf in (shell, profile):
        if leaf.exists() or leaf.is_symlink():
            raise ValueError(f"Pilot instance lock evidence needs inspection: {leaf}")
    if not allow_descriptors and any(p.exists() or p.is_symlink() for p in _owner_paths(home)):
        raise ValueError("Pilot owner descriptor needs exact stale-owner review")
    locks = []
    writer_fd = None
    try:
        for leaf in (shell, profile):
            lock = QLockFile(str(leaf))
            lock.setStaleLockTime(0)
            if not lock.tryLock(0):
                raise ValueError("Pilot window lock is held")
            locks.append(lock)
        _regular_owned(writer)
        writer_fd = os.open(writer, os.O_RDWR | os.O_NOFOLLOW)
        try:
            fcntl.flock(writer_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("Pilot backend writer lock is held") from exc
        running=(_exact_processes(home) if alternate_versions is None
                 else _exact_processes(home,alternate_versions=alternate_versions))
        if running:
            raise ValueError("An exact pilot executable or launcher is still running")
        yield
    finally:
        if writer_fd is not None:
            os.close(writer_fd)
        for lock in reversed(locks):
            lock.unlock()


def stage(home: Path, archive: Path, archive_digest: str, payload: Path,
          payload_digest: str) -> Path:
    """Stage reviewed pilot-02 without changing the active version or profile."""
    manifest, _ = verify(home)
    if manifest["version"] != 1:
        raise ValueError("Stage requires the original complete pilot-01 installation")
    if (not _SHA.fullmatch(archive_digest) or not _SHA.fullmatch(payload_digest)
            or sha256(archive) != archive_digest or inventory(payload) != payload_digest):
        raise ValueError("Reviewed replacement artifact differs")
    if not (payload / "DLMS-Desktop").is_file():
        raise ValueError("Replacement executable is missing")
    p = paths(home)
    target = p["opt"] / "versions" / NEW_VERSION
    temporary = target.with_name(f".{NEW_VERSION}-staging")
    for leaf in (target, temporary, p["opt"] / RECEIPT, p["opt"] / STAGE):
        if leaf.exists() or leaf.is_symlink():
            raise FileExistsError(f"Replacement staging collision: {leaf}")
    shutil.copytree(payload, temporary / "DLMS-Desktop", symlinks=True)
    _fsync_dir(temporary.parent)
    if inventory(temporary / "DLMS-Desktop") != payload_digest:
        raise ValueError("Staged replacement differs from reviewed payload")
    os.rename(temporary, target)
    _fsync_dir(target.parent)
    stage_record = {"kind": "dlms-desktop-pilot-staged-payload", "version": 1,
                    "install_id": manifest["install_id"], "target": f"versions/{NEW_VERSION}",
                    "archive_sha256": archive_digest, "payload_inventory_sha256": payload_digest}
    stage_path = p["opt"] / STAGE
    fd = os.open(stage_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(_json(stage_record))
        stream.flush()
        os.fsync(stream.fileno())
    _fsync_dir(stage_path.parent)
    return target


def _archive_receipt(path: Path, receipt: dict) -> Path:
    evidence = path.with_name(f"pilot-replacement-resolved-{receipt['operation_id']}.json")
    if evidence.exists() or evidence.is_symlink():
        raise FileExistsError("Resolved replacement evidence already exists")
    os.rename(path, evidence)
    _fsync_dir(path.parent)
    return evidence


def _transition(home: Path, target_version: str, *, archive_digest: str | None = None,
                fail_at: str | None = None,
                pause_at_updating: Callable[[], None] | None = None) -> dict:
    with _exclusive_window(home):
        _ensure_no_pending_data(home)
        current, raw = verify(home)
        old_version = current["current_target"].rsplit("/", 1)[1]
        if old_version == target_version:
            raise ValueError("Requested pilot version is already active")
        if target_version not in {VERSION, NEW_VERSION}:
            raise ValueError("Unknown replacement target")
        p = paths(home)
        if target_version == NEW_VERSION:
            if current["version"] != 1 or not archive_digest or not _SHA.fullmatch(archive_digest):
                raise ValueError("Activation requires the reviewed v1 baseline and archive digest")
            stage_record_path = p["opt"] / STAGE
            _regular_owned(stage_record_path, maximum=4096)
            stage_record = json.loads(stage_record_path.read_text())
            target_digest = inventory(p["opt"] / "versions" / NEW_VERSION / "DLMS-Desktop")
            if stage_record != {"kind": "dlms-desktop-pilot-staged-payload", "version": 1,
                                "install_id": current["install_id"],
                                "target": f"versions/{NEW_VERSION}",
                                "archive_sha256": archive_digest,
                                "payload_inventory_sha256": target_digest}:
                raise ValueError("Staged payload differs from the reviewed archive binding")
            recorded = {VERSION: current["payload_inventory_sha256"], NEW_VERSION: target_digest}
            data_digest = _data_fingerprint(home)
        else:
            if current["version"] != 2:
                raise ValueError("Rollback requires a complete v2 manifest")
            recorded = current["version_inventories"]
            data_digest = _data_fingerprint(home)
            if data_digest != current.get("activation_data_sha256"):
                raise ValueError("Pilot data changed after activation; code rollback needs compatibility review")
            archive_digest = current["archive_sha256"]
        if inventory(p["opt"] / "versions" / target_version / "DLMS-Desktop") != recorded[target_version]:
            raise ValueError("Target pilot payload changed")
        operation_id = uuid.uuid4().hex
        target = f"versions/{target_version}"
        receipt = {"kind": "dlms-desktop-pilot-code-transition", "version": 1,
                   "operation_id": operation_id, "install_id": current["install_id"],
                   "old_manifest_b64": base64.b64encode(raw).decode(),
                   "old_manifest_sha256": hashlib.sha256(raw).hexdigest(),
                   "old_target": current["current_target"], "new_target": target,
                   "version_inventories": recorded, "archive_sha256": archive_digest,
                   "activation_data_sha256": data_digest}
        if target_version == NEW_VERSION:
            receipt["old_launcher_b64"] = base64.b64encode(p["launcher"].read_bytes()).decode()
            receipt["new_launcher_sha256"] = hashlib.sha256(_guarded_launcher(p)).hexdigest()
        receipt_path = p["opt"] / RECEIPT
        fd = os.open(receipt_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(_json(receipt))
            stream.flush()
            os.fsync(stream.fileno())
        _fsync_dir(receipt_path.parent)
        if fail_at == "receipt":
            raise RuntimeError("Synthetic interruption after replacement receipt")
        updating = dict(current, phase="updating", replacement_operation_id=operation_id)
        _atomic_bytes(p["manifest"], _json(updating))
        if fail_at == "updating":
            raise RuntimeError("Synthetic interruption after blocking manifest")
        if pause_at_updating is not None:
            pause_at_updating()  # Fixture-only callback; not exposed by the CLI.
        if _exact_processes(home):
            raise ValueError("An exact pilot process entered before replacement phase; reconcile before retry")
        if target_version == NEW_VERSION:
            _atomic_bytes(p["launcher"], _guarded_launcher(p), mode=0o755)
            if fail_at == "launcher":
                raise RuntimeError("Synthetic interruption after guarded launcher publication")
        _pointer(p["current"], target)
        if fail_at == "pointer":
            raise RuntimeError("Synthetic interruption after pointer switch")
        complete = dict(current, version=2, phase="complete", current_target=target,
                        payload_inventory_sha256=recorded[target_version],
                        version_inventories=recorded, archive_sha256=archive_digest,
                        activation_data_sha256=data_digest)
        if target_version == NEW_VERSION:
            complete["file_sha256"] = {**current["file_sha256"],
                                       "launcher": sha256(p["launcher"])}
        complete.pop("replacement_operation_id", None)
        _atomic_bytes(p["manifest"], _json(complete))
        if fail_at == "commit":
            raise RuntimeError("Synthetic interruption after complete manifest")
        _archive_receipt(receipt_path, receipt)
        verify(home)
        return complete


def activate(home: Path, archive_digest: str, *, fail_at: str | None = None,
             pause_at_updating: Callable[[], None] | None = None) -> dict:
    return _transition(home, NEW_VERSION, archive_digest=archive_digest, fail_at=fail_at,
                       pause_at_updating=pause_at_updating)


def rollback(home: Path, *, fail_at: str | None = None) -> dict:
    return _transition(home, VERSION, fail_at=fail_at)


def reconcile(home: Path) -> str:
    """Resolve only states conclusively bound by the durable receipt."""
    _assert_home(home)
    p = paths(home)
    for leaf in (p["opt"], p["opt"] / "versions",
                 p["opt"] / "versions" / VERSION,
                 p["opt"] / "versions" / NEW_VERSION):
        _assert_parent_chain(leaf, home)
        if leaf.is_symlink() or not leaf.is_dir() or leaf.stat().st_uid != os.getuid():
            raise ValueError("Pilot replacement version path is unsafe")
    with _exclusive_window(home):
        path = p["opt"] / RECEIPT
        _regular_owned(path, maximum=32768)
        receipt = json.loads(path.read_text())
        if (receipt.get("kind") != "dlms-desktop-pilot-code-transition"
                or receipt.get("version") != 1
                or not re.fullmatch(r"[0-9a-f]{32}", receipt.get("operation_id", ""))):
            raise ValueError("Replacement receipt is malformed; state unresolved")
        old = base64.b64decode(receipt["old_manifest_b64"], validate=True)
        if hashlib.sha256(old).hexdigest() != receipt["old_manifest_sha256"]:
            raise ValueError("Replacement receipt's old manifest changed")
        old_manifest = json.loads(old)
        if (old_manifest.get("install_id") != receipt["install_id"]
                or old_manifest.get("phase") != "complete"
                or old_manifest.get("current_target") != receipt.get("old_target")
                or receipt.get("new_target") not in {f"versions/{VERSION}", f"versions/{NEW_VERSION}"}
                or receipt.get("old_target") == receipt.get("new_target")
                or not isinstance(receipt.get("version_inventories"), dict)
                or set(receipt["version_inventories"]) != {VERSION, NEW_VERSION}):
            raise ValueError("Replacement receipt install identity differs")
        if (old_manifest.get("payload_inventory_sha256")
                != receipt["version_inventories"][receipt["old_target"].rsplit("/", 1)[1]]
                or (old_manifest["version"] == 2
                    and old_manifest.get("version_inventories") != receipt["version_inventories"])):
            raise ValueError("Replacement receipt inventory lineage differs")
        for version, expected in receipt["version_inventories"].items():
            if not isinstance(expected, str) or not _SHA.fullmatch(expected):
                raise ValueError("Replacement receipt inventory digest is malformed")
            if inventory(p["opt"] / "versions" / version / "DLMS-Desktop") != expected:
                raise ValueError("Replacement payload differs from receipt")
        _regular_owned(p["manifest"], maximum=16384)
        current_raw = p["manifest"].read_bytes()
        current = json.loads(current_raw)
        if current.get("install_id") != receipt["install_id"]:
            raise ValueError("Current pilot installation identity differs")
        pointer = os.readlink(p["current"]) if p["current"].is_symlink() else None
        old_target, new_target = receipt["old_target"], receipt["new_target"]
        if pointer not in {old_target, new_target}:
            raise ValueError("Replacement pointer is unknown; state unresolved")
        if (current.get("phase") == "complete" and current.get("current_target") == new_target
                and pointer == new_target and current.get("version") == 2):
            verify(home, allow_receipt=True)
            if current.get("version_inventories") != receipt["version_inventories"]:
                raise ValueError("Committed replacement inventory differs")
            _archive_receipt(path, receipt)
            return "committed"
        if current_raw != old:
            if (current.get("phase") != "updating"
                    or current.get("replacement_operation_id") != receipt["operation_id"]
                    or current.get("current_target") != old_target):
                raise ValueError("Replacement manifest is ambiguous; state unresolved")
        old_launcher = None
        if "old_launcher_b64" in receipt:
            old_launcher = base64.b64decode(receipt["old_launcher_b64"], validate=True)
            if hashlib.sha256(old_launcher).hexdigest() != old_manifest["file_sha256"]["launcher"]:
                raise ValueError("Old launcher evidence differs from manifest")
            expected_new = receipt["new_launcher_sha256"]
            actual_launcher = sha256(p["launcher"])
            if actual_launcher not in {old_manifest["file_sha256"]["launcher"], expected_new}:
                raise ValueError("Launcher is neither old nor reviewed new version")
        if pointer == new_target:
            _pointer(p["current"], old_target)
        if old_launcher is not None:
            if actual_launcher != old_manifest["file_sha256"]["launcher"]:
                _atomic_bytes(p["launcher"], old_launcher, mode=0o755)
        _atomic_bytes(p["manifest"], old)
        verify(home, allow_receipt=True)
        _archive_receipt(path, receipt)
        return "rolled_back"


def retire_stale_descriptors(home: Path, evidence: Path) -> dict[str, str]:
    """Retire exact dead-owner descriptors only into a fresh private evidence dir."""
    _assert_home(home)
    verify(home)
    p = paths(home)
    if (not evidence.is_absolute() or evidence.exists() or evidence.is_symlink()
            or evidence.is_relative_to(p["opt"]) or evidence.is_relative_to(p["data"])):
        raise ValueError("Stale-owner evidence must be a fresh directory outside the pilot")
    _assert_parent_chain(evidence, home)
    owners = _owner_paths(home)
    lock_leaves = _lock_paths(home)[:2]
    if any(leaf.exists() or leaf.is_symlink() for leaf in lock_leaves):
        raise ValueError("Existing Qt lock evidence needs manual inspection")
    originals = {}
    for owner in owners:
        if owner.exists() or owner.is_symlink():
            _regular_owned(owner, maximum=4096)
            if owner.stat().st_mode & 0o077:
                raise ValueError("Pilot owner descriptor is not private")
            raw = owner.read_bytes()
            descriptor = json.loads(raw)
            pid = descriptor.get("pid")
            if (descriptor.get("name") != PROFILE or not isinstance(pid, int) or pid <= 0
                    or not isinstance(descriptor.get("start_ticks"), int)):
                raise ValueError("Pilot owner descriptor is malformed")
            if Path(f"/proc/{pid}").exists():
                raise ValueError("Owner PID exists or was reused; do not retire descriptor")
            originals[owner] = raw
    if not originals:
        raise ValueError("No stale pilot owner descriptor was found")
    with _exclusive_window(home, allow_descriptors=True):
        if any(owner.read_bytes() != raw for owner, raw in originals.items()):
            raise ValueError("Owner descriptor changed during stale review")
        if _exact_processes(home):
            raise ValueError("Pilot process appeared during stale-owner review")
        evidence.mkdir(mode=0o700)
        _fsync_dir(evidence.parent)
        digests = {}
        for owner, raw in originals.items():
            key = "shell" if "shell" in owner.parts else "profile"
            copy = evidence / f"{key}.original.json"
            fd = os.open(copy, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            digests[key] = hashlib.sha256(raw).hexdigest()
        _fsync_dir(evidence)
        if any(owner.read_bytes() != raw for owner, raw in originals.items()):
            raise ValueError("Owner descriptor changed before retirement")
        for owner in originals:
            owner.unlink()
            _fsync_dir(owner.parent)
        return digests


def main() -> None:
    parser = argparse.ArgumentParser(description="Manual exact-owned Fedora synthetic pilot replacement")
    parser.add_argument("operation", choices=("verify", "stage", "activate", "reconcile", "rollback", "retire-stale"))
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--archive-sha256")
    parser.add_argument("--payload", type=Path)
    parser.add_argument("--payload-inventory-sha256")
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    if args.operation == "verify":
        result = verify(args.home)[0]
    elif args.operation == "stage":
        if not all((args.archive, args.archive_sha256, args.payload, args.payload_inventory_sha256)):
            parser.error("stage requires reviewed archive, payload and both digests")
        result = {"staged": str(stage(args.home, args.archive, args.archive_sha256,
                                      args.payload, args.payload_inventory_sha256))}
    elif args.operation == "activate":
        if not args.archive_sha256:
            parser.error("activate requires the reviewed archive SHA-256")
        result = activate(args.home, args.archive_sha256)
    elif args.operation == "reconcile":
        result = {"outcome": reconcile(args.home)}
    elif args.operation == "rollback":
        result = rollback(args.home)
    else:
        if not args.evidence:
            parser.error("retire-stale requires a fresh private evidence directory")
        result = {"retained_descriptor_sha256": retire_stale_descriptors(args.home, args.evidence)}
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()

"""Offline, journaled maintenance for a closed synthetic Desktop backend.

The worker owns the writer lock. A complete, verified private preimage is the
rollback authority; a portable safety ZIP is retained for the user where the
captured web operation promises one. No narrow operation edits a portable ZIP.
"""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import stat
import sys
import uuid

from .backend import acquire_writer_lock
from .isolation import AREA, NAME, PROJECT, assert_safe_leaf, isolated_environment, profile_paths
from .frozen_runtime import source_environment, source_import_path
from .profile_state import atomic_json, read_manifest
from .recovery import fsync_directory
from .platform_files import owned, lock

SCOPES = {
    "exam": "Clear Exam results",
    "study": "Delete Study history",
    "learning": "Reset Learning Intelligence",
    "quiz": "Reset Quiz Library and results",
    "source": "Clear removable source material",
    "settings": "Restore default settings",
    "fresh": "Fresh-state reset",
}
SCOPE_EFFECTS = {
    "exam": "Removes saved Exam attempts and missed-question results. Study history, quizzes and settings remain.",
    "study": "Removes Study sessions, responses and Study learning evidence. Exam attempts, quizzes and settings remain.",
    "learning": "Resets learning estimates and schedules while keeping factual Study and Exam history.",
    "quiz": "Removes quiz records, generated quiz pages and results. Study Packs, certifications and settings remain.",
    "source": "Removes removable source packs, imports and drafts. Published quiz dependencies are retained.",
    "settings": "Restores appearance, navigation and other application defaults. Quizzes and saved history remain.",
    "fresh": "Creates an empty active dataset while retaining existing backup ZIPs. Browser recovery evidence is quarantined.",
}
PHASES = {"prepared", "mutation_started", "committed", "browser_check_pending",
          "epoch_publication_pending", "browser_done", "rolled_back"}


class MaintenanceUnresolved(RuntimeError):
    """A live profile stays closed until this journal is reconciled."""


def _owned_dir(path: Path, *, create: bool = False) -> None:
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise MaintenanceUnresolved(f"Unsafe maintenance directory: {path}")
    if create:
        path.mkdir(mode=0o700, exist_ok=True)
        fsync_directory(path.parent)
    if path.exists() and not owned(path):
        raise MaintenanceUnresolved(f"Maintenance directory is not private and owned: {path}")


def _external(name: str) -> tuple[Path, Path]:
    if not NAME.fullmatch(name):
        raise ValueError("Invalid disposable profile name")
    root = AREA / "maintenance"
    _owned_dir(AREA)
    _owned_dir(root, create=True)
    target = root / name
    _owned_dir(target, create=True)
    return target / "active.json", target / "lock"


@contextmanager
def _external_lock(name: str):
    _, path = _external(name)
    assert_safe_leaf(path)
    fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not owned(path):
            raise MaintenanceUnresolved("Maintenance lock is not a private owned file")
        lock(fd)
        yield
    finally:
        os.close(fd)


def read_marker(name: str) -> dict | None:
    path, _ = _external(name)
    assert_safe_leaf(path)
    if not path.exists():
        return None
    if path.stat().st_size > 16384:
        raise MaintenanceUnresolved("Maintenance journal is oversized")
    try:
        value = json.loads(path.read_text())
        if (value.get("version") != 1 or value.get("name") != name
                or value.get("scope") not in SCOPES or value.get("phase") not in PHASES
                or len(value.get("operation_id", "")) != 32
                or any(c not in "0123456789abcdef" for c in value["operation_id"])
                or len(value.get("preimage_sha256", "")) != 64
                or not isinstance(value.get("profile_uuid"), str)
                or not isinstance(value.get("epoch"), str)
                or (value.get("new_epoch") is not None and not isinstance(value["new_epoch"], str))):
            raise ValueError("journal fields")
        if value.get("new_epoch") is not None:
            uuid.UUID(value["new_epoch"])
        return value
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise MaintenanceUnresolved("Maintenance journal needs inspection") from exc


def _write(name: str, value: dict) -> None:
    path, _ = _external(name)
    atomic_json(path, value)


def _file_inventory(root: Path) -> dict[str, str]:
    """Reject links/special files and hash every regular file in a closed root."""
    _owned_dir(root)
    found = {}
    for base, dirs, files in os.walk(root, followlinks=False):
        parent = Path(base)
        _owned_dir(parent)
        for entry in sorted(dirs + files):
            path = parent / entry
            info = path.lstat()
            if not owned(path):
                raise MaintenanceUnresolved(f"Unsafe ownership or permissions: {path}")
            if stat.S_ISDIR(info.st_mode):
                if entry in files:
                    raise MaintenanceUnresolved(f"Directory changed during inventory: {path}")
            elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                if entry in dirs:
                    raise MaintenanceUnresolved(f"File changed during inventory: {path}")
                digest = hashlib.sha256()
                with path.open("rb") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(block)
                if path.lstat().st_size != info.st_size:
                    raise MaintenanceUnresolved(f"File changed during inventory: {path}")
                found[str(path.relative_to(root))] = f"{info.st_size}:{digest.hexdigest()}"
            else:
                raise MaintenanceUnresolved(f"Link or special file in maintenance root: {path}")
    return found


def _directory_inventory(root: Path) -> dict[str, int]:
    """Include empty directories and their private modes in recovery proof."""
    result = {}
    for base, dirs, _ in os.walk(root, followlinks=False):
        path = Path(base)
        _owned_dir(path)
        result[str(path.relative_to(root))] = stat.S_IMODE(path.stat().st_mode)
        for entry in dirs:
            if (path / entry).is_symlink():
                raise MaintenanceUnresolved("A recovery directory is a symlink")
    return result


def _digest(inventory: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _copy_verified(source: Path, target: Path) -> str:
    before = _file_inventory(source)
    directories = _directory_inventory(source)
    if target.exists() or target.is_symlink():
        raise MaintenanceUnresolved(f"Recovery destination already exists: {target}")
    _owned_dir(target.parent)
    if source.stat().st_dev != target.parent.stat().st_dev:
        raise MaintenanceUnresolved("Recovery copy requires the same filesystem")
    shutil.copytree(source, target, symlinks=True)
    for base, dirs, files in os.walk(target):
        for leaf in files:
            # Windows FlushFileBuffers requires a writable handle. The copy is
            # task-owned and bytes remain unchanged; Linux retains read-only.
            with (Path(base) / leaf).open("r+b" if os.name == "nt" else "rb") as stream:
                os.fsync(stream.fileno())
        fsync_directory(Path(base))
    fsync_directory(target.parent)
    if (_file_inventory(target) != before or _file_inventory(source) != before
            or _directory_inventory(target) != directories or _directory_inventory(source) != directories):
        raise MaintenanceUnresolved("Verified recovery copy does not match the closed source")
    return _digest(before)


def _recovery_dir(name: str, operation_id: str) -> Path:
    if not NAME.fullmatch(name) or len(operation_id) != 32 or any(c not in "0123456789abcdef" for c in operation_id):
        raise ValueError("Invalid maintenance recovery identity")
    root = AREA / "recovery"
    _owned_dir(root, create=True)
    profile = root / name
    _owned_dir(profile, create=True)
    return profile / operation_id


def _evidence_path(name: str, operation_id: str) -> Path:
    journal, _ = _external(name)
    return journal.parent / f"browser-{operation_id}.json"


def _receipt_path(name: str, operation_id: str) -> Path:
    journal, _ = _external(name)
    return journal.parent / f"receipt-{operation_id}.json"


def _completed_receipt(name: str, operation_id: str) -> dict | None:
    path = _receipt_path(name, operation_id)
    assert_safe_leaf(path)
    if not path.exists():
        return None
    if path.stat().st_size > 16384:
        raise MaintenanceUnresolved("Completed maintenance receipt is oversized")
    value = json.loads(path.read_text())
    if (value.get("operation_id") != operation_id or value.get("name") != name
            or value.get("phase") not in {"browser_done", "rolled_back"}):
        raise MaintenanceUnresolved("Completed maintenance receipt needs inspection")
    return value


def _browser_pending(snapshot: dict) -> str | None:
    local = snapshot.get("local")
    session = snapshot.get("session")
    if not isinstance(local, dict) or not isinstance(session, dict):
        return "Browser storage could not be read"
    for key, raw in {**session, **local}.items():
        if not isinstance(key, str) or not isinstance(raw, str):
            return "Browser storage has an invalid entry"
        if key.startswith("dlms.quiz-progress.v1:"):
            try:
                record = json.loads(raw)
            except ValueError:
                return "A quiz recovery record cannot be interpreted"
            if record.get("pendingAttempt") or record.get("unacknowledgedStudyEvents"):
                return "A Study or Exam save needs confirmation before maintenance"
        if (key == "dlms-study-mistakes-request" or key.startswith("dlms.markAction.")
                or key.startswith("dlms.reviewMarkPending.")):
            return "A retained Study mistakes or Review request needs confirmation before maintenance"
    return None


def _close_checkpoint(paths: dict[str, Path], manifest: dict) -> dict | None:
    """The last closed-page checkpoint is independent of Chromium storage."""
    path = paths["root"] / "recovery-evidence.json"
    assert_safe_leaf(path)
    if not path.exists():
        return None
    if path.stat().st_size > 4 * 1024 * 1024:
        raise MaintenanceUnresolved("Browser close checkpoint is oversized")
    try:
        value = json.loads(path.read_text())
        if (value.get("profile_uuid") != manifest["uuid"] or value.get("epoch") != manifest["epoch"]
                or value.get("origin") != f"http://127.0.0.1:{manifest['port']}"
                or not isinstance(value.get("records"), dict)):
            raise ValueError("checkpoint context")
        reason = _browser_pending({"local": value["records"], "session": {}})
        if reason:
            raise MaintenanceUnresolved(reason)
        return value
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise MaintenanceUnresolved("Browser close checkpoint needs inspection") from exc


def browser_preflight(name: str, operation_id: str, snapshot: dict) -> dict:
    """Called by the owning Qt window before it closes its normal page."""
    paths = profile_paths(name, create=False)
    manifest = read_manifest(paths, name)
    if manifest is None:
        raise MaintenanceUnresolved("Desktop identity is missing")
    if read_marker(name) is not None:
        raise MaintenanceUnresolved("Another maintenance operation is unresolved")
    reason = _browser_pending(snapshot)
    if reason:
        raise MaintenanceUnresolved(reason)
    checkpoint = _close_checkpoint(paths, manifest)
    if len(json.dumps(snapshot)) > 4 * 1024 * 1024:
        raise MaintenanceUnresolved("Browser evidence exceeds the bounded maintenance snapshot")
    value = {"version": 1, "operation_id": operation_id, "profile_uuid": manifest["uuid"],
             "epoch": manifest["epoch"], "origin": f"http://127.0.0.1:{manifest['port']}",
             "snapshot": snapshot, "close_checkpoint": checkpoint}
    atomic_json(_evidence_path(name, operation_id), value)
    return value


def _read_browser_evidence(name: str, operation_id: str, manifest: dict) -> dict:
    paths = profile_paths(name, create=False)
    path = _evidence_path(name, operation_id)
    assert_safe_leaf(path)
    if not path.exists() or path.stat().st_size > 4 * 1024 * 1024:
        raise MaintenanceUnresolved("Verified pre-operation browser evidence is unavailable")
    try:
        value = json.loads(path.read_text())
        if (value.get("version") != 1 or value.get("operation_id") != operation_id
                or value.get("profile_uuid") != manifest["uuid"] or value.get("epoch") != manifest["epoch"]
                or value.get("origin") != f"http://127.0.0.1:{manifest['port']}"):
            raise ValueError("browser evidence context")
        if _browser_pending(value["snapshot"]):
            raise ValueError("pending browser action")
        current_checkpoint = _close_checkpoint(paths, manifest)
        old_checkpoint = value.get("close_checkpoint")
        allowed_checkpoint = old_checkpoint
        marker = read_marker(name)
        if old_checkpoint and marker and marker["phase"] in {"committed", "browser_check_pending", "browser_done"}:
            allowed_checkpoint = dict(old_checkpoint)
            affected = affected_browser_keys(marker["scope"], value["snapshot"], backend=paths["backend"])
            allowed_checkpoint["records"] = {k: v for k, v in old_checkpoint["records"].items() if k not in affected}
        if (current_checkpoint is None and old_checkpoint is not None and marker
                and marker["scope"] == "fresh"):
            retained = _recovery_dir(name, marker["operation_id"]) / "recovery-evidence.json"
            assert_safe_leaf(retained)
            if retained.exists() and json.loads(retained.read_text()) == old_checkpoint:
                current_checkpoint = old_checkpoint
        if current_checkpoint not in (old_checkpoint, allowed_checkpoint):
            raise ValueError("close checkpoint changed after preflight")
        return value
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise MaintenanceUnresolved("Browser preflight evidence is invalid") from exc


def _quiz_fingerprint(backend: Path, record: dict) -> str | None:
    quiz = record.get("quiz")
    if not isinstance(quiz, dict):
        raise MaintenanceUnresolved("Quiz recovery identity cannot be interpreted")
    name = quiz.get("file")
    if (not isinstance(name, str) or not name.startswith("/data/")
            or "/" in name[len("/data/"):] or name.endswith("/")):
        raise MaintenanceUnresolved("Quiz recovery file escapes the published data folder")
    path = backend / "data" / name[len("/data/"):]
    if path.is_symlink():
        raise MaintenanceUnresolved("Published quiz data is a symlink")
    if not path.is_file():
        return None
    raw = path.read_bytes().decode("utf-8")
    identity = "\0".join(("quiz-recovery-v1", "1", str(quiz.get("id")), name,
                          str(quiz.get("examMinutes")), raw))
    return "sha256:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()


def affected_browser_keys(scope: str, snapshot: dict, *, backend: Path | None = None) -> list[str]:
    """Select only storage whose dataset meaning this source scope invalidates."""
    local = snapshot["local"]
    keys = []
    for key, raw in local.items():
        affected = False
        if scope == "fresh":
            affected = True
        elif key.startswith("dlms.quiz-progress.v1:"):
            try:
                mode = json.loads(raw)["session"]["mode"]
            except (ValueError, TypeError, KeyError):
                raise MaintenanceUnresolved("Quiz recovery record cannot be scoped")
            affected = scope == "quiz" or (scope in {"study", "learning"} and mode == "Study")
            if scope == "source":
                if backend is None:
                    raise MaintenanceUnresolved("Post-reset quiz source is unavailable")
                record = json.loads(raw)
                affected = _quiz_fingerprint(backend, record) != record["quiz"]["fingerprint"]
        elif key == "serverplus_history_v2":
            affected = scope in {"exam", "quiz"}
        elif key == "dlms-study-mistakes-request":
            affected = scope in {"study", "quiz"}
        elif key.startswith(("dlms.markAction.", "dlms.reviewMarkPending.", "dlms.reviewMarkRejected.")):
            affected = scope == "quiz"
        elif key == "dlmsCollapsedLibraryFolders":
            affected = scope in {"settings", "quiz"}
        elif key == "dlms.studyPacks.openState.v1":
            affected = scope in {"source", "fresh"}
        elif key in {"dlms.anki.custom.performanceHistory.openState.v1",
                     "dlms.reviewSchedule.questionQueueCollapsed"}:
            affected = scope in {"quiz", "learning"}
        elif key == "dlms.studyAreaVisibility.v1":
            affected = scope == "settings"
        elif key.startswith("dlms"):
            raise MaintenanceUnresolved(f"Unrecognized DLMS browser key requires inspection: {key}")
        if affected:
            keys.append(key)
    return sorted(keys)


def browser_transition_plan(name: str, observed: dict) -> dict:
    marker = read_marker(name)
    if marker is None or marker["phase"] not in {"committed", "browser_check_pending"}:
        raise MaintenanceUnresolved("No committed maintenance operation awaits browser evidence")
    paths = profile_paths(name, create=False)
    manifest = read_manifest(paths, name)
    if manifest is None or manifest["uuid"] != marker["profile_uuid"] or manifest["epoch"] != marker["epoch"]:
        raise MaintenanceUnresolved("Browser transition profile identity differs")
    stored = _read_browser_evidence(name, marker["operation_id"], manifest)
    old = stored["snapshot"]
    reason = _browser_pending(observed)
    if reason:
        raise MaintenanceUnresolved(reason)
    affected = affected_browser_keys(marker["scope"], old, backend=paths["backend"])
    for key, raw in old["local"].items():
        current = observed["local"].get(key)
        if key in affected:
            if current not in (raw, None):
                raise MaintenanceUnresolved(f"Affected browser evidence changed during maintenance: {key}")
        elif current != raw:
            raise MaintenanceUnresolved(f"Unrelated browser evidence changed during maintenance: {key}")
    for key in observed["local"]:
        if key not in old["local"]:
            raise MaintenanceUnresolved(f"New browser evidence appeared during maintenance: {key}")
    return {"operation_id": marker["operation_id"], "scope": marker["scope"],
            "remove": affected, "expected": {key: old["local"][key] for key in affected}}


def complete_browser_transition(name: str, observed_after: dict, *, removed_now: bool) -> dict:
    plan = browser_transition_plan(name, observed_after)
    if any(key in observed_after["local"] for key in plan["remove"]):
        raise MaintenanceUnresolved("Affected browser evidence was not removed")
    marker = read_marker(name)
    stored = _read_browser_evidence(name, marker["operation_id"], read_manifest(profile_paths(name, create=False), name))
    checkpoint = stored.get("close_checkpoint")
    if checkpoint is not None and marker["scope"] != "fresh":
        path = profile_paths(name, create=False)["root"] / "recovery-evidence.json"
        current = _close_checkpoint(profile_paths(name, create=False), read_manifest(profile_paths(name, create=False), name))
        reduced = dict(checkpoint)
        reduced["records"] = {k: v for k, v in checkpoint["records"].items() if k not in plan["remove"]}
        if current == checkpoint:
            atomic_json(path, reduced)
        elif current != reduced:
            raise MaintenanceUnresolved("Close checkpoint changed during browser cleanup")
    from .ownership import process_start_ticks
    identity = {"pid": os.getpid(), "start_ticks": process_start_ticks(os.getpid())}
    if marker["phase"] == "committed" or removed_now:
        marker["phase"] = "browser_check_pending"
        marker["cleanup_owner"] = identity
    elif marker.get("cleanup_owner") != identity:
        marker["phase"] = "epoch_publication_pending" if marker.get("new_epoch") else "browser_done"
    else:
        raise MaintenanceUnresolved("Browser storage needs a separate-process reopen before final confirmation")
    _write(name, marker)
    if marker["phase"] == "epoch_publication_pending":
        marker = _publish_epoch(name, marker)
    return marker


def _publish_epoch(name: str, marker: dict) -> dict:
    """Idempotent after a crash on either side of manifest publication."""
    from .profile_state import publish_manifest
    paths = profile_paths(name, create=False)
    manifest = read_manifest(paths, name)
    if manifest is None or manifest["uuid"] != marker["profile_uuid"] or manifest["epoch"] not in {
            marker["epoch"], marker["new_epoch"]}:
        raise MaintenanceUnresolved("Maintenance epoch publication identity changed")
    if manifest["epoch"] == marker["epoch"]:
        publish_manifest(paths, {**manifest, "epoch": marker["new_epoch"]})
    checkpoint_path = paths["root"] / "recovery-evidence.json"
    assert_safe_leaf(checkpoint_path)
    if checkpoint_path.exists():
        checkpoint = json.loads(checkpoint_path.read_text())
        if checkpoint.get("epoch") not in {marker["epoch"], marker["new_epoch"]}:
            raise MaintenanceUnresolved("Close checkpoint has a different dataset epoch")
        if checkpoint["epoch"] != marker["new_epoch"]:
            atomic_json(checkpoint_path, {**checkpoint, "epoch": marker["new_epoch"]})
    marker["phase"] = "browser_done"
    _write(name, marker)
    return marker


def _windows_retirement_path(name: str, operation_id: str) -> Path:
    if len(operation_id) != 32 or any(c not in "0123456789abcdef" for c in operation_id):
        raise MaintenanceUnresolved("Invalid browser retirement operation")
    path, _ = _external(name)
    return path.parent / ("browser-retired-" + operation_id + ".json")


def record_windows_browser_retirement(name: str, operation_id: str, proof: dict) -> None:
    from .windows_browser_quarantine import KEYS, valid_id, validate_processes
    paths = profile_paths(name, create=False)
    manifest = read_manifest(paths, name)
    if (manifest is None or not isinstance(proof, dict)
            or set(proof) != {"processes", "roots", "host_finished", "native_retired", "storage_pins_released"}
            or not all(proof.get(key) is True for key in
            ("host_finished", "native_retired", "storage_pins_released"))
            or not isinstance(proof.get("roots"), dict) or set(proof["roots"]) != KEYS
            or not all(map(valid_id, proof["roots"].values()))):
        raise MaintenanceUnresolved("Native browser retirement was not positively confirmed")
    validate_processes(proof["processes"])
    _read_browser_evidence(name, operation_id, manifest)
    value = {"version": 1, "name": name, "operation_id": operation_id,
             "profile_uuid": manifest["uuid"], "epoch": manifest["epoch"],
             "origin": f"http://127.0.0.1:{manifest['port']}",
             "processes": proof["processes"], "roots": proof["roots"]}
    path = _windows_retirement_path(name, operation_id)
    assert_safe_leaf(path)
    if path.exists(): raise MaintenanceUnresolved("Browser retirement receipt already exists")
    atomic_json(path, value)


def _quarantine_windows_browser_roots(name: str, paths: dict, recovery: Path, marker: dict, owner) -> None:
    from PySide6.QtCore import QLockFile
    from .windows_browser_quarantine import KEYS, valid_id, validate_processes, prepare, move
    from .windows_files import owned as native_owned
    from .ownership import process_start_ticks
    if (owner is None or owner.mode != "local" or owner.profile_name != name or owner.paths != paths
            or not isinstance(owner.local_lock, QLockFile) or not owner.local_lock.isLocked()
            or owner.backend is not None or owner.view is not None or owner._retiring_browser is not None
            or owner._browser_dialog_depth or owner._retirement_wait_active):
        raise MaintenanceUnresolved("Closed Local window ownership is required for browser quarantine")
    descriptor = paths["root"] / "instance-owner.json"
    native_owned(descriptor, private=True)
    current_owner = json.loads(descriptor.read_text())
    if current_owner != {"pid": os.getpid(), "start_ticks": process_start_ticks(os.getpid()),
                         "name": name, "secret": owner.instance_secret}:
        raise MaintenanceUnresolved("Browser quarantine window ownership changed")
    proof_path = _windows_retirement_path(name, marker["operation_id"])
    if not proof_path.exists():
        raise MaintenanceUnresolved("Windows browser retirement was not recorded; preserve this earlier operation for inspection")
    native_owned(proof_path, private=True)
    if proof_path.stat().st_size > 16384: raise MaintenanceUnresolved("Browser retirement receipt is oversized")
    def unique_fields(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise MaintenanceUnresolved("Duplicate browser retirement fields")
            result[key] = value
        return result
    proof = json.loads(proof_path.read_text(), object_pairs_hook=unique_fields)
    if (not isinstance(proof, dict) or set(proof) != {"version", "name", "operation_id", "profile_uuid", "epoch", "origin", "processes", "roots"}
            or proof["version"] != 1 or proof["name"] != name or proof["operation_id"] != marker["operation_id"]
            or proof["profile_uuid"] != marker["profile_uuid"] or proof["epoch"] != marker["epoch"]
            or proof["origin"] != f"http://127.0.0.1:{owner.manifest['port']}"
            or not isinstance(proof["roots"], dict) or set(proof["roots"]) != KEYS
            or not all(map(valid_id, proof["roots"].values()))):
        raise MaintenanceUnresolved("Browser retirement context differs; preserve the closed profile")
    validate_processes(proof["processes"])
    writer = acquire_writer_lock(paths["root"] / "backend-writer.lock")
    try:
        rows = marker.get("windows_opaque_quarantine")
        if rows is None:
            rows = prepare(paths, recovery, proof["roots"])
            marker["windows_opaque_quarantine"] = rows
            _write(name, marker)  # Both old and empty replacement IDs precede moves.
        else:
            # Inspect the journal spelling too: JSON duplicate keys must not
            # silently choose one of two proposed native identities.
            journal_path, _ = _external(name)
            native_owned(journal_path, private=True)
            strict = json.loads(journal_path.read_text(), object_pairs_hook=unique_fields)
            if strict.get("windows_opaque_quarantine") != rows:
                raise MaintenanceUnresolved("Browser quarantine journal changed")
        if (not isinstance(rows, dict) or set(rows) != KEYS
                or any(not isinstance(rows[key], dict) or rows[key].get("old") != proof["roots"][key] for key in KEYS)):
            raise MaintenanceUnresolved("Browser quarantine root identity differs from retirement")
        move(paths, recovery, rows)
    finally:
        writer.close()


def quarantine_fresh_browser(name: str, *, owner=None) -> dict:
    """Move the entire closed Chromium store, including cookies, after fresh reset."""
    marker = read_marker(name)
    if marker is None or marker["scope"] != "fresh" or marker["phase"] not in {"committed", "browser_check_pending"}:
        raise MaintenanceUnresolved("No committed fresh-state browser transition")
    paths = profile_paths(name, create=False)
    manifest = read_manifest(paths, name)
    if manifest is None or manifest["uuid"] != marker["profile_uuid"] or manifest["epoch"] != marker["epoch"]:
        raise MaintenanceUnresolved("Fresh-state browser identity changed")
    _read_browser_evidence(name, marker["operation_id"], manifest)
    recovery = _recovery_dir(name, marker["operation_id"])
    _owned_dir(recovery)
    with _external_lock(name):
        from .webview2_runtime import active as webview2_active
        opaque_windows = os.name == "nt" and webview2_active()
        if opaque_windows:
            if marker["phase"] != "committed":
                raise MaintenanceUnresolved("Fresh browser quarantine is not awaiting its initial verified transition")
            _quarantine_windows_browser_roots(name, paths, recovery, marker, owner)
        for key in (("recovery-evidence.json",) if opaque_windows else ("web_storage", "web_cache", "recovery-evidence.json")):
            source = paths["root"] / key if key == "recovery-evidence.json" else paths[key]
            target = recovery / key
            if target.is_symlink() or source.is_symlink():
                raise MaintenanceUnresolved("Unsafe Chromium storage path")
            if target.exists():
                if key == "recovery-evidence.json":
                    assert_safe_leaf(target)
                else:
                    _owned_dir(target)
                if source.exists() and (key == "recovery-evidence.json" or any(source.iterdir())):
                    raise MaintenanceUnresolved("Both old and new Chromium stores contain files")
            elif source.exists():
                if key == "recovery-evidence.json":
                    assert_safe_leaf(source)
                else:
                    _file_inventory(source)
                if source.stat().st_dev != recovery.stat().st_dev:
                    raise MaintenanceUnresolved("Chromium quarantine requires the same filesystem")
                os.rename(source, target)
                fsync_directory(source.parent)
                fsync_directory(target.parent)
            if key != "recovery-evidence.json":
                source.mkdir(mode=0o700, parents=True, exist_ok=True)
        from .ownership import process_start_ticks
        marker["phase"] = "browser_check_pending"
        marker["cleanup_owner"] = {"pid": os.getpid(), "start_ticks": process_start_ticks(os.getpid())}
        marker["whole_chromium_quarantine"] = True
        _write(name, marker)
    return marker


def clear_completed_marker(name: str) -> None:
    marker = read_marker(name)
    if marker is None or marker["phase"] not in {"browser_done", "rolled_back"}:
        raise MaintenanceUnresolved("Maintenance is not resolved")
    receipt = _completed_receipt(name, marker["operation_id"])
    if receipt is None:
        atomic_json(_receipt_path(name, marker["operation_id"]), marker)
    elif receipt != marker:
        raise MaintenanceUnresolved("Completed operation identity has a different receipt")
    path, _ = _external(name)
    path.unlink()
    fsync_directory(path.parent)


def serve_transition(paths: dict[str, Path], name: str, bound, port: int, nonce: str) -> None:
    """Exact-origin storage inspection page; no captured application routes."""
    from waitress import create_server
    marker = read_marker(name)
    if marker is None or marker["phase"] not in {"committed", "browser_check_pending"}:
        raise MaintenanceUnresolved("Only a committed operation may enter browser reconciliation")
    manifest = read_manifest(paths, name)
    if manifest is None or manifest["uuid"] != marker["profile_uuid"] or manifest["epoch"] != marker["epoch"]:
        raise MaintenanceUnresolved("Maintenance identity changed before transition service")
    body = ("<!doctype html><html lang='en'><meta charset='utf-8'>"
            "<title>DLMS Desktop maintenance recovery</title>"
            "<body style='font:18px system-ui;max-width:55rem;margin:4rem auto'>"
            "<h1>Finishing profile maintenance</h1>"
            "<p>The application is locked while saved browser evidence is checked. "
            "If this stops, reopen the same disposable profile to continue recovery.</p></body></html>").encode()

    def wsgi(environ, start_response):
        from .webview2_runtime import worker_active as webview2_active, local_response_policy
        if webview2_active():
            # The recovery-only backend is authenticated by the same native
            # host as the ordinary Local backend. Keep its required policy on
            # readiness, denials and the transition page before rendering.
            start_response = local_response_policy(start_response)
        path = environ.get("PATH_INFO")
        origin = f"http://127.0.0.1:{port}"
        if (environ.get("HTTP_HOST") != f"127.0.0.1:{port}"
                or environ.get("wsgi.url_scheme") != "http"
                or environ.get("HTTP_ORIGIN") not in (None, origin)
                or environ.get("HTTP_SEC_FETCH_SITE", "").lower() == "cross-site"
                or environ.get("HTTP_X_FORWARDED_HOST") or environ.get("HTTP_X_FORWARDED_PROTO")
                or environ.get("HTTP_X_DLMS_DESKTOP_TOKEN") != nonce):
            start_response("403 Forbidden", [("Content-Length", "0")])
            return [b""]
        if path == "/_desktop/ready" and environ.get("HTTP_X_DLMS_DESKTOP_NONCE") == nonce:
            payload = b"DLMS Desktop Block A ready"
            start_response("200 OK", [("Content-Type", "text/plain"), ("Content-Length", str(len(payload))),
                                        ("Cache-Control", "no-store")])
            return [payload]
        if path == "/_desktop/maintenance" and environ.get("REQUEST_METHOD") == "GET":
            start_response("200 OK", [("Content-Type", "text/html; charset=utf-8"),
                                        ("Content-Length", str(len(body))), ("Cache-Control", "no-store"),
                                        ("X-Frame-Options", "DENY"),
                                        ("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'")])
            return [body]
        start_response("403 Forbidden", [("Content-Length", "0")])
        return [b""]

    print(f"[DESKTOP] maintenance transition only on 127.0.0.1:{port}", flush=True)
    create_server(wsgi, sockets=[bound], threads=2).run()


def _abort(paths: dict[str, Path], phase: str) -> None:
    if (os.environ.get("DLMS_DESKTOP_AUTOMATED") == "1"
            and os.environ.get("DLMS_DESKTOP_TEST_MAINTENANCE_ABORT") == phase
            and paths["root"].resolve().is_relative_to(AREA.resolve())):
        os._exit(74)


def _ensure_no_pending(paths: dict[str, Path]) -> None:
    from .profile_state import read_manifest
    from .import_operations import unresolved_count
    from .pack_operations import unresolved_count as pending_pack_installs
    identity = read_manifest(paths, paths["root"].name)
    if identity and (unresolved_count(paths["root"], identity["epoch"])
                     or pending_pack_installs(paths["root"], identity["epoch"])):
        raise MaintenanceUnresolved("Portable import has unresolved accepted work; resume it before maintenance")
    for label in ("durable-actions", "pending-requests"):
        root = paths["root"] / label
        if root.is_symlink() or (root.exists() and not root.is_dir()):
            raise MaintenanceUnresolved(f"Accepted-action directory is unsafe: {label}")
        if root.exists() and any(root.glob("*.json")):
            raise MaintenanceUnresolved("Accepted Study, Exam, mistakes or Review work must be reconciled first")


def _source_ready(app, paths: dict[str, Path]) -> None:
    # Importing app.py has already run its startup reconciliation under the
    # writer lock. A second read/repair pass must report no failed work.
    result = app.reconcile_quiz_publications()
    if result.get("failed") or result.get("unsafe"):
        raise MaintenanceUnresolved("Source publication recovery is unresolved")
    for label in (".restore_operations", ".quiz_publications"):
        folder = paths["backend"] / label
        if folder.is_symlink() or (folder.exists() and not folder.is_dir()):
            raise MaintenanceUnresolved(f"Source journal path is unsafe: {label}")
        if folder.exists() and any(folder.iterdir()):
            raise MaintenanceUnresolved(f"Source journal or publication staging remains unresolved: {label}")


def _tables(path: Path) -> dict[str, list]:
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {name: conn.execute(f'SELECT * FROM "{name}" ORDER BY rowid').fetchall() for name in names}


def _columns(path: Path) -> dict[str, list[str]]:
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {name: [r[1] for r in conn.execute(f'PRAGMA table_info("{name}")')] for name in names}


def _apply(app, scope: str, recovery: Path, value: dict, name: str) -> str | None:
    if scope == "exam":
        with app._profile_snapshot.access(app.APP_DATA_DIR, exclusive=True), app.RESTORE_OPERATION_LOCK, app.registry_lock:
            app._clear_persistent_history()
        return None
    core = {
        "study": ("study-history", lambda: app._restore_service.delete_study_history_core(app.DB_PATH)),
        "learning": ("learning-intelligence", app._reset_learning_intelligence_core),
        "quiz": ("quiz-library", app._reset_quiz_library_core),
        "source": ("source-content", app._reset_source_content_core),
        "settings": ("app-settings", app._reset_app_settings_core),
        "fresh": ("all-data", app._full_data_reset_core),
    }[scope]
    label, callable_core = core
    # Match the captured wrapper's ownership and lock order, but retain and
    # verify its safety ZIP externally before invoking the destructive core.
    with app._profile_snapshot.access(app.APP_DATA_DIR, exclusive=True), app.RESTORE_OPERATION_LOCK, app.registry_lock:
        app._require_owned_app_data_root(f"run the {label} reset")
        archive, _ = app._create_dlms_backup("pre-reset-" + label)
        archive = Path(archive)
        if archive.is_symlink() or archive.parent.resolve() != Path(app.BACKUP_FOLDER).resolve():
            raise MaintenanceUnresolved("Source safety backup escaped the owned backup directory")
        app._validate_dlms_backup(str(archive))
        retained = recovery / archive.name
        assert_safe_leaf(retained)
        if retained.exists():
            raise MaintenanceUnresolved("Safety backup identity already exists in recovery")
        with archive.open("rb") as source, retained.open("xb") as target:
            shutil.copyfileobj(source, target, 1024 * 1024)
            target.flush()
            os.fsync(target.fileno())
        fsync_directory(recovery)
        if _file_sha256(archive) != _file_sha256(retained):
            raise MaintenanceUnresolved("Retained safety ZIP differs from source")
        value["safety_backup"] = archive.name
        value["retained_safety_sha256"] = _file_sha256(retained)
        _write(name, value)
        callable_core()
        if scope == "quiz":
            # The captured quiz reset disables foreign keys while deleting
            # questions and omits matching_pairs. Remove only these orphaned
            # child rows before the Desktop result can be committed.
            with closing(sqlite3.connect(app.DB_PATH)) as conn, conn:
                remaining = conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
                if remaining:
                    raise MaintenanceUnresolved("Quiz reset left questions; matching cleanup refused")
                conn.execute("DELETE FROM matching_pairs")
    return archive.name


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_result(scope: str, before: dict[str, list], after: dict[str, list],
                     columns: dict[str, list[str]]) -> None:
    if scope == "exam":
        changed = {"attempts", "attempt_answers", "missed_questions"}
        if any(after.get(name) for name in changed):
            raise MaintenanceUnresolved("Exam result tables were not cleared")
    elif scope == "study":
        changed = {"study_sessions", "study_responses", "study_legacy_responses",
                   "study_mistake_state", "study_state", "learning_events"}
        if any(after.get(name) for name in ("study_sessions", "study_responses", "study_legacy_responses")):
            raise MaintenanceUnresolved("Study history remains after delete")
        if ([row for row in before.get("learning_events", []) if row[1] not in {"study_answer", "study_action"}]
                != after.get("learning_events", [])):
            raise MaintenanceUnresolved("Non-Study learning evidence changed during Study history deletion")
    elif scope == "learning":
        changed = {"learning_events", "study_legacy_responses", "study_state"}
        if after.get("learning_events"):
            raise MaintenanceUnresolved("Learning evidence remains after reset")
        if not all(row in after.get("study_legacy_responses", []) for row in before.get("study_legacy_responses", [])):
            raise MaintenanceUnresolved("Factual legacy Study responses were removed")
    elif scope == "settings" or scope == "source":
        changed = set() if scope == "settings" else {"questions", "attempt_answers"}
        if scope == "source":
            for table, media_field in (("questions", "media_json"),
                                       ("attempt_answers", "response_json")):
                old, new = before.get(table, []), after.get(table, [])
                fields = columns.get(table, [])
                if len(old) != len(new) or len(fields) != (len(old[0]) if old else len(fields)):
                    raise MaintenanceUnresolved(f"Published {table} records changed during source clear")
                if any({field: value for field, value in zip(fields, a) if field != media_field}
                       != {field: value for field, value in zip(fields, b) if field != media_field}
                       for a, b in zip(old, new)):
                    raise MaintenanceUnresolved(f"Published {table} identity or grading changed during source clear")
    elif scope == "quiz":
        changed = {"quizzes", "questions", "choices", "matching_pairs", "attempts",
                   "attempt_answers", "missed_questions", "study_sessions", "study_responses",
                   "study_legacy_responses", "learning_events", "concepts", "question_concepts",
                   "study_mistake_state", "study_mistake_passes", "study_mistake_members",
                   "study_mistake_actions", "study_state", "review_mark_state", "review_marks",
                   "review_mark_actions", "exam_plan_actions", "exam_plan_state", "sqlite_sequence"}
        emptied = {"quizzes", "questions", "choices", "matching_pairs", "attempts",
                   "attempt_answers", "missed_questions", "study_sessions", "study_responses",
                   "study_legacy_responses", "learning_events", "concepts", "question_concepts",
                   "study_mistake_passes", "study_mistake_members", "study_mistake_actions", "sqlite_sequence"}
        if any(after.get(name) for name in emptied):
            raise MaintenanceUnresolved("Quiz records remain after reset")
        if after.get("review_marks") != before.get("review_marks") or after.get("review_mark_actions") != before.get("review_mark_actions"):
            raise MaintenanceUnresolved("Quiz reset changed factual Review mark records")
        old_plan_actions, new_plan_actions = before.get("exam_plan_actions", []), after.get("exam_plan_actions", [])
        if len(old_plan_actions) != len(new_plan_actions):
            raise MaintenanceUnresolved("Quiz reset removed Exam Plan actions")
        fields = columns.get("exam_plan_actions", [])
        if fields and "quiz_id" in fields:
            pos = fields.index("quiz_id")
            if any(a[:pos] + a[pos+1:] != b[:pos] + b[pos+1:] or b[pos] is not None
                   for a, b in zip(old_plan_actions, new_plan_actions)):
                raise MaintenanceUnresolved("Quiz reset changed Exam Plan action identity")
    else:  # fresh state intentionally changes nearly everything
        retained_state = {"schema_meta", "study_state", "study_mistake_state", "exam_plan_state",
                          "review_mark_state", "certification_state"}
        if any(rows for name, rows in after.items() if name not in retained_state):
            raise MaintenanceUnresolved("Fresh-state database is not empty")
        return
    for name, rows in before.items():
        if name not in changed and after.get(name) != rows:
            raise MaintenanceUnresolved(f"Unrelated table changed during {scope}: {name}")


def _validate_files(scope: str, before: dict[str, str], after: dict[str, str],
                    preimage_root: Path) -> None:
    """Verify preserved paths, including assets, before publishing commit."""
    if os.name == "nt":
        # Existing Windows journals hash native path spellings. Leave those
        # inventories/digests untouched; project only the policy comparison.
        def portable_names(values):
            projected = {key.replace("\\", "/"): value for key, value in values.items()}
            if len(projected) != len(values):
                raise MaintenanceUnresolved("Maintenance file paths collide after Windows normalization")
            return projected
        before, after = portable_names(before), portable_names(after)
    allowed = {
        "exam": ("results.db",),
        "study": ("results.db", "backups/"),
        "learning": ("results.db", "backups/"),
        "quiz": ("results.db", "backups/", "config/quizzes.json", "data/", "quizzes/",
                 "quiz_assets/", "static/logos/"),
        "source": ("results.db", "backups/", "content_packs/", "pdf_question_banks/",
                   "pdf_terminology_banks/", "pdf_import_drafts/", "external_ai_drafts/",
                   "image_builder_drafts/", "content_pack_staging/", "uploads/",
                   "data/", "quizzes/", "quiz_assets/"),
        "settings": ("backups/", "config/portal.json", "static/bg/"),
        "fresh": ("*",),
    }[scope]
    if scope == "fresh":
        for key, digest in before.items():
            if (key == ".dlms-data-root" or key.startswith("backups/")) and after.get(key) != digest:
                raise MaintenanceUnresolved(f"Fresh reset changed retained file: {key}")
        allowed_fresh = {".dlms-data-root", ".secret_key", "results.db",
                         "config/portal.json", "config/quizzes.json"}
        if any(key not in allowed_fresh and not key.startswith("backups/") for key in after):
            raise MaintenanceUnresolved("Fresh state retained an unexpected active file")
        if before.get(".secret_key") == after.get(".secret_key"):
            raise MaintenanceUnresolved("Fresh state retained its previous secret key")
        return
    for key in set(before) | set(after):
        if any(key == entry or (entry.endswith("/") and key.startswith(entry)) for entry in allowed):
            continue
        if before.get(key) != after.get(key):
            raise MaintenanceUnresolved(f"Unrelated file changed during {scope}: {key}")
    if scope == "source":
        cleared_prefixes = ("pdf_question_banks/", "pdf_terminology_banks/", "pdf_import_drafts/",
                            "external_ai_drafts/", "image_builder_drafts/", "content_pack_staging/",
                            "uploads/")
        if any(key.startswith(cleared_prefixes) for key in after):
            raise MaintenanceUnresolved("Removable source staging or uploads remain")
        protected_prefixes = []
        for manifest_key in before:
            if not (manifest_key.startswith("content_packs/") and manifest_key.endswith("/manifest.json")):
                continue
            manifest_path = preimage_root / manifest_key
            try:
                protected = bool(json.loads(manifest_path.read_text()).get("protected"))
            except (OSError, ValueError, TypeError, AttributeError):
                protected = False  # captured source treats malformed packs as removable
            if protected:
                prefix = manifest_key.rsplit("/", 1)[0] + "/"
                protected_prefixes.append(prefix)
                if any(after.get(key) != digest for key, digest in before.items() if key.startswith(prefix)):
                    raise MaintenanceUnresolved(f"Protected source pack changed: {prefix}")
        if any(key.startswith("content_packs/") and not key.startswith(tuple(protected_prefixes))
               for key in after):
            raise MaintenanceUnresolved("Removable source pack files remain")
        # Published quiz files may be rewritten to stable copied asset refs,
        # but clearing source material may never remove one.
        for key in before:
            if key.startswith(("data/", "quizzes/", "quiz_assets/")) and key not in after:
                raise MaintenanceUnresolved(f"Published quiz asset was removed: {key}")
    if scope == "quiz" and any(key.startswith(("data/", "quizzes/", "quiz_assets/", "static/logos/"))
                                for key in after):
        raise MaintenanceUnresolved("Quiz reset left generated quiz files")
    if scope == "settings" and any(key.startswith("static/bg/") for key in after):
        raise MaintenanceUnresolved("Settings reset left a background file")


def _validate_configuration(app, scope: str, backend: Path) -> None:
    """Check source-owned reset outcomes that a file hash whitelist cannot prove."""
    if scope in {"quiz", "fresh"}:
        registry = backend / "config" / "quizzes.json"
        try:
            if json.loads(registry.read_text()) != []:
                raise ValueError("nonempty registry")
        except (OSError, ValueError, TypeError) as exc:
            raise MaintenanceUnresolved("Quiz reset did not publish an empty registry") from exc
    if scope in {"settings", "fresh"}:
        from dlms.persistence.portal import _portal_defaults
        expected = _portal_defaults(
            default_theme=app.DEFAULT_THEME,
            default_ai_feedback_prompt=app.DEFAULT_AI_FEEDBACK_PROMPT,
            default_law_ai_prompt=app.DEFAULT_LAW_AI_PROMPT,
            default_study_content_pack_prompt=app.DEFAULT_STUDY_CONTENT_PACK_PROMPT,
            default_medical_study_pack_ai_addendum=app.DEFAULT_MEDICAL_STUDY_PACK_AI_ADDENDUM,
        )
        try:
            actual = json.loads((backend / "config" / "portal.json").read_text())
        except (OSError, ValueError, TypeError) as exc:
            raise MaintenanceUnresolved("Default portal settings are unreadable") from exc
        if actual != expected:
            raise MaintenanceUnresolved("Settings reset did not restore the source defaults")


def run(name: str, scope: str, operation_id: str) -> dict:
    if scope not in SCOPES or len(operation_id) != 32 or any(c not in "0123456789abcdef" for c in operation_id):
        raise ValueError("Unknown maintenance scope or operation identity")
    paths = profile_paths(name, create=False)
    manifest = read_manifest(paths, name)
    if manifest is None:
        raise MaintenanceUnresolved("Desktop profile identity is missing")
    receipt = _completed_receipt(name, operation_id)
    if receipt is not None:
        if (receipt["scope"] != scope or receipt["profile_uuid"] != manifest["uuid"]
                or manifest["epoch"] not in {receipt["epoch"], receipt.get("new_epoch")}):
            raise MaintenanceUnresolved("Completed maintenance identity is stale or belongs to another scope")
        return receipt
    marker = read_marker(name)
    if marker:
        if marker["operation_id"] != operation_id or marker["scope"] != scope:
            raise MaintenanceUnresolved("Another maintenance operation must reconcile first")
        return reconcile(name)  # Same ID reports proven state; never applies again.
    _ensure_no_pending(paths)
    from .transition import read_transition
    if read_transition(paths) is not None:
        raise MaintenanceUnresolved("Backup adoption must reconcile before maintenance")
    _read_browser_evidence(name, operation_id, manifest)
    with _external_lock(name):
        return _run_locked(name, scope, operation_id, paths, manifest)


def _run_locked(name: str, scope: str, operation_id: str, paths: dict[str, Path], manifest: dict) -> dict:
    writer = acquire_writer_lock(paths["root"] / "backend-writer.lock")
    try:
        owned_nonce = os.environ.get("DLMS_DESKTOP_NONCE", "")
        env = isolated_environment(paths)
        env.update(DLMS_DESKTOP_PROFILE_NAME=name, DLMS_DESKTOP_PORT=str(manifest["port"]),
                   DLMS_DESKTOP_NONCE=owned_nonce if len(owned_nonce) >= 32 else secrets.token_hex(32),
                   PYTHONNOUSERSITE="1")
        source_environment(env)
        for key in ("DLMS_DESKTOP_AUTOMATED", "DLMS_DESKTOP_TEST_MAINTENANCE_ABORT"):
            if key in os.environ:
                env[key] = os.environ[key]
        os.environ.clear()
        os.environ.update(env)
        source_import_path()
        import app as app  # noqa: PLC0415
        _source_ready(app, paths)
        _ensure_no_pending(paths)
        with app._profile_snapshot.access(app.APP_DATA_DIR, exclusive=True):
            before_tables = _tables(paths["backend"] / "results.db")
            before_columns = _columns(paths["backend"] / "results.db")
            before_files = _file_inventory(paths["backend"])
            before_dirs = _directory_inventory(paths["backend"])
            recovery = _recovery_dir(name, operation_id)
            _owned_dir(recovery, create=True)
            digest = _copy_verified(paths["backend"], recovery / "backend")
            value = {"version": 1, "name": name, "scope": scope, "operation_id": operation_id,
                     "profile_uuid": manifest["uuid"], "epoch": manifest["epoch"],
                     "new_epoch": str(uuid.uuid4()) if scope in {"quiz", "fresh"} else None,
                     "preimage_sha256": digest, "phase": "prepared", "safety_backup": None,
                     "postimage_sha256": None,
                     "preimage_directories": _digest(before_dirs), "postimage_directories": None}
            _write(name, value)
            _abort(paths, "prepared")
            if _digest(_file_inventory(paths["backend"])) != digest:
                raise MaintenanceUnresolved("Closed source changed after preimage")
            value["phase"] = "mutation_started"
            _write(name, value)
            _abort(paths, "mutation_started")
            try:
                value["safety_backup"] = _apply(app, scope, recovery, value, name)
                _abort(paths, "after_source")
                after_columns = _columns(paths["backend"] / "results.db")
                if scope == "fresh":
                    app._validate_current_restored_database(app.DB_PATH)
                elif after_columns != before_columns:
                    raise MaintenanceUnresolved("Maintenance changed application database schema")
                _validate_result(scope, before_tables, _tables(paths["backend"] / "results.db"), before_columns)
                after_files = _file_inventory(paths["backend"])
                _validate_files(scope, before_files, after_files, recovery / "backend")
                _validate_configuration(app, scope, paths["backend"])
                value["postimage_sha256"] = _digest(after_files)
                value["postimage_directories"] = _digest(_directory_inventory(paths["backend"]))
                value["phase"] = "committed"
                _write(name, value)
                _abort(paths, "committed")
            except BaseException:
                # The journal is authoritative. Startup or explicit reconciliation
                # restores the full preimage; never reopen this root yet.
                raise
            return value
    finally:
        writer.close()


def reconcile(name: str) -> dict | None:
    """Called before captured app import; never guesses a partial outcome."""
    value = read_marker(name)
    if value is None:
        return None
    paths = profile_paths(name, create=False)
    manifest = read_manifest(paths, name)
    allowed_epochs = {value["epoch"]}
    if value["phase"] in {"epoch_publication_pending", "browser_done"} and value.get("new_epoch"):
        allowed_epochs.add(value["new_epoch"])
    if manifest is None or manifest["uuid"] != value["profile_uuid"] or manifest["epoch"] not in allowed_epochs:
        raise MaintenanceUnresolved("Maintenance profile identity changed")
    source = _recovery_dir(name, value["operation_id"]) / "backend"
    if _digest(_file_inventory(source)) != value["preimage_sha256"]:
        raise MaintenanceUnresolved("Maintenance preimage is missing or damaged")
    if (value.get("preimage_directories") is not None
            and _digest(_directory_inventory(source)) != value["preimage_directories"]):
        raise MaintenanceUnresolved("Maintenance preimage directories changed")
    with _external_lock(name):
        return _reconcile_locked(name, value, paths, source)


def _reconcile_locked(name: str, value: dict, paths: dict[str, Path], source: Path) -> dict:
    writer = acquire_writer_lock(paths["root"] / "backend-writer.lock")
    try:
        expected_dirs = value.get("preimage_directories")
        def original(root: Path) -> bool:
            return (_digest(_file_inventory(root)) == value["preimage_sha256"]
                    and (expected_dirs is None or _digest(_directory_inventory(root)) == expected_dirs))
        if value["phase"] in {"committed", "browser_check_pending", "epoch_publication_pending", "browser_done"}:
            if _digest(_file_inventory(paths["backend"])) != value["postimage_sha256"]:
                raise MaintenanceUnresolved("Committed maintenance result changed before browser reconciliation")
            if (value.get("postimage_directories") is not None
                    and _digest(_directory_inventory(paths["backend"])) != value["postimage_directories"]):
                raise MaintenanceUnresolved("Committed maintenance directories changed")
            return _publish_epoch(name, value) if value["phase"] == "epoch_publication_pending" else value
        if value["phase"] == "rolled_back":
            if not original(paths["backend"]):
                raise MaintenanceUnresolved("Rolled-back maintenance preimage no longer matches")
            return value
        if value["phase"] == "prepared":
            if not original(paths["backend"]):
                raise MaintenanceUnresolved("Prepared maintenance root changed unexpectedly")
            value["phase"] = "rolled_back"
            _write(name, value)
            return value
        # Before commit, a complete preimage is the only authority. The copy
        # and both rename positions are stable and recoverable across crashes.
        root = paths["backend"]
        replacement = paths["root"] / f".maintenance-replace-{value['operation_id']}"
        partial = _recovery_dir(name, value["operation_id"]) / "partial"
        if root.exists() and original(root):
            value["phase"] = "rolled_back"
            _write(name, value)
            return value
        if not replacement.exists():
            _copy_verified(source, replacement)
        elif not original(replacement):
            raise MaintenanceUnresolved("Rollback replacement is damaged")
        if root.exists():
            if partial.exists():
                raise MaintenanceUnresolved("Two partial maintenance roots require inspection")
            os.rename(root, partial)
            fsync_directory(root.parent)
            _abort(paths, "rollback_partial")
        os.rename(replacement, root)
        fsync_directory(root.parent)
        _abort(paths, "rollback_replaced")
        if not original(root):
            raise MaintenanceUnresolved("Maintenance rollback verification failed")
        value["phase"] = "rolled_back"
        _write(name, value)
        return value
    finally:
        writer.close()


def main(argv=None) -> int:
    if sys.platform == "darwin":
        from .macos_processes import seal_private_descriptors
        seal_private_descriptors()
    parser = argparse.ArgumentParser(description="Closed-profile synthetic maintenance worker")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--scope", choices=sorted(SCOPES))
    parser.add_argument("--operation-id", default=None)
    parser.add_argument("--reconcile", action="store_true")
    args = parser.parse_args(argv)
    try:
        paths = profile_paths(args.profile, create=False)
        owner_secret = os.environ.get("DLMS_DESKTOP_MAINT_OWNER_SECRET")
        parent_text = os.environ.get("DLMS_DESKTOP_MAINT_PARENT_PID")
        pipe_text = os.environ.get("DLMS_DESKTOP_MAINT_PARENT_PIPE")
        instance = None
        if owner_secret:
            from .ownership import process_start_ticks
            if parent_text is None or pipe_text is None or int(parent_text) != os.getppid():
                raise MaintenanceUnresolved("Maintenance worker parent ownership is inconsistent")
            descriptor = json.loads((paths["root"] / "instance-owner.json").read_text())
            if (descriptor.get("pid") != os.getppid() or descriptor.get("name") != args.profile
                    or descriptor.get("secret") != owner_secret
                    or descriptor.get("start_ticks") != process_start_ticks(os.getppid())):
                raise MaintenanceUnresolved("Maintenance caller does not own this Desktop window")
            import signal
            import threading
            parent_pipe = int(pipe_text)
            def watch_parent():
                try:
                    os.read(parent_pipe, 1)
                finally:
                    os.close(parent_pipe)
                if sys.platform == "darwin":
                    from .macos_processes import parent_lost
                    parent_lost()
                if os.name == "nt":
                    os._exit(70)
                if os.getppid() != int(parent_text):
                    os.killpg(os.getpgrp(), signal.SIGTERM)
            threading.Thread(target=watch_parent, name="maintenance-owner", daemon=True).start()
        else:
            from PySide6.QtCore import QLockFile
            instance = QLockFile(str(paths["root"] / "instance.lock"))
            instance.setStaleLockTime(0)
            if not instance.tryLock(0):
                raise MaintenanceUnresolved("Close the owned Desktop window before direct synthetic maintenance")
        try:
            result = reconcile(args.profile) if args.reconcile else run(args.profile, args.scope, args.operation_id or secrets.token_hex(16))
        finally:
            if instance is not None:
                instance.unlock()
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        if os.environ.get("DLMS_DESKTOP_AUTOMATED") == "1":
            import traceback
            traceback.print_exc()
        print(f"DLMS Desktop maintenance stopped: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

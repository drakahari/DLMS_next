"""Desktop-owned dataset transition receipt and closed-browser evidence quarantine.

The source restore journal decides application rollback/adoption. This sidecar
records its outcome before that journal can be removed, then changes the Qt
epoch only after the matching dataset has been verified. No portable format or
application schema is changed.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid

from .isolation import assert_safe_leaf
from .profile_state import atomic_json, publish_manifest, read_manifest
from .recovery import fsync_directory

MARKER = "desktop-data-transition.json"
QUARANTINE_ITEMS = ("web_storage", "web_cache", "recovery-evidence.json", "durable-actions", "pending-requests")
SOURCE_STATES = {
    "safety_backup_created", "live_apply_started", "live_apply_completed",
    "post_apply_validated", "reconciliation_completed", "complete",
    "rollback_pending", "rollback_started", "rollback_completed",
}


def _synthetic_abort(paths, phase):
    """Deterministic process-crash checkpoint, unavailable outside test area."""
    from .isolation import AREA
    if (os.environ.get("DLMS_DESKTOP_AUTOMATED") == "1"
            and os.environ.get("DLMS_DESKTOP_TEST_ABORT_AT") == phase
            and paths["root"].resolve().is_relative_to(AREA.resolve())):
        atomic_json(paths["root"] / "blockb-abort-evidence.json", {"phase": phase})
        os._exit(71)
    if (os.environ.get("DLMS_DESKTOP_AUTOMATED") == "1"
            and os.environ.get("DLMS_DESKTOP_TEST_PAUSE_AT") == phase
            and paths["root"].resolve().is_relative_to(AREA.resolve())):
        atomic_json(paths["root"] / "blockb-pause-evidence.json", {"phase": phase, "pid": os.getpid()})
        deadline = time.monotonic() + 45
        continue_path = paths["root"] / "blockb-pause-continue"
        while not continue_path.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        if not continue_path.exists():
            raise TransitionUnresolved("Synthetic restore pause was not released")


class TransitionUnresolved(RuntimeError):
    """Keep the marker and leave the application page closed."""


def _marker_path(paths):
    return paths["root"] / MARKER


def read_transition(paths):
    path = _marker_path(paths)
    assert_safe_leaf(path)
    if not path.exists():
        return None
    if path.stat().st_size > 32768:
        raise TransitionUnresolved("Desktop transition marker is oversized")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(value, dict) or value.get("version") != 1
                or not isinstance(value.get("profile_uuid"), str)
                or not isinstance(value.get("old_epoch"), str)
                or not isinstance(value.get("new_epoch"), str)
                or not isinstance(value.get("token"), str)
                or not isinstance(value.get("input_sha256"), str)
                or not isinstance(value.get("old_identity"), str)
                or not isinstance(value.get("operation_id"), (str, type(None)))
                or value.get("source_state") not in SOURCE_STATES | {"prepared"}
                or value.get("outcome") not in {None, "abandoned", "adopted", "rolled_back"}
                or not isinstance(value.get("moved"), dict)):
            raise ValueError("invalid transition fields")
        for key in ("profile_uuid", "old_epoch", "new_epoch"):
            uuid.UUID(value[key])
        if not (len(value["token"]) == 32 and all(c in "0123456789abcdef" for c in value["token"])):
            raise ValueError("invalid restore token")
        if not (len(value["input_sha256"]) == 64 and all(c in "0123456789abcdef" for c in value["input_sha256"])):
            raise ValueError("invalid archive digest")
        if value["operation_id"] is not None and (len(value["operation_id"]) != 32
                or any(c not in "0123456789abcdef" for c in value["operation_id"])):
            raise ValueError("invalid source operation")
        if set(value["moved"]) - set(QUARANTINE_ITEMS):
            raise ValueError("unknown quarantine item")
        return value
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise TransitionUnresolved(f"Desktop transition marker requires inspection: {path}") from exc


def _write(paths, value):
    atomic_json(_marker_path(paths), value)


def archive_digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def dataset_identity(app) -> str:
    """Logical SQLite rows plus the copied app's portable file inventory.

    A read-only transaction makes this suitable for a closed, single-writer
    profile. It is a reconciliation check, not a portable-format definition.
    """
    h = hashlib.sha256()
    database = Path(app.DB_PATH)
    if not database.is_file() or database.is_symlink():
        raise TransitionUnresolved("Desktop dataset database is missing or unsafe")
    try:
        conn = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
        try:
            for statement in conn.iterdump():
                h.update(statement.encode("utf-8"))
                h.update(b"\n")
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        raise TransitionUnresolved("Desktop dataset database cannot be inventoried") from exc
    for full, relative in app._backup_file_inventory():
        if relative in {"results.db", "results.db-wal", "results.db-shm"}:
            continue  # The logical SQLite dump above is the DB identity.
        path = Path(full)
        if path.is_symlink() or not path.is_file():
            raise TransitionUnresolved(f"Dataset file is unsafe: {relative}")
        h.update(relative.encode("utf-8"))
        h.update(b"\0")
        h.update(archive_digest(path).encode("ascii"))
        h.update(b"\n")
    return h.hexdigest()


def begin(paths, name, app, token: str, archive: Path, *, expected_digest: str | None = None):
    if read_transition(paths) is not None:
        raise TransitionUnresolved("A previous Desktop data transition is unresolved")
    manifest = read_manifest(paths, name)
    if manifest is None:
        raise TransitionUnresolved("Desktop identity must exist before import")
    from .backup_selection import digest as private_digest
    observed_digest = private_digest(archive)
    if expected_digest is not None and observed_digest != expected_digest:
        raise TransitionUnresolved("Confirmed private backup changed before transition publication")
    record = {
        "version": 1, "profile_uuid": manifest["uuid"],
        "old_epoch": manifest["epoch"], "new_epoch": str(uuid.uuid4()),
        "token": token, "input_sha256": observed_digest,
        "old_identity": dataset_identity(app), "operation_id": None,
        "source_state": "prepared", "outcome": None, "moved": {},
    }
    _write(paths, record)
    _synthetic_abort(paths, "marker")
    return record


def _matching(record, journal):
    if (not isinstance(journal, dict) or journal.get("staging", {}).get("token") != record["token"]
            or not isinstance(journal.get("operation_id"), str)):
        raise TransitionUnresolved("Source restore journal does not match Desktop transition")
    if record["operation_id"] is not None and record["operation_id"] != journal["operation_id"]:
        raise TransitionUnresolved("Source restore operation identity changed")


def source_checkpoint(paths, state: str, journal: dict):
    record = read_transition(paths)
    if record is None:
        return
    if state not in SOURCE_STATES:
        raise TransitionUnresolved("Unknown source restore checkpoint")
    _matching(record, journal)
    record.update(operation_id=journal["operation_id"], source_state=state)
    _write(paths, record)
    _synthetic_abort(paths, f"source-{state}")


def source_cleanup_receipt(paths, journal: dict):
    """Called before the source journal's final unlink, including startup repair."""
    record = read_transition(paths)
    if record is None:
        return
    _matching(record, journal)
    state = journal.get("state")
    outcome = {
        "safety_backup_created": "abandoned",
        "rollback_completed": "rolled_back",
        "reconciliation_completed": "adopted",
        "complete": "adopted",
    }.get(state)
    if outcome is None:
        raise TransitionUnresolved("Source attempted cleanup before a verified outcome")
    record.update(operation_id=journal["operation_id"], source_state=state, outcome=outcome)
    _write(paths, record)
    _synthetic_abort(paths, "source-receipt")


def pre_import_journal(paths):
    """Observe, never mutate, source state before app import can clean it."""
    record = read_transition(paths)
    if record is None:
        return None
    root = paths["backend"] / ".restore_operations"
    if not root.exists():
        return None
    if root.is_symlink() or not root.is_dir():
        raise TransitionUnresolved("Source restore journal directory is unsafe")
    journals = list(root.glob("restore_*.json"))
    if len(journals) > 1:
        raise TransitionUnresolved("Multiple source restore journals require inspection")
    if not journals:
        return None
    path = journals[0]
    assert_safe_leaf(path)
    if path.stat().st_size > 32768:
        raise TransitionUnresolved("Source restore journal is oversized")
    try:
        journal = json.loads(path.read_text(encoding="utf-8"))
        _matching(record, journal)
        if journal.get("state") not in SOURCE_STATES:
            raise ValueError("source state")
        return {"operation_id": journal["operation_id"], "state": journal["state"]}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise TransitionUnresolved("Source restore journal requires inspection before startup") from exc


def _quarantine(paths, record):
    root = paths["root"]
    target = root / "quarantine" / record["old_epoch"] / f"adoption-{record['token']}"
    for directory in (root / "quarantine", root / "quarantine" / record["old_epoch"], target):
        if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
            raise TransitionUnresolved("Desktop quarantine path is unsafe")
        if not directory.exists():
            directory.mkdir(mode=0o700)
            fsync_directory(directory.parent)
    owner = target / "transition-owner.json"
    assert_safe_leaf(owner)
    if owner.exists():
        if owner.stat().st_size > 4096:
            raise TransitionUnresolved("Desktop quarantine owner receipt is oversized")
        if json.loads(owner.read_text()) != {"token": record["token"], "profile_uuid": record["profile_uuid"]}:
            raise TransitionUnresolved("Existing quarantine belongs to a different transition")
    else:
        if any(target.iterdir()):
            raise TransitionUnresolved("Existing quarantine has no ownership receipt")
        atomic_json(owner, {"token": record["token"], "profile_uuid": record["profile_uuid"]})
    sources = {
        "web_storage": paths["web_storage"],
        "web_cache": paths["web_cache"],
        "recovery-evidence.json": paths["root"] / "recovery-evidence.json",
        "durable-actions": paths["root"] / "durable-actions",
        "pending-requests": paths["root"] / "pending-requests",
    }
    for key in QUARANTINE_ITEMS:
        src = sources[key]
        dst = target / key
        if src.is_symlink() or dst.is_symlink():
            raise TransitionUnresolved(f"Unsafe browser evidence path: {key}")
        expect_dir = key in {"web_storage", "web_cache", "durable-actions", "pending-requests"}
        for leaf in (src, dst):
            if leaf.exists() and (leaf.is_dir() if expect_dir else leaf.is_file()) is False:
                raise TransitionUnresolved(f"Unexpected browser evidence type: {key}")
        if record["moved"].get(key):
            if not dst.exists():
                raise TransitionUnresolved(f"Quarantined browser evidence is missing: {key}")
            if src.exists() and (not src.is_dir() or any(src.iterdir())):
                raise TransitionUnresolved(f"Old browser evidence reappeared after quarantine: {key}")
            continue
        if dst.exists():
            # A crash may occur after rename and before the progress receipt.
            if src.exists() and (not src.is_dir() or any(src.iterdir())):
                raise TransitionUnresolved(f"Quarantine source and destination both contain evidence: {key}")
        elif src.exists():
            src.rename(dst)
            fsync_directory(src.parent)
            fsync_directory(target)
            _synthetic_abort(paths, f"quarantine-{key}-renamed")
        else:
            # Optional close checkpoint may not have been created.
            if key != "recovery-evidence.json":
                raise TransitionUnresolved(f"Browser evidence path disappeared: {key}")
        record["moved"][key] = True
        _write(paths, record)
        _synthetic_abort(paths, f"quarantine-{key}-recorded")


def finalize(paths, name, app, pre_journal=None):
    """Run under the backend writer lock, before action replay/readiness."""
    record = read_transition(paths)
    if record is None:
        return None
    if pre_import_journal(paths) is not None:
        raise TransitionUnresolved("Matching source restore journal still needs cleanup; Desktop transition remains blocked")
    manifest = read_manifest(paths, name)
    if manifest is None or manifest["uuid"] != record["profile_uuid"] or manifest["epoch"] not in {record["old_epoch"], record["new_epoch"]}:
        raise TransitionUnresolved("Desktop profile identity changed during restore")
    archive = paths["root"] / "imports" / f"{record['token']}.zip"
    imports_root = archive.parent
    if imports_root.is_symlink() or not imports_root.is_dir():
        raise TransitionUnresolved("Desktop import-copy directory is unsafe")
    if not archive.is_file() or archive.is_symlink() or archive_digest(archive) != record["input_sha256"]:
        raise TransitionUnresolved("Preserved Desktop import copy is missing or changed")
    if record["outcome"] is None:
        if record["source_state"] == "prepared" and pre_journal is None and dataset_identity(app) == record["old_identity"]:
            record["outcome"] = "abandoned"
            _write(paths, record)
        else:
            raise TransitionUnresolved("Source restore outcome is not proved; keep the transition and safety backup")
    app._validate_current_restored_database(app.DB_PATH)
    if record["outcome"] == "abandoned":
        if dataset_identity(app) != record["old_identity"]:
            raise TransitionUnresolved("Pre-mutation dataset identity changed unexpectedly")
        if manifest["epoch"] != record["old_epoch"]:
            raise TransitionUnresolved("Old dataset has a new browser epoch")
    else:
        # Existing snapshot/portable validator checks cross-store relationships
        # before old browser evidence is moved or the new epoch is published.
        check_path, _ = app._create_dlms_backup("desktop-transition-verified")
        app._validate_dlms_backup(check_path)
        _quarantine(paths, record)
        if manifest["epoch"] == record["old_epoch"]:
            publish_manifest(paths, {**manifest, "epoch": record["new_epoch"]})
            _synthetic_abort(paths, "epoch-published")
    _marker_path(paths).unlink()
    fsync_directory(paths["root"])
    _synthetic_abort(paths, "marker-removed")
    return record["outcome"]

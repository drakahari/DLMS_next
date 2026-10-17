"""Offline, disposable Desktop backup adoption using the copied restore service."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import sys
import threading

from .backend import acquire_writer_lock
from .isolation import AREA, PROJECT, assert_safe_leaf, isolated_environment, profile_paths
from .frozen_runtime import source_environment, source_import_path
from .profile_state import atomic_json, read_manifest
from .recovery import DurableActions, fsync_directory
from .requests import PendingRequests
from .transition import begin, finalize, pre_import_journal, read_transition, TransitionUnresolved


class VerifiedImportFailure(RuntimeError):
    """Restore failed; application outcome was reconciled and is not adoption."""


def _progress(paths, stage: str) -> None:
    """Best-effort UI hint; never an authority for transaction outcome."""
    try:
        atomic_json(paths["root"] / "import-progress.json",
                    {"worker_pid": os.getpid(), "stage": stage})
    except (OSError, ValueError):
        pass


def _preserve_input(paths, original: Path, token: str) -> Path:
    resolved = original.resolve(strict=True)
    if original.is_symlink() or not resolved.is_file() or not resolved.is_relative_to(AREA.resolve()):
        raise ValueError("Select a regular synthetic backup inside this project's disposable test area")
    root = paths["root"] / "imports"
    if root.is_symlink() or (root.exists() and not root.is_dir()):
        raise ValueError("Desktop import-copy directory is unsafe")
    root.mkdir(mode=0o700, exist_ok=True)
    output = root / f"{token}.zip"
    assert_safe_leaf(output)
    if output.exists():
        raise FileExistsError("Desktop import-copy identity already exists")
    temporary = root / f".{token}.{secrets.token_hex(8)}.tmp"
    with resolved.open("rb") as source, temporary.open("xb") as target:
        shutil.copyfileobj(source, target, 1024 * 1024)
        target.flush()
        os.fsync(target.fileno())
    os.replace(temporary, output)
    fsync_directory(root)
    return output


def run(name: str, original: Path | None = None, *, selection_token: str | None = None) -> dict:
    from .maintenance import read_marker
    # Never create an absent backend while maintenance rollback may be between
    # its two atomic renames.
    if read_marker(name) is not None:
        raise TransitionUnresolved("A Desktop maintenance transition must reconcile before backup adoption")
    paths = profile_paths(name)
    owner_secret = os.environ.get("DLMS_DESKTOP_ADOPT_OWNER_SECRET")
    from PySide6.QtCore import QLockFile
    instance = None
    if owner_secret:
        from .ownership import process_start_ticks, verified_instance
        verified = verified_instance(paths["root"] / "instance-owner.json", name)
        if verified is None and os.environ.get("DLMS_DESKTOP_AUTOMATED") == "1":
            # The real launcher is checked by verified_instance. Qt test
            # drivers use a different -m entry point but must still be this
            # worker's exact parent with the recorded process start identity.
            from .isolation import AREA
            if paths["root"].resolve().is_relative_to(AREA.resolve()):
                descriptor = json.loads((paths["root"] / "instance-owner.json").read_text())
                if (descriptor.get("name") == name and descriptor.get("pid") == os.getppid()
                        and descriptor.get("start_ticks") == process_start_ticks(os.getppid())):
                    verified = descriptor.get("secret")
        if not verified or verified != owner_secret:
            raise TransitionUnresolved("Adoption caller does not own the Desktop window")
        descriptor = json.loads((paths["root"] / "instance-owner.json").read_text())
        if descriptor["pid"] != os.getppid():
            raise TransitionUnresolved("Adoption worker is not a child of the owning window")
    else:
        instance = QLockFile(str(paths["root"] / "instance.lock"))
        instance.setStaleLockTime(0)
        if not instance.tryLock(0):
            # A killed adoption worker may leave Qt's advisory lock file. Qt
            # removes it only after checking that its recorded owner is gone;
            # never remove a lock while a verified window descriptor exists.
            if (paths["root"] / "instance-owner.json").exists():
                raise TransitionUnresolved("Close the disposable Desktop window before command-line adoption")
            if not instance.removeStaleLockFile() or not instance.tryLock(0):
                raise TransitionUnresolved("Disposable profile is still owned; no second restore was started")
    try:
        return _run_owned(name, original, paths, selection_token=selection_token)
    finally:
        if instance is not None:
            instance.unlock()


def _run_owned(name: str, original: Path | None, paths: dict[str, Path], *, selection_token: str | None = None) -> dict:
    from .maintenance import read_marker
    if read_marker(name) is not None:
        raise TransitionUnresolved("A Desktop maintenance transition must reconcile before backup adoption")
    _progress(paths, "Checking this profile and unresolved saves…")
    manifest = read_manifest(paths, name)
    if manifest is None:
        raise ValueError("Open this disposable Desktop profile once before adopting a backup")
    from .import_operations import unresolved_count
    from .pack_operations import unresolved_count as pending_pack_installs
    if unresolved_count(paths["root"], manifest["epoch"]) or pending_pack_installs(paths["root"], manifest["epoch"]):
        raise TransitionUnresolved("A portable quiz import has unresolved accepted work or staging cleanup; resume it before backup adoption")
    if read_transition(paths) is not None:
        raise TransitionUnresolved("Resolve the existing Desktop data transition before importing another backup")
    test_mode = os.environ.get("DLMS_DESKTOP_AUTOMATED") == "1"
    abort_phase = os.environ.get("DLMS_DESKTOP_TEST_ABORT_AT") if test_mode else None
    pause_phase = os.environ.get("DLMS_DESKTOP_TEST_PAUSE_AT") if test_mode else None
    owner_nonce = os.environ.get("DLMS_DESKTOP_NONCE")
    env = isolated_environment(paths)
    env.update(DLMS_DESKTOP_PROFILE_NAME=name, DLMS_DESKTOP_PORT=str(manifest["port"]),
               DLMS_DESKTOP_NONCE=owner_nonce if owner_nonce and len(owner_nonce) >= 32 else secrets.token_hex(32), PYTHONNOUSERSITE="1")
    source_environment(env)
    if test_mode:
        env["DLMS_DESKTOP_AUTOMATED"] = "1"
    if abort_phase:
        env.update(DLMS_DESKTOP_AUTOMATED="1", DLMS_DESKTOP_TEST_ABORT_AT=abort_phase)
    if pause_phase:
        env.update(DLMS_DESKTOP_AUTOMATED="1", DLMS_DESKTOP_TEST_PAUSE_AT=pause_phase)
    os.environ.clear()
    os.environ.update(env)
    writer = acquire_writer_lock(paths["root"] / "backend-writer.lock")
    try:
        source_import_path()
        import app as captured_app  # noqa: PLC0415
        actions = DurableActions(paths, name, captured_app)
        # An offline import must not quietly settle a crash-surviving Study
        # or Exam action and then replace the dataset containing its result.
        # Reopen in Qt first so the owner can inspect that result.
        if list(actions.root.glob("*.json")):
            raise TransitionUnresolved("Accepted Study or Exam work needs recovery in this profile before importing a backup")
        actions.reconcile()
        pending = PendingRequests(paths, name, captured_app, actions.lock)
        if actions.pending_summary()["count"] or pending.count():
            raise TransitionUnresolved("Accepted Desktop work is unresolved; the backup was not adopted")
        selected = None
        if selection_token is not None:
            from .backup_selection import _archive_path, advance
            selected = advance(paths, name, selection_token, "confirmed", "claimed")
            token = selection_token
            archive = _archive_path(paths, token)
            _progress(paths, "Checking the confirmed private backup snapshot…")
        else:
            if original is None:
                raise ValueError("A backup source or confirmed selection is required")
            if not test_mode:
                raise ValueError("Normal Desktop imports require a confirmed private backup selection")
            token = secrets.token_hex(16)
            _progress(paths, "Copying the selected backup into this disposable profile…")
            archive = _preserve_input(paths, original, token)
        _progress(paths, "Validating archive, database and required assets…")
        stage = Path(captured_app._restore_staging_dir(token))
        captured_app._backup_service.create_backup_restore_stage(str(stage))
        try:
            from werkzeug.datastructures import FileStorage
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(archive, flags)
            with os.fdopen(descriptor, "rb") as stream:
                if selected is not None:
                    from .backup_selection import descriptor_digest
                    if not os.path.isfile(archive) or os.path.islink(archive):
                        raise ValueError("Confirmed private archive is unsafe")
                    before = descriptor_digest(stream)
                    if before != selected["sha256"]:
                        raise ValueError("Confirmed private archive changed before staging")
                upload = FileStorage(stream=stream, filename="synthetic-desktop-import.zip")
                report, semantics = captured_app._stage_dlms_backup(upload, token, stage_dir=str(stage))
                if selected is not None:
                    if descriptor_digest(stream) != selected["sha256"]:
                        raise ValueError("Confirmed private archive changed during staging")
            if selected is not None:
                from .backup_selection import digest
                if digest(stage / "restore.zip") != selected["sha256"]:
                    raise ValueError("Application restore stage differs from the confirmed bytes")
        except BaseException:
            # The existing stage function removes failed stages. Preserve the
            # input copy for diagnostics; no Desktop transition was begun.
            raise
        _progress(paths, "Validated; recording the dataset transition before the safety backup…")
        marker = begin(paths, name, captured_app, token, archive,
                       expected_digest=selected["sha256"] if selected is not None else None)
        if selected is not None and marker["input_sha256"] != selected["sha256"]:
            raise TransitionUnresolved("Confirmed input changed at transition publication; retained marker needs reconciliation")
        _progress(paths, "Creating a safety backup and applying the validated data. Keep this window open…")
        try:
            if selected is not None and digest(stage / "restore.zip") != selected["sha256"]:
                raise ValueError("Application restore stage changed before live apply")
            result = captured_app._complete_staged_restore(token)
        except BaseException:
            # A source rollback may already have completed. Resolve only when
            # its source receipt proves the outcome; otherwise keep the marker.
            _progress(paths, "Reconciling the failed restore against its journal and safety backup…")
            outcome = finalize(paths, name, captured_app, pre_import_journal(paths))
            raise VerifiedImportFailure(f"Backup was not adopted; verified {outcome}. Preserved input: {archive}")
        _progress(paths, "Verifying the dataset and isolating old browser recovery evidence…")
        outcome = finalize(paths, name, captured_app, pre_import_journal(paths))
        if selected is not None:
            try:
                from .backup_selection import advance
                advance(paths, name, token, "claimed", "completed", check_epoch=False)
            except Exception as exc:
                # The source and Desktop journals have already established the
                # outcome. Keep the claimed receipt as non-replayable evidence.
                print(f"[DLMS Desktop] Confirmed selection receipt cleanup needs inspection: {exc}", file=sys.stderr)
        _progress(paths, "Verified import complete; restarting the local application…")
        return {"outcome": outcome, "source_restore": "completed",
                "archive": str(archive), "input_sha256": marker["input_sha256"],
                "safety_backup": result["safety_path"], "cleanup_pending": result["cleanup_pending"],
                "staged_files": report["file_count"], "semantic_validation": semantics["status"]}
    finally:
        writer.close()


def main(argv=None):
    if sys.platform == "darwin":
        from .macos_processes import seal_private_descriptors
        seal_private_descriptors()
    parser = argparse.ArgumentParser(description="Adopt a synthetic backup into a closed disposable Desktop profile")
    parser.add_argument("--profile", required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--archive", type=Path)
    group.add_argument("--selection")
    args = parser.parse_args(argv)
    try:
        pipe_text = os.environ.get("DLMS_DESKTOP_ADOPT_PARENT_PIPE")
        parent_text = os.environ.get("DLMS_DESKTOP_ADOPT_PARENT_PID")
        if pipe_text is not None or parent_text is not None:
            if pipe_text is None or parent_text is None or os.getppid() != int(parent_text):
                raise TransitionUnresolved("Adoption worker parent ownership is inconsistent")
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
            threading.Thread(target=watch_parent, name="desktop-adoption-owner", daemon=True).start()
        result = run(args.profile, args.archive, selection_token=args.selection)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"DLMS Desktop adoption stopped safely: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3 if isinstance(exc, VerifiedImportFailure) else 2


if __name__ == "__main__":
    raise SystemExit(main())

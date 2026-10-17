"""Bind a Local backup confirmation to one private, validated byte sequence.

The source may be mutable. The selected path is never reopened by the managed
restore worker; its private copy and the application's restore.zip are checked
against the durable confirmation receipt before live data can change.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import secrets
import stat

from .frozen_runtime import source_import_path
from .isolation import AREA, assert_safe_leaf
from .profile_state import atomic_json, read_manifest
from .recovery import fsync_directory
from .platform_files import owned, lock

MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024  # Captured app BACKUP_UPLOAD_MAX_BYTES.
CHUNK = 1024 * 1024
RECEIPT_VERSION = 1


def _private_root(paths: dict[str, Path]) -> Path:
    root = paths["root"] / "imports"
    if root.is_symlink() or (root.exists() and not root.is_dir()):
        raise ValueError("Desktop import-copy directory is unsafe")
    root.mkdir(mode=0o700, exist_ok=True)
    if root.resolve() != paths["root"].resolve() / "imports":
        raise ValueError("Desktop import-copy directory escapes its profile")
    if not owned(root, private=True):
        raise ValueError("Desktop import-copy directory is not private")
    return root


def _source_path(path: Path) -> tuple[Path, os.stat_result]:
    raw = path.absolute()
    if (not path.is_absolute() or (os.name != "nt" and path.anchor != "/")
            or ".." in path.parts or raw.suffix.lower() != ".zip"):
        raise ValueError("Choose an absolute local path to a DLMS backup ZIP")
    for component in (raw, *raw.parents):
        if component.is_symlink():
            raise ValueError("Selected backup path contains a symbolic link")
    if os.name == "nt":
        from .windows_files import assert_path
        assert_path(raw, leaf=True)
    resolved = raw.resolve(strict=True)
    selected = os.lstat(raw)
    if not stat.S_ISREG(selected.st_mode) or not owned(raw):
        raise ValueError("Selected backup must be a regular file owned by the current user")
    return raw, selected


def _same_source(path: Path, descriptor: os.stat_result, initial: os.stat_result) -> bool:
    try:
        _, current = _source_path(path)
    except (OSError, ValueError):
        return False
    # Windows CPython's path stat and CRT-descriptor fstat expose different
    # legacy st_ctime meanings. Compare their explicit birth time instead;
    # the pinned read handle denies writes/deletion throughout the copy.
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns",
              "st_birthtime_ns" if os.name == "nt" else "st_ctime_ns")
    return all(getattr(descriptor, key) == getattr(initial, key) == getattr(current, key)
               for key in fields) and stat.S_ISREG(current.st_mode)


def _open_source(path: Path) -> int:
    """Pin each parent while opening; a check/open symlink swap cannot redirect."""
    if os.name == "nt":
        from .windows_files import open_read
        return open_read(path)
    directory = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parent.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        return os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    finally:
        os.close(directory)


def digest(path: Path) -> str:
    assert_safe_leaf(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("Staged backup is not a regular file")
        value = hashlib.sha256()
        total = 0
        with os.fdopen(fd, "rb", closefd=False) as stream:
            for block in iter(lambda: stream.read(CHUNK), b""):
                total += len(block)
                if total > MAX_ARCHIVE_BYTES:
                    raise ValueError("Private backup grew beyond the supported 1 GiB import limit")
                value.update(block)
        return value.hexdigest()
    finally:
        os.close(fd)


def descriptor_digest(stream, *, limit: int = MAX_ARCHIVE_BYTES) -> str:
    """Hash an opened regular-file descriptor without buffering the archive."""
    stream.seek(0)
    value = hashlib.sha256()
    total = 0
    while block := stream.read(CHUNK):
        total += len(block)
        if total > limit:
            raise ValueError("Backup exceeds the supported 1 GiB import limit")
        value.update(block)
    stream.seek(0)
    return value.hexdigest()


def _validate_archive(path: Path) -> dict:
    # Import the copied pure service, never source.app: importing app would
    # initialize application data while the Local backend owns its writer lock.
    source_import_path()
    from dlms.services import backups

    excluded = {".restore_operations", "backups", "uploads", "content_pack_staging",
                "external_ai_drafts"}
    return backups.validate_dlms_backup(
        str(path), backup_manifest="DLMS_BACKUP_MANIFEST.json",
        backup_data_prefix="DLMS_DATA/", backup_schema_version=1,
        max_files=20000, max_uncompressed=2 * 1024 * 1024 * 1024,
        max_compressed=2 * 1024 * 1024 * 1024,
        max_single_file=768 * 1024 * 1024,
        max_compression_ratio=1000, ratio_min_uncompressed=16 * 1024 * 1024,
        rel_is_excluded=lambda rel: backups.backup_rel_is_excluded(
            rel, data_root_marker=".dlms-data-root", excluded_top_level=excluded),
        safe_member_name=backups.safe_backup_member_name,
    )


def _receipt_path(paths: dict[str, Path], token: str) -> Path:
    if len(token) != 32 or any(char not in "0123456789abcdef" for char in token):
        raise ValueError("Invalid backup selection identity")
    return _private_root(paths) / f"{token}.json"


def _archive_path(paths: dict[str, Path], token: str) -> Path:
    _receipt_path(paths, token)  # Validate token and private parent.
    return paths["root"] / "imports" / f"{token}.zip"


def prepare(paths: dict[str, Path], name: str, source: Path, *, after_chunk=None) -> dict:
    """Publish a private copy and receipt only after stable-copy checks pass."""
    identity = read_manifest(paths, name)
    if identity is None:
        raise ValueError("The destination profile has no stable Desktop identity")
    raw, initial = _source_path(source)
    if initial.st_size > MAX_ARCHIVE_BYTES:
        raise ValueError("Backup exceeds the supported 1 GiB import limit")
    root = _private_root(paths)
    token = secrets.token_hex(16)
    final = _archive_path(paths, token)
    partial = root / f".{token}.part"
    receipt_path = _receipt_path(paths, token)
    source_fd = _open_source(raw)
    try:
        opened = os.fstat(source_fd)
        if not stat.S_ISREG(opened.st_mode) or not _same_source(raw, opened, initial):
            raise ValueError("Selected backup changed before copying began")
        target_fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                            | getattr(os, "O_NOFOLLOW", 0), 0o600)
        copied = hashlib.sha256()
        total = 0
        try:
            with os.fdopen(source_fd, "rb", closefd=False) as input_file, os.fdopen(target_fd, "wb") as output:
                while block := input_file.read(CHUNK):
                    total += len(block)
                    if total > MAX_ARCHIVE_BYTES:
                        raise ValueError("Backup grew beyond the supported 1 GiB import limit")
                    output.write(block)
                    copied.update(block)
                    if after_chunk is not None:
                        after_chunk(total)
                output.flush()
                os.fsync(output.fileno())
            os.lseek(source_fd, 0, os.SEEK_SET)
            with os.fdopen(source_fd, "rb", closefd=False) as input_file:
                second_digest = descriptor_digest(input_file)
            if second_digest != copied.hexdigest() or not _same_source(raw, os.fstat(source_fd), initial):
                raise ValueError("Selected backup changed while it was copied; no confirmation was offered")
            if total != initial.st_size:
                raise ValueError("Selected backup size changed while it was copied")
            if os.name != "nt":
                os.chmod(partial, 0o400)
            if final.exists() or final.is_symlink():
                raise FileExistsError("Backup selection identity already exists")
            os.replace(partial, final)
            fsync_directory(root)
            if digest(final) != copied.hexdigest():
                raise ValueError("Private backup copy changed before validation")
            report = _validate_archive(final)
            manifest = report["manifest"]
            value = {
                "version": RECEIPT_VERSION, "token": token, "state": "ready",
                "profile": name, "profile_uuid": identity["uuid"], "epoch": identity["epoch"],
                "archive": final.name, "sha256": copied.hexdigest(), "size": total,
                "source_name": raw.name, "schema_version": manifest["schema_version"],
                "file_count": report["file_count"],
                "summary": {key: item for key, item in (manifest.get("summary") or {}).items()
                            if key in {"quizzes", "attempts", "content_packs",
                                       "pdf_question_banks", "pdf_terminology_banks"}
                            and type(item) is int and item >= 0}
                if isinstance(manifest.get("summary"), dict) else {},
            }
            atomic_json(receipt_path, value)
            return value
        except BaseException:
            partial.unlink(missing_ok=True)
            if not receipt_path.exists():
                final.unlink(missing_ok=True)
            raise
    finally:
        os.close(source_fd)


def read(paths: dict[str, Path], name: str, token: str, *, state: str | None = None,
         check_epoch: bool = True) -> dict:
    receipt_path = _receipt_path(paths, token)
    assert_safe_leaf(receipt_path)
    if not receipt_path.is_file() or receipt_path.stat().st_size > 32768:
        raise ValueError("Backup selection receipt is missing or oversized")
    import json
    value = json.loads(receipt_path.read_text())
    archive = _archive_path(paths, token)
    if (value.get("version") != RECEIPT_VERSION or value.get("token") != token
            or value.get("profile") != name or value.get("archive") != archive.name
            or value.get("state") not in {"ready", "confirmed", "claimed", "completed", "refused", "canceled"}
            or not isinstance(value.get("sha256"), str) or len(value["sha256"]) != 64
            or not isinstance(value.get("size"), int) or value["size"] < 0
            or value["size"] > MAX_ARCHIVE_BYTES):
        raise ValueError("Backup selection receipt is invalid")
    if state is not None and value["state"] != state:
        raise ValueError("Backup selection was already used or is no longer confirmable")
    if check_epoch:
        manifest = read_manifest(paths, name)
        if manifest is None or (manifest["uuid"], manifest["epoch"]) != (
                value.get("profile_uuid"), value.get("epoch")):
            raise ValueError("Backup selection belongs to another profile or dataset epoch")
    assert_safe_leaf(archive)
    if not archive.is_file() or archive.stat().st_size != value["size"] or digest(archive) != value["sha256"]:
        raise ValueError("Confirmed private backup bytes changed; import is blocked")
    return value


def advance(paths: dict[str, Path], name: str, token: str, old: str, new: str,
            *, check_epoch: bool = True) -> dict:
    if (old, new) not in {("ready", "confirmed"), ("ready", "canceled"),
                          ("confirmed", "claimed"), ("confirmed", "refused"),
                          ("claimed", "completed")}:
        raise ValueError("Invalid backup selection transition")
    _receipt_path(paths, token)
    lock_path = _private_root(paths) / f"{token}.lock"
    assert_safe_leaf(lock_path)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        lock(fd, blocking=True)
        value = read(paths, name, token, state=old, check_epoch=check_epoch)
        value["state"] = new
        atomic_json(_receipt_path(paths, token), value)
        return value
    finally:
        os.close(fd)


def cancel(paths: dict[str, Path], name: str, token: str) -> None:
    advance(paths, name, token, "ready", "canceled")
    archive = _archive_path(paths, token)
    assert_safe_leaf(archive)
    archive.unlink()
    fsync_directory(archive.parent)

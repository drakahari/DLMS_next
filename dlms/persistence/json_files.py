"""Durable low-level file operations for DLMS."""

import json
import os
import re
import tempfile


# ``tempfile.mkstemp`` uses one eight-character candidate from this alphabet
# between the caller-provided prefix and suffix on supported CPython runtimes.
_TEMPFILE_CANDIDATE_RE = re.compile(r"^[a-z0-9_]{8}$")


def _atomic_persistence_target_name(name):
    """Return the original data basename encoded by a persistence temp name."""
    basename = os.path.basename(os.fspath(name))
    if not basename.startswith(".") or not basename.endswith(".tmp"):
        return None

    stem = basename[1:-4]
    target, separator, candidate = stem.rpartition(".")
    if separator and target and _TEMPFILE_CANDIDATE_RE.fullmatch(candidate):
        return target

    target, separator, candidate = stem.rpartition(".corrupt-")
    if separator and target and _TEMPFILE_CANDIDATE_RE.fullmatch(candidate):
        return target
    return None


def _fsync_json_directory(path, *, os_module=None):
    """Best-effort directory durability after replacing a durable JSON file."""
    os_module = os if os_module is None else os_module
    descriptor = None
    try:
        descriptor = os_module.open(path, os_module.O_RDONLY)
        os_module.fsync(descriptor)
    except OSError:
        # Directory handles/fsync are unavailable on some supported platforms.
        pass
    finally:
        if descriptor is not None:
            os_module.close(descriptor)


def _atomic_write_text(
    path,
    text,
    *,
    encoding="utf-8",
    os_module=None,
    tempfile_module=None,
    fsync_directory=None,
):
    """Durably replace one text file through a same-directory temporary file."""
    os_module = os if os_module is None else os_module
    tempfile_module = tempfile if tempfile_module is None else tempfile_module
    if fsync_directory is None:
        def fsync_directory(directory):
            return _fsync_json_directory(directory, os_module=os_module)

    directory = os_module.path.dirname(os_module.path.abspath(path))
    os_module.makedirs(directory, exist_ok=True)
    descriptor, temp_path = tempfile_module.mkstemp(
        prefix=f".{os_module.path.basename(path)}.", suffix=".tmp", dir=directory
    )
    try:
        with os_module.fdopen(descriptor, "w", encoding=encoding) as temporary:
            descriptor = None
            temporary.write(text)
            temporary.flush()
            os_module.fsync(temporary.fileno())
        os_module.replace(temp_path, path)
        fsync_directory(directory)
    finally:
        if descriptor is not None:
            os_module.close(descriptor)
        if os_module.path.exists(temp_path):
            os_module.remove(temp_path)


def _preserve_malformed_json(
    path,
    *,
    os_module=None,
    tempfile_module=None,
    open_file=None,
    fsync_directory=None,
):
    """Keep one recoverable copy of malformed JSON without backup-file churn."""
    os_module = os if os_module is None else os_module
    tempfile_module = tempfile if tempfile_module is None else tempfile_module
    open_file = open if open_file is None else open_file
    if fsync_directory is None:
        def fsync_directory(directory):
            return _fsync_json_directory(directory, os_module=os_module)

    with open_file(path, "rb") as source:
        malformed_bytes = source.read()

    backup_path = path + ".corrupt"
    try:
        with open_file(backup_path, "rb") as existing_backup:
            if existing_backup.read() == malformed_bytes:
                return backup_path
    except FileNotFoundError:
        pass

    directory = os_module.path.dirname(os_module.path.abspath(path))
    os_module.makedirs(directory, exist_ok=True)
    descriptor, temp_path = tempfile_module.mkstemp(
        prefix=f".{os_module.path.basename(path)}.corrupt-",
        suffix=".tmp",
        dir=directory,
    )
    try:
        with os_module.fdopen(descriptor, "wb") as temporary:
            descriptor = None
            temporary.write(malformed_bytes)
            temporary.flush()
            os_module.fsync(temporary.fileno())
        os_module.replace(temp_path, backup_path)
        fsync_directory(directory)
    finally:
        if descriptor is not None:
            os_module.close(descriptor)
        if os_module.path.exists(temp_path):
            os_module.remove(temp_path)
    return backup_path


def _atomic_write_json(
    path,
    payload,
    *,
    indent=2,
    ensure_ascii=True,
    expected_type=None,
    os_module=None,
    tempfile_module=None,
    json_module=None,
    open_file=None,
    preserve_malformed=None,
    fsync_directory=None,
):
    """Durably replace one user-owned JSON file while retaining malformed input."""
    os_module = os if os_module is None else os_module
    tempfile_module = tempfile if tempfile_module is None else tempfile_module
    json_module = json if json_module is None else json_module
    open_file = open if open_file is None else open_file
    if fsync_directory is None:
        def fsync_directory(directory):
            return _fsync_json_directory(directory, os_module=os_module)
    if preserve_malformed is None:
        def preserve_malformed(malformed_path):
            return _preserve_malformed_json(
                malformed_path,
                os_module=os_module,
                tempfile_module=tempfile_module,
                open_file=open_file,
                fsync_directory=fsync_directory,
            )

    directory = os_module.path.dirname(os_module.path.abspath(path))
    os_module.makedirs(directory, exist_ok=True)

    if os_module.path.isfile(path):
        malformed = False
        try:
            with open_file(path, "r", encoding="utf-8") as current:
                current_payload = json_module.load(current)
            malformed = expected_type is not None and not isinstance(
                current_payload, expected_type
            )
        except (json_module.JSONDecodeError, UnicodeError):
            malformed = True
        if malformed:
            preserve_malformed(path)

    descriptor, temp_path = tempfile_module.mkstemp(
        prefix=f".{os_module.path.basename(path)}.", suffix=".tmp", dir=directory
    )
    try:
        with os_module.fdopen(descriptor, "w", encoding="utf-8") as temporary:
            descriptor = None
            json_module.dump(
                payload,
                temporary,
                indent=indent,
                ensure_ascii=ensure_ascii,
            )
            temporary.flush()
            os_module.fsync(temporary.fileno())
        with open_file(temp_path, "r", encoding="utf-8") as temporary:
            validated = json_module.load(temporary)
        if expected_type is not None and not isinstance(validated, expected_type):
            raise ValueError(f"JSON payload must contain {expected_type.__name__}")
        os_module.replace(temp_path, path)
        fsync_directory(directory)
    finally:
        if descriptor is not None:
            os_module.close(descriptor)
        if os_module.path.exists(temp_path):
            os_module.remove(temp_path)

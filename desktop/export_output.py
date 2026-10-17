"""Adapted no-replace primitive from backup_output; backup contract unchanged.

Explicit native export publication; never overwrite an existing destination.

Only the native Local/Server Save As chooser calls this adapter. Directory descriptors pin each
component; a completed private download is copied, synced, then linked under
the selected name with no replacement. A crash can leave a private .part file
or a complete published file, never a truncated pre-existing destination.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import secrets
import stat

from .backup_selection import MAX_ARCHIVE_BYTES, CHUNK


@contextmanager
def parent_fd(path: Path):
    if path.anchor != "/" or ".." in path.parts or not path.name or path.name in {".", ".."} or any(ord(c)<32 or ord(c)==127 for c in path.name):
        raise ValueError("Choose an absolute local export filename without control characters")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parent.parts[1:]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise ValueError("Choose a folder owned by you that others cannot modify")
        yield fd
    finally:
        os.close(fd)


def select(path: Path, *, forbidden=()) -> dict:
    if any(path.is_relative_to(root) for root in forbidden):
        raise ValueError("Choose a visible folder outside managed application storage")
    with parent_fd(path) as fd:
        try:
            os.stat(path.name, dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError("That filename already exists; choose a different name. No file was replaced")
        info = os.fstat(fd)
        return {"path": str(path), "parent_dev": info.st_dev, "parent_ino": info.st_ino,
                "operation": secrets.token_hex(16)}


def publish(source: Path, selection: dict, *, checkpoint=None) -> dict:
    destination = Path(selection["path"])
    temporary = f".dlms-export-{selection['operation']}.part"
    linked = False
    with parent_fd(destination) as directory:
        info = os.fstat(directory)
        if (info.st_dev, info.st_ino) != (selection["parent_dev"], selection["parent_ino"]):
            raise ValueError("Export destination folder changed after selection")
        source_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            initial = os.fstat(source_fd)
            if not stat.S_ISREG(initial.st_mode) or initial.st_size > MAX_ARCHIVE_BYTES:
                raise ValueError("Completed export is not a supported regular file")
            target = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=directory)
            target_identity = os.fstat(target)
            def owns_temporary():
                try:
                    found = os.stat(temporary, dir_fd=directory, follow_symlinks=False)
                    return (found.st_dev, found.st_ino) == (target_identity.st_dev, target_identity.st_ino)
                except FileNotFoundError:
                    return False
            digest = hashlib.sha256()
            total = 0
            try:
                # Hold this inode open until cleanup, preventing inode reuse
                # from turning a substituted temporary name into an owned file.
                with os.fdopen(target, "wb", closefd=False) as output:
                    while block := os.read(source_fd, CHUNK):
                        total += len(block)
                        if total > MAX_ARCHIVE_BYTES:
                            raise ValueError("Export exceeds the supported publication limit")
                        output.write(block)
                        digest.update(block)
                        if checkpoint:
                            checkpoint("copy")
                    output.flush()
                    os.fsync(output.fileno())
                current = os.fstat(source_fd)
                if any(getattr(initial, key) != getattr(current, key) for key in
                       ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")) or total != initial.st_size:
                    raise ValueError("Private export changed during publication")
                with parent_fd(destination) as check:
                    check_info = os.fstat(check)
                    if (check_info.st_dev, check_info.st_ino) != (info.st_dev, info.st_ino):
                        raise ValueError("Destination path changed during publication")
                if checkpoint:
                    checkpoint("before_publish")
                if not owns_temporary():
                    raise ValueError("Publication temporary file changed; no export was published")
                os.link(temporary, destination.name, src_dir_fd=directory, dst_dir_fd=directory,
                        follow_symlinks=False)
                linked = True
                os.fsync(directory)
                if checkpoint:
                    checkpoint("published")
                with parent_fd(destination) as check:
                    check_info = os.fstat(check)
                    if (check_info.st_dev, check_info.st_ino) != (info.st_dev, info.st_ino):
                        raise ValueError("Destination moved after publication; inspect the selected folder")
                if not owns_temporary():
                    raise ValueError("Publication temporary name changed during cleanup; retained for inspection")
                os.unlink(temporary, dir_fd=directory)
                os.fsync(directory)
                return {"path": str(destination), "sha256": digest.hexdigest(), "bytes": total}
            except BaseException as exc:
                # Never delete the destination: it may be a complete output or
                # an unrelated file that won a collision. Preserve crash evidence.
                if linked:
                    raise RuntimeError(f"A complete export may exist at {destination}; publication cleanup/acknowledgment failed: {exc}") from exc
                if owns_temporary():
                    os.unlink(temporary, dir_fd=directory)
                raise
            finally:
                os.close(target)
        finally:
            os.close(source_fd)

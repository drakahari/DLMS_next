"""No-replace Windows backup publication with pinned parent and file handles."""
import ctypes as c
from ctypes import wintypes as w
import hashlib
import os
from pathlib import Path

from .backup_selection import CHUNK, MAX_ARCHIVE_BYTES
from .windows_files import (pinned_parents, owned, identity, info, open_read,
                            create, checked, close, k, api)

rename_info = api(k, "SetFileInformationByHandle", w.BOOL, w.HANDLE, c.c_int, w.LPVOID, w.DWORD)
write_file = api(k, "WriteFile", w.BOOL, w.HANDLE, w.LPVOID, w.DWORD, c.POINTER(w.DWORD), w.LPVOID)
flush = api(k, "FlushFileBuffers", w.BOOL, w.HANDLE)

def select(path, *, forbidden=()):
    import secrets
    if path.suffix.lower() != ".zip" or any(path.is_relative_to(root) for root in forbidden):
        raise ValueError("Choose a ZIP outside managed storage")
    with pinned_parents(path) as parent:
        owned(path.parent)
        if path.exists() or path.is_symlink():
            raise FileExistsError("Destination exists; no file was replaced")
        return {"path": str(path), "parent_identity": identity(parent), "operation": secrets.token_hex(16)}

def publish(source, selection, *, checkpoint=None):
    destination = Path(selection["path"])
    temporary = destination.parent / (".dlms-backup-" + selection["operation"] + ".part")
    linked = False
    with pinned_parents(destination) as parent:
        if tuple(selection["parent_identity"]) != identity(parent):
            raise ValueError("Backup destination folder changed after selection")
        owned(destination.parent)
        source_fd = open_read(source)
        handle = None
        try:
            initial = os.fstat(source_fd)
            if initial.st_size > MAX_ARCHIVE_BYTES:
                raise ValueError("Completed backup exceeds the supported limit")
            # DELETE access permits our own handle-based rename; no sharing of
            # deletion/writes means another opener cannot replace the temp name.
            handle = create(str(temporary), 0xC0010000, 1, None, 1, 0x00200000 | 0x80000000, None)
            if handle == w.HANDLE(-1).value:
                handle = None
                raise c.WinError(c.get_last_error())
            info(handle)
            digest, total = hashlib.sha256(), 0
            while block := os.read(source_fd, CHUNK):
                total += len(block)
                if total > MAX_ARCHIVE_BYTES:
                    raise ValueError("Backup grew beyond publication limit")
                data = c.create_string_buffer(block)
                written = w.DWORD()
                checked(write_file(handle, data, len(block), c.byref(written), None))
                if written.value != len(block):
                    raise OSError("Windows backup write was incomplete")
                digest.update(block)
                if checkpoint:
                    checkpoint("copy")
            checked(flush(handle))
            current = os.fstat(source_fd)
            if total != initial.st_size or any(getattr(initial, key) != getattr(current, key)
                    for key in ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")):
                raise ValueError("Private backup changed during publication")
            if checkpoint:
                checkpoint("before_publish")
            name = str(destination).encode("utf-16-le")
            class Rename(c.Structure):
                _fields_ = [("replace", w.DWORD), ("root", w.HANDLE), ("length", w.DWORD),
                            ("name", w.WCHAR * (len(name) // 2 + 1))]
            value = Rename()
            value.length = len(name)
            value.name = str(destination)
            checked(rename_info(handle, 3, c.byref(value), c.sizeof(value)))
            linked = True
            checked(flush(handle))
            if checkpoint:
                checkpoint("published")
            return {"path": str(destination), "sha256": digest.hexdigest(), "bytes": total}
        except BaseException as exc:
            if linked:
                raise RuntimeError(f"A complete backup may exist at {destination}; acknowledgment failed: {exc}") from exc
            raise
        finally:
            try:
                if handle:
                    try:
                        if not linked:
                            try:
                                if checkpoint:
                                    checkpoint("before_cleanup")
                            finally:
                                # Delete this exact open file, before releasing
                                # its no-delete-sharing handle. No pathname is
                                # deleted after the exclusive handle closes.
                                delete = c.c_ubyte(1)  # FILE_DISPOSITION_INFO
                                checked(rename_info(handle, 4, c.byref(delete), c.sizeof(delete)))
                    finally:
                        close(handle)
            finally:
                os.close(source_fd)

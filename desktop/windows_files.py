"""Windows file identity, reparse-point refusal and private ACL checks.

No global ACLs change. Parent handles deny rename/delete while a selected
file is opened; a selected read handle also denies writes and deletion.
"""
from __future__ import annotations

from contextlib import contextmanager
import ctypes as c
from ctypes import wintypes as w
import msvcrt
import os
from pathlib import Path
import stat

from .windows_processes import api, checked, close, current, process_sid, sid_text, k, a, local_free

create = api(k, "CreateFileW", w.HANDLE, w.LPCWSTR, w.DWORD, w.DWORD, w.LPVOID,
             w.DWORD, w.DWORD, w.HANDLE)
get_security = api(a, "GetSecurityInfo", w.DWORD, w.HANDLE, c.c_int, w.DWORD,
                   c.POINTER(w.LPVOID), c.POINTER(w.LPVOID), c.POINTER(w.LPVOID),
                   c.POINTER(w.LPVOID), c.POINTER(w.LPVOID))
get_ace = api(a, "GetAce", w.BOOL, w.LPVOID, w.DWORD, c.POINTER(w.LPVOID))
move = api(k, "MoveFileExW", w.BOOL, w.LPCWSTR, w.LPCWSTR, w.DWORD)

class FileInfo(c.Structure):
    _fields_ = [("attributes", w.DWORD), ("created", w.FILETIME), ("accessed", w.FILETIME),
                ("written", w.FILETIME), ("volume", w.DWORD), ("size_hi", w.DWORD),
                ("size_lo", w.DWORD), ("links", w.DWORD), ("index_hi", w.DWORD), ("index_lo", w.DWORD)]

information = api(k, "GetFileInformationByHandle", w.BOOL, w.HANDLE, c.POINTER(FileInfo))

def lexical(path):
    path = Path(path)
    # Candidate v1 supports local drive paths only. No devices, UNC, ADS,
    # trailing-dot/space aliases, traversal, DOS device names or reparse points.
    if (not path.is_absolute() or len(path.drive) != 2 or path.drive[1] != ":"
            or str(path).startswith("\\\\") or ".." in path.parts):
        raise ValueError("Choose an absolute local Windows drive path")
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in (*range(1, 10), '¹', '²', '³')),
                *(f"LPT{i}" for i in (*range(1, 10), '¹', '²', '³'))}
    for part in path.parts[1:]:
        if (part.endswith((" ", ".")) or any(x in part for x in ':<>"|?*')
                or any(ord(x) < 32 for x in part) or part.split(".")[0].strip().upper() in reserved):
            raise ValueError("Windows path has an ambiguous or reserved component")
    return path

def info(handle):
    result = FileInfo()
    checked(information(handle, c.byref(result)))
    if result.attributes & 0x400:
        raise ValueError("Windows reparse points are not accepted")
    return result

def identity(handle):
    value = info(handle)
    return value.volume, value.index_hi, value.index_lo

def _open(path, *, directory=False, read=False):
    handle = create(str(path), 0x20000 | 0x80 | (1 if directory else 0) | (0x80000000 if read else 0),
                    1 if read else 3, None, 3, 0x00200000 | (0x02000000 if directory else 0), None)
    if handle == w.HANDLE(-1).value:
        raise c.WinError(c.get_last_error())
    try:
        value = info(handle)
        if bool(value.attributes & 0x10) != directory:
            raise ValueError("Windows path type changed")
        if not directory and value.links != 1:
            raise ValueError("Hard-linked files are not accepted")
        return handle
    except BaseException:
        close(handle)
        raise

@contextmanager
def pinned_parents(path):
    path = lexical(path)
    handles = []
    try:
        for parent in reversed(path.parents):
            handles.append(_open(parent, directory=True))
        yield handles[-1]
    finally:
        for handle in reversed(handles):
            close(handle)

def assert_path(path, *, leaf=False):
    path = lexical(path)
    # Existing prefix only: creation is performed under its checked private
    # profile root. Selected input/output paths additionally pin every parent.
    for item in reversed((path, *path.parents)):
        try:
            value = item.lstat()
        except FileNotFoundError:
            continue
        if value.st_file_attributes & 0x400:
            raise ValueError(f"Windows reparse point refused: {item}")
        if item == path and leaf and not stat.S_ISREG(value.st_mode):
            raise ValueError(f"Windows output is not a regular file: {item}")

def owned(path, *, private=False):
    path = lexical(path)
    assert_path(path)
    handle = _open(path, directory=path.is_dir())
    try:
        owned_handle(handle, private=private)
    finally:
        close(handle)


def owned_handle(handle, *, private=False):
    """Check the retained object's ACL, without reopening a replaceable name."""
    owner, dacl, descriptor = w.LPVOID(), w.LPVOID(), w.LPVOID()
    try:
        error = get_security(handle, 1, 1 | 4, c.byref(owner), None, c.byref(dacl), None, c.byref(descriptor))
        if error:
            raise c.WinError(error)
        sid = process_sid(current())
        if sid_text(owner) != sid:
            raise ValueError("Windows object is owned by another account")
        if not dacl:
            raise ValueError("Windows path has an unrestricted DACL")
        # ACL header: revision/reserved/size/ace-count/reserved, all WORDs
        count = c.cast(dacl, c.POINTER(w.WORD))[2]
        trusted = {sid, "S-1-5-18", "S-1-5-32-544", "S-1-3-4"}  # OWNER RIGHTS after owner verification.
        for i in range(count):
            ace = w.LPVOID()
            checked(get_ace(dacl, i, c.byref(ace)))
            header = c.cast(ace, c.POINTER(c.c_ubyte))
            kind, flags = header[0], header[1]
            if flags & 8:  # INHERIT_ONLY_ACE does not authorize this object.
                continue
            if kind == 1:  # A deny ACE never grants access.
                continue
            if kind != 0:
                raise ValueError("Unsupported Windows access ACE; refusing ambiguous ownership")
            mask = c.cast(ace.value + 4, c.POINTER(w.DWORD))[0]
            principal = sid_text(ace.value + 8)
            # Private data: no other principal can read; chosen output folders:
            # no other principal can mutate/delete/change ACL or ownership.
            forbidden = 0xF01FF | 0xF0000000 if private else 0xD0156 | 0x50000000
            if principal not in trusted and mask & forbidden:
                raise ValueError("Windows object permits another account access")
    finally:
        if descriptor:
            local_free(descriptor)


@contextmanager
def publication_handle(path):
    """Pin verified bytes and deny other writers/renamers until publication."""
    path = lexical(path)
    handle = create(str(path), 0x20000 | 0x80 | 0x80000000 | 0x10000,
                    1, None, 3, 0x00200000, None)
    if handle == w.HANDLE(-1).value:
        raise c.WinError(c.get_last_error())
    try:
        value = info(handle)
        if value.attributes & 0x10 or value.links != 1:
            raise ValueError("Publication requires a regular, singly linked file")
        owned_handle(handle, private=True)
        yield handle
    finally:
        close(handle)


def rename_by_handle(handle, target):
    """Rename this exact retained file; existing destinations are never replaced.

    Caller must retain checked parent handles for both paths. The source is
    never looked up by name after verification, closing the leaf-swap race.
    """
    target = lexical(target)
    assert_path(target, leaf=True)
    filename = str(target)
    encoded = filename.encode('utf-16-le')
    class RenameInfo(c.Structure):
        _fields_ = [("ReplaceIfExists", w.BOOL), ("RootDirectory", w.HANDLE),
                    ("FileNameLength", w.DWORD), ("FileName", w.WCHAR * (len(encoded) // 2 + 1))]
    value = RenameInfo()
    value.ReplaceIfExists = False
    value.RootDirectory = None
    value.FileNameLength = len(encoded)
    value.FileName = filename
    setter = api(k, "SetFileInformationByHandle", w.BOOL, w.HANDLE, c.c_int, w.LPVOID, w.DWORD)
    checked(setter(handle, 3, c.byref(value), c.sizeof(value)))

def open_read(path):
    with pinned_parents(path):
        handle = _open(path, read=True)
        try:
            owned(path)
            return msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        except BaseException:
            close(handle)
            raise

def replace(source, target):
    assert_path(target, leaf=True)
    checked(move(str(source), str(target), 1 | 8))  # REPLACE_EXISTING | WRITE_THROUGH

def sync_directory(path):
    # Windows has no unprivileged POSIX directory fsync. Keep an explicit,
    # flushed write-through metadata barrier in the same private directory.
    # This does not establish power-loss/media-controller durability.
    import secrets
    owned(path)
    temporary = Path(path) / (".dlms-barrier-" + secrets.token_hex(12))
    target = temporary.with_suffix(".done")
    try:
        with temporary.open("xb") as stream:
            stream.write(b"DLMS Desktop Windows publication barrier\n")
            stream.flush()
            os.fsync(stream.fileno())
        checked(move(str(temporary), str(target), 8))
    finally:
        temporary.unlink(missing_ok=True)
        target.unlink(missing_ok=True)

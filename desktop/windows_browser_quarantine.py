"""Opaque retirement of closed, owned WebView2 storage; never trust its children.

Only strict private directory roots are opened. Child cache ACLs, links and bytes
are neither inspected nor changed and never become backend recovery authority.
"""
from contextlib import ExitStack, contextmanager
import ctypes as c
from ctypes import wintypes as w
import os
from pathlib import Path

from .windows_files import (create, info, identity as file_identity, lexical,
                            owned_handle, pinned_parents)
from .windows_processes import api, checked, close, current, identity, process_sid, open_process, times, k

KEYS = {"web_storage", "web_cache"}
_wait_process = api(k, "WaitForSingleObject", w.DWORD, w.HANDLE, w.DWORD)


def valid_id(value):
    return (isinstance(value, list) and len(value) == 3
            and all(type(item) is int and 0 <= item <= 0xffffffff for item in value))


@contextmanager
def directory(path, *, exclusive=True, list_new=False):
    """No-follow root handle; listing access is reserved for known new roots."""
    path = lexical(path)
    handle = create(str(path), 0x20000 | 0x80 | (0x10000 if exclusive else 0) | (1 if list_new else 0),
                    0 if exclusive else 3, None, 3, 0x00200000 | 0x02000000, None)
    if handle == w.HANDLE(-1).value: raise c.WinError(c.get_last_error())
    try:
        if not info(handle).attributes & 0x10: raise ValueError("Browser root is not a directory")
        owned_handle(handle, private=True)
        yield handle
    finally:
        close(handle)


def empty_new(handle):
    """Enumerate only a known replacement through its retained exclusive handle."""
    class Entry(c.Structure):
        _fields_ = [("next", w.DWORD), ("index", w.DWORD),
                    ("times_and_sizes", c.c_longlong * 6), ("attributes", w.DWORD),
                    ("name_bytes", w.DWORD), ("ea_size", w.DWORD), ("short_length", c.c_byte),
                    ("short_name", w.WCHAR * 12), ("file_id", c.c_longlong), ("name", w.WCHAR * 1)]
    query = api(k, "GetFileInformationByHandleEx", w.BOOL, w.HANDLE, c.c_int, w.LPVOID, w.DWORD)
    buffer = c.create_string_buffer(65536)
    restart = True
    while True:
        if not query(handle, 11 if restart else 10, buffer, len(buffer)):
            error = c.get_last_error()
            if error == 18: return True  # ERROR_NO_MORE_FILES
            raise c.WinError(error)
        restart = False
        offset = 0
        while True:
            if offset + Entry.name.offset > len(buffer): raise ValueError("Invalid replacement directory record")
            entry = Entry.from_buffer(buffer, offset)
            size = entry.name_bytes
            if size % 2 or offset + Entry.name.offset + size > len(buffer):
                raise ValueError("Invalid replacement directory name")
            name = c.wstring_at(c.addressof(buffer) + offset + Entry.name.offset, size // 2)
            if name not in {".", ".."}: return False
            if entry.next == 0: break
            if entry.next < Entry.name.offset or offset + entry.next >= len(buffer):
                raise ValueError("Invalid replacement directory offset")
            offset += entry.next


def root_ids(paths):
    result = {}
    for key in sorted(KEYS):
        with pinned_parents(paths[key]), directory(paths[key], exclusive=False) as handle:
            result[key] = list(file_identity(handle))
    return result


def capture(owner):
    """Before deletion, capture birth-bound native identities from the owned view."""
    view = owner.view
    if owner.mode != "local" or view is None or view.page().owner is not owner:
        raise ValueError("Fresh browser retirement requires the owned Local view")
    runtime = view.runtime_info
    host_pid, browser_pid = int(view.process.processId()), runtime.get("pid")
    if (host_pid <= 0 or type(browser_pid) is not int or browser_pid <= 0
            or host_pid == browser_pid or runtime.get("exclusive_storage") is not True):
        raise ValueError("Owned WebView2 runtime identity is unavailable")
    processes = {"host": dict(identity(host_pid), pid=host_pid),
                 "browser": dict(identity(browser_pid), pid=browser_pid)}
    sid = process_sid(current())
    if (processes["host"]["image"] != os.path.normcase(str(Path(view.process.program()).resolve()))
            or Path(processes["host"]["image"]).name.lower() != "dlms-webview2-host.exe"
            or Path(processes["browser"]["image"]).name.lower() != "msedgewebview2.exe"
            or any(value["sid"] != sid for value in processes.values())):
        raise ValueError("Browser process identity differs from the owned native runtime")
    proof = {"processes": processes, "roots": root_ids(owner.paths), "host_finished": False,
             "native_retired": False, "storage_pins_released": False}
    # Existing View._exited runs first and drains native retirement records.
    # This callback executes while Qt objects still exist; confirmation below
    # reads only this private Python dictionary, never deleted Qt wrappers.
    def finished(code, status):
        proof["host_finished"] = code == 0
        proof["native_retired"] = view._retirement_confirmed()
        proof["storage_pins_released"] = not view._storage_pins._exit_callbacks
    view.process.finished.connect(finished)
    return proof


def validate_processes(processes):
    if not isinstance(processes, dict) or set(processes) != {"host", "browser"}:
        raise ValueError("Retired browser process records are malformed")
    sid = process_sid(current())
    for role, value in processes.items():
        if (not isinstance(value, dict) or set(value) != {"pid", "start", "image", "sid"}
                or type(value["pid"]) is not int or value["pid"] <= 0
                or type(value["start"]) is not int or value["start"] <= 0
                or value["sid"] != sid or not isinstance(value["image"], str) or not Path(value["image"]).is_absolute()
                or Path(value["image"]).name.lower() != ("dlms-webview2-host.exe" if role == "host" else "msedgewebview2.exe")):
            raise ValueError("Retired browser birth/image/owner identity is invalid")
    if processes["host"]["pid"] == processes["browser"]["pid"]:
        raise ValueError("Retired browser processes are not distinct")
    for value in processes.values():
        if not process_retired(value["pid"], value["start"]):
            raise ValueError("The exact captured browser process is still alive")


def process_retired(pid, captured_start):
    """Retain a process object for its death/birth proof; never query dead images.

    Windows can retain a terminated process object while image queries fail with
    ERROR_GEN_FAILURE. Its signaled process handle is the positive death proof.
    A live, reused PID is compared by birth and is never acted on or terminated.
    """
    handle = open_process(0x1000 | 0x100000, False, pid)
    if not handle:
        error = c.get_last_error()
        if error == 87: return True  # ERROR_INVALID_PARAMETER: no such process.
        raise c.WinError(error)
    try:
        state = _wait_process(handle, 0)
        if state == 0: return True  # WAIT_OBJECT_0: this process object terminated.
        if state == 258:
            values = [w.FILETIME() for _ in range(4)]
            checked(times(handle, *(c.byref(value) for value in values)))
            observed = (values[0].dwHighDateTime << 32) | values[0].dwLowDateTime
            return observed != captured_start
        if state == 0xffffffff: raise c.WinError(c.get_last_error())
        raise OSError("Unexpected native browser liveness result; retirement is unconfirmed")
    finally:
        close(handle)


def rename(handle, target):
    target = lexical(target)
    encoded = str(target).encode("utf-16-le")
    class Rename(c.Structure):
        _fields_ = [("ReplaceIfExists", w.BOOL), ("RootDirectory", w.HANDLE),
                    ("FileNameLength", w.DWORD), ("FileName", w.WCHAR * (len(encoded)//2+1))]
    value = Rename(); value.ReplaceIfExists = False; value.RootDirectory = None
    value.FileNameLength = len(encoded); value.FileName = str(target)
    setter = api(k, "SetFileInformationByHandle", w.BOOL, w.HANDLE, c.c_int, w.LPVOID, w.DWORD)
    checked(setter(handle, 3, c.byref(value), c.sizeof(value)))


def prepare(paths, recovery, expected):
    """Prepare known empty replacements; caller journals both IDs before moves."""
    if not isinstance(expected, dict) or set(expected) != KEYS or not all(map(valid_id, expected.values())):
        raise ValueError("Captured browser root identities are malformed")
    rows = {}
    for key in sorted(KEYS):
        source, target, staging = paths[key], recovery / key, recovery / (".new-" + key)
        with ExitStack() as stack:
            stack.enter_context(pinned_parents(source))
            stack.enter_context(pinned_parents(target))
            for parent in {source.parent, recovery}:
                with directory(parent, exclusive=False): pass
            with directory(source) as old:
                if list(file_identity(old)) != expected[key]: raise ValueError("Browser root identity changed")
                if os.path.lexists(target) or os.path.lexists(staging): raise ValueError("Browser quarantine destination collision")
                staging.mkdir(mode=0o700)
                with directory(staging) as new:
                    new_id = list(file_identity(new))
                    if new_id[0] != expected[key][0]: raise ValueError("Browser quarantine requires the same volume")
                rows[key] = {"old": expected[key], "new": new_id}
    return rows


def move(paths, recovery, rows, *, checkpoint=lambda stage: None):
    """Resume only the three identity-proven old/new rename positions."""
    if (not isinstance(rows, dict) or set(rows) != KEYS
            or any(not isinstance(row, dict) or set(row) != {"old", "new"}
                   or not valid_id(row["old"]) or not valid_id(row["new"])
                   or row["old"] == row["new"] or row["old"][0] != row["new"][0] for row in rows.values())):
        raise ValueError("Opaque browser quarantine identities are malformed")
    for key in sorted(KEYS):
        source, target, staging = paths[key], recovery / key, recovery / (".new-" + key)
        row = rows[key]
        with ExitStack() as stack:
            for path in (source, target, staging): stack.enter_context(pinned_parents(path))
            for parent in {source.parent, recovery}:
                with directory(parent, exclusive=False): pass
            handles, units = {}, {}
            for name, path in (("source", source), ("target", target), ("staging", staging)):
                if os.path.lexists(path):
                    units[name] = stack.enter_context(ExitStack())
                    handles[name] = units[name].enter_context(directory(path))
            ids = {name: list(file_identity(handle)) for name, handle in handles.items()}
            def check_empty(name, path):
                # Only the identity-proven empty replacement can acquire list
                # access. Reopening cannot silently adopt a substituted leaf.
                units[name].close()
                handles[name] = units[name].enter_context(directory(path, list_new=True))
                if list(file_identity(handles[name])) != row["new"]:
                    raise ValueError("New browser root identity changed while reopening")
                if not empty_new(handles[name]): raise ValueError("New browser replacement is not empty")
            if ids == {"source": row["old"], "staging": row["new"]}:
                check_empty("staging", staging)
                rename(handles["source"], target); checkpoint(key + ":old-moved")
                rename(handles["staging"], source); checkpoint(key + ":new-moved")
            elif ids == {"target": row["old"], "staging": row["new"]}:
                check_empty("staging", staging)
                rename(handles["staging"], source); checkpoint(key + ":new-moved")
            elif ids == {"source": row["new"], "target": row["old"]}:
                check_empty("source", source)
            else:
                raise ValueError("Ambiguous browser quarantine identity/position; preserve all evidence")

"""Read-only inspection of explicitly launched synthetic package descendants.

This lives only in the external test harness. It adds no shipped diagnostic or
privileged page channel and never reads an unrelated process environment.
"""
import ctypes as c
from ctypes import wintypes as w
import os
import struct

from desktop.windows_processes import api, checked, close, open_process, identity, arguments, k

class Entry(c.Structure):
    _fields_=[("size",w.DWORD),("usage",w.DWORD),("pid",w.DWORD),("heap",c.c_size_t),
              ("module",w.DWORD),("threads",w.DWORD),("parent",w.DWORD),
              ("priority",w.LONG),("flags",w.DWORD),("name",w.WCHAR*260)]

def descendants(parent):
    cutoff=w.FILETIME()
    api(k,"GetSystemTimeAsFileTime",None,c.POINTER(w.FILETIME))(c.byref(cutoff))
    snapshot_start=(cutoff.dwHighDateTime<<32)|cutoff.dwLowDateTime
    snapshot=api(k,"CreateToolhelp32Snapshot",w.HANDLE,w.DWORD,w.DWORD)(2,0)
    if snapshot==w.HANDLE(-1).value:raise c.WinError(c.get_last_error())
    first=api(k,"Process32FirstW",w.BOOL,w.HANDLE,c.POINTER(Entry))
    next_entry=api(k,"Process32NextW",w.BOOL,w.HANDLE,c.POINTER(Entry))
    rows={}
    try:
        entry=Entry();entry.size=c.sizeof(entry)
        ok=first(snapshot,c.byref(entry))
        while ok:
            rows[entry.pid]=entry.parent
            ok=next_entry(snapshot,c.byref(entry))
    finally:close(snapshot)
    def born(pid):
        try:return identity(pid)['start']
        except OSError:return None
    return birth_safe_descendants(parent,rows,born,snapshot_start)

def birth_safe_descendants(parent,rows,born,snapshot_start):
    """A stale PPID can refer to a newly reused PID. Never adopt that subtree."""
    start=born(parent)
    if start is None or start>snapshot_start:return set()
    found={parent:start};queue=[parent]
    while queue:
        owner=queue.pop()
        for pid,reported_parent in rows.items():
            if reported_parent!=owner or pid in found:continue
            child_start=born(pid)
            if child_start is not None and found[owner]<=child_start<=snapshot_start:
                found[pid]=child_start;queue.append(pid)
    # Recheck every birth, then rebuild reachability so a changed intermediate
    # parent invalidates its entire branch. No post-snapshot PID is adopted.
    stable={pid for pid,value in found.items() if born(pid)==value}
    if parent not in stable:return set()
    result={parent};queue=[parent]
    while queue:
        owner=queue.pop()
        for pid,reported_parent in rows.items():
            if reported_parent==owner and pid in stable and pid not in result:
                result.add(pid);queue.append(pid)
    return result

def alive(pid,born):
    try:return identity(pid)["start"]==born
    except OSError:return False

def backend_nonce(launcher, expected_image, diagnostics=None):
    # Only a descendant with the exact frozen backend role/image is opened.
    for pid in descendants(launcher)-{launcher}:
        try:
            owner=identity(pid)
            if owner["image"]!=os.path.normcase(str(expected_image)):continue
            argv=arguments(pid)
            if argv[1:3]!=["--desktop-worker","backend"]:continue
            handle=checked(open_process(0x10|0x400,False,pid))
            try:
                read=api(k,"ReadProcessMemory",w.BOOL,w.HANDLE,w.LPCVOID,w.LPVOID,c.c_size_t,c.POINTER(c.c_size_t))
                def memory(address,length):
                    target=c.create_string_buffer(length);count=c.c_size_t()
                    checked(read(handle,address,target,length,c.byref(count)))
                    if count.value!=length:raise OSError("Incomplete owned backend memory read")
                    return target.raw
                query=api(c.WinDLL("ntdll"),"NtQueryInformationProcess",c.c_long,w.HANDLE,c.c_int,w.LPVOID,w.DWORD,c.POINTER(w.DWORD))
                basic=c.create_string_buffer(48);size=w.DWORD()
                if query(handle,0,basic,len(basic),c.byref(size))<0:raise OSError("Owned backend PEB unavailable")
                peb=struct.unpack_from("<Q",basic.raw,8)[0]
                parameters=struct.unpack("<Q",memory(peb+0x20,8))[0]
                environment=struct.unpack("<Q",memory(parameters+0x80,8))[0]
                raw=bytearray()
                # Read bounded UTF-16 code units, stopping before an unallocated
                # trailing page; never log or serialize the environment.
                for offset in range(0,128*1024,2):
                    raw.extend(memory(environment+offset,2))
                    if len(raw)>=4 and raw[-4:]==b"\0\0\0\0":break
                else:raise ValueError("Owned backend environment exceeds harness bound")
                values=dict(item.split("=",1) for item in raw.decode("utf-16-le").split("\0") if "=" in item and not item.startswith("="))
                nonce=values["DLMS_DESKTOP_NONCE"]
                if len(nonce)!=64 or identity(pid)!=owner:raise ValueError("Owned backend identity changed")
                return pid,nonce
            finally:close(handle)
        except (OSError,ValueError,KeyError) as exc:
            if diagnostics is not None:
                diagnostics[pid] = {"type":type(exc).__name__, "reason":str(exc)}
            continue
    return None

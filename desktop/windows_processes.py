"""Native Windows ownership. Handles and jobs, never PID-only termination.

The launcher joins a kill-on-close job before starting Qt. Every worker waits
on an explicitly inherited bootstrap handle until assigned to its own job.
Winsock duplicates the still-bound socket for that exact child PID.
"""
from __future__ import annotations

import base64
import ctypes as c
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

k = c.WinDLL("kernel32", use_last_error=True)
a = c.WinDLL("advapi32", use_last_error=True)

def api(dll, name, result, *args):
    fn = getattr(dll, name)
    fn.restype, fn.argtypes = result, list(args)
    return fn

close = api(k, "CloseHandle", w.BOOL, w.HANDLE)
current = api(k, "GetCurrentProcess", w.HANDLE)
open_process = api(k, "OpenProcess", w.HANDLE, w.DWORD, w.BOOL, w.DWORD)
times = api(k, "GetProcessTimes", w.BOOL, w.HANDLE, *([c.POINTER(w.FILETIME)] * 4))
image = api(k, "QueryFullProcessImageNameW", w.BOOL, w.HANDLE, w.DWORD, w.LPWSTR, c.POINTER(w.DWORD))
open_token = api(a, "OpenProcessToken", w.BOOL, w.HANDLE, w.DWORD, c.POINTER(w.HANDLE))
token_info = api(a, "GetTokenInformation", w.BOOL, w.HANDLE, c.c_int, w.LPVOID, w.DWORD, c.POINTER(w.DWORD))
sid_string = api(a, "ConvertSidToStringSidW", w.BOOL, w.LPVOID, c.POINTER(w.LPWSTR))
local_free = api(k, "LocalFree", w.LPVOID, w.LPVOID)

def checked(ok):
    if not ok:
        raise c.WinError(c.get_last_error())
    return ok

def default_data_root():
    """Resolve the real user's LocalAppData, independent of synthetic env vars."""
    import uuid
    folder = (c.c_ubyte * 16).from_buffer_copy(uuid.UUID("f1b32785-6fba-4fcf-9d55-7b8e7f157091").bytes_le)
    get_folder = api(c.WinDLL("shell32"), "SHGetKnownFolderPath", c.c_long,
                     w.LPVOID, w.DWORD, w.HANDLE, c.POINTER(w.LPWSTR))
    release = api(c.WinDLL("ole32"), "CoTaskMemFree", None, w.LPVOID)
    output = w.LPWSTR()
    if get_folder(folder, 0, None, c.byref(output)) != 0:
        raise RuntimeError("Windows LocalAppData is unavailable; no fallback is permitted")
    try:
        return Path(output.value) / "DLMSDesktop" / "WindowsCandidate"
    finally:
        release(output)


_webview2_default_root = None


def _frozen_webview2():
    selected = sys.modules.get('package_windows_webview2')
    return bool(getattr(sys, 'frozen', False) and getattr(selected, 'ACTIVE', False) is True)


def _validated_webview2_default_root(value):
    from .windows_files import lexical, assert_path
    if (not isinstance(value, str) or not value or len(json.dumps(value).encode('utf-8')) > 8192):
        raise ValueError('Windows WebView2 default-root capture is malformed or too long')
    root = lexical(value)
    if str(root) != value:
        raise ValueError('Windows WebView2 default-root capture must be canonical')
    assert_path(root)
    return root


def capture_webview2_default_root(value):
    """Native entry only: remember the validated omitted-root meaning before isolation."""
    global _webview2_default_root
    if not _frozen_webview2():
        raise RuntimeError('Default-root capture requires the frozen Windows WebView2 entry')
    root = _validated_webview2_default_root(value)
    if _webview2_default_root is not None:
        if _webview2_default_root != root:
            raise RuntimeError('Windows WebView2 default-root capture changed')
        return
    _webview2_default_root = root


def captured_webview2_default_root():
    """Never query Known Folders from a profile-scoped launcher or worker."""
    return _webview2_default_root if _frozen_webview2() else None


def _webview2_ownership_payload(environment):
    if not _frozen_webview2():
        return None
    root = captured_webview2_default_root()
    if root is not None and str(root) != environment.get('DLMS_DESKTOP_DATA_ROOT'):
        raise RuntimeError('Windows WebView2 default-root capture differs from worker data root')
    return {'renderer': 'webview2', 'default_root': str(root) if root is not None else None}


def _restore_webview2_ownership(payload):
    """Called only after existing parent identity and inherited-pipe authentication."""
    key = 'webview2_ownership'
    if not _frozen_webview2():
        if key in payload:
            raise RuntimeError('Windows worker renderer does not match ownership capture')
        return
    if not isinstance(payload, dict):
        raise RuntimeError('Windows WebView2 ownership bootstrap is malformed')
    value = payload.get(key)
    if (not isinstance(value, dict) or set(value) != {'renderer', 'default_root'}
            or value['renderer'] != 'webview2'):
        raise RuntimeError('Windows WebView2 ownership capture is missing or malformed')
    root = value['default_root']
    if root is not None:
        validated = _validated_webview2_default_root(root)
        if str(validated) != os.environ.get('DLMS_DESKTOP_DATA_ROOT'):
            raise RuntimeError('Windows WebView2 captured default differs from authenticated data root')
        capture_webview2_default_root(str(validated))
    elif _webview2_default_root is not None:
        raise RuntimeError('Windows WebView2 ownership capture unexpectedly lost its default')

def sid_text(sid):
    output = w.LPWSTR()
    checked(sid_string(sid, c.byref(output)))
    try:
        return output.value
    finally:
        local_free(output)

def process_sid(handle):
    token = w.HANDLE()
    checked(open_token(handle, 8, c.byref(token)))
    try:
        size = w.DWORD()
        token_info(token, 1, None, 0, c.byref(size))
        buf = c.create_string_buffer(size.value)
        checked(token_info(token, 1, buf, size, c.byref(size)))
        return sid_text(c.cast(buf, c.POINTER(w.LPVOID))[0])
    finally:
        close(token)

def identity(pid):
    handle = open_process(0x1000, False, pid)
    if not handle:
        error = c.get_last_error()
        if error == 87 and isinstance(pid, int) and pid > 0:
            raise FileNotFoundError(f"Windows process {pid} no longer exists")
        raise c.WinError(error)
    try:
        values = [w.FILETIME() for _ in range(4)]
        checked(times(handle, *(c.byref(v) for v in values)))
        size = w.DWORD(32768)
        path = c.create_unicode_buffer(size.value)
        checked(image(handle, 0, path, c.byref(size)))
        return {"start": (values[0].dwHighDateTime << 32) | values[0].dwLowDateTime,
                "image": os.path.normcase(str(Path(path.value).resolve())),
                "sid": process_sid(handle)}
    finally:
        close(handle)

def arguments(pid):
    """Read the exact Win11 process command line; unsupported query fails closed."""
    class UnicodeString(c.Structure):
        _fields_ = [("length", w.WORD), ("maximum", w.WORD), ("buffer", w.LPVOID)]
    query = api(c.WinDLL("ntdll"), "NtQueryInformationProcess", c.c_long,
                w.HANDLE, c.c_int, w.LPVOID, w.DWORD, c.POINTER(w.DWORD))
    split = api(c.WinDLL("shell32"), "CommandLineToArgvW", c.POINTER(w.LPWSTR),
                w.LPCWSTR, c.POINTER(c.c_int))
    handle = checked(open_process(0x1000, False, pid))
    try:
        size = w.DWORD()
        query(handle, 60, None, 0, c.byref(size))
        if not c.sizeof(UnicodeString) <= size.value <= 128 * 1024:
            raise ValueError("Windows command-line identity is unavailable")
        buffer = c.create_string_buffer(size.value)
        if query(handle, 60, buffer, size, c.byref(size)) < 0:
            raise ValueError("Windows command-line query failed")
        value = c.cast(buffer, c.POINTER(UnicodeString)).contents
        begin = c.addressof(buffer)
        if not (value.length % 2 == 0 and begin <= value.buffer
                and value.buffer + value.length <= begin + len(buffer)):
            raise ValueError("Windows command-line query returned invalid bounds")
        command = c.wstring_at(value.buffer, value.length // 2)
        count = c.c_int()
        argv = split(command, c.byref(count))
        checked(bool(argv))
        try:
            return [argv[i] for i in range(count.value)]
        finally:
            local_free(argv)
    finally:
        close(handle)

class Limits(c.Structure):
    _fields_ = [("PerProcessUserTimeLimit", c.c_longlong), ("PerJobUserTimeLimit", c.c_longlong),
                ("LimitFlags", w.DWORD), ("MinimumWorkingSetSize", c.c_size_t),
                ("MaximumWorkingSetSize", c.c_size_t), ("ActiveProcessLimit", w.DWORD),
                ("Affinity", c.c_size_t), ("PriorityClass", w.DWORD), ("SchedulingClass", w.DWORD)]

class IO(c.Structure):
    _fields_ = [(name, c.c_ulonglong) for name in
                ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                 "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

class ExtendedLimits(c.Structure):
    _fields_ = [("BasicLimitInformation", Limits), ("IoInfo", IO),
                ("ProcessMemoryLimit", c.c_size_t), ("JobMemoryLimit", c.c_size_t),
                ("PeakProcessMemoryUsed", c.c_size_t), ("PeakJobMemoryUsed", c.c_size_t)]

create_job = api(k, "CreateJobObjectW", w.HANDLE, w.LPVOID, w.LPCWSTR)
set_job = api(k, "SetInformationJobObject", w.BOOL, w.HANDLE, c.c_int, w.LPVOID, w.DWORD)
assign_job = api(k, "AssignProcessToJobObject", w.BOOL, w.HANDLE, w.HANDLE)
terminate_job = api(k, "TerminateJobObject", w.BOOL, w.HANDLE, w.UINT)
in_job = api(k, "IsProcessInJob", w.BOOL, w.HANDLE, w.HANDLE, c.POINTER(w.BOOL))

class Job:
    def __init__(self):
        self.handle = checked(create_job(None, None))
        try:
            limits = ExtendedLimits()
            limits.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE; no breakaway.
            checked(set_job(self.handle, 9, c.byref(limits), c.sizeof(limits)))
            os.set_handle_inheritable(self.handle, False)
        except BaseException:
            close(self.handle)
            raise

    def assign(self, process_handle):
        checked(assign_job(self.handle, process_handle))
        member = w.BOOL()
        checked(in_job(process_handle, self.handle, c.byref(member)))
        if not member.value:
            raise RuntimeError("Windows did not confirm Desktop job membership")

    def stop(self):
        if self.handle:
            checked(terminate_job(self.handle, 1))
            close(self.handle)
            self.handle = None

_outer = None
_running_mutex = None
_workers = {}
_launch_lock = threading.Lock()

def own_launcher():
    global _outer, _running_mutex
    if _outer is None:
        job = Job()
        try:
            job.assign(current())
        except BaseException:
            job.stop()
            raise
        # Do not close this while running: the launcher is itself a member.
        # Windows closes this noninherited handle at process death/normal exit.
        _outer = job
        if getattr(sys, "frozen", False):
            mutex = api(k, "CreateMutexW", w.HANDLE, w.LPVOID, w.BOOL, w.LPCWSTR)
            from .webview2_runtime import active as webview2_active
            name = ("Local\\DLMSDesktop.WebView2Candidate.Running" if webview2_active()
                    else "Local\\DLMSDesktop.WindowsCandidate.Running")
            _running_mutex = checked(mutex(None, False, name))
            os.set_handle_inheritable(_running_mutex, False)

def spawn(command, *, cwd, env, stdin, stdout, stderr, start_new_session=True,
          close_fds=True, pass_fds=(), bound=None):
    import msvcrt
    own_launcher()
    job = Job()
    read_fd, write_fd = os.pipe()
    environment = dict(env)
    me = identity(os.getpid())
    environment["DLMS_WINDOWS_PARENT"] = json.dumps(dict(me, pid=os.getpid()))
    environment["DLMS_WINDOWS_BOOTSTRAP"] = str(msvcrt.get_osfhandle(read_fd))
    inherited = [msvcrt.get_osfhandle(read_fd)]
    # Translate only the explicitly requested CRT descriptors. Socket ownership
    # uses WSADuplicateSocket below; raw SOCKET values never cross this API.
    for fd in pass_fds:
        if bound is not None and fd == bound.fileno():
            continue
        native = msvcrt.get_osfhandle(fd)
        inherited.append(native)
        for key, value in list(environment.items()):
            if key.endswith("_PARENT_PIPE") and value == str(fd):
                environment[key] = str(native)
    if not getattr(sys, "frozen", False):
        import sysconfig
        role_index = command.index("-m") + 1
        role = command[role_index].rsplit(".", 1)[-1]
        # Windows venv python.exe is a redirector. Spawning it would put an
        # intermediate process between the authenticated launcher and worker,
        # and an already-spawned child would miss subsequent nested-job
        # assignment. Start the same real interpreter as this process directly,
        # with only this isolated environment's packages and no site startup.
        interpreter = getattr(sys, "_base_executable", sys.executable)
        roots = environment.get("PYTHONPATH", "").split(os.pathsep)
        roots.append(sysconfig.get_path("purelib"))
        environment["PYTHONPATH"] = os.pathsep.join(x for x in roots if x)
        environment["PYTHONNOUSERSITE"] = "1"
        command = [interpreter, "-S", "-m", "desktop.windows_worker", role, *command[role_index + 1:]]
    info = subprocess.STARTUPINFO()
    info.lpAttributeList = {"handle_list": inherited}
    proc = None
    try:
        with _launch_lock:
            for handle in inherited:
                os.set_handle_inheritable(handle, True)
            try:
                proc = subprocess.Popen(command, cwd=cwd, env=environment, stdin=stdin,
                                        stdout=stdout, stderr=stderr, close_fds=True,
                                        startupinfo=info, creationflags=subprocess.CREATE_NO_WINDOW)
            finally:
                for handle in inherited:
                    os.set_handle_inheritable(handle, False)
        job.assign(int(proc._handle))  # Child cannot pass bootstrap before this.
        _workers[proc.pid] = (env.get("DLMS_DESKTOP_NONCE"), job)
        payload = {"socket": base64.b64encode(bound.share(proc.pid)).decode() if bound else None}
        ownership = _webview2_ownership_payload(environment)
        if ownership is not None:
            payload['webview2_ownership'] = ownership
        wire = json.dumps(payload).encode() + b"\n"
        if len(wire) > 16384:
            raise RuntimeError('Windows worker bootstrap payload exceeds its supported bound')
        os.write(write_fd, wire)
        return proc
    except BaseException:
        job.stop()
        if proc is not None:
            proc.kill()  # Original retained Popen handle, never a reopened PID.
            proc.wait(timeout=5)
        raise
    finally:
        os.close(read_fd)
        os.close(write_fd)

def bootstrap():
    import msvcrt
    import socket
    parent = json.loads(os.environ.pop("DLMS_WINDOWS_PARENT"))
    found = identity(parent.pop("pid"))
    if found != parent or found["sid"] != process_sid(current()):
        raise RuntimeError("Windows worker parent identity changed")
    if found["image"] != identity(os.getpid())["image"]:
        raise RuntimeError("Windows worker parent executable does not match")
    handle = int(os.environ.pop("DLMS_WINDOWS_BOOTSTRAP"))
    os.set_handle_inheritable(handle, False)
    with os.fdopen(msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY), "rb") as pipe:
        data = pipe.readline(16384)
    if not data.endswith(b"\n"):
        raise RuntimeError("Owning launcher did not release the Windows worker")
    for key, value in list(os.environ.items()):
        if key.endswith("_PARENT_PIPE"):
            handle = int(value)
            os.set_handle_inheritable(handle, False)
            os.environ[key] = str(msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY))
    payload = json.loads(data)
    _restore_webview2_ownership(payload)
    share = payload["socket"]
    if share:
        bound = socket.fromshare(base64.b64decode(share, validate=True))
        bound.set_inheritable(False)
        os.environ["DLMS_DESKTOP_SOCKET_FD"] = str(bound.detach())

def reap(group, nonce):
    value = _workers.get(group)
    if value is not None and value[0] == nonce:
        value[1].stop()
        del _workers[group]
    return []

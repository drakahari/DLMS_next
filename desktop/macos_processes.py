"""Darwin process identities and exact, nonce-scoped helper cleanup.

The combined BSD/unique-id ABI and audit-token signal API are described in
Apple XNU's bsd/sys/proc_info_private.h and libsyscall/wrappers/libproc.
Unsupported kernels fail closed; numeric PID signaling is never a fallback.
"""
from __future__ import annotations

import ctypes
import errno
import hashlib
from functools import lru_cache
import os
from pathlib import Path
import re
import signal
import stat
import struct
import sys
import time


class _BSDInfo(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint32) for name in (
        'flags', 'status', 'xstatus', 'pid', 'ppid', 'uid', 'gid', 'ruid',
        'rgid', 'svuid', 'svgid', 'reserved')]
    _fields_ += [('comm', ctypes.c_char * 16), ('name', ctypes.c_char * 32)]
    _fields_ += [(name, ctypes.c_uint32) for name in ('nfiles', 'pgid', 'jobc', 'tdev', 'tpgid')]
    _fields_ += [('nice', ctypes.c_int32), ('seconds', ctypes.c_uint64), ('microseconds', ctypes.c_uint64)]


class _UniqueInfo(ctypes.Structure):
    _fields_ = [('uuid', ctypes.c_ubyte * 16), ('unique', ctypes.c_uint64),
                ('parent_unique', ctypes.c_uint64), ('version', ctypes.c_int32),
                ('parent_version', ctypes.c_int32), ('reserved2', ctypes.c_uint64),
                ('reserved3', ctypes.c_uint64)]


class _CombinedInfo(ctypes.Structure):
    _fields_ = [('bsd', _BSDInfo), ('unique', _UniqueInfo)]


@lru_cache(maxsize=1)
def _library():
    if sys.platform != 'darwin':
        raise RuntimeError('Darwin process adapter requires macOS')
    library = ctypes.CDLL('/usr/lib/libSystem.B.dylib', use_errno=True)
    library.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
    library.proc_pidinfo.restype = ctypes.c_int
    library.proc_signal_with_audittoken.argtypes = [ctypes.POINTER(ctypes.c_uint32), ctypes.c_int]
    library.proc_signal_with_audittoken.restype = ctypes.c_int
    library.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    library.proc_pidpath.restype = ctypes.c_int
    library.proc_listpgrppids.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
    library.proc_listpgrppids.restype = ctypes.c_int
    library.sysctl.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_uint, ctypes.c_void_p,
                               ctypes.POINTER(ctypes.c_size_t), ctypes.c_void_p, ctypes.c_size_t]
    library.sysctl.restype = ctypes.c_int
    return library


def identity(pid: int) -> dict:
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        raise ValueError('Invalid Darwin process identifier')
    found = _CombinedInfo()
    lib = _library()
    count = lib.proc_pidinfo(pid, 18, 0, ctypes.byref(found), ctypes.sizeof(found))
    if count != ctypes.sizeof(found):
        raise OSError(ctypes.get_errno() or errno.ESRCH, 'Cannot verify Darwin process identity')
    path = ctypes.create_string_buffer(4096)
    if not lib.proc_pidpath(pid, path, len(path)):
        raise OSError(ctypes.get_errno() or errno.ESRCH, 'Cannot verify Darwin process executable')
    return {'pid': pid, 'uid': found.bsd.uid, 'group': found.bsd.pgid,
            'start': found.bsd.seconds * 1_000_000 + found.bsd.microseconds,
            'unique': found.unique.unique, 'version': found.unique.version,
            'status': found.bsd.status, 'image': os.fsdecode(path.value)}


def arguments_environment(pid: int) -> tuple[list[str], list[bytes]]:
    """Read kernel-captured argv/environment, never a shell/ps rendering."""
    lib = _library()
    mib = (ctypes.c_int * 3)(1, 49, pid)  # CTL_KERN, KERN_PROCARGS2
    # macOS ARG_MAX is bounded; refuse truncated or unusually large metadata.
    capacity = os.sysconf('SC_ARG_MAX')
    if not 4096 <= capacity <= 2 * 1024 * 1024:
        raise RuntimeError('Unsupported Darwin argument limit')
    value = ctypes.create_string_buffer(capacity)
    size = ctypes.c_size_t(len(value))
    if lib.sysctl(mib, 3, value, ctypes.byref(size), None, 0) != 0:
        raise OSError(ctypes.get_errno(), 'Cannot read Darwin process arguments')
    raw = value.raw[:size.value]
    if len(raw) < 5:
        raise ValueError('Truncated Darwin argument metadata')
    argc = struct.unpack_from('i', raw)[0]
    if not 1 <= argc <= 65536:
        raise ValueError('Invalid Darwin argument count')
    cursor = raw.index(b'\0', 4) + 1  # executable path, then NUL padding
    while cursor < len(raw) and raw[cursor] == 0:
        cursor += 1
    args = []
    for _ in range(argc):
        end = raw.index(b'\0', cursor)
        args.append(os.fsdecode(raw[cursor:end]))
        cursor = end + 1
    return args, [item for item in raw[cursor:].split(b'\0') if item]


def _same_birth(left: dict, right: dict) -> bool:
    return all(left[key] == right[key] for key in ('pid', 'uid', 'start', 'unique'))


def signal_identity(found: dict, action: int) -> bool:
    """Kernel checks PID generation atomically with signal permission/delivery."""
    current = identity(found['pid'])
    if not _same_birth(found, current):
        return False
    token = (ctypes.c_uint32 * 8)()
    token[5] = current['pid']
    token[7] = current['version']
    result = _library().proc_signal_with_audittoken(token, action)
    if result == errno.ESRCH:  # exited, reused or exec changed the generation
        return False
    if result:
        raise OSError(result, 'Cannot signal exact owned Darwin process')
    return True


def _owned(group: int, nonce: str) -> list[dict]:
    if group <= 0 or re.fullmatch(r'[0-9a-f]{32,128}', nonce) is None:
        raise ValueError('Darwin cleanup requires an exact group and launch nonce')
    lib = _library()
    ctypes.set_errno(0)
    count = lib.proc_listpgrppids(group, None, 0)
    if count < 0 or (count == 0 and ctypes.get_errno()):
        raise OSError(ctypes.get_errno(), 'Cannot enumerate Darwin process group')
    values = (ctypes.c_int * (count + 64))()
    ctypes.set_errno(0)
    size = lib.proc_listpgrppids(group, values, ctypes.sizeof(values))
    if size < 0 or (size == 0 and ctypes.get_errno()) or size >= len(values):
        raise RuntimeError('Darwin process group enumeration is incomplete')
    marker = f'DLMS_DESKTOP_NONCE={nonce}'.encode()
    found = []
    for pid in values[:size]:
        if pid <= 0:
            continue
        try:
            before = identity(pid)
            if before['uid'] != os.getuid() or before['group'] != group or before['status'] == 5:
                continue  # SZOMB has no live helpers to terminate
            _args, environment = arguments_environment(pid)
            after = identity(pid)
            if marker in environment and _same_birth(before, after) and after['group'] == group:
                found.append(after)
        except OSError as exc:
            if exc.errno not in {errno.ESRCH, errno.ENOENT}:
                raise
        except ValueError as exc:
            # Truncated metadata can race exit. A still-live matching process
            # must be reported rather than silently treating it as cleaned up.
            try:
                after = identity(pid)
            except ProcessLookupError:
                continue
            if _same_birth(before, after) and after['status'] != 5:
                raise RuntimeError('Live Darwin helper metadata cannot be verified') from exc
    return found


def reap(group: int, nonce: str, *, exclude: set[int] | None = None) -> list[int]:
    excluded = exclude or set()
    # Stop parents first, then repeat the exact owned scan to include a helper
    # forked during the first scan. No loose process-group signal is used.
    for action, seconds in ((signal.SIGTERM, 2), (signal.SIGKILL, 1)):
        deadline = time.monotonic() + seconds
        while True:
            active = [item for item in _owned(group, nonce) if item['pid'] not in excluded]
            if not active:
                return []
            for item in active:
                try:
                    signal_identity(item, action)
                except ProcessLookupError:
                    pass
            if time.monotonic() >= deadline:
                break
            time.sleep(0.05)
    return [item['pid'] for item in _owned(group, nonce) if item['pid'] not in excluded]


def parent_lost(*, parent_group: int | None = None) -> None:
    """Pipe EOF ends this worker and only its verified launch's helpers."""
    nonce = os.environ.get('DLMS_DESKTOP_NONCE', '')
    try:
        if parent_group is not None and parent_group != os.getpgrp():
            reap(parent_group, nonce, exclude={os.getpid()})
        reap(os.getpgrp(), nonce, exclude={os.getpid()})
    finally:
        os._exit(70)


def seal_private_descriptors() -> None:
    """The intentional pipe/socket handoff ends at this worker's exec boundary."""
    for name in os.listdir('/dev/fd'):
        fd = int(name)
        if fd >= 3:
            try:
                os.set_inheritable(fd, False)
            except OSError as exc:
                if exc.errno != errno.EBADF:
                    raise


def spawn(command, *, bound=None, **kwargs):
    import subprocess
    # Probe the required identity/signaling ABI before creating a worker.
    identity(os.getpid())
    seal_private_descriptors()
    process = subprocess.Popen(command, **kwargs)
    try:
        found = identity(process.pid)
        process._dlms_macos_identity = found
    except ProcessLookupError:
        if process.poll() is not None:
            return process  # a completed short worker still has a normal result
        process.kill()
        process.wait(timeout=3)
        raise
    except BaseException:
        # Popen owns this unreaped direct child, so its kill/wait operations
        # cannot target a reused PID. Never leave a worker after failed setup.
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)
        raise
    return process


def instance_socket_name(profile_root: Path) -> str:
    """Short private filesystem socket, independent of Application Support depth."""
    # Confstr uses the real OS user temp namespace, unaffected by scoped TMPDIR.
    parent = Path(os.confstr(65537)).resolve()
    directory = parent / 'dlms-ipc'
    directory.mkdir(mode=0o700, exist_ok=True)
    status = directory.lstat()
    if not stat.S_ISDIR(status.st_mode) or status.st_uid != os.getuid() or status.st_mode & 0o077:
        raise ValueError('Darwin Desktop IPC directory is not privately owned')
    key = f'{os.getuid()}:{profile_root.resolve()}'.encode()
    path = directory / (hashlib.sha256(key).hexdigest()[:24] + '.sock')
    if len(os.fsencode(path)) >= 104:
        raise ValueError('Darwin Desktop IPC path exceeds native socket limit')
    return str(path)


def launch_matches(arguments: list[str], name: str, root: Path, *, frozen: bool) -> bool:
    if '--desktop-worker' in arguments:
        return False
    if frozen:
        options = arguments[1:]
    else:
        if arguments[1:3] != ['-m', 'package_macos']:
            return False
        options = arguments[3:]
    parsed = {}
    index = 0
    while index < len(options):
        key, separator, value = options[index].partition('=')
        if key == '--capture-window-events':
            if separator or key in parsed:
                return False
            parsed[key] = True
            index += 1
            continue
        if key not in {'--profile', '--data-root'} or key in parsed:
            return False
        if not separator:
            index += 1
            if index >= len(options) or options[index].startswith('--'):
                return False
            value = options[index]
        if not value:
            return False
        parsed[key] = value
        index += 1
    from .macos_paths import default_data_root
    chosen = Path(parsed.get('--data-root', default_data_root()))
    return (parsed.get('--profile', 'walkthrough') == name and chosen.is_absolute()
            and chosen == root)

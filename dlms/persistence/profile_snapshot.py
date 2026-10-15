"""Bounded, reentrant snapshot exclusion across cooperating DLMS processes.

Normal requests share access; only snapshot capture and profile replacement are
exclusive. This does not make simultaneous normal writers in multiple servers
supported. The stable sibling lock is deliberately never restored or unlinked.
"""
from contextlib import contextmanager
from functools import wraps
import errno
import hashlib
import os
from pathlib import Path
import stat
import threading
import time


BUSY_MESSAGE = (
    "DLMS is busy saving data or taking a backup. This operation has not started. "
    "Wait for the current operation to finish, then retry."
)


class ProfileBusyError(RuntimeError):
    """The snapshot boundary was not available within the bounded wait."""


_local = threading.local()


def lock_path(root):
    canonical = Path(os.path.realpath(os.path.abspath(root)))
    key = hashlib.sha256(os.fsencode(os.path.normcase(str(canonical)))).hexdigest()[:32]
    return canonical.parent / ('.dlms-profile-' + key + '.lock')


def _try_lock(fd, exclusive):
    if os.name != 'nt':
        import fcntl
        fcntl.flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        return
    import ctypes
    from ctypes import wintypes
    import msvcrt
    class Overlapped(ctypes.Structure):
        _fields_ = [('Internal', ctypes.c_size_t), ('InternalHigh', ctypes.c_size_t),
                    ('Offset', wintypes.DWORD), ('OffsetHigh', wintypes.DWORD),
                    ('hEvent', wintypes.HANDLE)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    function = kernel.LockFileEx
    function.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                         wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(Overlapped)]
    function.restype = wintypes.BOOL
    position = Overlapped()
    if not function(msvcrt.get_osfhandle(fd), 1 | (2 if exclusive else 0), 0, 1, 0,
                    ctypes.byref(position)):
        error = ctypes.get_last_error()
        if error == 33:  # ERROR_LOCK_VIOLATION; no asynchronous I/O is requested.
            raise BlockingIOError(errno.EAGAIN, 'Profile snapshot lock is held')
        raise ctypes.WinError(error)


@contextmanager
def access(root, *, exclusive=False, timeout=5.0):
    """Acquire before restore/registry/DB locks; never upgrade a shared permit."""
    path = lock_path(root)
    owners = getattr(_local, 'owners', None)
    if owners is None:
        owners = _local.owners = {}
    key = str(path)
    held = owners.get(key)
    if held:
        if held['pid'] != os.getpid():
            raise RuntimeError('A profile snapshot permit cannot be inherited across fork')
        if exclusive and not held['exclusive']:
            raise ProfileBusyError(BUSY_MESSAGE)
        yield
        return
    # Do not follow or replace an existing lock: that could create two lock
    # identities for the same profile. A writable profile parent is required.
    if path.is_symlink():
        raise OSError('Profile snapshot lock must not be a symbolic link')
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise OSError('Profile snapshot lock must be a private regular file')
        deadline = time.monotonic() + timeout
        while True:
            try:
                _try_lock(fd, exclusive)
                break
            except OSError as exc:
                if exc.errno not in {errno.EAGAIN, errno.EACCES}:
                    raise
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ProfileBusyError(BUSY_MESSAGE) from exc
                # Bounded lock polling, not a correctness/timing assumption.
                threading.Event().wait(min(0.025, remaining))
        owners[key] = {'pid': os.getpid(), 'exclusive': exclusive}
        try:
            yield
        finally:
            owners.pop(key, None)
    finally:
        os.close(fd)  # OS also releases the lock if the process exits.


def guard(root, *, exclusive=False):
    """Decorate supported direct entry points using their current profile root."""
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            with access(root(), exclusive=exclusive):
                return function(*args, **kwargs)
        return wrapped
    return decorate

"""Standalone AppImage adapter; never opens the per-user installation namespace."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

NAMESPACE = 'dlms-desktop-appimage-test'
MARKER = '.dlms-desktop-appimage-test.json'
VALUE = {'format': 1, 'namespace': NAMESPACE, 'purpose': 'personal synthetic AppImage testing'}
DISPOSABLE = {'kind': 'dlms-desktop-fedora-package-feasibility', 'version': 1}


def _directory(path: Path) -> int:
    """Walk pinned, nonsymlink parents; create only absent directory components."""
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('AppImage storage requires an absolute unambiguous path')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for name in path.parts[1:]:
            try:
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            except FileNotFoundError:
                try:
                    os.mkdir(name, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _read_at(directory: int, name: str, expected: dict):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_size > 512):
            raise ValueError('AppImage storage marker is unsafe')
        value = json.loads(os.read(fd, 513))
        if value != expected:
            raise ValueError('AppImage storage marker differs; no data will be adopted')
    finally:
        os.close(fd)


def prepare_root(environment: dict[str, str], *, payload: Path) -> Path:
    home = environment.get('HOME', '')
    if not home or not Path(home).is_absolute() or '..' in Path(home).parts:
        raise ValueError('AppImage needs an absolute HOME; no installed-profile fallback')
    base = Path(environment.get('XDG_DATA_HOME') or str(Path(home) / '.local/share'))
    if not base.is_absolute() or '..' in base.parts:
        raise ValueError('XDG_DATA_HOME must be an absolute unambiguous path')
    root = base / NAMESPACE
    payload = payload.resolve()
    if root.is_relative_to(payload) or payload.is_relative_to(root):
        raise ValueError('AppImage data must be outside the payload/mount')
    protected = [('dlms-desktop-pilot',), ('.local', 'opt', 'dlms-desktop'),
                 ('.local', 'state', 'dlms-desktop-management')]
    if any(tuple(root.parts[i:i+len(parts)]) == parts
           for parts in protected for i in range(len(root.parts))):
        raise ValueError('AppImage storage must not be nested in installed DLMS storage')
    parent = _directory(base)
    fresh = False
    try:
        try:
            os.mkdir(NAMESPACE, 0o700, dir_fd=parent)
            fresh = True
        except FileExistsError:
            pass
        directory = os.open(NAMESPACE, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        try:
            info = os.fstat(directory)
            if info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError('AppImage data namespace is not privately owned')
            # Initialization is atomic as a *refusal boundary*: partial marker
            # publication is never mistaken for a usable existing namespace.
            if fresh:
                for name, value in [(MARKER, VALUE), ('.dlms-desktop-disposable.json', DISPOSABLE)]:
                    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=directory)
                    with os.fdopen(fd, 'wb') as stream:
                        stream.write((json.dumps(value, sort_keys=True)+'\n').encode())
                        stream.flush()
                        os.fsync(stream.fileno())
                os.fsync(directory)
                os.fsync(parent)
            _read_at(directory, MARKER, VALUE)
            _read_at(directory, '.dlms-desktop-disposable.json', DISPOSABLE)
            final = os.stat(NAMESPACE, dir_fd=parent, follow_symlinks=False)
            if (final.st_dev, final.st_ino) != (info.st_dev, info.st_ino):
                raise ValueError('AppImage storage changed during initialization')
        finally:
            os.close(directory)
    finally:
        os.close(parent)
    return root


def launch(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description='DLMS Desktop AppImage — separate synthetic test data')
    parser.add_argument('--profile', default='appimage01', help='named profile in the separate AppImage test namespace')
    args = parser.parse_args(argv)
    import re
    if not re.fullmatch(r'[a-z][a-z0-9_-]{0,31}', args.profile):
        parser.error('Profile must use 1–32 lowercase letters, digits, _ or -')
    if not same_image_executable(os.getpid()):
        raise ValueError('Standalone AppImage identity is unavailable; no data was initialized')
    image_dir = Path(sys.executable).resolve().parents[3]
    descriptors = mount_handoff_descriptors()
    root = prepare_root(dict(os.environ), payload=image_dir)
    # Same-process exec gives /proc/cmdline the exact existing ownership contract.
    # Workers still use the reviewed --data-root role, without an install pointer.
    try:
        for fd in descriptors: os.set_inheritable(fd, True)
        os.execv(sys.executable, [sys.executable, '--profile', args.profile, '--data-root', str(root)])
    finally:
        # Failed exec must not leave private runtime descriptors inheritable.
        # Successful exec immediately seals them again in package_entry.main.
        for fd in descriptors: os.set_inheritable(fd, False)


def same_image_executable(pid: int) -> bool:
    """Across distinct FUSE mounts, verify exact frozen code, never names alone.

    The caller also verifies PID birth, UID, profile/root arguments and owner
    secret before IPC. Only an AppImage-tagged current payload enables this
    alternate byte comparison. Non-AppImage ownership remains path-exact.
    """
    try:
        meta = Path(sys._MEIPASS) / 'desktop_assets/appimage-info.json'
        if meta.is_symlink() or not meta.is_file() or meta.stat().st_size > 2048:
            return False
        value = json.loads(meta.read_text())
        if (value.get('format') != 1 or value.get('namespace') != NAMESPACE
                or value.get('executable_sha256') is None):
            return False
        from .build_info import information
        if value.get('release') != information()['release']:
            return False
        if Path(f'/proc/{pid}').stat().st_uid != os.getuid():
            return False
        def digest(path):
            h = hashlib.sha256()
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(1024*1024), b''): h.update(block)
            return h.hexdigest()
        expected = value['executable_sha256']
        return digest(Path(sys.executable)) == expected == digest(Path(f'/proc/{pid}/exe'))
    except (OSError, ValueError, AttributeError, KeyError, TypeError):
        return False


def mount_handoff_descriptors() -> list[int]:
    """Pinned type2 runtime's exact lifetime handles, for one same-process exec.

    Runtime opens its read-only mount on1023 and retains one anonymous read
    pipe; closing that pipe makes its FUSE daemon exit. Never pass these to a
    worker/helper/external app. The second entry seals them immediately.
    """
    appdir = os.environ.get('APPDIR')
    image = os.environ.get('APPIMAGE')
    if not appdir or not image:
        return []  # Explicit extraction has no FUSE lifetime handoff.
    try:
        mounted = os.fstat(1023)
    except OSError:
        return []  # Official extract-and-run fallback likewise has no mountFD.
    info = Path(appdir).stat()
    if not stat.S_ISDIR(mounted.st_mode) or (mounted.st_dev, mounted.st_ino) != (info.st_dev, info.st_ino):
        return []
    if not os.statvfs(appdir).f_flag & os.ST_RDONLY:
        raise ValueError('AppImage mount descriptor is not read-only')
    meta = json.loads((Path(sys._MEIPASS)/'desktop_assets/appimage-info.json').read_text())
    if (type(meta.get('runtime_bytes')) is not int or not 0 < meta['runtime_bytes'] <= 4*1024*1024
            or not isinstance(meta.get('runtime_sha256'), str) or len(meta['runtime_sha256']) != 64):
        raise ValueError('AppImage runtime handoff metadata is invalid')
    with Path(image).open('rb') as stream:
        prefix = stream.read(meta['runtime_bytes'])
    # Pinned appimagetool fills the runtime's nonexecutable .digest_md5
    # section after SquashFS assembly. Normalize only those exact16bytes in
    # this pinned runtime; never mask code, update info or signature sections.
    if (meta['runtime_bytes'] == 944632
            and meta['runtime_sha256'] == '156f4bdbde9c52d01814600013e0a273f0118dc2de98975f3c8c63427ec79074'
            and len(prefix) == 944632):
        prefix = prefix[:932096] + b'\0'*16 + prefix[932112:]
    if len(prefix) != meta['runtime_bytes'] or hashlib.sha256(prefix).hexdigest() != meta['runtime_sha256']:
        raise ValueError('AppImage runtime identity differs; mount handoff refused')
    pipes = []
    for name in os.listdir('/proc/self/fd'):
        fd = int(name)
        if fd < 3 or fd == 1023:
            continue
        try:
            if (os.readlink(f'/proc/self/fd/{fd}').startswith('pipe:[')
                    and stat.S_ISFIFO(os.fstat(fd).st_mode)
                    and fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDONLY):
                pipes.append(fd)
        except OSError:
            pass
    if len(pipes) != 1:
        raise ValueError('AppImage mount lifetime pipe is ambiguous; no exec handoff')
    return [1023, pipes[0]]

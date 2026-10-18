"""Separate macOS preview storage; never discover or adopt installed profiles."""
import json
import os
from pathlib import Path
import pwd
import stat
import sys

MARKER = '.dlms-macos-preview.json'
IDENTITY = {'kind': 'dlms-desktop-macos-preview', 'version': 1}


def real_home():
    return Path(pwd.getpwuid(os.getuid()).pw_dir)


def default_data_root():
    return real_home() / 'Library/Application Support/DLMS Desktop Preview'


def prepare_root(path=None, *, create=True):
    root = Path(path) if path is not None else default_data_root()
    if not root.is_absolute() or '..' in root.parts:
        raise ValueError('Mac Desktop requires an absolute, unambiguous data root')
    payload = Path(sys._MEIPASS) if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1]
    if getattr(sys, 'frozen', False):
        payload = next((p for p in (payload, *payload.parents) if p.suffix.casefold() == '.app'), payload)
        for component in (root, *root.parents):
            if component.exists() and payload.exists() and os.path.samestat(component.stat(), payload.stat()):
                raise ValueError('Mac Desktop data must be outside its application payload')
    if root.resolve().is_relative_to(payload.resolve()) and (getattr(sys, 'frozen', False)
            or not root.resolve().is_relative_to(payload.resolve() / '.gate1')):
        raise ValueError('Mac Desktop data must be outside its application payload')
    for part in (*reversed(root.parents), root):
        if part.is_symlink() or (part.exists() and not part.is_dir()):
            raise ValueError('Mac Desktop data path contains a symlink or non-directory')
    if root.exists():
        info = root.stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('Mac Desktop data root is not private to this user')
    elif create:
        root.mkdir(mode=0o700, parents=True)
        # Only this newly created root may receive a marker. Existing unmarked
        # data is never adopted, erased, repaired or treated as disposable.
        fd = os.open(root / MARKER, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(IDENTITY, stream)
            stream.flush()
            os.fsync(stream.fileno())
    else:
        raise ValueError('Mac Desktop data root does not exist')
    marker = root / MARKER
    fd = os.open(marker, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 512 or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('Mac Desktop marker is unsafe')
        value = json.loads(os.read(fd, 513))
        if (value != IDENTITY or not isinstance(value, dict)
                or type(value.get('version')) is not int):
            raise ValueError('Mac Desktop marker identity differs')
    finally:
        os.close(fd)
    return root

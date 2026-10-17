"""Existing private shell places for Windows' scoped GUI environment."""
from pathlib import Path

def prepare(home: Path):
    from .windows_files import assert_path,owned
    owned(home,private=True)
    # The native Windows picker expands these places from USERPROFILE even
    # when its explicit starting directory is elsewhere. Never create them in
    # the real Windows home or change the user's Known Folder configuration.
    for name in ('Desktop','Documents','Downloads','Pictures','Music','Videos'):
        path=home/name
        assert_path(path)
        path.mkdir(mode=0o700,exist_ok=True)
        owned(path,private=True)

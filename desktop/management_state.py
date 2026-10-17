"""Fixed private state paths; incomplete management always blocks app startup."""
from pathlib import Path


def state_root(home: Path) -> Path:
    return home / '.local/state/dlms-desktop-management'


def assert_resolved(home: Path):
    root=state_root(home)
    for part in (root,*root.parents):
        if part==home:break
        if part.is_symlink():raise ValueError('Installation management state path needs inspection')
    active=root/'active.json'
    if active.exists() or active.is_symlink():
        raise ValueError('Installation management is incomplete. Close DLMS and run the extracted Install/Manage tool → Reconcile. Data was not reset.')

"""Read-only, bounded storage reporting and best-effort capacity preflight."""
import os
from pathlib import Path
import shutil
import stat
import time

MIB = 1024 ** 2
GIB = 1024 ** 3
RESERVE_BYTES = 256 * MIB
LOW_SPACE_MESSAGE = (
    "Not enough available disk space for this operation and its working files. "
    "Free space on the data and temporary-file drives, then retry. "
    "Keep safety backups and recovery files."
)


class InsufficientStorageError(OSError):
    def __init__(self):
        super().__init__(LOW_SPACE_MESSAGE)


def available_space(path):
    """Find the filesystem of a destination that may not exist yet."""
    try:
        path = Path(path).absolute()
        while not path.exists() and path != path.parent:
            path = path.parent
        usage = shutil.disk_usage(path)
        return usage.total, usage.free
    except OSError:
        return None, None


def require_capacity(path, additional_bytes):
    """Advisory estimate, not a reservation or quota; unknown space fails open."""
    _, free = available_space(path)
    if free is not None and free < max(0, additional_bytes) + RESERVE_BYTES:
        raise InsufficientStorageError()


def space_status(total, free):
    if free is None or not total:
        return "unknown"
    if free < 512 * MIB:
        return "critical"
    if free < 2 * GIB or (free < 10 * GIB and free / total < 0.05):
        return "low"
    return "healthy"


def format_size(size):
    if size is None:
        return "Unavailable"
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:,.1f} {unit}"
        size /= 1024


def storage_snapshot(root, *, max_entries=50000, max_seconds=0.5):
    """Logical file sizes, without opening SQLite or following symbolic links.

    One bounded scan per explicit request. Concurrent writes, permissions and
    traversal limits mean this is a snapshot, not an accounting guarantee.
    """
    groups = {name: 0 for name in (
        "Database size", "Database journals", "Backups", "Content / Study Packs",
        "Quiz and generated artifacts", "Images and appearance", "Import sources and drafts",
        "Uploads and staging", "Recovery files", "Other data",
    )}
    categories = {
        "results.db": "Database size", "backups": "Backups",
        "content_packs": "Content / Study Packs", "quizzes": "Quiz and generated artifacts",
        "data": "Quiz and generated artifacts", "quiz_assets": "Images and appearance",
        "static": "Images and appearance", "uploads": "Uploads and staging",
        "content_pack_staging": "Uploads and staging", ".restore_operations": "Recovery files",
    }
    deadline = time.monotonic() + max_seconds
    pending = [(Path(root), None)]
    partial = False
    checked = 0
    while pending:
        directory, category = pending.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    checked += 1
                    if checked > max_entries or time.monotonic() >= deadline:
                        partial = True
                        pending.clear()
                        break
                    group = category or categories.get(entry.name, "Other data")
                    if category is None:
                        if entry.name.startswith("results.db-"):
                            group = "Database journals"
                        elif entry.name.endswith(("_drafts", "_banks")) or entry.name == "law":
                            group = "Import sources and drafts"
                    try:
                        info = entry.stat(follow_symlinks=False)
                        if stat.S_ISLNK(info.st_mode):
                            partial = True
                        elif stat.S_ISDIR(info.st_mode):
                            pending.append((Path(entry.path), group))
                        elif stat.S_ISREG(info.st_mode):
                            groups[group] += info.st_size
                    except OSError:
                        partial = True
        except FileNotFoundError:
            partial = partial or directory != Path(root)
        except OSError:
            partial = True
    total, free = available_space(root)
    return {
        "bytes": sum(groups.values()), "size": format_size(sum(groups.values())),
        "groups": [{"label": key, "bytes": value, "size": format_size(value)} for key, value in groups.items()],
        "free": format_size(free), "status": space_status(total, free), "partial": partial,
    }

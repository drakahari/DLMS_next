"""Small platform-specific file primitives; POSIX behavior stays unchanged."""
import os

def writer_path(path):
    if os.name != "nt" or path.name != "backend-writer.lock":
        return path
    import hashlib
    from .isolation import AREA, PROFILES
    from .windows_files import assert_path, owned as native_owned
    if path.parent.parent != PROFILES:
        raise ValueError("Windows writer lock is outside the scoped profile namespace")
    directory = AREA / "writer-locks"
    assert_path(directory)
    directory.mkdir(mode=0o700, exist_ok=True)
    native_owned(directory, private=True)
    key = hashlib.sha256(os.path.normcase(str(path.parent.absolute())).encode("utf-8")).hexdigest()
    # Windows byte locks are mandatory: an in-profile lock cannot be read by
    # inventory/copy, and its open handle prevents directory replacement.
    # A stable sibling keeps exclusion across the whole data transaction.
    return directory / (key + ".lock")

def lock(fd, *, blocking=False):
    if os.name == "nt":
        import msvcrt
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))

def owned(path, *, private=False):
    if os.name == "nt":
        from .windows_files import owned as native_owned
        native_owned(path, private=private)
        return True
    value = path.stat()
    return value.st_uid == os.getuid() and not value.st_mode & (0o077 if private else 0o022)

def sync_directory(path):
    if os.name == "nt":
        from .windows_files import sync_directory as native_sync
        return native_sync(path)
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)

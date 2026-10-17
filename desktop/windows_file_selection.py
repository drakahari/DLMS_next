"""Windows ordinary-file snapshots for the WebView2 file chooser.

The browser receives a private copy whose retained Windows read handle denies
write and delete sharing. Validation reads that same handle. This is not a
read-only-attribute or hash-only promise, and does not claim atomic capture
against a malicious same-user writer before the source handle is acquired.
Stores belong to an actual browser/page lifetime, not a navigation lifetime.
"""
from __future__ import annotations

from contextlib import ExitStack
import base64
from dataclasses import dataclass
import ctypes as c
from ctypes import wintypes as w
import hashlib
import msvcrt
import os
from pathlib import Path, PurePosixPath
import secrets
import stat
import struct
import threading
import zipfile

from . import windows_files as wf

MiB = 1024 * 1024
MAX_SELECTION = 25
PAGE_FILES = 256
PAGE_BYTES = 384 * MiB
LAUNCHER_BYTES = 768 * MiB
CHUNK = 256 * 1024


def _private_component():
    # Case-insensitive Windows names preserve all128 random bits: unlike
    # URL-safe base64, this alphabet has no upper/lowercase filename aliases.
    return base64.b32encode(secrets.token_bytes(16)).decode('ascii').rstrip('=').lower()
# Generic native-picker resource ceiling, a superset of ordinary bundle and
# Study Pack regular-file limits. Pathological directory-heavy Study Packs may
# be refused here; receiving formats and narrower limits remain unchanged.
ZIP_ENTRIES = 20000
TYPE_LIMITS = {'.txt': 16 * MiB, '.csv': 16 * MiB, '.pdf': 64 * MiB,
               '.zip': 256 * MiB, '.png': 32 * MiB, '.jpg': 32 * MiB,
               '.jpeg': 32 * MiB, '.webp': 32 * MiB, '.gif': 32 * MiB}


class SelectionError(ValueError):
    """An actionable selection failure, never a successful cancellation."""


class SelectionCanceled(SelectionError):
    pass


class _BasicInfo(c.Structure):
    _fields_ = [('creation', c.c_longlong), ('access', c.c_longlong),
                ('write', c.c_longlong), ('change', c.c_longlong), ('attributes', w.DWORD)]


_basic_info = wf.api(wf.k, 'GetFileInformationByHandleEx', w.BOOL,
                     w.HANDLE, c.c_int, w.LPVOID, w.DWORD)
_file_type = wf.api(wf.k, 'GetFileType', w.DWORD, w.HANDLE)
_final_name = wf.api(wf.k, 'GetFinalPathNameByHandleW', w.DWORD,
                    w.HANDLE, w.LPWSTR, w.DWORD, w.DWORD)
_lock = threading.RLock()
_launcher_bytes = 0


def _fingerprint(handle):
    value = wf.info(handle)
    basic = _BasicInfo()
    wf.checked(_basic_info(handle, 0, c.byref(basic), c.sizeof(basic)))
    if _file_type(handle) != 1 or value.attributes & 0x10 or value.links != 1:
        raise SelectionError('Choose a regular, singly linked local file.')
    return (value.volume, value.index_hi, value.index_lo,
            value.size_hi << 32 | value.size_lo, basic.creation, basic.write, basic.change)


def _owned_source(handle):
    # Ordinary readable folders need not have a private DACL. Only the selected
    # file must be owned by this account; staging has a separate private ACL.
    owner, descriptor = w.LPVOID(), w.LPVOID()
    try:
        error = wf.get_security(handle, 1, 1, c.byref(owner), None, None, None, c.byref(descriptor))
        if error:
            raise c.WinError(error)
        if wf.sid_text(owner) != wf.process_sid(wf.current()):
            raise SelectionError('The selected file is owned by another Windows account.')
    finally:
        if descriptor:
            wf.local_free(descriptor)


def _beneath(path, root):
    # Windows Path comparison is case insensitive and lexical: resolving would
    # follow a user-supplied reparse point before it is refused.
    return path == root or root in path.parents


def _canonical(handle):
    buffer = c.create_unicode_buffer(32768)
    count = _final_name(handle, buffer, len(buffer), 0)
    if not count or count >= len(buffer):
        raise SelectionError('Windows could not establish the selected file identity.')
    value = buffer.value
    if value.startswith('\\\\?\\'):
        value = value[4:]
    return wf.lexical(value)


def _canonical_root(raw):
    path = wf.lexical(raw)
    wf.assert_path(path)
    if not path.exists():
        return path
    with wf.pinned_parents(path):
        handle = wf._open(path, directory=path.is_dir())
        try:
            return _canonical(handle)
        finally:
            wf.close(handle)


def _read_handle(path):
    handle = wf._open(path, read=True)
    try:
        os.set_handle_inheritable(handle, False)
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except BaseException:
        wf.close(handle)
        raise
    return os.fdopen(descriptor, 'rb', buffering=0)


def _handle(stream):
    return msvcrt.get_osfhandle(stream.fileno())


def _same_name(path, expected):
    # Reopening with read sharing is allowed by our retained immutable handle.
    with _read_handle(path) as stream:
        if _fingerprint(_handle(stream)) != expected:
            raise SelectionError('The selected file changed or was replaced. Select it again.')


@dataclass
class CapturedFile:
    path: Path
    name: str
    size: int
    identity: tuple
    _stream: object
    _pins: ExitStack


class CapturedBatch:
    def __init__(self, files):
        self.files = tuple(files)
        self.total_bytes = sum(item.size for item in files)
        self.closed = False

    def close(self):
        if self.closed:
            return
        self.closed = True
        errors = []
        for item in self.files:
            for closer in (item._stream.close, item._pins.close):
                try:
                    closer()
                except Exception as error:
                    errors.append(str(error))
        return tuple(errors)


def capture(paths, *, blocked_roots=(), allowed_private_roots=()):
    """Capture identity immediately after the chooser, before Server consent.

    The caller supplies all private roots and only the current Local temp and
    downloads exceptions. Server callers must supply no private exceptions.
    Source handles stay read-locked until batch.close(), including consent.
    """
    paths = tuple(paths)
    if not 1 <= len(paths) <= MAX_SELECTION:
        raise SelectionError('Select between 1 and 25 files.')
    blocked = tuple(_canonical_root(path) for path in blocked_roots)
    allowed = tuple(_canonical_root(path) for path in allowed_private_roots)
    captured = []
    try:
        for raw in paths:
            path = wf.lexical(raw)
            if (any(_beneath(path, root) for root in blocked)
                    and not any(_beneath(path, root) for root in allowed)):
                raise SelectionError('Choose an ordinary file outside private application data.')
            limit = TYPE_LIMITS.get(path.suffix.lower())
            if limit is None:
                raise SelectionError('This file type is unsupported. Select TXT, CSV, PDF, ZIP or a supported raster image.')
            pins = ExitStack()
            stream = None
            try:
                pins.enter_context(wf.pinned_parents(path))
                stream = _read_handle(path)
                handle = _handle(stream)
                _owned_source(handle)
                canonical = _canonical(handle)
                if (any(_beneath(canonical, root) for root in blocked)
                        and not any(_beneath(canonical, root) for root in allowed)):
                    raise SelectionError('Choose an ordinary file outside private application data.')
                identity = _fingerprint(handle)
                size = identity[3]
                if not 0 < size <= limit:
                    raise SelectionError(f'{path.name}: the file is empty or exceeds its {limit // MiB} MiB selection limit.')
                captured.append(CapturedFile(path, path.name, size, identity, stream, pins))
            except BaseException:
                if stream is not None:
                    stream.close()
                pins.close()
                raise
        return CapturedBatch(captured)
    except BaseException:
        CapturedBatch(captured).close()
        raise


def _cancelled(cancel):
    if cancel():
        raise SelectionCanceled('File selection canceled. No new files were selected or submitted.')


def _digest(stream, *, cancel):
    stream.seek(0)
    digest = hashlib.sha256()
    while True:
        _cancelled(cancel)
        block = stream.read(CHUNK)
        if not block:
            break
        digest.update(block)
    stream.seek(0)
    return digest.hexdigest()


def _zip_directory_bound(stream, *, cancel):
    """Walk actual bounded headers before ZipFile allocates its directory.

    CPython's pinned _EndRecData reads only fixed ZIP64 records and the final
    65558 bytes. Neither a lying EOCD entry count nor size grants allocation.
    """
    end = zipfile._EndRecData(stream)
    if end is None:
        raise SelectionError('The ZIP end record is missing or invalid.')
    count, size = end[zipfile._ECD_ENTRIES_TOTAL], end[zipfile._ECD_SIZE]
    start = end[zipfile._ECD_LOCATION] - size
    if end[zipfile._ECD_SIGNATURE] == zipfile.stringEndArchive64:
        start -= zipfile.sizeEndCentDir64 + zipfile.sizeEndCentDir64Locator
    stream.seek(0, os.SEEK_END)
    file_size = stream.tell()
    if count > ZIP_ENTRIES or count < 1 or size < 0 or start < 0 or start + size > file_size:
        raise SelectionError('The ZIP directory exceeds its safe native-selection bounds.')
    position, actual = start, 0
    while position < start + size:
        _cancelled(cancel)
        if start + size - position < zipfile.sizeCentralDir:
            raise SelectionError('The ZIP directory is truncated.')
        stream.seek(position)
        raw = stream.read(zipfile.sizeCentralDir)
        if len(raw) != zipfile.sizeCentralDir:
            raise SelectionError('The ZIP directory is truncated.')
        record = struct.unpack(zipfile.structCentralDir, raw)
        if record[zipfile._CD_SIGNATURE] != zipfile.stringCentralDir:
            raise SelectionError('The ZIP directory contains an invalid record.')
        actual += 1
        if actual > ZIP_ENTRIES:
            raise SelectionError('The ZIP directory has too many members for native selection.')
        length = (zipfile.sizeCentralDir + record[zipfile._CD_FILENAME_LENGTH]
                  + record[zipfile._CD_EXTRA_FIELD_LENGTH] + record[zipfile._CD_COMMENT_LENGTH])
        if position + length > start + size:
            raise SelectionError('The ZIP directory member exceeds its recorded boundary.')
        position += length
    if actual != count or position != start + size:
        raise SelectionError('The ZIP directory count or boundary is inconsistent.')
    stream.seek(0)


def _validate(stream, name, *, cancel=lambda: False):
    """Preliminary checks only; receivers retain all narrower semantic rules."""
    extension = Path(name).suffix.lower()
    stream.seek(0)
    if extension in {'.txt', '.csv'}:
        # Captured parsers retain their encoding/content/choice validation.
        return
    if extension == '.pdf':
        if b'%PDF-' not in stream.read(1024):
            raise SelectionError(f'{name}: this is not a PDF file.')
    elif extension == '.zip':
        try:
            _zip_directory_bound(stream, cancel=cancel)
            with zipfile.ZipFile(stream) as archive:
                infos = archive.infolist()
                if not infos:
                    raise SelectionError(f'{name}: the ZIP archive is empty.')
                seen = set()
                for item in infos:
                    _cancelled(cancel)
                    normalized = item.filename.replace('\\', '/')
                    parts = PurePosixPath(normalized).parts
                    key = normalized.rstrip('/').casefold()
                    mode = item.external_attr >> 16
                    if (not parts or normalized.startswith('/') or '..' in parts
                            or any(':' in part or '\x00' in part for part in parts)
                            or key in seen or item.flag_bits & 1
                            or stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)):
                        raise SelectionError(f'{name}: the ZIP archive contains an unsafe, encrypted or duplicate member.')
                    seen.add(key)
        except (zipfile.BadZipFile, NotImplementedError, RuntimeError, struct.error, OSError) as error:
            raise SelectionError(f'{name}: the ZIP archive is invalid or unsupported.') from error
    else:
        try:
            import warnings
            from PIL import Image
            formats = {'.png': 'PNG', '.jpg': 'JPEG', '.jpeg': 'JPEG', '.webp': 'WEBP', '.gif': 'GIF'}
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                image = Image.open(stream)
                if image.format != formats[extension]:
                    raise SelectionError(f'{name}: the raster content does not match its filename.')
                image.verify()
        except SelectionError:
            raise
        except Exception as error:
            raise SelectionError(f'{name}: the raster image is invalid or exceeds safe decoder dimensions.') from error
    stream.seek(0)


@dataclass
class Snapshot:
    path: Path
    name: str
    size: int
    sha256: str
    _stream: object
    _identity: tuple
    _pins: ExitStack
    _store: object
    _directory: Path
    _retired: bool = False


class SnapshotStore:
    """Page-owned sealed copies. Close only after browser retirement is proven."""
    def __init__(self, private_root):
        self.snapshots = []
        self.cleanup_errors = []
        self.closed = False
        self._reserved_count = self._reserved_bytes = 0
        self._directory_closed = False
        self._pins = ExitStack()
        parent = wf.lexical(private_root)
        try:
            self._pins.enter_context(wf.pinned_parents(parent / '.dlms-selection-anchor'))
            wf.owned(parent, private=True)
            self.path = parent / ('.wv-s-' + _private_component())
            self.path.mkdir(mode=0o700)
            self._pins.enter_context(wf.pinned_parents(self.path / '.dlms-anchor'))
            wf.owned(self.path, private=True)
        except BaseException:
            self._pins.close()
            raise

    def _reserve(self, count, size):
        global _launcher_bytes
        with _lock:
            if self.closed:
                raise SelectionError('This file-selection page has retired.')
            if (len(self.snapshots) + self._reserved_count + count > PAGE_FILES
                    or sum(item.size for item in self.snapshots) + self._reserved_bytes + size > PAGE_BYTES
                    or _launcher_bytes + size > LAUNCHER_BYTES):
                raise SelectionError('Selected-file storage is full. Close and reopen this window before selecting more files.')
            _launcher_bytes += size
            self._reserved_count += count
            self._reserved_bytes += size

    def stage(self, batch, *, cancel=lambda: False, progress=lambda copied, total: None):
        """Copy/check off the UI thread; do not touch browser objects here."""
        global _launcher_bytes
        if batch.closed:
            raise SelectionError('This selected-file batch has already retired.')
        self._reserve(len(batch.files), batch.total_bytes)
        requested_cancel = cancel
        cancel = lambda: self.closed or requested_cancel()
        staged = []
        copied = 0
        try:
            for source in batch.files:
                _cancelled(cancel)
                if _fingerprint(_handle(source._stream)) != source.identity:
                    raise SelectionError('The selected file changed. Select it again.')
                _same_name(source.path, source.identity)
                directory = self.path / _private_component()
                directory.mkdir(mode=0o700)
                pins = ExitStack()
                path = directory / source.name
                stream = None
                writer_identity = None
                try:
                    pins.enter_context(wf.pinned_parents(path))
                    wf.owned(directory, private=True)
                    digest = hashlib.sha256()
                    source._stream.seek(0)
                    with path.open('xb', buffering=0) as writer:
                        os.set_handle_inheritable(_handle(writer), False)
                        writer_identity = _fingerprint(_handle(writer))
                        wf.owned_handle(_handle(writer), private=True)
                        while True:
                            _cancelled(cancel)
                            data = source._stream.read(CHUNK)
                            if not data:
                                break
                            if copied + len(data) > batch.total_bytes:
                                raise SelectionError('The selected file grew during staging.')
                            writer.write(data)
                            digest.update(data)
                            copied += len(data)
                            progress(copied, batch.total_bytes)
                        os.fsync(writer.fileno())
                        writer_identity = _fingerprint(_handle(writer))
                    stream = _read_handle(path)
                    wf.owned_handle(_handle(stream), private=True)
                    sealed_identity = _fingerprint(_handle(stream))
                    # Closing a Windows write handle can update change/write
                    # timestamps. Compare stable file ID/size, then digest under
                    # the retained deny-write/delete handle.
                    if sealed_identity[:4] != writer_identity[:4] or sealed_identity[3] != source.size:
                        raise SelectionError('The private selected copy was replaced or resized.')
                    expected = digest.hexdigest()
                    if _digest(stream, cancel=cancel) != expected:
                        raise SelectionError('The private selected copy changed before it was sealed.')
                    writer_identity = sealed_identity
                    if (_digest(source._stream, cancel=cancel) != expected
                            or _fingerprint(_handle(source._stream)) != source.identity):
                        raise SelectionError('The selected source changed during staging. Select it again.')
                    _same_name(source.path, source.identity)
                    _validate(stream, source.name, cancel=cancel)
                    _cancelled(cancel)
                    staged.append(Snapshot(path, source.name, source.size, expected, stream,
                                           sealed_identity, pins, self, directory))
                except BaseException:
                    if stream is not None:
                        stream.close()
                    self._remove_exact(path, writer_identity, directory, pins)
                    raise
            with _lock:
                if self.closed:
                    raise SelectionCanceled('The selected-file page retired before staging completed.')
                self.snapshots.extend(staged)
                self._reserved_count -= len(batch.files)
                self._reserved_bytes -= batch.total_bytes
            return tuple(staged)
        except BaseException:
            for item in staged:
                self._retire(item)
            with _lock:
                _launcher_bytes -= batch.total_bytes
                self._reserved_count -= len(batch.files)
                self._reserved_bytes -= batch.total_bytes
                self._finish_close()
            raise

    def _remove_exact(self, path, expected, directory, pins):
        # Never recursively remove unexpected crash leftovers or substitutions.
        try:
            if path.exists():
                if expected is None:
                    raise SelectionError('An unverified private staging file was preserved.')
                handle = wf.create(str(path), 0x80000000 | 0x20000 | 0x80 | 0x10000,
                                   1, None, 3, 0x00200000, None)
                if handle == w.HANDLE(-1).value:
                    raise c.WinError(c.get_last_error())
                try:
                    actual = _fingerprint(handle)
                    if (actual[:3] != expected[:3]
                            or (expected[3] and actual != expected)):
                        raise SelectionError('An unexpected private staging replacement was preserved.')
                    wf.owned_handle(handle, private=True)
                    setter = wf.api(wf.k, 'SetFileInformationByHandle', w.BOOL,
                                    w.HANDLE, c.c_int, w.LPVOID, w.DWORD)
                    dispose = w.BOOL(True)
                    wf.checked(setter(handle, 4, c.byref(dispose), c.sizeof(dispose)))
                finally:
                    wf.close(handle)
        except Exception as error:
            self.cleanup_errors.append(str(error))
        # Release the directory's deny-delete pin only after capturing its ID;
        # delete using a new verified DELETE handle, never a name-only rmdir.
        directory_id = None
        try:
            handle = wf._open(directory, directory=True)
            try:
                directory_id = wf.identity(handle)
            finally:
                wf.close(handle)
        except Exception as error:
            self.cleanup_errors.append(str(error))
        finally:
            try:
                pins.close()
            except Exception as error:
                self.cleanup_errors.append(str(error))
        if directory_id is not None:
            try:
                handle = wf.create(str(directory), 0x20000 | 0x80 | 0x10000,
                                   3, None, 3, 0x00200000 | 0x02000000, None)
                if handle == w.HANDLE(-1).value:
                    raise c.WinError(c.get_last_error())
                try:
                    if wf.identity(handle) != directory_id:
                        raise SelectionError('An unexpected private staging directory was preserved.')
                    wf.owned_handle(handle, private=True)
                    setter = wf.api(wf.k, 'SetFileInformationByHandle', w.BOOL,
                                    w.HANDLE, c.c_int, w.LPVOID, w.DWORD)
                    dispose = w.BOOL(True)
                    wf.checked(setter(handle, 4, c.byref(dispose), c.sizeof(dispose)))
                finally:
                    wf.close(handle)
            except Exception as error:
                self.cleanup_errors.append(str(error))

    def _retire(self, snapshot):
        if snapshot._retired:
            return
        snapshot._retired = True
        for closer in (snapshot._stream.close,):
            try:
                closer()
            except Exception as error:
                self.cleanup_errors.append(str(error))
        self._remove_exact(snapshot.path, snapshot._identity, snapshot._directory, snapshot._pins)

    def discard(self, snapshots):
        global _launcher_bytes
        snapshots = tuple(snapshots)
        if any(item._store is not self for item in snapshots):
            raise SelectionError('A selected-file batch belongs to another browser page.')
        with _lock:
            for item in snapshots:
                if item in self.snapshots:
                    self.snapshots.remove(item)
                    _launcher_bytes -= item.size
                    self._retire(item)
        return tuple(self.cleanup_errors)

    def close(self):
        with _lock:
            if self.closed:
                return tuple(self.cleanup_errors)
            self.closed = True
        self.discard(tuple(self.snapshots))
        with _lock:
            self._finish_close()
        return tuple(self.cleanup_errors)

    def _finish_close(self):
        if not self.closed or self._reserved_count or self._directory_closed:
            return
        self._directory_closed = True
        # The anchor was never created. _remove_exact captures/pins the actual
        # directory identity before releasing our deny-delete directory handle.
        self._remove_exact(self.path / ('.absent-' + secrets.token_hex(16)), None,
                           self.path, self._pins)

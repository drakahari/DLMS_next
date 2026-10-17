"""Actual Windows handle/identity tests; no GUI or browser is launched."""
from pathlib import Path
import ctypes as c
import hashlib
import io
import os
import struct
import subprocess
import threading
import zipfile

import pytest

if os.name != 'nt':
    pytest.skip('Native Windows file handles', allow_module_level=True)

from desktop import windows_file_selection as fs

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='native Windows handles')


@pytest.fixture
def inputs(tmp_path):
    ordinary = tmp_path / 'Ordinary folder 日本語'
    ordinary.mkdir()
    private = tmp_path / 'private'
    private.mkdir(mode=0o700)
    yield ordinary, private
    assert fs._launcher_bytes == 0


def text(parent, name='quiz 日本語.txt', data=b'1. Synthetic question\nA. one\nB. two\nANSWER: A\n'):
    path = parent / name
    path.write_bytes(data)
    return path


def test_snapshot_preserves_order_names_exact_bytes_and_handle_exclusion(inputs):
    ordinary, private = inputs
    paths = [text(ordinary, 'second 日本語.txt'), text(ordinary, 'first name.csv', b'a,b\n1,2\n')]
    batch = fs.capture(paths)
    store = fs.SnapshotStore(private)
    try:
        snapshots = store.stage(batch)
        assert [item.name for item in snapshots] == [item.name for item in paths]
        for source, snapshot in zip(paths, snapshots):
            assert snapshot.path.name == source.name
            assert snapshot.path.read_bytes() == source.read_bytes()
            assert snapshot.sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
            assert not os.get_handle_inheritable(fs._handle(snapshot._stream))
            with pytest.raises(OSError):
                snapshot.path.write_bytes(b'corrupt')
            with pytest.raises(OSError):
                snapshot.path.unlink()
            with pytest.raises(OSError):
                snapshot.path.rename(snapshot.path.with_suffix('.other'))
        assert fs._launcher_bytes == sum(item.size for item in snapshots)
    finally:
        batch.close()
        assert store.close() == ()
    assert not store.path.exists()


def test_source_is_pinned_before_consent(inputs):
    ordinary, private = inputs
    path = text(ordinary)
    batch = fs.capture([path])
    try:
        with pytest.raises(OSError): path.write_bytes(b'replaced')
        with pytest.raises(OSError): path.unlink()
        with pytest.raises(OSError): ordinary.rename(ordinary.with_name('replacement'))
        assert not os.get_handle_inheritable(fs._handle(batch.files[0]._stream))
    finally:
        assert batch.close() == ()
    path.write_bytes(b'after canceled consent')


@pytest.mark.parametrize('name,data', [('empty.txt', b''), ('script.exe', b'bad'), ('fake.png', b'no image'),
                                        ('fake.pdf', b'not a pdf'), ('fake.zip', b'no zip')])
def test_invalid_sources_fail_capture_or_staging_as_whole(inputs, name, data):
    ordinary, private = inputs
    good, bad = text(ordinary), text(ordinary, name, data)
    store = fs.SnapshotStore(private)
    batch = None
    try:
        with pytest.raises((fs.SelectionError, ValueError)):
            batch = fs.capture([good, bad])
            store.stage(batch)
        assert store.snapshots == []
        assert fs._launcher_bytes == 0
        assert list(store.path.iterdir()) == []
    finally:
        if batch: batch.close()
        assert store.close() == ()


def test_cancellation_new_batch_does_not_retire_previous_files(inputs):
    ordinary, private = inputs
    batch = fs.capture([text(ordinary)])
    store = fs.SnapshotStore(private)
    try:
        earlier = store.stage(batch)
        with pytest.raises(fs.SelectionCanceled):
            store.stage(batch, cancel=lambda: True)
        assert store.snapshots == list(earlier)
        assert earlier[0].path.read_bytes()
        assert fs._launcher_bytes == earlier[0].size
        store.discard(earlier)
        assert not earlier[0].path.exists()
    finally:
        batch.close()
        assert store.close() == ()


def test_existing_writable_mapping_is_refused_after_writer_handle_closes(inputs):
    import mmap
    ordinary, _ = inputs
    path = text(ordinary)
    with path.open('r+b') as writer:
        mapping = mmap.mmap(writer.fileno(), 0, access=mmap.ACCESS_WRITE)
    try:
        # A live writable section still owns write access even after the
        # creating file handle closes. It cannot coexist with our read seal.
        with pytest.raises(OSError): fs.capture([path])
        mapping[0:1] = b'X'
        mapping.flush()
    finally:
        mapping.close()
    batch = fs.capture([path])
    batch.close()


def test_cancel_during_chunked_copy_releases_only_new_quota(inputs):
    ordinary, private = inputs
    batch = fs.capture([text(ordinary, data=b'x' * (fs.CHUNK * 2))])
    store = fs.SnapshotStore(private)
    stop = threading.Event()
    try:
        with pytest.raises(fs.SelectionCanceled):
            store.stage(batch, cancel=stop.is_set, progress=lambda *_: stop.set())
        assert fs._launcher_bytes == 0
        assert store.snapshots == [] and list(store.path.iterdir()) == []
        assert not store.cleanup_errors
    finally:
        batch.close()
        assert store.close() == ()


def test_private_roots_and_local_only_exceptions(inputs):
    ordinary, private = inputs
    downloads = private / 'downloads'
    downloads.mkdir(mode=0o700)
    selected = text(downloads)
    with pytest.raises(fs.SelectionError): fs.capture([selected], blocked_roots=[private])
    batch = fs.capture([selected], blocked_roots=[private], allowed_private_roots=[downloads])
    batch.close()
    secret = text(private, 'configuration.txt')
    with pytest.raises(fs.SelectionError):
        fs.capture([secret], blocked_roots=[private], allowed_private_roots=[downloads])


def test_case_and_short_path_cannot_bypass_private_root(inputs):
    ordinary, private = inputs
    path = text(private)
    with pytest.raises(fs.SelectionError): fs.capture([str(path).upper()], blocked_roots=[private])
    short_path = c.create_unicode_buffer(32768)
    short_name = fs.wf.api(fs.wf.k, 'GetShortPathNameW', fs.w.DWORD,
                          fs.w.LPCWSTR, fs.w.LPWSTR, fs.w.DWORD)
    count = short_name(str(path), short_path, len(short_path))
    if count and short_path.value != str(path):
        with pytest.raises(fs.SelectionError): fs.capture([short_path.value], blocked_roots=[private])


def test_hard_link_refused(inputs):
    ordinary, _ = inputs
    path = text(ordinary)
    other = ordinary / 'hard.txt'
    os.link(path, other)
    with pytest.raises(ValueError): fs.capture([path])


def test_reparse_directory_refused_when_unprivileged_symlink_available(inputs):
    ordinary, _ = inputs
    path = text(ordinary)
    link = ordinary.parent / 'directory-link'
    try:
        link.symlink_to(ordinary, target_is_directory=True)
    except OSError:
        pytest.skip('host does not grant unprivileged symlink creation')
    with pytest.raises(ValueError): fs.capture([link / path.name])


def test_open_writer_and_unreadable_file_are_refused(inputs):
    ordinary, _ = inputs
    path = text(ordinary)
    with path.open('r+b'):
        with pytest.raises(OSError): fs.capture([path])
    # A real deny-read handle creates a sharing failure without modifying ACLs.
    handle = fs.wf.create(str(path), 0x80000000 | 0x80, 0, None, 3, 0x00200000, None)
    assert handle != fs.w.HANDLE(-1).value
    try:
        with pytest.raises(OSError): fs.capture([path])
    finally:
        fs.wf.close(handle)


def test_oversized_selection_and_per_file_limits(inputs, monkeypatch):
    ordinary, _ = inputs
    path = text(ordinary)
    with pytest.raises(fs.SelectionError): fs.capture([path] * 26)
    monkeypatch.setitem(fs.TYPE_LIMITS, '.txt', 2)
    with pytest.raises(fs.SelectionError): fs.capture([path])


@pytest.mark.parametrize('limit', ['PAGE_FILES', 'PAGE_BYTES', 'LAUNCHER_BYTES'])
def test_quota_refusal_and_release(inputs, monkeypatch, limit):
    ordinary, private = inputs
    batch = fs.capture([text(ordinary)])
    store = fs.SnapshotStore(private)
    try:
        earlier = store.stage(batch)
        monkeypatch.setattr(fs, limit, 1 if limit == 'PAGE_FILES' else earlier[0].size)
        with pytest.raises(fs.SelectionError, match='Close and reopen'):
            store.stage(batch)
        assert store.snapshots == list(earlier)
    finally:
        batch.close()
        assert store.close() == ()


def test_source_identity_rechecked_not_just_size_mtime(inputs, monkeypatch):
    ordinary, private = inputs
    batch = fs.capture([text(ordinary)])
    store = fs.SnapshotStore(private)
    real = fs._fingerprint
    calls = 0
    def mutated(handle):
        nonlocal calls
        result = real(handle)
        if handle == fs._handle(batch.files[0]._stream):
            calls += 1
            if calls > 1:
                return (*result[:-1], result[-1] + 1)
        return result
    monkeypatch.setattr(fs, '_fingerprint', mutated)
    try:
        with pytest.raises(fs.SelectionError, match='changed'):
            store.stage(batch)
        assert store.snapshots == [] and fs._launcher_bytes == 0
    finally:
        batch.close()
        assert store.close() == ()


@pytest.mark.parametrize('member', ['../escape.txt', '/absolute.txt', 'C:/drive.txt'])
def test_malicious_archive_members_refused(inputs, member):
    ordinary, private = inputs
    path = ordinary / 'unsafe.zip'
    with zipfile.ZipFile(path, 'w') as archive: archive.writestr(member, 'synthetic')
    batch, store = fs.capture([path]), fs.SnapshotStore(private)
    try:
        with pytest.raises(fs.SelectionError, match='unsafe'):
            store.stage(batch)
        assert list(store.path.iterdir()) == []
    finally:
        batch.close()
        assert store.close() == ()


def test_cleanup_failure_does_not_leak_handles_or_quota(inputs, monkeypatch):
    ordinary, private = inputs
    batch, store = fs.capture([text(ordinary)]), fs.SnapshotStore(private)
    snapshots = store.stage(batch)
    real = store._remove_exact
    def failure(path, expected, directory, pins):
        pins.close()
        store.cleanup_errors.append('Synthetic cleanup failure; unexpected bytes preserved.')
    monkeypatch.setattr(store, '_remove_exact', failure)
    batch.close()
    assert store.close()
    assert snapshots[0]._stream.closed and fs._launcher_bytes == 0
    assert snapshots[0].path.exists()
    # Test teardown removes only the exact synthetic objects after restoring
    # the cleanup primitive; production never replays leftover crash stages.
    monkeypatch.setattr(store, '_remove_exact', real)
    snapshots[0].path.unlink()
    snapshots[0]._directory.rmdir()
    store.path.rmdir()


def test_store_does_not_adopt_old_staging(inputs):
    _, private = inputs
    old = private / '.dlms-selected-old-evidence'
    old.mkdir(mode=0o700)
    evidence = text(old)
    store = fs.SnapshotStore(private)
    assert store.path != old and store.snapshots == []
    assert store.close() == () and evidence.read_bytes()


def test_compact_private_names_preserve_128_bits_under_windows_case_folding(inputs, monkeypatch):
    import base64
    ordinary, private = inputs
    requested = []
    raw = bytes(range(16))
    monkeypatch.setattr(fs.secrets, 'token_bytes', lambda amount: requested.append(amount) or raw)
    store = fs.SnapshotStore(private)
    batch = fs.capture([text(ordinary)])
    try:
        encoded = store.path.name.removeprefix('.wv-s-')
        assert len(encoded) == 26 and encoded == encoded.lower()
        assert base64.b32decode(encoded.upper() + '=' * 6) == raw
        assert requested == [16] and len(store.path.name) == 32
        snapshot, = store.stage(batch)
        assert snapshot.path.parent.name == encoded and snapshot.name == 'quiz 日本語.txt'
        assert requested == [16, 16]
    finally:
        batch.close()
        assert store.close() == ()


def test_actual_junction_path_refused_without_privileged_symlink(inputs):
    ordinary, _ = inputs
    path = text(ordinary)
    junction = ordinary.parent / 'directory junction'
    made = subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(junction), str(ordinary)],
                          capture_output=True, text=True)
    if made.returncode:
        pytest.skip('junction creation unavailable: ' + made.stderr.strip())
    try:
        with pytest.raises(ValueError): fs.capture([junction / path.name])
    finally:
        os.rmdir(junction)  # Removes the junction itself, never its target.


def test_pending_reservations_count_against_page_quota(inputs, monkeypatch):
    ordinary, private = inputs
    batch, store = fs.capture([text(ordinary)]), fs.SnapshotStore(private)
    entered, release = threading.Event(), threading.Event()
    outcome = []
    monkeypatch.setattr(fs, 'PAGE_FILES', 1)
    def worker():
        try:
            outcome.append(store.stage(batch, progress=lambda *_: (entered.set(), release.wait(5))))
        except Exception as error:
            outcome.append(error)
    thread = threading.Thread(target=worker)
    thread.start()
    try:
        assert entered.wait(5)
        assert store.snapshots == []
        with pytest.raises(fs.SelectionError, match='Close and reopen'): store.stage(batch)
    finally:
        release.set()
        thread.join(5)
        assert not thread.is_alive()
        batch.close()
        assert store.close() == ()
    assert len(outcome) == 1 and isinstance(outcome[0], tuple)


def test_close_during_stage_cancels_then_releases_directory(inputs):
    ordinary, private = inputs
    batch = fs.capture([text(ordinary, data=b'x' * (fs.CHUNK * 2))])
    store = fs.SnapshotStore(private)
    entered, release = threading.Event(), threading.Event()
    outcome = []
    def worker():
        try:
            store.stage(batch, progress=lambda *_: (entered.set(), release.wait(5)))
        except Exception as error:
            outcome.append(error)
    thread = threading.Thread(target=worker)
    thread.start()
    try:
        assert entered.wait(5)
        assert store.close() == ()
        assert store.path.exists()  # Pending copy still owns its directory pins.
    finally:
        release.set()
        thread.join(5)
        assert not thread.is_alive()
        batch.close()
    assert len(outcome) == 1 and isinstance(outcome[0], fs.SelectionCanceled)
    assert store.close() == () and not store.path.exists()


def test_created_file_acl_checked_before_first_byte(inputs, monkeypatch):
    ordinary, private = inputs
    batch, store = fs.capture([text(ordinary)]), fs.SnapshotStore(private)
    actual = fs.wf.owned_handle
    calls, progress = [], []
    def reject_first(handle, **kwargs):
        if fs.wf.info(handle).attributes & 0x10:
            return actual(handle, **kwargs)
        if not calls:
            calls.append(fs._fingerprint(handle)[3])
            raise fs.SelectionError('Synthetic unsafe created-file ACL')
        return actual(handle, **kwargs)
    monkeypatch.setattr(fs.wf, 'owned_handle', reject_first)
    try:
        with pytest.raises(fs.SelectionError, match='unsafe created-file ACL'):
            store.stage(batch, progress=lambda *_: progress.append(True))
        assert calls == [0] and progress == []
        assert list(store.path.iterdir()) == []
    finally:
        batch.close()
        assert store.close() == ()


def test_cleanup_leaf_substitution_preserves_new_object(inputs):
    ordinary, private = inputs
    batch, store = fs.capture([text(ordinary)]), fs.SnapshotStore(private)
    snapshot, = store.stage(batch)
    stream = snapshot._stream
    evidence = snapshot.path.with_name('old evidence.txt')
    class ReplacingClose:
        def close(self):
            stream.close()
            snapshot.path.rename(evidence)
            snapshot.path.write_bytes(b'newer private evidence')
    snapshot._stream = ReplacingClose()
    batch.close()
    store.discard([snapshot])
    assert store.cleanup_errors and fs._launcher_bytes == 0
    assert snapshot.path.read_bytes() == b'newer private evidence'
    assert evidence.exists()
    store.close()
    snapshot.path.unlink()
    evidence.unlink()
    snapshot._directory.rmdir()
    store.path.rmdir()


def test_cleanup_directory_substitution_preserves_new_object(inputs):
    ordinary, private = inputs
    batch, store = fs.capture([text(ordinary)]), fs.SnapshotStore(private)
    snapshot, = store.stage(batch)
    pins = snapshot._pins
    evidence = snapshot._directory.with_name('old directory evidence')
    class ReplacingPins:
        def close(self):
            pins.close()
            snapshot._directory.rename(evidence)
            snapshot._directory.mkdir(mode=0o700)
            text(snapshot._directory, 'replacement.txt', b'newer directory evidence')
    snapshot._pins = ReplacingPins()
    batch.close()
    store.discard([snapshot])
    assert store.cleanup_errors and fs._launcher_bytes == 0
    assert (snapshot._directory / 'replacement.txt').read_bytes() == b'newer directory evidence'
    store.close()
    (snapshot._directory / 'replacement.txt').unlink()
    snapshot._directory.rmdir()
    evidence.rmdir()
    store.path.rmdir()


def zip_bytes(count):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        for index in range(count): archive.writestr(f'directory-{index}/', b'')
    stream.seek(0)
    return stream


def test_zip_actual_member_bound_and_boundary():
    fs._zip_directory_bound(zip_bytes(fs.ZIP_ENTRIES), cancel=lambda: False)
    with pytest.raises(fs.SelectionError, match='bounds'):
        fs._zip_directory_bound(zip_bytes(fs.ZIP_ENTRIES + 1), cancel=lambda: False)


def test_zip_lying_eocd_count_rejected_by_actual_directory_walk():
    raw = bytearray(zip_bytes(3).getvalue())
    offset = raw.rfind(zipfile.stringEndArchive)
    struct.pack_into('<HH', raw, offset + 8, 1, 1)
    with pytest.raises(fs.SelectionError, match='inconsistent'):
        fs._zip_directory_bound(io.BytesIO(raw), cancel=lambda: False)


def test_zip_lying_directory_member_length_refused():
    raw = bytearray(zip_bytes(1).getvalue())
    offset = raw.find(zipfile.stringCentralDir)
    struct.pack_into('<H', raw, offset + 28, 65535)
    with pytest.raises(fs.SelectionError, match='boundary'):
        fs._zip_directory_bound(io.BytesIO(raw), cancel=lambda: False)


def test_normal_zip64_member_remains_supported():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        with archive.open('normal.txt', 'w', force_zip64=True) as member: member.write(b'synthetic')
    stream.seek(0)
    fs._validate(stream, 'normal.zip')

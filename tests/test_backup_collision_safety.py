"""Distinct fixed-clock and concurrent snapshots must never replace each other."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import threading
import zipfile
from types import SimpleNamespace

import pytest

from tests.test_backup_size_contract import creator, dlms
from dlms.services import backups


def contents(path):
    with zipfile.ZipFile(path) as archive:
        assert archive.testzip() is None
        return {name: archive.read(name) for name in archive.namelist()}


def test_same_second_backups_preserve_both_snapshots(creator):
    create, output = creator
    first, _ = create()
    original = Path(first).read_bytes()
    (output.parent / 'portal.json').write_text('{"title":"Changed"}')
    second, _ = create()
    assert first != second
    assert Path(first).read_bytes() == original
    assert contents(first)['DLMS_DATA/config/portal.json'] != contents(second)['DLMS_DATA/config/portal.json']
    assert len(list(output.glob('*.zip'))) == 2


def test_simultaneous_fixed_clock_backups_are_complete_and_restorable(creator):
    create, output = creator
    barrier = threading.Barrier(4)
    def validate(path):
        result = dlms._validate_dlms_backup(path)
        barrier.wait(timeout=5)
        return result
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: create(validator=validate), range(4)))
    paths = [Path(path) for path, _ in results]
    assert len(set(paths)) == 4
    for index, path in enumerate(paths):
        assert contents(path)
        report = dlms._validate_dlms_backup(path)
        stage = output.parent / f'restore-{index}'
        dlms._extract_validated_backup(path, str(stage), report)
        dlms._validate_staged_backup_semantics(str(stage), report['manifest'])
        dlms.bootstrap_database(str(stage / 'results.db'), require_owned_root=False)
        dlms._validate_current_restored_database(str(stage / 'results.db'))
    assert sorted(output.iterdir()) == sorted(paths)


def test_even_a_repeated_generated_name_cannot_replace_snapshot(creator, monkeypatch):
    create, output = creator
    names = iter(['a' * 32, 'a' * 32, 'b' * 32])
    monkeypatch.setattr(backups.uuid, 'uuid4', lambda: SimpleNamespace(hex=next(names)))
    first, _ = create()
    original = Path(first).read_bytes()
    second, _ = create()
    assert first != second
    assert Path(first).read_bytes() == original
    assert len(list(output.iterdir())) == 2


def test_failed_atomic_publication_preserves_prior_backup(creator, monkeypatch):
    create, output = creator
    first, _ = create()
    original = Path(first).read_bytes()
    def failure(*args):
        raise OSError('Atomic publication unavailable')
    monkeypatch.setattr(backups.os, 'link', failure)
    with pytest.raises(OSError, match='Atomic publication unavailable'):
        create()
    assert Path(first).read_bytes() == original
    assert list(output.iterdir()) == [Path(first)]


def test_backup_flush_uses_writable_handle_without_truncation(creator, monkeypatch):
    """Windows flushing requires write access; opening r+b keeps ZIP bytes."""
    create, _ = creator
    writable = {}
    seen = []
    real_open, real_fsync = open, os.fsync

    def record_open(path, *args, **kwargs):
        handle = real_open(path, *args, **kwargs)
        if str(path).endswith('.zip.tmp'):
            writable[handle.fileno()] = handle.writable()
        return handle

    def flush(fd):
        access = writable.pop(fd, None)
        if access is not None:
            seen.append(access)
            if not access:
                raise OSError('Windows flushing requires a writable file handle')
        return real_fsync(fd)

    monkeypatch.setattr(backups, 'open', record_open, raising=False)
    monkeypatch.setattr(backups.os, 'fsync', flush)
    path, _ = create()
    assert seen == [True]
    assert contents(path)

"""Bounded ordinary-folder selection and no-replace publication faults."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

from desktop import backup_output as output
from desktop import backup_selection as binding


def test_ordinary_source_and_unsupported_paths(tmp_path):
    source = tmp_path / 'Documents' / 'backup.zip'
    source.parent.mkdir()
    source.write_bytes(b'fixture')
    assert binding._source_path(source)[0] == source
    for path in (Path('relative.zip'), source.with_suffix('.txt')):
        with pytest.raises(ValueError): binding._source_path(path)
    link = tmp_path / 'link.zip'; link.symlink_to(source)
    with pytest.raises(ValueError): binding._source_path(link)
    fifo = tmp_path / 'pipe.zip'; os.mkfifo(fifo)
    with pytest.raises(ValueError): binding._source_path(fifo)


def files(tmp_path):
    source = tmp_path / 'private.zip'; source.write_bytes(b'complete synthetic backup' * 100)
    destination = tmp_path / 'Documents' / 'visible.zip'; destination.parent.mkdir(mode=0o700)
    return source, destination


def test_publish_exact_bytes_and_collision(tmp_path):
    source, destination = files(tmp_path)
    selected = output.select(destination)
    result = output.publish(source, selected)
    assert destination.read_bytes() == source.read_bytes()
    assert destination.stat().st_mode & 0o777 == 0o600
    assert result['bytes'] == source.stat().st_size
    with pytest.raises(FileExistsError): output.publish(source, selected)
    assert destination.read_bytes() == source.read_bytes()
    with pytest.raises(FileExistsError): output.select(destination)


@pytest.mark.parametrize('phase', ['copy', 'before_publish', 'published'])
def test_fault_boundaries(tmp_path, phase):
    source, destination = files(tmp_path)
    def fail(checkpoint):
        if checkpoint == phase: raise OSError('simulated write/cleanup failure')
    with pytest.raises((OSError, RuntimeError)):
        output.publish(source, output.select(destination), checkpoint=fail)
    assert destination.exists() == (phase == 'published')
    if destination.exists(): assert destination.read_bytes() == source.read_bytes()
    assert source.exists()


@pytest.mark.parametrize('phase', ['before_publish', 'published'])
def test_process_interruption(tmp_path, phase):
    source, destination = files(tmp_path)
    import json
    selected = output.select(destination)
    code = '''import json,os,sys
from pathlib import Path
from desktop.backup_output import publish
publish(Path(sys.argv[1]), json.loads(sys.argv[2]), checkpoint=lambda p: os._exit(73) if p == sys.argv[3] else None)
'''
    run = subprocess.run([sys.executable, '-c', code, str(source), json.dumps(selected), phase])
    assert run.returncode == 73
    assert destination.exists() == (phase == 'published')
    if destination.exists(): assert destination.read_bytes() == source.read_bytes()
    assert list(destination.parent.glob('.dlms-backup-*.part'))


def test_parent_swap_and_symlinks(tmp_path):
    source, destination = files(tmp_path)
    selected = output.select(destination)
    moved = tmp_path / 'moved'; destination.parent.rename(moved); destination.parent.mkdir()
    with pytest.raises(ValueError, match='changed'): output.publish(source, selected)
    link = tmp_path / 'linked'; link.symlink_to(moved, target_is_directory=True)
    with pytest.raises(OSError): output.select(link / 'new.zip')
    dangling = destination.parent / 'dangling.zip'; dangling.symlink_to('/does-not-exist')
    with pytest.raises(FileExistsError): output.select(dangling)


def test_collision_at_publication_preserved(tmp_path):
    source, destination = files(tmp_path)
    def race(phase):
        if phase == 'before_publish': destination.write_bytes(b'unrelated winner')
    with pytest.raises(FileExistsError): output.publish(source, output.select(destination), checkpoint=race)
    assert destination.read_bytes() == b'unrelated winner'


def test_parent_move_after_link_is_uncertain(tmp_path):
    source, destination = files(tmp_path)
    def race(phase):
        if phase == 'published': destination.parent.rename(tmp_path / 'moved')
    with pytest.raises(RuntimeError, match='may exist'):
        output.publish(source, output.select(destination), checkpoint=race)
    assert (tmp_path / 'moved' / destination.name).read_bytes() == source.read_bytes()


def test_managed_destination_refused(tmp_path):
    _, destination = files(tmp_path)
    with pytest.raises(ValueError, match='managed'):
        output.select(destination, forbidden=(tmp_path,))


def test_ambiguous_double_slash_root_refused(tmp_path):
    source, destination = files(tmp_path)
    with pytest.raises(ValueError): output.select(Path('/' + str(destination)), forbidden=(destination.parent,))
    with pytest.raises(ValueError): binding._source_path(Path('/' + str(source)))


@pytest.mark.parametrize('fail_call,exists',[(1,False),(2,True),(3,True)])
def test_directory_and_file_sync_failures(tmp_path,monkeypatch,fail_call,exists):
    source,destination=files(tmp_path)
    real=output.os.fsync; calls=[]
    def sync(fd):
        calls.append(fd)
        if len(calls)==fail_call:raise OSError('simulated fsync failure')
        return real(fd)
    monkeypatch.setattr(output.os,'fsync',sync)
    with pytest.raises((OSError,RuntimeError)):
        output.publish(source,output.select(destination))
    assert destination.exists()==exists
    if exists:assert destination.read_bytes()==source.read_bytes()


def test_existing_temporary_collision_preserved(tmp_path):
    source,destination=files(tmp_path);selected=output.select(destination)
    temporary=destination.parent/f".dlms-backup-{selected['operation']}.part"
    temporary.write_bytes(b'prior evidence')
    with pytest.raises(FileExistsError):output.publish(source,selected)
    assert temporary.read_bytes()==b'prior evidence' and not destination.exists()


def test_substituted_temporary_is_not_deleted(tmp_path):
    source,destination=files(tmp_path);selected=output.select(destination)
    temporary=destination.parent/f".dlms-backup-{selected['operation']}.part"
    def substitute(phase):
        if phase=='before_publish':
            temporary.unlink();temporary.write_bytes(b'unrelated substituted file')
    with pytest.raises(ValueError,match='temporary file changed'):
        output.publish(source,selected,checkpoint=substitute)
    assert temporary.read_bytes()==b'unrelated substituted file' and not destination.exists()


def test_unwritable_destination_does_not_damage_existing_file(tmp_path):
    source,destination=files(tmp_path);selected=output.select(destination)
    survivor=destination.parent/'other.txt';survivor.write_bytes(b'keep')
    destination.parent.chmod(0o500)
    try:
        with pytest.raises(PermissionError):output.publish(source,selected)
        assert survivor.read_bytes()==b'keep' and not destination.exists()
    finally:destination.parent.chmod(0o700)

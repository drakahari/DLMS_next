"""Native API checks; these are not normal-package physical acceptance."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Native Windows APIs")


def test_external_dispatch_seals_low_level_descriptor_above_stdio_limit(tmp_path):
    from desktop.package_entry import _seal_private_descriptors
    fd=os.open(tmp_path/'synthetic-private-handle',os.O_RDWR|os.O_CREAT|os.O_EXCL,0o600)
    high=1000
    try:
        os.dup2(fd,high,inheritable=True)
        assert os.get_inheritable(high)
        _seal_private_descriptors()
        assert not os.get_inheritable(fd) and not os.get_inheritable(high)
    finally:
        os.close(high);os.close(fd)

def test_process_identity_and_command_line():
    from desktop.windows_processes import identity, arguments
    value = identity(os.getpid())
    assert value["start"] > 0 and value["sid"].startswith("S-1-5-")
    assert Path(arguments(os.getpid())[0]).name.lower().startswith("python")
    assert value == identity(os.getpid())

@pytest.mark.parametrize("name", ["file.zip:ads", "CON.zip", "NUL", "file. ", "a/../b.zip", "\\\\server\\share\\file.zip"])
def test_path_alias_refusal(tmp_path, name):
    from desktop.windows_files import lexical
    path = Path(name) if name.startswith("\\\\") else tmp_path / name
    with pytest.raises(ValueError):
        lexical(path)

def test_atomic_unicode_json_and_acl(tmp_path):
    from desktop.profile_state import atomic_json
    from desktop.windows_files import owned
    root = tmp_path / "Synthetic path with spaces 日本語"
    root.mkdir(mode=0o700)
    owned(root, private=True)
    path = root / "identity.json"
    atomic_json(path, {"value": "first"})
    atomic_json(path, {"value": "second"})
    assert json.loads(path.read_text()) == {"value": "second"}
    assert sorted(x.name for x in root.iterdir()) == ["identity.json"]

def test_read_handle_denies_mutation_and_pins_parents(tmp_path):
    from desktop.windows_files import open_read
    root = tmp_path / "parent"
    root.mkdir(mode=0o700)
    source = root / "input.zip"
    source.write_bytes(b"confirmed bytes\r\n")
    fd = open_read(source)
    try:
        assert os.read(fd, 99) == b"confirmed bytes\r\n"
        with pytest.raises(PermissionError):
            source.write_bytes(b"replacement")
        with pytest.raises(PermissionError):
            source.unlink()
    finally:
        os.close(fd)
    from desktop.windows_files import pinned_parents
    with pinned_parents(source):
        with pytest.raises(PermissionError):
            root.rename(tmp_path / "substituted")

def test_junction_refused(tmp_path):
    from desktop.windows_files import assert_path
    target = tmp_path / "target"
    target.mkdir()
    junction = tmp_path / "junction"
    result = subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(junction), str(target)], capture_output=True)
    assert result.returncode == 0
    try:
        with pytest.raises(ValueError):
            assert_path(junction / "output.zip")
    finally:
        junction.rmdir()

def test_writer_lock_excludes_second_process(tmp_path):
    from desktop.backend import acquire_writer_lock
    path = tmp_path / "writer.lock"
    with acquire_writer_lock(path):
        script = "import os,sys; from desktop.platform_files import lock; fd=os.open(sys.argv[1],os.O_RDWR); lock(fd)"
        result = subprocess.run([sys.executable, "-c", script, str(path)], capture_output=True)
        assert result.returncode != 0 and b"PermissionError" in result.stderr
    with acquire_writer_lock(path):
        pass

def test_backup_publication_no_overwrite_and_parent_substitution(tmp_path):
    from desktop.backup_output import select, publish
    root = tmp_path / "Destination 日本語"
    root.mkdir(mode=0o700)
    source = tmp_path / "private.zip"
    source.write_bytes(b"zip bytes\r\n" * 100)
    destination = root / "backup.zip"
    chosen = select(destination)
    def checkpoint(stage):
        if stage == "before_publish":
            with pytest.raises(PermissionError):
                root.rename(tmp_path / "swapped")
    result = publish(source, chosen, checkpoint=checkpoint)
    assert destination.read_bytes() == source.read_bytes()
    assert result["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    with pytest.raises(FileExistsError):
        select(destination)
    collision = root / "collision.zip"
    selection = select(collision)
    collision.write_bytes(b"unrelated")
    with pytest.raises(OSError):
        publish(source, selection)
    assert collision.read_bytes() == b"unrelated"

def test_job_owner_death_removes_descendant(tmp_path):
    from desktop.windows_processes import open_process, checked, close, api, k
    import ctypes as c
    from ctypes import wintypes as w
    script = """
from desktop.windows_processes import own_launcher
import subprocess,sys,time
own_launcher()
p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])
print(p.pid,flush=True)
time.sleep(60)
"""
    proc = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    child_handle = None
    try:
        pid = int(proc.stdout.readline())
        child_handle = checked(open_process(0x100000, False, pid))
        proc.kill()
        proc.wait(timeout=5)
        wait = api(k, "WaitForSingleObject", w.DWORD, w.HANDLE, w.DWORD)
        assert wait(child_handle, 5000) == 0
    finally:
        if child_handle:
            close(child_handle)
        if proc.poll() is None:
            proc.kill()
        proc.communicate(timeout=5)

def test_backup_failure_deletes_retained_handle(tmp_path):
    from desktop.backup_output import select, publish
    source, destination = tmp_path / "source.zip", tmp_path / "backup.zip"
    source.write_bytes(b"confirmed")
    selection = select(destination)
    temporary = destination.parent / (".dlms-backup-" + selection["operation"] + ".part")
    observed = []
    def checkpoint(stage):
        if stage == "before_publish":
            raise RuntimeError("synthetic copy failure")
        if stage == "before_cleanup":
            with pytest.raises(PermissionError):
                temporary.rename(tmp_path / "stolen")
            with pytest.raises(PermissionError):
                temporary.write_bytes(b"unrelated")
            observed.append(stage)
    with pytest.raises(RuntimeError, match="synthetic copy failure"):
        publish(source, selection, checkpoint=checkpoint)
    assert observed == ["before_cleanup"] and not temporary.exists() and not destination.exists()

def test_frozen_identity_binds_default_and_every_option_form(tmp_path):
    from desktop.ownership import windows_launch_matches
    default, explicit = tmp_path / "default", tmp_path / "explicit"
    assert windows_launch_matches(["app"], "default", default, default)
    assert not windows_launch_matches(["app"], "default", explicit, default)
    args = ["app", "--profile=synthetic", "--data-root=" + str(explicit)]
    assert windows_launch_matches(args, "synthetic", explicit, default)
    for extra in (["--profile=synthetic"], ["--profile", "synthetic"],
                  ["--data-root=" + str(explicit)], ["--data-root", str(explicit)], ["--desktop-worker", "backend"]):
        assert not windows_launch_matches(args + extra, "synthetic", explicit, default)

@pytest.mark.parametrize("relative", ["backend", "web"])
def test_managed_subdirectory_junction_refused_before_write(tmp_path, relative):
    from unittest.mock import patch
    import desktop.isolation as isolation
    area=tmp_path/"private"
    area.mkdir(mode=0o700)
    profiles=area/"profiles";profiles.mkdir(mode=0o700)
    root=profiles/"junctiontest";root.mkdir(mode=0o700)
    outside=tmp_path/"outside";outside.mkdir()
    sentinel=outside/"sentinel.txt";sentinel.write_bytes(b"unchanged")
    junction=root/relative
    result=subprocess.run(["cmd.exe","/c","mklink","/J",str(junction),str(outside)],capture_output=True)
    assert result.returncode==0
    try:
        with patch.object(isolation,"AREA",area),patch.object(isolation,"PROFILES",profiles):
            with pytest.raises(ValueError,match="reparse"):
                isolation.profile_paths("junctiontest")
        assert [(x.name,x.read_bytes()) for x in outside.iterdir()]==[("sentinel.txt",b"unchanged")]
    finally:junction.rmdir()

def test_backup_path_and_pinned_descriptor_agree(tmp_path):
    from desktop.backup_selection import _source_path,_open_source,_same_source
    source=tmp_path/"source.zip";source.write_bytes(b"original")
    _,initial=_source_path(source);fd=_open_source(source)
    try:
        assert _same_source(source,os.fstat(fd),initial)
        other=tmp_path/"different.zip";other.write_bytes(b"original")
        assert not _same_source(other,os.fstat(fd),initial)
    finally:os.close(fd)

def test_candidate_data_cannot_be_inside_payload(tmp_path,monkeypatch):
    from package_windows.entry import root_path
    payload=tmp_path/'Application payload';payload.mkdir()
    monkeypatch.setattr(sys,'executable',str(payload/'DLMS-Desktop.exe'))
    for path in (payload,payload/'data',tmp_path):
        with pytest.raises(ValueError,match='outside the application payload'):
            root_path(path,create=True)
    assert not (payload/'data').exists()

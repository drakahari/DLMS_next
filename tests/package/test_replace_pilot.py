"""Isolated synthetic homes only; no installed pilot is modified."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from desktop.package_entry import _root, main as frozen_entry
from package_fedora.install_pilot import install, inventory, paths, sha256
from package_fedora.replace_pilot import (activate, reconcile, retire_stale_descriptors,
                                          rollback, stage, verify)
import package_fedora.replace_pilot as replacement
from tests.package.test_install_pilot import fixture_inputs


def prepared(tmp_path):
    home, old, archive, archive_sha, old_sha = fixture_inputs(tmp_path)
    install(home, old, archive, archive_sha, old_sha)
    p = paths(home)
    (p["data"] / "shell/pilot01").mkdir(parents=True)
    (p["data"] / "profiles/pilot01").mkdir(parents=True)
    (p["data"] / "profiles/pilot01/backend-writer.lock").write_bytes(b"")
    sentinel = p["data"] / "profiles/pilot01/quiz.txt"
    sentinel.write_text("original synthetic quiz and Study history\n")
    new = tmp_path / "new-payload"
    import shutil
    shutil.copytree(old, new)
    exe = new / "DLMS-Desktop"
    exe.write_text("#!/bin/sh\nexit 2\n")
    exe.chmod(0o755)
    new_archive = tmp_path / "new-review.tar.zst"
    new_archive.write_bytes(b"distinct reviewed pilot-02 archive\n")
    digest = sha256(new_archive)
    stage(home, new_archive, digest, new, inventory(new))
    return home, p, digest, sentinel


def _check_root_in_separate_process(data: Path) -> subprocess.CompletedProcess:
    command = ("import sys; sys._MEIPASS='/tmp/dlms-pilot-unit-payload'; "
               "from desktop.package_entry import _root; "
               f"_root({str(data)!r}, kind='installed-pilot', profile='pilot01')")
    return subprocess.run([sys.executable, "-c", command], capture_output=True, text=True)


def test_staged_activation_startup_and_rollback_preserve_data(tmp_path, monkeypatch):
    home, p, digest, sentinel = prepared(tmp_path)
    before = sentinel.read_bytes()
    old_payload = inventory(p["version"] / "DLMS-Desktop")
    monkeypatch.setattr(sys, "_MEIPASS", "/tmp/dlms-pilot-unit-payload", raising=False)
    assert _root(str(p["data"]), kind="installed-pilot", profile="pilot01") == p["data"]
    result = activate(home, digest)
    assert result["version"] == 2
    assert p["current"].readlink() == Path("versions/pilot-02")
    assert verify(home)[0]["phase"] == "complete"
    assert _check_root_in_separate_process(p["data"]).returncode == 0
    assert "--pilot-launch" in p["launcher"].read_text()
    assert inventory(p["version"] / "DLMS-Desktop") == old_payload
    assert sentinel.read_bytes() == before
    with pytest.raises(ValueError, match="already active"):
        activate(home, digest)
    assert rollback(home)["current_target"] == "versions/pilot-01"
    assert sentinel.read_bytes() == before
    assert verify(home)[0]["version"] == 2
    assert "--pilot-launch" in p["launcher"].read_text()
    assert (p["opt"] / "versions/pilot-02/DLMS-Desktop").is_dir()
    assert _check_root_in_separate_process(p["data"]).returncode == 0


def test_frozen_executable_must_match_manifest_version(tmp_path, monkeypatch):
    home, p, digest, sentinel = prepared(tmp_path)
    activate(home, digest)
    monkeypatch.setattr(sys, "_MEIPASS", "/tmp/dlms-pilot-unit-payload", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(p["version"] / "DLMS-Desktop/DLMS-Desktop"))
    with pytest.raises(ValueError, match="executable"):
        _root(str(p["data"]), kind="installed-pilot", profile="pilot01")
    monkeypatch.setattr(sys, "executable", str(p["opt"] / "versions/pilot-02/DLMS-Desktop/DLMS-Desktop"))
    assert _root(str(p["data"]), kind="installed-pilot", profile="pilot01") == p["data"]


def test_guarded_launcher_execs_active_version_in_same_process_after_rollback(tmp_path, monkeypatch):
    home, p, digest, sentinel = prepared(tmp_path)
    activate(home, digest)
    rollback(home)
    guard = p["opt"] / "versions/pilot-02/DLMS-Desktop/DLMS-Desktop"
    monkeypatch.setattr(sys, "_MEIPASS", "/tmp/dlms-pilot-unit-payload", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(guard))
    monkeypatch.setattr(sys, "argv", [str(guard), "--pilot-launch", "--profile", "pilot01",
                                  "--installed-pilot-root", str(p["data"])])
    chosen = []

    def capture_exec(path, args):
        chosen.append((path, args))
        raise RuntimeError("fixture captured same-process exec")

    monkeypatch.setattr(os, "execv", capture_exec)
    with pytest.raises(RuntimeError, match="fixture captured"):
        frozen_entry(instrumented=False)
    assert chosen == [(str(p["current"] / "DLMS-Desktop/DLMS-Desktop"),
                       [str(p["current"] / "DLMS-Desktop/DLMS-Desktop"),
                        "--profile", "pilot01", "--installed-pilot-root", str(p["data"])])]


@pytest.mark.parametrize("boundary", ("receipt", "updating", "pointer", "commit"))
def test_activation_interruption_and_separate_process_reconciliation(tmp_path, boundary):
    home, p, digest, sentinel = prepared(tmp_path)
    old_bytes = sentinel.read_bytes()
    with pytest.raises(RuntimeError, match="Synthetic interruption"):
        activate(home, digest, fail_at=boundary)
    root_check = _check_root_in_separate_process(p["data"])
    # The new code rejects the receipt at every boundary. The already installed
    # v1 executable does not read it and could still run before `updating`.
    assert root_check.returncode != 0
    command = [sys.executable, "-m", "package_fedora.replace_pilot", "reconcile", "--home", str(home)]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["outcome"] == ("committed" if boundary == "commit" else "rolled_back")
    assert _check_root_in_separate_process(p["data"]).returncode == 0
    assert sentinel.read_bytes() == old_bytes
    assert not (p["opt"] / "pilot-replacement.json").exists()
    assert len(list(p["opt"].glob("pilot-replacement-resolved-*.json"))) == 1


def test_pointer_manifest_tampering_and_unknown_recovery_refuse(tmp_path):
    home, p, digest, sentinel = prepared(tmp_path)
    activate(home, digest)
    p["current"].unlink()
    p["current"].symlink_to("versions/pilot-01")
    assert _check_root_in_separate_process(p["data"]).returncode != 0
    with pytest.raises(ValueError, match="pointer"):
        verify(home)
    p["current"].unlink()
    p["current"].symlink_to("versions/pilot-02")
    with pytest.raises(RuntimeError):
        rollback(home, fail_at="pointer")
    p["current"].unlink()
    p["current"].symlink_to("versions/unknown")
    with pytest.raises(ValueError, match="unknown"):
        reconcile(home)
    assert sentinel.is_file()


def test_malformed_receipt_refuses_before_pointer_or_manifest_mutation(tmp_path):
    home, p, digest, sentinel = prepared(tmp_path)
    with pytest.raises(RuntimeError):
        activate(home, digest, fail_at="pointer")
    before_manifest = p["manifest"].read_bytes()
    before_pointer = p["current"].readlink()
    receipt = p["opt"] / "pilot-replacement.json"
    record = json.loads(receipt.read_text())
    record["version_inventories"]["pilot-01"] = "0" * 64
    receipt.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="inventory lineage"):
        reconcile(home)
    assert p["manifest"].read_bytes() == before_manifest
    assert p["current"].readlink() == before_pointer
    assert sentinel.is_file()


def test_rollback_refuses_later_data_and_never_restores_snapshot(tmp_path):
    home, p, digest, sentinel = prepared(tmp_path)
    activate(home, digest)
    sentinel.write_text("new later Study result\n")
    with pytest.raises(ValueError, match="data changed"):
        rollback(home)
    assert verify(home)[0]["current_target"] == "versions/pilot-02"
    assert sentinel.read_text() == "new later Study result\n"


@pytest.mark.parametrize("boundary", ("receipt", "updating", "pointer", "commit"))
def test_rollback_interruption_keeps_both_versions_and_profile(tmp_path, boundary):
    home, p, digest, sentinel = prepared(tmp_path)
    activate(home, digest)
    before = sentinel.read_bytes()
    with pytest.raises(RuntimeError, match="Synthetic interruption"):
        rollback(home, fail_at=boundary)
    assert _check_root_in_separate_process(p["data"]).returncode != 0
    outcome = reconcile(home)
    assert outcome == ("committed" if boundary == "commit" else "rolled_back")
    assert verify(home)[0]["current_target"] == (
        "versions/pilot-01" if boundary == "commit" else "versions/pilot-02")
    assert sentinel.read_bytes() == before
    assert (p["opt"] / "versions/pilot-01/DLMS-Desktop").exists()
    assert (p["opt"] / "versions/pilot-02/DLMS-Desktop").exists()


def test_concurrent_launches_during_activation_and_live_lock_refusal(tmp_path):
    home, p, digest, sentinel = prepared(tmp_path)
    from PySide6.QtCore import QLockFile
    shell = p["data"] / "shell/pilot01/instance.lock"
    lock = QLockFile(str(shell))
    lock.setStaleLockTime(0)
    assert lock.tryLock(0)
    try:
        with pytest.raises(ValueError, match="lock evidence"):
            activate(home, digest)
    finally:
        lock.unlock()
    with pytest.raises(RuntimeError):
        activate(home, digest, fail_at="updating")
    attempts = [_check_root_in_separate_process(p["data"]) for _ in range(4)]
    assert all(attempt.returncode != 0 for attempt in attempts)
    assert all("identity" in attempt.stderr or "phase" in attempt.stderr for attempt in attempts)
    assert reconcile(home) == "rolled_back"
    assert sentinel.is_file()


def test_simultaneous_launch_attempts_while_replacer_holds_locks(tmp_path):
    home, p, digest, sentinel = prepared(tmp_path)
    entered, release = threading.Event(), threading.Event()
    result: list[object] = []

    def pause():
        entered.set()
        assert release.wait(10), "fixture barrier timed out"

    def worker():
        try:
            result.append(activate(home, digest, pause_at_updating=pause))
        except BaseException as exc:
            result.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    try:
        assert entered.wait(10)
        assert json.loads(p["manifest"].read_text())["phase"] == "updating"
        assert (p["data"] / "shell/pilot01/instance.lock").exists()
        assert (p["data"] / "profiles/pilot01/instance.lock").exists()
        attempts = [_check_root_in_separate_process(p["data"]) for _ in range(4)]
        assert all(attempt.returncode != 0 for attempt in attempts)
        assert sentinel.read_text() == "original synthetic quiz and Study history\n"
    finally:
        release.set()
        thread.join(timeout=10)
    assert not thread.is_alive()
    assert len(result) == 1 and isinstance(result[0], dict), result
    assert verify(home)[0]["current_target"] == "versions/pilot-02"


def test_changed_stage_and_pending_data_refuse_before_mutation(tmp_path):
    home, p, digest, sentinel = prepared(tmp_path)
    manifest = p["manifest"].read_bytes()
    old_target = p["current"].readlink()
    new_exe = p["opt"] / "versions/pilot-02/DLMS-Desktop/DLMS-Desktop"
    new_exe.write_text("#!/bin/sh\nexit 3\n")
    with pytest.raises(ValueError, match="Staged payload differs"):
        activate(home, digest)
    assert p["manifest"].read_bytes() == manifest
    assert p["current"].readlink() == old_target
    new_exe.write_text("#!/bin/sh\nexit 2\n")
    pending = p["data"] / "profiles/pilot01/durable-actions"
    pending.mkdir()
    (pending / "pending.json").write_text("{}")
    with pytest.raises(ValueError, match="needs reconciliation"):
        activate(home, digest)
    assert p["manifest"].read_bytes() == manifest
    assert sentinel.is_file()


def test_version_chain_symlink_and_held_writer_refuse(tmp_path):
    home, p, digest, sentinel = prepared(tmp_path)
    versions = p["opt"] / "versions"
    renamed = p["opt"] / "versions-retained"
    versions.rename(renamed)
    versions.symlink_to(renamed, target_is_directory=True)
    try:
        with pytest.raises(ValueError, match="version path"):
            activate(home, digest)
    finally:
        versions.unlink()
        renamed.rename(versions)
    writer = p["data"] / "profiles/pilot01/backend-writer.lock"
    script = ("import fcntl,os,sys; f=os.open(sys.argv[1],os.O_RDWR); "
              "fcntl.flock(f,fcntl.LOCK_EX); print('held',flush=True); sys.stdin.read(1)")
    holder = subprocess.Popen([sys.executable, "-c", script, str(writer)],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "held"
        with pytest.raises(ValueError, match="backend writer lock"):
            activate(home, digest)
        assert sentinel.is_file()
    finally:
        holder.stdin.write("x")
        holder.stdin.flush()
        assert holder.wait(timeout=5) == 0


def test_process_entering_before_blocking_phase_leaves_unresolved_evidence(tmp_path, monkeypatch):
    home, p, digest, sentinel = prepared(tmp_path)
    original_scan = replacement._exact_processes
    calls = iter(([], [123456]))
    monkeypatch.setattr(replacement, "_exact_processes", lambda _home: next(calls))
    with pytest.raises(ValueError, match="entered before replacement phase"):
        activate(home, digest)
    assert json.loads(p["manifest"].read_text())["phase"] == "updating"
    assert (p["opt"] / "pilot-replacement.json").is_file()
    monkeypatch.setattr(replacement, "_exact_processes", original_scan)
    assert reconcile(home) == "rolled_back"
    assert sentinel.is_file()


def test_stale_descriptors_retired_to_exact_private_evidence(tmp_path):
    home, p, digest, sentinel = prepared(tmp_path)
    owners = [p["data"] / "shell/pilot01/instance-owner.json",
              p["data"] / "profiles/pilot01/instance-owner.json"]
    original = json.dumps({"name": "pilot01", "pid": 99999999, "start_ticks": 11,
                           "secret": "a" * 64}).encode()
    for owner in owners:
        owner.write_bytes(original)
        owner.chmod(0o600)
    with pytest.raises(ValueError, match="descriptor"):
        activate(home, digest)
    evidence = home / "stale-owner-evidence"
    hashes = retire_stale_descriptors(home, evidence)
    assert hashes == {"shell": sha256(evidence / "shell.original.json"),
                      "profile": sha256(evidence / "profile.original.json")}
    assert all(not owner.exists() for owner in owners)
    assert all((evidence / f"{key}.original.json").read_bytes() == original
               for key in ("shell", "profile"))
    assert evidence.stat().st_mode & 0o077 == 0
    assert activate(home, digest)["phase"] == "complete"


def test_stale_owner_refuses_live_pid_and_lock_evidence(tmp_path):
    home, p, digest, sentinel = prepared(tmp_path)
    owner = p["data"] / "shell/pilot01/instance-owner.json"
    owner.write_text(json.dumps({"name": "pilot01", "pid": os.getpid(),
                                 "start_ticks": 1, "secret": "a" * 64}))
    owner.chmod(0o600)
    with pytest.raises(ValueError, match="PID exists"):
        retire_stale_descriptors(home, home / "evidence-live")
    assert owner.exists()
    owner.write_text(json.dumps({"name": "pilot01", "pid": 99999999,
                                 "start_ticks": 1, "secret": "a" * 64}))
    owner.chmod(0o600)
    lock = p["data"] / "shell/pilot01/instance.lock"
    lock.write_bytes(b"retained stale Qt lock evidence")
    with pytest.raises(ValueError, match="lock evidence"):
        retire_stale_descriptors(home, home / "evidence-locked")
    assert lock.read_bytes() == b"retained stale Qt lock evidence"
    assert owner.exists()


def test_stale_owner_requires_verified_installation_before_retirement(tmp_path):
    home, p, digest, sentinel = prepared(tmp_path)
    owner = p["data"] / "shell/pilot01/instance-owner.json"
    owner.write_text(json.dumps({"name": "pilot01", "pid": 99999999,
                                 "start_ticks": 1, "secret": "a" * 64}))
    owner.chmod(0o600)
    marker = p["marker"]
    original = marker.read_bytes()
    changed_marker = json.loads(original)
    changed_marker["install_id"] = "0" * 32
    marker.write_text(json.dumps(changed_marker))
    with pytest.raises(ValueError, match="changed"):
        retire_stale_descriptors(home, home / "untrusted-evidence")
    assert owner.exists() and not (home / "untrusted-evidence").exists()
    marker.write_bytes(original)
    manifest = p["manifest"]
    old = manifest.read_bytes()
    changed = json.loads(old)
    changed["current_target"] = "versions/pilot-02"
    manifest.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="pointer"):
        retire_stale_descriptors(home, home / "untrusted-evidence")
    assert owner.exists() and not (home / "untrusted-evidence").exists()

"""Native closed-root quarantine: opaque children, pinned identity, no replay."""
from copy import deepcopy
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

if os.name != "nt":
    pytest.skip("Native Windows directory-handle quarantine", allow_module_level=True)

from desktop import windows_browser_quarantine as q
from desktop.windows_files import owned


@pytest.fixture
def stores(tmp_path):
    web, recovery = tmp_path / "private web 日本語", tmp_path / "private recovery"
    web.mkdir(mode=0o700); recovery.mkdir(mode=0o700)
    paths = {"web_storage": web / "storage", "web_cache": web / "cache"}
    for value in paths.values():
        value.mkdir(mode=0o700)
        (value / "opaque.bin").write_bytes(b"old browser bytes")
    return paths, recovery


def result_ids(paths, recovery):
    return q.root_ids(paths), q.root_ids({key: recovery / key for key in q.KEYS})


def test_exact_opaque_rename_never_walks_old_descendants(stores, monkeypatch):
    paths, recovery = stores
    expected = q.root_ids(paths)
    rows = q.prepare(paths, recovery, expected)
    with monkeypatch.context() as patch:
        patch.setattr(Path, "iterdir", lambda *a, **k: pytest.fail("Only retained known-new handle may enumerate"))
        patch.setattr(Path, "rglob", lambda *a, **k: pytest.fail("No recursive browser inspection"))
        q.move(paths, recovery, rows)
    new, old = result_ids(paths, recovery)
    assert old == expected
    assert new == {key: row["new"] for key, row in rows.items()}
    assert all(not list(path.iterdir()) for path in paths.values())
    assert all((recovery / key / "opaque.bin").read_bytes() == b"old browser bytes" for key in q.KEYS)


@pytest.mark.parametrize("stage", ["web_cache:old-moved", "web_cache:new-moved", "web_storage:old-moved", "web_storage:new-moved"])
def test_crash_resume_only_expected_three_identity_positions(stores, stage):
    paths, recovery = stores
    expected = q.root_ids(paths)
    rows = q.prepare(paths, recovery, expected)
    class Crash(Exception): pass
    def checkpoint(observed):
        if observed == stage: raise Crash(stage)
    with pytest.raises(Crash, match=stage): q.move(paths, recovery, rows, checkpoint=checkpoint)
    q.move(paths, recovery, rows)
    new, old = result_ids(paths, recovery)
    assert old == expected and new == {key: row["new"] for key, row in rows.items()}
    q.move(paths, recovery, rows)  # Completed operation is idempotent only while fresh roots remain empty.
    (paths["web_storage"] / "new-work.bin").write_bytes(b"must preserve")
    with pytest.raises(ValueError, match="not empty"): q.move(paths, recovery, rows)
    assert (paths["web_storage"] / "new-work.bin").read_bytes() == b"must preserve"


@pytest.mark.parametrize("stage", ["web_cache:old-moved", "web_cache:new-moved"])
def test_owned_child_death_resumes_only_persisted_native_ids(stores, stage):
    import json
    import sys
    from desktop.profile_state import atomic_json
    paths, recovery = stores
    original = q.root_ids(paths)
    rows = q.prepare(paths, recovery, original)
    journal = recovery / "persisted-native-ids.json"
    atomic_json(journal, {"paths": {key: str(value) for key, value in paths.items()},
                          "recovery": str(recovery), "rows": rows})
    script = """
import json, os, sys
from pathlib import Path
from desktop.windows_browser_quarantine import move
value=json.loads(Path(sys.argv[1]).read_text())
def checkpoint(observed):
    if observed==sys.argv[2]: os._exit(79)
move({key:Path(path) for key,path in value['paths'].items()},
     Path(value['recovery']), value['rows'], checkpoint=checkpoint)
raise SystemExit('The requested crash boundary was not reached')
"""
    child = subprocess.run([sys.executable, "-X", "utf8", "-c", script, str(journal), stage],
        cwd=Path(__file__).resolve().parents[2], capture_output=True, timeout=20)
    assert child.returncode == 79, child.stderr.decode("utf-8", errors="replace")
    persisted = json.loads(journal.read_text())
    assert persisted["rows"] == rows
    with q.directory(recovery / "web_cache") as retained:
        assert list(q.file_identity(retained)) == rows["web_cache"]["old"]
    if stage.endswith("old-moved"):
        assert not paths["web_cache"].exists()
        with q.directory(recovery / ".new-web_cache") as replacement:
            assert list(q.file_identity(replacement)) == rows["web_cache"]["new"]
    else:
        assert not (recovery / ".new-web_cache").exists()
        with q.directory(paths["web_cache"]) as replacement:
            assert list(q.file_identity(replacement)) == rows["web_cache"]["new"]
    # The child died with exclusive metadata/DELETE handles held. Their kernel
    # lifetime ends with that exact process; the parent resumes from durable
    # IDs and never derives authority from or enumerates the opaque old tree.
    q.move(paths, recovery, persisted["rows"])
    new, old = result_ids(paths, recovery)
    assert old == original and new == {key: row["new"] for key, row in rows.items()}
    assert all((recovery / key / "opaque.bin").read_bytes() == b"old browser bytes" for key in q.KEYS)


@pytest.mark.parametrize("collision", ["web_cache", ".new-web_cache"])
def test_existing_destination_never_replaced(stores, collision):
    paths, recovery = stores
    target = recovery / collision
    target.mkdir(mode=0o700); (target / "keep.bin").write_bytes(b"untouched")
    with pytest.raises(ValueError, match="collision"): q.prepare(paths, recovery, q.root_ids(paths))
    assert (target / "keep.bin").read_bytes() == b"untouched"


@pytest.mark.parametrize("substitute", ["source", "target", "staging"])
def test_leaf_substitution_and_foreign_targets_fail_closed(stores, substitute):
    paths, recovery = stores
    rows = q.prepare(paths, recovery, q.root_ids(paths))
    path = {"source": paths["web_cache"], "target": recovery / "web_cache",
            "staging": recovery / ".new-web_cache"}[substitute]
    if path.exists(): path.rename(path.with_name(path.name + "-preserved"))
    path.mkdir(mode=0o700)
    with pytest.raises(ValueError, match="Ambiguous"): q.move(paths, recovery, rows)
    assert path.exists()


def test_parent_and_exact_root_handles_prevent_substitution(stores):
    paths, _ = stores
    source = paths["web_cache"]
    with q.pinned_parents(source), q.directory(source):
        with pytest.raises(PermissionError): source.rename(source.with_name("swapped"))
        with pytest.raises(PermissionError): source.parent.rename(source.parent.with_name("swapped-parent"))


def junction(link, target):
    result = subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
    assert result.returncode == 0, result.stderr


def test_reparse_root_rejected_and_opaque_child_link_preserved(stores, tmp_path):
    paths, recovery = stores
    outside = tmp_path / "outside"; outside.mkdir(mode=0o700)
    sentinel = outside / "never-read-or-deleted.bin"; sentinel.write_bytes(b"outside")
    child = paths["web_storage"] / "child-link"
    junction(child, outside)
    try:
        rows = q.prepare(paths, recovery, q.root_ids(paths))
        q.move(paths, recovery, rows)
        assert (recovery / "web_storage" / "child-link").lstat().st_file_attributes & 0x400
        assert sentinel.read_bytes() == b"outside"
    finally:
        (recovery / "web_storage" / "child-link").rmdir()
    root_link = paths["web_storage"] / "root-link"
    junction(root_link, outside)
    try:
        with pytest.raises(ValueError, match="reparse"): q.root_ids({**paths, "web_storage": root_link})
    finally: root_link.rmdir()


def test_child_capability_acl_is_preserved_without_becoming_root_authority(stores):
    paths, recovery = stores
    child = paths["web_storage"] / "capability-cache"
    child.mkdir(mode=0o700)
    capability = "S-1-15-3-1024-3239966617-1410756637-3494353204-65451782-2225605771-3526040376-1730753648-3419555762"
    def acl(path):
        import ctypes as c
        from ctypes import wintypes as w
        from desktop.windows_files import _open, get_security
        from desktop.windows_processes import a, api, checked, close, local_free
        descriptor, text = w.LPVOID(), w.LPWSTR()
        handle = _open(path, directory=True)
        convert = api(a, "ConvertSecurityDescriptorToStringSecurityDescriptorW", w.BOOL,
                      w.LPVOID, w.DWORD, w.DWORD, c.POINTER(w.LPWSTR), w.LPVOID)
        try:
            assert get_security(handle, 1, 1 | 4, None, None, None, None, c.byref(descriptor)) == 0
            checked(convert(descriptor, 1, 1 | 4, c.byref(text), None))
            return text.value
        finally:
            if text: local_free(text)
            if descriptor: local_free(descriptor)
            close(handle)
    subprocess.run(["icacls.exe", str(child), "/grant", "*" + capability + ":(OI)(CI)(M)"], check=True, capture_output=True)
    with pytest.raises(ValueError, match="another account"): owned(child, private=True)
    before = acl(child)
    rows = q.prepare(paths, recovery, q.root_ids(paths)); q.move(paths, recovery, rows)
    retained = recovery / "web_storage" / child.name
    assert acl(retained) == before
    with pytest.raises(ValueError, match="another account"): owned(retained, private=True)


@pytest.mark.parametrize("where", ["root", "parent"])
def test_untrusted_root_or_immediate_parent_acl_rejected(stores, where):
    paths, recovery = stores
    expected = q.root_ids(paths)
    path = paths["web_cache"] if where == "root" else recovery
    subprocess.run(["icacls.exe", str(path), "/grant", "*S-1-1-0:(M)"], check=True, capture_output=True)
    with pytest.raises(ValueError, match="another account"): q.prepare(paths, recovery, expected)
    assert (paths["web_cache"] / "opaque.bin").read_bytes() == b"old browser bytes"


def test_untrusted_owner_rejected_before_source_move(stores, monkeypatch):
    paths, recovery = stores
    expected = q.root_ids(paths)
    def foreign(*args, **kwargs): raise ValueError("Windows object is owned by another account")
    monkeypatch.setattr(q, "owned_handle", foreign)
    with pytest.raises(ValueError, match="owned by another"): q.prepare(paths, recovery, expected)
    assert not list(recovery.iterdir())


@pytest.mark.parametrize("mutation", ["extra", "missing", "identity", "same", "cross-volume"])
def test_malformed_or_mismatched_resume_records_rejected(stores, mutation):
    paths, recovery = stores
    rows = q.prepare(paths, recovery, q.root_ids(paths)); invalid = deepcopy(rows)
    if mutation == "extra": invalid["web_cache"]["arbitrary_path"] = "C:/Windows"
    elif mutation == "missing": del invalid["web_cache"]
    elif mutation == "identity": invalid["web_cache"]["old"][2] += 1
    elif mutation == "same": invalid["web_cache"]["new"] = invalid["web_cache"]["old"]
    else: invalid["web_cache"]["new"][0] += 1
    with pytest.raises(ValueError): q.move(paths, recovery, invalid)
    assert (paths["web_cache"] / "opaque.bin").exists()


def test_replacement_reopen_detects_leaf_substitution_before_enumeration(stores, monkeypatch):
    from contextlib import contextmanager
    paths, recovery = stores
    rows = q.prepare(paths, recovery, q.root_ids(paths))
    original = q.directory
    @contextmanager
    def changed(path, **kwargs):
        if kwargs.get("list_new"):
            path.rename(path.with_name(path.name + "-preserved"))
            path.mkdir(mode=0o700)
        with original(path, **kwargs) as handle: yield handle
    monkeypatch.setattr(q, "directory", changed)
    monkeypatch.setattr(q, "empty_new", lambda *a: pytest.fail("Changed new root must not enumerate"))
    with pytest.raises(ValueError, match="identity changed"): q.move(paths, recovery, rows)
    assert (paths["web_cache"] / "opaque.bin").read_bytes() == b"old browser bytes"


def process_records():
    sid = q.process_sid(q.current())
    return {"host": {"pid": 12341, "start": 5001, "image": "C:/owned/DLMS-WebView2-Host.exe", "sid": sid},
            "browser": {"pid": 12342, "start": 5002, "image": "C:/runtime/msedgewebview2.exe", "sid": sid}}


def test_retirement_requires_birth_bound_processes_gone(monkeypatch):
    records = process_records()
    monkeypatch.setattr(q, "process_retired", lambda pid, start: True); q.validate_processes(records)
    monkeypatch.setattr(q, "process_retired", lambda pid, start: False)
    with pytest.raises(ValueError, match="still alive"): q.validate_processes(records)
    def denied(pid, start): raise PermissionError("identity inaccessible")
    monkeypatch.setattr(q, "process_retired", denied)
    with pytest.raises(PermissionError): q.validate_processes(records)


@pytest.mark.parametrize("mutation", ["same-pid", "extra", "missing", "bad-sid", "relative", "wrong-image", "bool-pid"])
def test_unbound_or_ambiguous_process_records_rejected(monkeypatch, mutation):
    records = process_records()
    if mutation == "same-pid": records["browser"]["pid"] = records["host"]["pid"]
    elif mutation == "extra": records["host"]["closed"] = True
    elif mutation == "missing": del records["host"]
    elif mutation == "bad-sid": records["host"]["sid"] = "S-1-1-0"
    elif mutation == "relative": records["host"]["image"] = "DLMS-WebView2-Host.exe"
    elif mutation == "wrong-image": records["browser"]["image"] = "C:/owned/other.exe"
    else: records["host"]["pid"] = True
    monkeypatch.setattr(q, "process_retired", lambda *a: pytest.fail("Malformed proof must not query a supplied PID"))
    with pytest.raises(ValueError): q.validate_processes(records)


def test_actual_owned_process_termination_does_not_require_dead_image_query():
    import sys
    child = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(.6)"])
    try:
        captured = q.identity(child.pid)
        assert q.process_retired(child.pid, captured["start"]) is False
        assert q.process_retired(child.pid, captured["start"] - 1) is True  # Reused-PID birth comparison only.
        child.wait(timeout=5)
        assert q.process_retired(child.pid, captured["start"]) is True
    finally:
        if child.poll() is None: child.terminate(); child.wait(timeout=5)


@pytest.mark.parametrize("state", [0xffffffff, 128, 19])
def test_native_wait_failures_never_confirm_retirement(monkeypatch, state):
    closed = []
    monkeypatch.setattr(q, "open_process", lambda *a: 456)
    monkeypatch.setattr(q, "_wait_process", lambda *a: state)
    monkeypatch.setattr(q, "close", closed.append)
    monkeypatch.setattr(q.c, "get_last_error", lambda: 5)
    with pytest.raises(OSError): q.process_retired(12341, 5001)
    assert closed == [456]


@pytest.mark.parametrize("error,expected", [(87, True), (5, None), (31, None)])
def test_missing_process_is_distinct_from_access_or_query_failure(monkeypatch, error, expected):
    monkeypatch.setattr(q, "open_process", lambda *a: None)
    monkeypatch.setattr(q.c, "get_last_error", lambda: error)
    if expected: assert q.process_retired(12341, 5001) is True
    else:
        with pytest.raises(OSError): q.process_retired(12341, 5001)


@pytest.mark.parametrize("missing", ["host_finished", "native_retired", "storage_pins_released"])
def test_retirement_receipt_requires_every_positive_native_proof(stores, monkeypatch, missing):
    from desktop import maintenance as m
    paths, recovery = stores
    proof = {"processes": process_records(), "roots": q.root_ids(paths),
             "host_finished": True, "native_retired": True, "storage_pins_released": True}
    proof[missing] = False
    monkeypatch.setattr(m, "profile_paths", lambda *a, **k: paths)
    monkeypatch.setattr(m, "read_manifest", lambda *a: {"uuid": "synthetic", "epoch": "old", "port": 43171})
    monkeypatch.setattr(q, "validate_processes", lambda *a: pytest.fail("Incomplete retirement must not become a receipt"))
    with pytest.raises(m.MaintenanceUnresolved, match="not positively confirmed"):
        m.record_windows_browser_retirement("synthetic", "a" * 32, proof)
    assert not list(recovery.iterdir())


def owned_window(stores, tmp_path, monkeypatch):
    """A real held QLockFile/current instance record; no fake product lock."""
    import json
    from PySide6.QtCore import QLockFile
    from desktop import maintenance as m
    from desktop.ownership import process_start_ticks
    from desktop.profile_state import atomic_json
    paths, recovery = stores
    root = tmp_path / "owned-profile"; root.mkdir(mode=0o700)
    paths["root"] = root
    lock = QLockFile(str(root / "desktop.lock"))
    assert lock.tryLock(0)
    owner = SimpleNamespace(mode="local", profile_name="synthetic", paths=paths, local_lock=lock,
        backend=None, view=None, _retiring_browser=None, _browser_dialog_depth=0, _retirement_wait_active=False,
        instance_secret="s" * 64, manifest={"port": 43171})
    atomic_json(root / "instance-owner.json", {"pid": os.getpid(), "start_ticks": process_start_ticks(os.getpid()),
                                              "name": "synthetic", "secret": owner.instance_secret})
    proof_path = recovery / "retired.json"
    monkeypatch.setattr(m, "_windows_retirement_path", lambda *a: proof_path)
    marker = {"operation_id": "a" * 32, "profile_uuid": "synthetic-uuid", "epoch": "old-epoch"}
    return m, paths, recovery, owner, marker, proof_path


def test_old_journal_without_retirement_receipt_remains_blocked(stores, tmp_path, monkeypatch):
    m, paths, recovery, owner, marker, _ = owned_window(stores, tmp_path, monkeypatch)
    try:
        with pytest.raises(m.MaintenanceUnresolved, match="not recorded"):
            m._quarantine_windows_browser_roots("synthetic", paths, recovery, marker, owner)
        assert (paths["web_storage"] / "opaque.bin").read_bytes() == b"old browser bytes"
    finally: owner.local_lock.unlock()


@pytest.mark.parametrize("invalid", ["no-lock", "lock-not-held", "live-backend", "live-view", "wrong-profile", "dialog", "retiring", "wrong-instance"])
def test_quarantine_requires_current_window_lock_and_no_live_runtime(stores, tmp_path, monkeypatch, invalid):
    m, paths, recovery, owner, marker, _ = owned_window(stores, tmp_path, monkeypatch)
    held = owner.local_lock
    try:
        if invalid == "no-lock": owner.local_lock = True
        elif invalid == "lock-not-held": owner.local_lock.unlock()
        elif invalid == "live-backend": owner.backend = object()
        elif invalid == "live-view": owner.view = object()
        elif invalid == "wrong-profile": owner.profile_name = "other"
        elif invalid == "dialog": owner._browser_dialog_depth = 1
        elif invalid == "retiring": owner._retiring_browser = object()
        else: owner.instance_secret = "different"
        with pytest.raises(m.MaintenanceUnresolved):
            m._quarantine_windows_browser_roots("synthetic", paths, recovery, marker, owner)
        assert not (recovery / ".new-web_cache").exists()
    finally: held.unlock()


@pytest.mark.parametrize("invalid", ["wrong-epoch", "wrong-origin", "wrong-operation", "extra-root", "duplicate-field", "wrong-root-id"])
def test_quarantine_receipt_exact_context_and_roots_bound(stores, tmp_path, monkeypatch, invalid):
    import json
    from desktop.profile_state import atomic_json
    m, paths, recovery, owner, marker, proof_path = owned_window(stores, tmp_path, monkeypatch)
    proof = {"version": 1, "name": "synthetic", **marker, "origin": "http://127.0.0.1:43171",
             "processes": process_records(), "roots": q.root_ids(paths)}
    if invalid == "wrong-epoch": proof["epoch"] = "different"
    elif invalid == "wrong-origin": proof["origin"] = "http://127.0.0.1:43172"
    elif invalid == "wrong-operation": proof["operation_id"] = "b" * 32
    elif invalid == "extra-root": proof["roots"]["outside"] = [1, 2, 3]
    elif invalid == "wrong-root-id": proof["roots"]["web_cache"][2] += 1
    atomic_json(proof_path, proof)
    if invalid == "duplicate-field":
        proof_path.write_text(json.dumps(proof)[:-1] + ', "epoch": "old-epoch"}')
    monkeypatch.setattr(q, "validate_processes", lambda *a: None)  # Isolate context/root checks only.
    try:
        with pytest.raises((m.MaintenanceUnresolved, ValueError)):
            m._quarantine_windows_browser_roots("synthetic", paths, recovery, marker, owner)
        assert (paths["web_cache"] / "opaque.bin").read_bytes() == b"old browser bytes"
    finally: owner.local_lock.unlock()


def test_current_receipt_journals_old_and_new_ids_before_first_rename(stores, tmp_path, monkeypatch):
    import json
    from desktop import isolation
    from desktop.profile_state import atomic_json
    m, paths, recovery, owner, marker, proof_path = owned_window(stores, tmp_path, monkeypatch)
    # Scope the real Windows sibling writer-lock namespace to this disposable
    # test root; retain the production namespace check and actual native lock.
    monkeypatch.setattr(isolation, "PROFILES", paths["root"].parent)
    monkeypatch.setattr(isolation, "AREA", tmp_path)
    old = q.root_ids(paths)
    atomic_json(proof_path, {"version": 1, "name": "synthetic", **marker,
        "origin": "http://127.0.0.1:43171", "processes": process_records(), "roots": old})
    monkeypatch.setattr(q, "validate_processes", lambda *a: None)  # Process lifetime is tested separately above.
    journal = recovery / "active.json"
    monkeypatch.setattr(m, "_external", lambda *a: (journal, recovery / "lock"))
    original, moves = q.rename, []
    def check_journal(handle, target):
        persisted = json.loads(journal.read_text())["windows_opaque_quarantine"]
        assert set(persisted) == q.KEYS
        assert {key: row["old"] for key, row in persisted.items()} == old
        assert all(q.valid_id(row["new"]) for row in persisted.values())
        moves.append(str(target))
        original(handle, target)
    monkeypatch.setattr(q, "rename", check_journal)
    try:
        m._quarantine_windows_browser_roots("synthetic", paths, recovery, marker, owner)
        assert len(moves) == 4
        assert result_ids(paths, recovery)[1] == old
        # Separate resume entry validates the persisted IDs, never reconstructs
        # them from surviving path names or treats old descendants as authority.
        m._quarantine_windows_browser_roots("synthetic", paths, recovery, marker, owner)
        assert len(moves) == 4
    finally: owner.local_lock.unlock()

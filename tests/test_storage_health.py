"""Storage visibility and preflight must preserve data and recovery semantics."""
import inspect
from unittest.mock import Mock

import pytest

from dlms.services import storage_health as storage, backups, restore


def test_report_sizes_missing_directories_and_no_mutation(tmp_path):
    files = {"results.db": b"db", "results.db-wal": b"wal", "backups/one.zip": b"archive",
             "content_packs/demo/image.png": b"image", "quizzes/one.html": b"quiz"}
    for name, value in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
    report = storage.storage_snapshot(tmp_path)
    assert report["bytes"] == sum(map(len, files.values()))
    groups = {g["label"]: g["bytes"] for g in report["groups"]}
    assert groups["Database size"] == 2
    assert groups["Database journals"] == 3
    assert groups["Backups"] == 7
    assert groups["Content / Study Packs"] == 5
    assert not report["partial"]
    assert {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == files
    assert storage.storage_snapshot(tmp_path / "missing")["bytes"] == 0
    assert not (tmp_path / "missing").exists()


def test_scan_bounded_and_does_not_follow_symlinks(tmp_path):
    (tmp_path / "file").write_bytes(b"abc")
    (tmp_path / "loop").symlink_to(tmp_path, target_is_directory=True)
    report = storage.storage_snapshot(tmp_path)
    assert report["bytes"] == 3 and report["partial"]
    assert storage.storage_snapshot(tmp_path, max_entries=0)["partial"]
    assert storage.storage_snapshot(tmp_path, max_seconds=0)["partial"]


@pytest.mark.parametrize("total,free,status", [
    (100 * storage.GIB, 511 * storage.MIB, "critical"),
    (100 * storage.GIB, 512 * storage.MIB, "low"),
    (100 * storage.GIB, 4 * storage.GIB, "low"),
    (100 * storage.GIB, 5 * storage.GIB, "healthy"),
    (1000 * storage.GIB, 10 * storage.GIB, "healthy"),
    (None, None, "unknown"),
])
def test_warning_thresholds(total, free, status):
    assert storage.space_status(total, free) == status


def test_unreadable_filesystem_is_safe_and_partial(tmp_path, monkeypatch):
    monkeypatch.setattr(storage.shutil, "disk_usage", Mock(side_effect=PermissionError("private path")))
    monkeypatch.setattr(storage.os, "scandir", Mock(side_effect=PermissionError("private path")))
    report = storage.storage_snapshot(tmp_path)
    assert report["status"] == "unknown" and report["partial"]
    assert "private path" not in str(report)
    storage.require_capacity(tmp_path, 100)  # unknown is not a quota


def test_preflight_estimate_plus_reserve(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "available_space", lambda _: (10**12, storage.RESERVE_BYTES + 100))
    storage.require_capacity(tmp_path, 100)
    with pytest.raises(storage.InsufficientStorageError):
        storage.require_capacity(tmp_path, 101)


def test_missing_destination_checks_existing_parent(tmp_path, monkeypatch):
    usage = Mock(return_value=type("Usage", (), {"total": 1000, "free": 500})())
    monkeypatch.setattr(storage.shutil, "disk_usage", usage)
    assert storage.available_space(tmp_path / "new" / "destination") == (1000, 500)
    usage.assert_called_once_with(tmp_path)
    assert not (tmp_path / "new").exists()


@pytest.mark.parametrize("free_values", [(0,), (10**12, 0)])
def test_backup_refused_before_snapshot_or_archive(tmp_path, monkeypatch, free_values):
    db = tmp_path / "results.db"
    db.write_bytes(b"untouched")
    monkeypatch.setattr(storage, "available_space", Mock(side_effect=[(10**12, n) for n in free_values]))
    sqlite = Mock()
    with pytest.raises(storage.InsufficientStorageError):
        backups.create_dlms_backup(
            ensure_runtime_data_dirs=lambda: None, backup_folder=str(tmp_path),
            app_data_dir=str(tmp_path), db_path=str(db), app_version="test",
            backup_schema_version=1, backup_manifest="manifest", backup_data_prefix="data/",
            file_inventory=lambda: [], summary=lambda: {}, sqlite_module=sqlite,
        )
    sqlite.connect.assert_not_called()
    assert list(tmp_path.iterdir()) == [db]
    assert db.read_bytes() == b"untouched"


def test_restore_staging_preflight_precedes_extraction(tmp_path, monkeypatch):
    stage = tmp_path / "stage"
    stage.mkdir()
    monkeypatch.setattr(storage, "available_space", lambda _: (10**12, 0))
    extract = Mock()
    with pytest.raises(storage.InsufficientStorageError):
        backups.stage_backup_restore(
            None, "token", stage_dir=str(stage), upload_max_bytes=100,
            bounded_save_upload=Mock(), validate_backup=lambda _: {"uncompressed_bytes": 500},
            extract_backup=extract, validate_semantics=Mock(), atomic_write_json=Mock(),
            staging_state_filename="state.json", staging_marker="test", staging_version=1,
        )
    extract.assert_not_called()
    assert not stage.exists()  # existing request-owned staging cleanup


@pytest.mark.parametrize("free_values", [(0,), (10**12, 0)])
def test_restore_preflight_failure_never_mutates_live_data(tmp_path, monkeypatch, free_values):
    stage = tmp_path / "stage"
    stage.mkdir()
    (stage / "restore.zip").write_bytes(b"fixture")
    callbacks = {name: Mock() for name, p in inspect.signature(restore.complete_staged_restore).parameters.items()
                 if p.kind == p.KEYWORD_ONLY}
    callbacks.update(restore_staging_dir=lambda _: str(stage),
                     validate_backup=lambda _: {"uncompressed_bytes": 100, "manifest": {}},
                     db_path=str(tmp_path / "results.db"),
                     create_backup=Mock(return_value=("safety.zip", {"total_uncompressed_bytes": 200})))
    monkeypatch.setattr(storage, "available_space", Mock(side_effect=[(10**12, n) for n in free_values]))
    with pytest.raises(restore.RestoreFailure) as error:
        restore.complete_staged_restore("token", **callbacks)
    assert error.value.outcome == "not_modified"
    callbacks["apply_data"].assert_not_called()
    callbacks["new_operation"].assert_not_called()


def test_backup_page_explicit_check_only_and_escaping(tmp_path, monkeypatch):
    from tests._isolation import ensure_test_data_isolation
    ensure_test_data_isolation()
    import app
    from dlms.routes import maintenance
    scan = Mock(return_value=storage.storage_snapshot(tmp_path))
    monkeypatch.setattr(maintenance, "storage_snapshot", scan)
    client = app.app.test_client()
    assert client.get("/settings/backup").status_code == 200
    scan.assert_not_called()
    scan.return_value["free"] = '<script>alert("bad")</script>'
    response = client.get("/settings/backup?storage=1")
    assert scan.call_count == 1
    assert b"Database size" in response.data
    assert b"&lt;script&gt;" in response.data and b'<script>alert("bad")' not in response.data


@pytest.mark.parametrize("status,expected", [
    ("low", b"Available disk space is low."),
    ("critical", b"Very little disk space remains."),
    ("unknown", b"Available disk space could not be checked."),
])
def test_storage_page_warning_states(tmp_path, monkeypatch, status, expected):
    from tests._isolation import ensure_test_data_isolation
    ensure_test_data_isolation()
    import app
    from dlms.routes import maintenance
    report = storage.storage_snapshot(tmp_path)
    report.update(status=status, partial=True)
    monkeypatch.setattr(maintenance, "storage_snapshot", lambda _: report)
    response = app.app.test_client().get("/settings/backup?storage=1")
    assert response.status_code == 200 and expected in response.data
    assert b"lower bounds" in response.data
    assert b"Available disk space is healthy" not in response.data

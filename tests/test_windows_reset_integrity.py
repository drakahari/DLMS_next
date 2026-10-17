"""Reset recovery and owned SQLite lifetimes; synthetic data, no UI or GC."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from types import SimpleNamespace
import uuid
import zipfile

import pytest

from dlms.services import restore

# Match application-suite collection isolation. The explicit subprocess worker
# must instead import app only after selecting its own disposable Desktop root.
if __name__ != "__main__":
    from tests._isolation import ensure_test_data_isolation
    ensure_test_data_isolation()
    import app as _collection_app

ROOT = Path(__file__).resolve().parents[1]
RESET_PATHS = {
    "UPLOAD_FOLDER": "uploads", "DATA_FOLDER": "data", "QUIZ_FOLDER": "quizzes", "CONFIG_FOLDER": "config",
    "LAW_FOLDER": "law", "LAW_CASES_FOLDER": "law/cases", "LAW_IMPORTS_FOLDER": "law/imports",
    "LAW_EXPORTS_FOLDER": "law/exports", "LAW_REGISTRY": "config/law.json",
    "LOGO_FOLDER": "static/logos", "LOGO_TEMP_FOLDER": "static/logos/_temp", "BACKGROUND_FOLDER": "static/bg",
    "CONTENT_PACK_FOLDER": "content_packs", "QUIZ_ASSET_FOLDER": "quiz_assets",
    "IMAGE_BUILDER_DRAFT_FOLDER": "image_builder_drafts", "EXTERNAL_AI_DRAFT_FOLDER": "external_ai_drafts",
    "PDF_IMPORT_DRAFT_FOLDER": "pdf_import_drafts", "OCR_IMPORT_STAGING_FOLDER": "uploads/ocr_screenshots",
    "PDF_OCR_STAGING_FOLDER": "uploads/ocr_pdfs", "PORTABLE_QUIZ_BUNDLE_STAGING_FOLDER": "uploads/quiz_bundles",
    "PDF_QUESTION_BANK_FOLDER": "pdf_question_banks", "PDF_TERMINOLOGY_BANK_FOLDER": "pdf_terminology_banks",
    "CONTENT_PACK_STAGING_FOLDER": "content_pack_staging", "BACKUP_FOLDER": "backups",
    "BACKUP_RESTORE_STAGING_FOLDER": "backups/restore_staging", "PORTAL_CONFIG": "config/portal.json",
    "QUIZ_REGISTRY": "config/quizzes.json", "DB_PATH": "results.db",
}


class TrackedConnection(sqlite3.Connection):
    closed_explicitly = False
    def close(self):
        self.closed_explicitly = True
        return super().close()


@pytest.mark.parametrize("reader", ["_tables", "_columns"])
def test_maintenance_readers_close_owned_database_handles_without_gc(tmp_path, monkeypatch, reader):
    from desktop import maintenance
    database = tmp_path / "Database space #50% 日本語.db"
    with closing(sqlite3.connect(database)) as conn, conn:
        conn.execute("CREATE TABLE retained (id INTEGER)")
        conn.execute("INSERT INTO retained VALUES (7)")
    connections, real = [], sqlite3.connect
    def connect(*args, **kwargs):
        value = real(*args, **kwargs, factory=TrackedConnection)
        connections.append(value)  # Deliberately retain references; no GC claim.
        return value
    monkeypatch.setattr(maintenance.sqlite3, "connect", connect)
    result = getattr(maintenance, reader)(database)
    assert result["retained"] == ([(7,)] if reader == "_tables" else ["id"])
    assert connections and all(conn.closed_explicitly for conn in connections)
    renamed = database.with_suffix(".renamed")
    database.rename(renamed); renamed.rename(database)


def test_quiz_reset_closes_own_connection_on_failure(tmp_path, monkeypatch):
    database = tmp_path / "results.db"
    with closing(sqlite3.connect(database)) as conn:
        conn.executescript((ROOT / "init.sql").read_text(encoding="utf-8"))
    held, real = [], sqlite3.connect
    def connect(*args):
        value = real(*args, factory=TrackedConnection); held.append(value); return value
    monkeypatch.setattr(restore, "invalidate_queues", lambda conn: (_ for _ in ()).throw(OSError("injected reset failure")))
    with pytest.raises(OSError, match="injected reset failure"):
        restore.reset_quiz_library_core(db_path=database, save_registry=lambda value: None, folders=[],
            clear_directory=lambda path: None, ensure_runtime_dirs=lambda: None,
            sqlite_module=SimpleNamespace(connect=connect))
    assert held and all(conn.closed_explicitly for conn in held)


def _bind_reset_app(root, monkeypatch):
    import app
    root.mkdir(mode=0o700)
    # Aggregate tests can leave mutually inconsistent prior globals. Bind each
    # runtime location from its application contract, never from those values.
    for key, relative in RESET_PATHS.items():
        monkeypatch.setattr(app, key, str(root / relative))
    monkeypatch.setattr(app, "APP_DATA_DIR", str(root))
    monkeypatch.setenv("QUIZAPP_DATA_DIR", str(root))
    monkeypatch.setenv("DLMS_TEST_DATA_ROOT", str(root))
    assert app._initialize_data_root_ownership(str(root))
    app._ensure_runtime_data_dirs(); app.ensure_db_initialized(); app.save_registry([]); app.load_portal_config()
    return app, root


@pytest.fixture
def reset_app(tmp_path, monkeypatch):
    return _bind_reset_app(tmp_path / "owned application", monkeypatch)


def _assert_web_partial_failure(app, root, monkeypatch):
    from tests.csrf_test_utils import csrf_headers
    source = Path(app.DATA_FOLDER) / "retained-source.txt"
    source.write_text("synthetic source before reset", encoding="utf-8")
    def partial_reset():
        source.unlink()
        raise OSError("Private diagnostic path " + str(root))
    monkeypatch.setattr(app, "_full_data_reset_core", partial_reset)
    client = app.app.test_client()
    response = client.post("/api/reset_all_data", headers=csrf_headers(client))
    assert response.status_code == 500 and response.json["status"] == "error"
    message = response.json["error"]
    assert "some data may already have changed" in message and "No automatic rollback is confirmed" in message
    assert str(root) not in message and "Private diagnostic" not in message
    backups = list(Path(app.BACKUP_FOLDER).glob("*.zip"))
    assert len(backups) == 1 and backups[0].name in message
    assert not source.exists(), "The failure must not be mislabeled as no mutation"
    with zipfile.ZipFile(backups[0]) as archive:
        name = next(name for name in archive.namelist() if name.endswith("/data/retained-source.txt"))
        assert archive.read(name) == b"synthetic source before reset"


def test_web_reset_partial_failure_reports_retained_backup_without_claiming_rollback(reset_app, monkeypatch):
    _assert_web_partial_failure(*reset_app, monkeypatch)


def test_reset_fixture_rebinds_inconsistent_prior_paths_and_environment(tmp_path, monkeypatch):
    import app
    foreign = tmp_path / "earlier synthetic backup folder"
    foreign.mkdir(mode=0o700)
    for index in range(7): (foreign / f"prior-{index}.zip").write_bytes(b"earlier synthetic evidence")
    monkeypatch.setattr(app, "APP_DATA_DIR", str(tmp_path / "different prior root"))
    for key in RESET_PATHS: monkeypatch.setattr(app, key, str(foreign / ("inconsistent-" + key)))
    monkeypatch.setattr(app, "BACKUP_FOLDER", str(foreign))
    monkeypatch.setenv("QUIZAPP_DATA_DIR", str(foreign))
    monkeypatch.setenv("DLMS_TEST_DATA_ROOT", str(foreign))
    app, root = _bind_reset_app(tmp_path / "fresh bound application", monkeypatch)
    assert app.APP_DATA_DIR == str(root)
    assert all(Path(getattr(app, key)) == root / relative for key, relative in RESET_PATHS.items())
    assert os.environ["QUIZAPP_DATA_DIR"] == os.environ["DLMS_TEST_DATA_ROOT"] == str(root)
    _assert_web_partial_failure(app, root, monkeypatch)  # Retains the exact one-backup and honest-error assertions.
    assert sorted(path.name for path in foreign.iterdir()) == [f"prior-{index}.zip" for index in range(7)]
    assert all(path.read_bytes() == b"earlier synthetic evidence" for path in foreign.iterdir())


def test_reset_failure_annotation_preserves_original_exception_and_unsafe_names_are_not_exposed():
    original = OSError("synthetic mutation failure")
    def fail(): raise original
    with pytest.raises(OSError) as caught:
        restore.run_reset_with_backup("test", fail, require_owned_root=lambda _: None,
                                     create_backup=lambda _: ("/private/pre-reset-safe.zip", {}))
    assert caught.value is original and original.dlms_reset_safety_backup == "pre-reset-safe.zip"
    assert original.dlms_reset_outcome == "possibly_modified"
    other = OSError("same original type")
    def invalid(): raise other
    with pytest.raises(OSError) as caught:
        restore.run_reset_with_backup("test", invalid, require_owned_root=lambda _: None,
                                     create_backup=lambda _: ("/private/unsafe\nname.zip", {}))
    assert caught.value is other and not hasattr(other, "dlms_reset_safety_backup")


@pytest.mark.skipif(os.name != "nt", reason="Windows native inventory spellings")
def test_windows_file_policy_normalizes_only_comparison_not_existing_journal(tmp_path):
    from desktop import maintenance
    before = {".dlms-data-root": "owner", ".secret_key": "old", "results.db": "old-db",
              "config\\portal.json": "old-portal", "backups\\prior.zip": "prior"}
    after = {**before, ".secret_key": "new", "results.db": "new-db", "config\\portal.json": "new-portal"}
    original_before, original_after = dict(before), dict(after)
    digest = maintenance._digest(before)
    maintenance._validate_files("fresh", before, after, tmp_path)
    assert before == original_before and after == original_after and maintenance._digest(before) == digest
    with pytest.raises(maintenance.MaintenanceUnresolved, match="retained file"):
        maintenance._validate_files("fresh", before, {**after, "backups\\prior.zip": "changed"}, tmp_path)
    with pytest.raises(maintenance.MaintenanceUnresolved, match="unexpected active"):
        maintenance._validate_files("fresh", before, {**after, "data\\unremoved.txt": "unsafe"}, tmp_path)
    with pytest.raises(maintenance.MaintenanceUnresolved, match="collide"):
        maintenance._validate_files("fresh", before, {**after, "config/portal.json": "collision"}, tmp_path)


@pytest.mark.skipif(os.name != "nt", reason="Windows SQLite deletion sharing and maintenance restart")
@pytest.mark.parametrize("case", ["locked", "partial-crash"])
def test_desktop_failed_reset_journal_reconciles_exact_preimage_in_new_process(case):
    from desktop.isolation import AREA
    name = "wvreset" + uuid.uuid4().hex[:12]
    output = ROOT / ".gate1/windows-native" / (name + "-evidence")
    output.mkdir(mode=0o700)
    command = [sys.executable, "-X", "utf8", "-m", "tests.test_windows_reset_integrity", "--worker", case, name, str(output)]
    with (output / "mutation.log").open("w", encoding="utf-8") as log:
        mutation = subprocess.run(command + ["mutate"], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=90)
    assert mutation.returncode == (79 if case == "partial-crash" else 2)
    marker_path = AREA / "maintenance" / name / "active.json"
    marker = json.loads(marker_path.read_text())
    assert marker["phase"] == "mutation_started" and marker["retained_safety_sha256"]
    from desktop.maintenance import _digest, _file_inventory
    live = AREA / "profiles" / name / "backend"
    baseline = json.loads((output / "baseline.json").read_text())
    # Failure is explicit; no successful commit/reopen is reported for partial data.
    assert _digest(_file_inventory(live)) != baseline["files_sha256"]
    with (output / "reconcile.log").open("w", encoding="utf-8") as log:
        recovery = subprocess.run(command + ["reconcile"], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=90)
    assert recovery.returncode == 0
    result = json.loads((output / "reconcile.json").read_text())
    assert result["phase"] == "rolled_back" and result["exact_preimage"] and result["directories_match"]
    assert result["safety_backup_retained"] and result["sqlite_integrity"] == "ok"


@pytest.mark.skipif(os.name != "nt", reason="Native Windows fresh reset closes owned inspection handles")
def test_desktop_fresh_reset_commits_without_held_inspection_handles():
    name = "wvreset" + uuid.uuid4().hex[:12]
    output = ROOT / ".gate1/windows-native" / (name + "-evidence")
    output.mkdir(mode=0o700)
    command = [sys.executable, "-X", "utf8", "-m", "tests.test_windows_reset_integrity", "--worker", "success", name, str(output), "mutate"]
    with (output / "mutation.log").open("w", encoding="utf-8") as log:
        result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=90)
    assert result.returncode == 0, (output / "mutation.log").read_text()
    report = json.loads((output / "success.json").read_text())
    assert report["phase"] == "committed" and report["empty_quizzes"]
    assert report["safety_backup_retained"] and report["sqlite_integrity"] == "ok"


def _worker(case, name, output, phase):
    """Only this helper's fresh project-local synthetic profile, never UI input."""
    if not name.startswith("wvreset") or len(name) != 19 or case not in {"locked", "partial-crash", "success"}:
        raise ValueError("Synthetic reset worker identity required")
    output = Path(output).absolute()
    if output.parent != ROOT / ".gate1/windows-native" or output.name != name + "-evidence":
        raise ValueError("Project-local reset evidence required")
    from desktop import maintenance
    from desktop.isolation import profile_paths, isolated_environment
    from desktop.profile_state import new_manifest, publish_manifest
    paths = profile_paths(name, create=False)
    if phase == "reconcile":
        result = maintenance.reconcile(name)
        baseline = json.loads((output / "baseline.json").read_text())
        retained = maintenance._recovery_dir(name, result["operation_id"])
        with closing(sqlite3.connect(paths["backend"] / "results.db")) as conn:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        report = {"phase": result["phase"], "exact_preimage": maintenance._digest(maintenance._file_inventory(paths["backend"])) == baseline["files_sha256"],
                  "directories_match": maintenance._digest(maintenance._directory_inventory(paths["backend"])) == baseline["directories_sha256"],
                  "safety_backup_retained": (retained / result["safety_backup"]).is_file(), "sqlite_integrity": integrity}
        (output / "reconcile.json").write_text(json.dumps(report, indent=2) + "\n")
        return 0
    if paths["root"].exists(): raise ValueError("Fresh synthetic profile required")
    paths = profile_paths(name)
    manifest = new_manifest(name, 43171); publish_manifest(paths, manifest)
    env = isolated_environment(paths)
    env.update(DLMS_DESKTOP_PROFILE_NAME=name, DLMS_DESKTOP_PORT="43171", DLMS_DESKTOP_NONCE="a" * 64,
               PYTHONNOUSERSITE="1")
    os.environ.clear(); os.environ.update(env)
    import app
    sentinel = Path(app.DATA_FOLDER) / "reset-integrity-sentinel.txt"
    sentinel.write_text("synthetic preimage", encoding="utf-8")
    operation = uuid.uuid4().hex
    maintenance.browser_preflight(name, operation, {"local": {}, "session": {}})
    (output / "baseline.json").write_text(json.dumps({
        "files_sha256": maintenance._digest(maintenance._file_inventory(paths["backend"])),
        "directories_sha256": maintenance._digest(maintenance._directory_inventory(paths["backend"]))}, indent=2) + "\n")
    held = None
    if case == "locked":
        held = sqlite3.connect(app.DB_PATH)
        held.execute("SELECT count(*) FROM quizzes").fetchone()
    elif case == "partial-crash":
        def crash_after_mutation():
            sentinel.unlink()
            os._exit(79)  # Only this synthetic worker; journal/preimage already durable.
        app._full_data_reset_core = crash_after_mutation
    try:
        result = maintenance.run(name, "fresh", operation)
        if case == "success":
            with closing(sqlite3.connect(app.DB_PATH)) as conn:
                integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
                quizzes = conn.execute("SELECT count(*) FROM quizzes").fetchone()[0]
            retained = maintenance._recovery_dir(name, operation)
            (output / "success.json").write_text(json.dumps({"phase": result["phase"], "empty_quizzes": quizzes == 0,
                "sqlite_integrity": integrity, "safety_backup_retained": (retained / result["safety_backup"]).is_file()}, indent=2) + "\n")
            return 0
    except Exception as exc:
        (output / "mutation-error.json").write_text(json.dumps({"type": type(exc).__name__, "winerror": getattr(exc, "winerror", None),
            "journal_phase": maintenance.read_marker(name)["phase"], "source_instrumented": True}, indent=2) + "\n")
        return 2
    finally:
        if held is not None: held.close()
    raise AssertionError("Expected the injected failure, never a successful reset")


if __name__ == "__main__":
    if len(sys.argv) != 6 or sys.argv[1] != "--worker": raise SystemExit("Synthetic worker arguments required")
    raise SystemExit(_worker(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]))

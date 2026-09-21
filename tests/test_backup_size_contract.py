"""A published backup must meet the very same bounds as restore."""
import io
import json
import zipfile
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

import pytest

from tests._isolation import ensure_test_data_isolation
ensure_test_data_isolation()
import app as dlms
from dlms.services import backups
from tests.csrf_test_utils import csrf_headers


@pytest.fixture
def creator(tmp_path):
    output = tmp_path / "backups"
    output.mkdir()
    source = tmp_path / "portal.json"
    source.write_text(json.dumps({"title": "A" * 5000}))
    database = tmp_path / "results.db"
    dlms.bootstrap_database(str(database), require_owned_root=False)
    def create(upload_limit=None, validator=None):
        return backups.create_dlms_backup(
            ensure_runtime_data_dirs=lambda: None, backup_folder=str(output),
            app_data_dir=str(tmp_path), db_path=str(database),
            app_version=dlms.APP_VERSION, backup_schema_version=dlms.DLMS_BACKUP_SCHEMA_VERSION,
            backup_manifest=dlms.DLMS_BACKUP_MANIFEST, backup_data_prefix=dlms.DLMS_BACKUP_DATA_PREFIX,
            file_inventory=lambda: [(str(source), "config/portal.json")], summary=lambda: {},
            restore_upload_max_bytes=dlms.BACKUP_UPLOAD_MAX_BYTES if upload_limit is None else upload_limit,
            validate_restore_archive=validator or dlms._validate_dlms_backup,
            now=lambda: datetime(2026, 9, 21),
        )
    return create, output


def test_small_backup_passes_restore_upload_and_validation(creator):
    create, _ = creator
    path, manifest = create()
    assert dlms._validate_dlms_backup(path)["manifest"] == manifest
    client = dlms.app.test_client()
    response = client.post("/settings/backup/restore/stage",
                           data={"backup_file": (io.BytesIO(Path(path).read_bytes()), "backup.zip")},
                           headers=csrf_headers(client))
    assert response.status_code == 200
    assert b"Confirm Restore" in response.data


@pytest.mark.parametrize("bound", ["upload", "expanded", "compressed", "single", "members"])
def test_exact_boundary_accepted_one_byte_or_member_over_rejected(creator, monkeypatch, bound):
    create, output = creator
    path, _ = create()
    original = Path(path).read_bytes()
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        limits = {
            "expanded": ("DLMS_BACKUP_MAX_UNCOMPRESSED", sum(i.file_size for i in infos)),
            "compressed": ("DLMS_BACKUP_MAX_COMPRESSED", sum(i.compress_size for i in infos)),
            "single": ("DLMS_BACKUP_MAX_SINGLE_FILE", max(i.file_size for i in infos)),
            "members": ("DLMS_BACKUP_MAX_FILES", len(infos)),
        }
    if bound == "upload":
        create(upload_limit=len(original))
        with pytest.raises(backups.BackupRestoreLimitError):
            create(upload_limit=len(original) - 1)
    else:
        key, value = limits[bound]
        monkeypatch.setattr(dlms, key, value)
        create()
        monkeypatch.setattr(dlms, key, value - 1)
        with pytest.raises(backups.BackupRestoreLimitError):
            create()
    assert Path(path).read_bytes() == original  # prior backup is never replaced by failure
    assert list(output.iterdir()) == [Path(path)]  # no failed temp ZIP


def test_compressible_data_cannot_bypass_expansion_or_ratio_safety(creator, monkeypatch):
    create, output = creator
    monkeypatch.setattr(dlms, "DLMS_BACKUP_RATIO_MIN_UNCOMPRESSED", 100)
    monkeypatch.setattr(dlms, "DLMS_BACKUP_MAX_COMPRESSION_RATIO", 2)
    with pytest.raises(backups.BackupRestoreLimitError, match="ratio"):
        create()
    assert not list(output.iterdir())


def test_upload_limit_checked_before_validator_and_failure_not_published(creator):
    create, output = creator
    validator = Mock()
    with pytest.raises(backups.BackupRestoreLimitError):
        create(upload_limit=1, validator=validator)
    validator.assert_not_called()
    assert not list(output.iterdir())


def test_production_creator_uses_authoritative_restore_contract(monkeypatch):
    call = Mock(return_value=("backup.zip", {}))
    monkeypatch.setattr(backups, "create_dlms_backup", call)
    monkeypatch.setattr(dlms, "BACKUP_UPLOAD_MAX_BYTES", 12345)
    dlms._create_dlms_backup()
    assert call.call_args.kwargs["restore_upload_max_bytes"] == 12345
    assert call.call_args.kwargs["validate_restore_archive"] is dlms._validate_dlms_backup


def test_limit_error_is_actionable_and_never_discloses_internal_path(monkeypatch):
    monkeypatch.setattr(dlms, "_create_dlms_backup", Mock(side_effect=
        backups.BackupRestoreLimitError('<script>secret/path</script>')))
    client = dlms.app.test_client()
    response = client.post("/settings/backup/create", headers=csrf_headers(client))
    assert response.status_code == 500
    assert b"exceed the supported restore size" in response.data
    assert b"Older backup ZIPs are excluded" in response.data
    assert b"secret/path" not in response.data
    assert "Content-Disposition" not in response.headers

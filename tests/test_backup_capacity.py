"""Restore HTTP capacity is bounded independently of unrelated workflows."""
import io
from unittest.mock import Mock

import pytest
from flask import request

from tests._isolation import ensure_test_data_isolation
ensure_test_data_isolation()
import app as dlms
from tests.csrf_test_utils import csrf_headers


ROUTES = ("/settings/backup/restore/stage", "/settings/data/restore/stage")


def test_fixed_archive_safety_limits_remain_independent():
    assert dlms.BACKUP_UPLOAD_MAX_BYTES == 1024**3
    assert dlms.DLMS_BACKUP_MAX_UNCOMPRESSED == 2 * 1024**3
    assert dlms.DLMS_BACKUP_MAX_COMPRESSED == 2 * 1024**3
    assert dlms.DLMS_BACKUP_MAX_SINGLE_FILE == 768 * 1024**2
    assert dlms.DLMS_BACKUP_MAX_FILES == 20000
    assert dlms.DLMS_BACKUP_MAX_COMPRESSION_RATIO == 1000
    assert dlms.DLMS_BACKUP_RATIO_MIN_UNCOMPRESSED == 16 * 1024**2
    assert dlms.app.config["MAX_CONTENT_LENGTH"] == 300 * 1024**2


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("delta", [-1, 0, 1])
def test_declared_restore_request_boundary(route, delta):
    limit = dlms.BACKUP_UPLOAD_MAX_BYTES + dlms.UPLOAD_MULTIPART_OVERHEAD_BYTES
    with dlms.app.test_request_context(route, method="POST", environ_overrides={"CONTENT_LENGTH": str(limit + delta)}):
        response = dlms.reject_declared_oversized_workflow_upload()
        assert request.max_content_length == limit
        if delta > 0:
            assert response[1] == 413
        else:
            assert response is None


@pytest.mark.parametrize("route", ROUTES)
def test_multipart_restore_exceeds_general_cap_but_reaches_stage(route, monkeypatch, tmp_path):
    monkeypatch.setitem(dlms.app.config, "MAX_CONTENT_LENGTH", 64)
    monkeypatch.setattr(dlms, "BACKUP_UPLOAD_MAX_BYTES", 2048)
    monkeypatch.setattr(dlms, "_restore_staging_dir", lambda _: str(tmp_path / "stage"))
    stage = Mock(side_effect=ValueError("synthetic archive rejected after upload"))
    monkeypatch.setattr(dlms, "_stage_dlms_backup", stage)
    client = dlms.app.test_client()
    response = client.post(route, data={"backup_file": (io.BytesIO(b"x" * 1024), "test.zip")}, headers=csrf_headers(client))
    assert response.status_code == 400
    stage.assert_called_once()
    assert dlms.app.config["MAX_CONTENT_LENGTH"] == 64
    with dlms.app.test_request_context("/unrelated", method="POST"):
        dlms.reject_declared_oversized_workflow_upload()
        assert request.max_content_length == 64


@pytest.mark.parametrize("route", ROUTES)
def test_unknown_length_restore_stream_still_has_request_ceiling(route, monkeypatch):
    monkeypatch.setattr(dlms, "BACKUP_UPLOAD_MAX_BYTES", 1024)
    monkeypatch.setattr(dlms, "UPLOAD_MULTIPART_OVERHEAD_BYTES", 1024)
    stage = Mock()
    monkeypatch.setattr(dlms, "_stage_dlms_backup", stage)
    client = dlms.app.test_client()
    response = client.post(route, data={"backup_file": (io.BytesIO(b"x" * 4096), "test.zip")},
                           headers=csrf_headers(client),
                           environ_overrides={"CONTENT_LENGTH": "", "wsgi.input_terminated": True})
    assert response.status_code == 413
    stage.assert_not_called()

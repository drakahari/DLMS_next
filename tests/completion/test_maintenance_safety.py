"""Focused project-boundary checks for external maintenance paths."""
from __future__ import annotations

import pytest

from desktop.isolation import AREA
import desktop.maintenance as maintenance
from desktop.maintenance import _external, _recovery_dir, _file_inventory


@pytest.mark.parametrize("name", ["../escape", "../../escape", "valid/../escape", "Uppercase", "a" * 33])
def test_external_maintenance_path_rejects_bad_name_without_writing(name):
    marker = AREA / "maintenance" / name / "active.json"
    before = marker.exists()
    with pytest.raises(ValueError, match="Invalid disposable profile name"):
        _external(name)
    assert marker.exists() == before


def test_recovery_path_rejects_bad_name_and_operation_identity():
    with pytest.raises(ValueError, match="Invalid maintenance recovery identity"):
        _recovery_dir("../escape", "a" * 32)
    with pytest.raises(ValueError, match="Invalid maintenance recovery identity"):
        _recovery_dir("valid", "../escape")


def test_recovery_inventory_rejects_links_before_copy(tmp_path):
    root = tmp_path / "profile"
    root.mkdir(mode=0o700)
    outside = tmp_path / "outside"
    outside.write_text("unrelated")
    (root / "escape").symlink_to(outside)
    with pytest.raises(Exception, match="Unsafe ownership or permissions|Link or special file"):
        _file_inventory(root)
    assert outside.read_text() == "unrelated"


def test_completed_receipt_refuses_stale_epoch_or_scope(monkeypatch, tmp_path):
    operation_id = "a" * 32
    receipt = {"scope": "study", "profile_uuid": "fixture-uuid", "epoch": "old-epoch",
               "new_epoch": None, "operation_id": operation_id, "phase": "committed"}
    monkeypatch.setattr(maintenance, "profile_paths", lambda name, create=False: {"root": tmp_path})
    monkeypatch.setattr(maintenance, "read_manifest", lambda paths, name: {"uuid": "fixture-uuid", "epoch": "old-epoch"})
    monkeypatch.setattr(maintenance, "_completed_receipt", lambda name, identity: receipt)
    assert maintenance.run("fixture", "study", operation_id) is receipt
    with pytest.raises(maintenance.MaintenanceUnresolved, match="stale or belongs"):
        maintenance.run("fixture", "quiz", operation_id)
    monkeypatch.setattr(maintenance, "read_manifest", lambda paths, name: {"uuid": "fixture-uuid", "epoch": "other-epoch"})
    with pytest.raises(maintenance.MaintenanceUnresolved, match="stale or belongs"):
        maintenance.run("fixture", "study", operation_id)

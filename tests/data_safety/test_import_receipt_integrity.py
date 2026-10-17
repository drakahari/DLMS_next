"""Focused checks for the private Desktop item receipt's asset boundary."""
from pathlib import Path
import hashlib

import pytest

from desktop.import_operations import ImportUnresolved, _remove_stage, _semantic, _verify_tree, unresolved_count
from desktop.pack_operations import _owned_destination


def test_exact_owned_asset_tree(tmp_path):
    base = tmp_path / "quiz_assets"
    bucket = base / "portable_quiz_item"
    (bucket / "images").mkdir(parents=True)
    payload = b"synthetic image bytes"
    (bucket / "images" / "figure.png").write_bytes(payload)
    expected = {"images/figure.png": hashlib.sha256(payload).hexdigest()}
    _verify_tree(bucket, expected, "published", base=base)

    (bucket / "images" / "figure.png").write_bytes(b"changed")
    with pytest.raises(ImportUnresolved, match="changed or unexpected"):
        _verify_tree(bucket, expected, "published", base=base)
    (bucket / "images" / "figure.png").write_bytes(payload)

    (bucket / "unrelated").mkdir()
    with pytest.raises(ImportUnresolved, match="unexpected directory"):
        _verify_tree(bucket, expected, "published", base=base)
    (bucket / "unrelated").rmdir()

    bucket.rename(base / "real_bucket")
    bucket.symlink_to(base / "real_bucket", target_is_directory=True)
    with pytest.raises(ImportUnresolved):
        _verify_tree(bucket, expected, "published", base=base)


def test_empty_asset_bucket_and_concept_projection(tmp_path):
    base = tmp_path / "quiz_assets"
    base.mkdir()
    _verify_tree(base / "missing", {}, "published", base=base, allow_missing_empty=True)
    assert _semantic([{"question": "Synthetic", "concepts": ["retained"]}]) == [
        {"question": "Synthetic", "concepts": ["retained"]}
    ]


def test_stage_cleanup_refuses_extra_evidence(tmp_path):
    stage = tmp_path / "operation-stage"
    stage.mkdir()
    (stage / "bundle.zip").write_bytes(b"synthetic archive")
    (stage / "stage.json").write_text("{}")
    (stage / "unknown").mkdir()
    with pytest.raises(ImportUnresolved, match="unexpected entries"):
        _remove_stage(stage)
    assert stage.exists()
    (stage / "unknown").rmdir()
    _remove_stage(stage)
    assert not stage.exists()


def test_pack_destination_rejects_symlinked_base(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    app = type("SyntheticApp", (), {"CONTENT_PACK_FOLDER": str(linked)})()
    with pytest.raises(ImportUnresolved, match="owned directory"):
        _owned_destination(app, linked / "DLMS_Study_synthetic")


def test_started_stage_cannot_cross_epoch_or_lose_record(tmp_path):
    import json
    import uuid

    profile = tmp_path / "synthetic-profile"
    token = "a" * 32
    old_epoch, new_epoch = str(uuid.uuid4()), str(uuid.uuid4())
    stage = profile / "backend/uploads/quiz_bundles" / token
    stage.mkdir(parents=True)
    (stage / "stage.json").write_text(json.dumps({"desktop_import": {
        "version": 1, "profile_uuid": str(uuid.uuid4()),
        "epoch": old_epoch, "started": True,
    }}))
    with pytest.raises(ImportUnresolved, match="no matching current operation"):
        unresolved_count(profile, old_epoch)
    with pytest.raises(ImportUnresolved, match="no matching current operation"):
        unresolved_count(profile, new_epoch)

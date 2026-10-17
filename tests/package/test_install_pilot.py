"""Only project-local fixture homes; never exercise the real per-user target."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys

import pytest

from desktop.package_entry import _root
from package_fedora.install_pilot import (APP_ID, SIZES, install, inventory, paths,
                                          removal_plan, remove, repair_icon_entry, sha256)

PROJECT = Path(__file__).resolve().parents[2]


def fixture_inputs(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    payload = tmp_path / "source-payload"
    payload.mkdir()
    executable = payload / "DLMS-Desktop"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    assets = payload / "_internal/desktop_assets"
    assets.mkdir(parents=True)
    shutil.copy2(PROJECT / "desktop_assets/dlms_omarchy.png", assets / "dlms_omarchy.png")
    for size in SIZES:
        target = assets / f"icons/hicolor/{size}x{size}/apps/{APP_ID}.png"
        target.parent.mkdir(parents=True)
        shutil.copy2(PROJECT / f"desktop_assets/icons/hicolor/{size}x{size}/apps/{APP_ID}.png", target)
    archive = tmp_path / "reviewed-archive.tar.zst"
    archive.write_bytes(b"bounded fixture archive\n")
    return home, payload, archive, sha256(archive), inventory(payload)


def test_install_identity_and_data_preserving_remove(tmp_path, monkeypatch):
    home, payload, archive, archive_sha, payload_sha = fixture_inputs(tmp_path)
    result = install(home, payload, archive, archive_sha, payload_sha)
    p = paths(home)
    assert result["phase"] == "complete"
    assert p["entry"].read_text().count(f"Icon={p['icon_64']}") == 1
    assert p["current"].readlink() == Path("versions/pilot-01")
    assert inventory(p["version"] / "DLMS-Desktop") == payload_sha
    monkeypatch.setattr(sys, "_MEIPASS", str(payload), raising=False)
    assert _root(str(p["data"]), kind="installed-pilot", profile="pilot01") == p["data"]
    with pytest.raises(ValueError):
        _root(str(p["data"]), kind="disposable")
    with pytest.raises(ValueError):
        _root(str(p["data"]), kind="installed-pilot", profile="other")
    sentinel = p["data"] / "profiles/pilot01/backend/sentinel.txt"
    sentinel.parent.mkdir(parents=True)
    sentinel.write_text("synthetic study evidence")
    assert removal_plan(home)["install_id"] == result["install_id"]
    remove(home)
    assert sentinel.read_text() == "synthetic study evidence"
    assert not p["entry"].exists() and not p["launcher"].exists()
    assert not p["opt"].exists()


@pytest.mark.parametrize("boundary", ("payload", "resources", "activation"))
def test_interrupted_install_fails_closed(tmp_path, monkeypatch, boundary):
    home, payload, archive, archive_sha, payload_sha = fixture_inputs(tmp_path)
    p = paths(home)
    with pytest.raises(RuntimeError, match="Synthetic failure"):
        install(home, payload, archive, archive_sha, payload_sha, fail_at=boundary)
    assert p["manifest"].is_file()
    assert json.loads(p["manifest"].read_text())["phase"] != "complete"
    assert not p["entry"].exists()
    with pytest.raises(FileExistsError):
        install(home, payload, archive, archive_sha, payload_sha)
    if p["data"].exists():
        monkeypatch.setattr(sys, "_MEIPASS", str(payload), raising=False)
        with pytest.raises(ValueError, match="Installed pilot identity"):
            _root(str(p["data"]), kind="installed-pilot", profile="pilot01")


def test_collision_and_changed_artifact_refuse_without_data_loss(tmp_path):
    home, payload, archive, archive_sha, payload_sha = fixture_inputs(tmp_path)
    p = paths(home)
    p["entry"].parent.mkdir(parents=True)
    p["entry"].write_text("preexisting owner entry")
    with pytest.raises(FileExistsError):
        install(home, payload, archive, archive_sha, payload_sha)
    assert p["entry"].read_text() == "preexisting owner entry"
    assert not p["opt"].exists() and not p["data"].exists()
    p["entry"].unlink()
    result = install(home, payload, archive, archive_sha, payload_sha)
    icon = p["icon_64"]
    original = icon.read_bytes()
    icon.write_bytes(b"unexpected replacement")
    with pytest.raises(ValueError, match="changed"):
        remove(home)
    assert p["entry"].exists() and p["data"].exists()
    icon.write_bytes(original)
    assert removal_plan(home)["install_id"] == result["install_id"]


def test_symlink_and_input_drift_rejected_before_install(tmp_path):
    home, payload, archive, archive_sha, payload_sha = fixture_inputs(tmp_path)
    p = paths(home)
    p["data"].parent.mkdir(parents=True)
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    p["data"].symlink_to(unrelated, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        install(home, payload, archive, archive_sha, payload_sha)
    assert not p["opt"].exists()
    p["data"].unlink()
    archive.write_bytes(b"same-size fixture mutation!")
    with pytest.raises(ValueError, match="archive SHA-256"):
        install(home, payload, archive, archive_sha, payload_sha)
    assert not p["opt"].exists()


def test_reviewed_old_entry_repair_preserves_payload_and_rollback(tmp_path):
    home, payload, archive, archive_sha, payload_sha = fixture_inputs(tmp_path)
    install(home, payload, archive, archive_sha, payload_sha)
    p = paths(home)
    old_entry = p["entry"].read_bytes().replace(
        f"Icon={p['icon_64']}".encode(), f"Icon={APP_ID}".encode())
    p["entry"].write_bytes(old_entry)
    manifest = json.loads(p["manifest"].read_text())
    manifest["file_sha256"]["entry"] = sha256(p["entry"])
    p["manifest"].write_text(json.dumps(manifest))
    before_manifest = p["manifest"].read_bytes()
    before_payload = inventory(p["version"] / "DLMS-Desktop")
    backup = tmp_path / "rollback"
    backup.mkdir()
    updated = repair_icon_entry(home, backup)
    assert updated["file_sha256"]["entry"] == sha256(p["entry"])
    assert p["entry"].read_text().count(f"Icon={p['icon_64']}") == 1
    assert (backup / "entry.before.desktop").read_bytes() == old_entry
    assert (backup / "manifest.before.json").read_bytes() == before_manifest
    assert inventory(p["version"] / "DLMS-Desktop") == before_payload
    assert removal_plan(home)["install_id"] == updated["install_id"]
    with pytest.raises((FileExistsError, ValueError)):
        repair_icon_entry(home, backup)
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="backup directory"):
        repair_icon_entry(home, linked_parent / "rollback")

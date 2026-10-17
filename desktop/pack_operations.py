"""Desktop-only exact Study Pack move intent and restart reconciliation."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil

from .import_operations import ImportUnresolved, _profile
from .isolation import assert_safe_leaf
from .profile_state import atomic_json

TOKEN = re.compile(r"[0-9a-f]{32}\Z")


def _receipt_path(profile, epoch, token):
    if not TOKEN.fullmatch(token):
        raise ImportUnresolved("Study Pack operation token is invalid")
    root = profile / "pack-install-receipts"
    folder = root / epoch
    for path in (root, folder):
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise ImportUnresolved("Study Pack receipt storage is unsafe")
    return folder / (token + ".json")


def _stage(app, token):
    path = Path(app._content_pack_stage_path(token))
    if path.is_symlink() or path.parent.is_symlink():
        raise ImportUnresolved("Study Pack stage is unsafe")
    return path


def _metadata(stage):
    path = stage / "stage.json"
    assert_safe_leaf(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ImportUnresolved("Study Pack stage metadata is malformed")
    return value


def _tree(app, path):
    if path.is_symlink() or not path.is_dir():
        raise ImportUnresolved("Study Pack tree is missing or unsafe")
    return app._content_pack_mutation_service._staged_pack_tree_sha256(str(path))


def _owned_destination(app, destination):
    base = Path(app.CONTENT_PACK_FOLDER)
    target = Path(destination)
    if (base.is_symlink() or not base.is_dir() or target.parent != base
            or target.is_symlink() or target.name in {"", ".", ".."}):
        raise ImportUnresolved("Study Pack destination is outside its owned directory")
    return target


def _intent(app, token, pack_root, destination, metadata, report):
    profile, identity = _profile()
    folder = Path(destination).name
    manifest = report.get("manifest") or {}
    intent = {"version": 1, "token": token, "profile_uuid": identity["uuid"],
              "epoch": identity["epoch"], "pack_id": str(manifest.get("id") or "").lower(),
              "folder": folder, "tree_sha256": metadata.get("tree_sha256")}
    if (not intent["pack_id"] or not isinstance(intent["tree_sha256"], str)
            or len(intent["tree_sha256"]) != 64
            or _tree(app, Path(pack_root)) != intent["tree_sha256"]):
        raise ImportUnresolved("Study Pack intent differs from the reviewed stage")
    _owned_destination(app, destination)
    stage = _stage(app, token)
    saved = _metadata(stage)
    prior = saved.get("desktop_install_intent")
    if prior is not None and prior != intent:
        raise ImportUnresolved("Study Pack operation identity conflicts with accepted input")
    saved["desktop_install_intent"] = intent
    atomic_json(stage / "stage.json", saved)  # Durable before the first move.
    return intent


def prepare(app, token, pack_root, destination, metadata, report):
    _intent(app, token, pack_root, destination, metadata, report)


def _write_receipt(app, profile, identity, intent, destination, installed):
    destination = _owned_destination(app, destination)
    if _tree(app, destination) != intent["tree_sha256"]:
        raise ImportUnresolved("Installed Study Pack differs from its reviewed staged tree")
    existing = app.discover_content_packs().get(intent["pack_id"])
    if not existing or Path(existing.get("root", destination)).name != intent["folder"]:
        raise ImportUnresolved("Installed Study Pack identity is not discoverable")
    receipt = {**intent, "state": "installed", "name": installed.get("name") or intent["pack_id"]}
    path = _receipt_path(profile, identity["epoch"], intent["token"])
    if path.exists():
        assert_safe_leaf(path)
        if json.loads(path.read_text(encoding="utf-8")) != receipt:
            raise ImportUnresolved("Study Pack installed receipt conflicts with the destination")
    else:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        atomic_json(path, receipt)
    return receipt


def installed(app, token, pack_root, destination, metadata, report, installed_pack):
    profile, identity = _profile()
    intent = _metadata(_stage(app, token)).get("desktop_install_intent")
    if not intent or intent["profile_uuid"] != identity["uuid"] or intent["epoch"] != identity["epoch"]:
        raise ImportUnresolved("Study Pack move has no matching Desktop intent")
    _write_receipt(app, profile, identity, intent, destination, installed_pack)


def receipt(app, token):
    profile, identity = _profile()
    path = _receipt_path(profile, identity["epoch"], token)
    if not path.exists():
        return None
    assert_safe_leaf(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(value, dict) or value.get("token") != token
            or value.get("profile_uuid") != identity["uuid"]
            or value.get("epoch") != identity["epoch"] or value.get("state") != "installed"):
        raise ImportUnresolved("Study Pack receipt belongs to another dataset or is malformed")
    return value


def replay(app, token):
    value = receipt(app, token)
    if value is None:
        return None
    # A completed token is never a request to recreate a later-deleted pack.
    return {"status": "installed", "replayed": True, "metadata": {},
            "pack_id": value["pack_id"], "installed": {"name": value["name"]}}


def cancel(app, token):
    stage = _stage(app, token)
    if stage.exists() and _metadata(stage).get("desktop_install_intent"):
        raise ImportUnresolved("This Study Pack move has accepted work; reopen to reconcile it before cancellation")
    return app._content_pack_mutation_service.cancel_staged_content_pack(
        token, load_staged_content_pack=app._load_staged_content_pack,
        remove_content_pack_stage=app._remove_content_pack_stage)


def _reconcile_one(app, stage, intent, profile, identity):
    if (not isinstance(intent, dict) or intent.get("version") != 1
            or intent.get("token") != stage.name
            or intent.get("profile_uuid") != identity["uuid"]
            or intent.get("epoch") != identity["epoch"]
            or not isinstance(intent.get("folder"), str)
            or Path(intent["folder"]).name != intent["folder"]):
        raise ImportUnresolved("Study Pack move intent is stale or malformed")
    metadata = _metadata(stage)
    root_name = metadata.get("root_name")
    if (not isinstance(root_name, str) or "\\" in root_name
            or len(Path(root_name).parts) != 2
            or Path(root_name).parts[0] != "extracted"
            or Path(root_name).parts[1] in {"", ".", ".."}
            or Path(root_name).parts[1] != intent["folder"]
            or (stage / "extracted").is_symlink()):
        raise ImportUnresolved("Study Pack staged root name is unsafe")
    source = stage / root_name
    destination = _owned_destination(app, Path(app.CONTENT_PACK_FOLDER) / intent["folder"])
    source_exists = source.exists()
    destination_exists = destination.exists()
    if source_exists and not destination_exists:
        if _tree(app, source) != intent["tree_sha256"]:
            raise ImportUnresolved("Unmoved Study Pack staging tree changed")
        return "not_moved"
    if not source_exists and destination_exists:
        if _tree(app, destination) != intent["tree_sha256"]:
            raise ImportUnresolved("Moved Study Pack differs from reviewed input")
        discovered = app.discover_content_packs().get(intent["pack_id"])
        if not discovered:
            raise ImportUnresolved("Moved Study Pack is not discoverable")
        _write_receipt(app, profile, identity, intent, destination, discovered)
        if stage.is_symlink():
            raise ImportUnresolved("Study Pack stage changed before cleanup")
        shutil.rmtree(stage)
        return "installed"
    raise ImportUnresolved("Study Pack move has ambiguous staged/destination trees; evidence retained")


def reconcile(app):
    profile, identity = _profile()
    root = Path(app.CONTENT_PACK_STAGING_FOLDER)
    if root.is_symlink() or (root.exists() and not root.is_dir()):
        raise ImportUnresolved("Study Pack staging root is unsafe")
    result = {"not_moved": 0, "installed": 0}
    if root.exists():
        for stage in sorted(root.iterdir()):
            if stage.is_symlink() or not stage.is_dir():
                raise ImportUnresolved("Study Pack staging contains an unsafe entry")
            metadata = stage / "stage.json"
            if not metadata.exists():
                continue
            intent = _metadata(stage).get("desktop_install_intent")
            if intent:
                result[_reconcile_one(app, stage, intent, profile, identity)] += 1
    return result


def unresolved_count(profile, epoch):
    root = profile / "backend" / "content_pack_staging"
    if root.is_symlink() or (root.exists() and not root.is_dir()):
        raise ImportUnresolved("Study Pack staging root is unsafe")
    count = 0
    if root.exists():
        for stage in root.iterdir():
            if stage.is_symlink() or not stage.is_dir():
                raise ImportUnresolved("Study Pack staging contains an unsafe entry")
            metadata = stage / "stage.json"
            if metadata.exists():
                intent = _metadata(stage).get("desktop_install_intent")
                if intent:
                    if intent.get("epoch") != epoch:
                        raise ImportUnresolved("Study Pack operation belongs to a different dataset")
                    count += 1
    return count

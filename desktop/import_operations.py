"""Desktop-only durable identities for resumable portable quiz bundle imports.

The source publication journal remains the authority until a matching item
receipt has been fsynced. This store is local to one Desktop UUID/epoch and is
intentionally excluded from portable backups.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import threading
import uuid
import zipfile

from .isolation import AREA, assert_safe_leaf
from .profile_state import atomic_json

_MUTEX = threading.RLock()
_TOKEN = re.compile(r"[0-9a-f]{32}\Z")


class ImportUnresolved(RuntimeError):
    """No new quiz may be published until the exact outcome is established."""


def checkpoint(stage, journal=None):
    """Exact-process crash hook limited to a disposable automated profile."""
    if (os.environ.get("DLMS_DESKTOP_AUTOMATED") != "1"
            or os.environ.get("DLMS_DESKTOP_TEST_ABORT_IMPORT_AT") != stage):
        return
    profile, _ = _profile()
    atomic_json(profile / "gate-a-checkpoint.json", {
        "stage": stage, "pid": os.getpid(),
        "item": (journal or {}).get("desktop_import", {}).get("item"),
        "quiz_id": (journal or {}).get("quiz", {}).get("id"),
    })
    os._exit(77)


def _profile():
    root = Path(os.environ["DLMS_DESKTOP_PROFILE"])
    if root.is_symlink() or not root.resolve().is_relative_to((AREA / "profiles").resolve()):
        raise ImportUnresolved("Desktop import profile is outside disposable ownership")
    marker = root / "desktop-profile.json"
    assert_safe_leaf(marker)
    value = json.loads(marker.read_text(encoding="utf-8"))
    if set(value) != {"version", "name", "uuid", "epoch", "port"}:
        raise ImportUnresolved("Desktop import profile identity is invalid")
    if value["name"] != root.name:
        raise ImportUnresolved("Desktop import profile name does not match its owned root")
    return root, value


def _root(profile, epoch):
    root = profile / "portable-import-operations"
    part = root / epoch
    for directory in (root, part):
        if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
            raise ImportUnresolved("Portable-import operation storage is unsafe")
    return part


def _file(profile, epoch, token):
    if not _TOKEN.fullmatch(token):
        raise ImportUnresolved("Portable-import operation token is invalid")
    return _root(profile, epoch) / (token + ".json")


def _sha(path):
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _read(path):
    assert_safe_leaf(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("version") != 1:
        raise ImportUnresolved("Portable-import operation record is invalid")
    if not _TOKEN.fullmatch(str(value.get("token", ""))) or path.name != value["token"] + ".json":
        raise ImportUnresolved("Portable-import operation token is inconsistent")
    try:
        uuid.UUID(value["profile_uuid"])
        uuid.UUID(value["epoch"])
        if path.parent.name != value["epoch"]:
            raise ValueError("epoch directory mismatch")
    except (KeyError, TypeError, ValueError) as exc:
        raise ImportUnresolved("Portable-import operation dataset identity is invalid") from exc
    if (not isinstance(value.get("archive_sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", value["archive_sha256"])
            or value.get("state") not in {"prepared", "running", "cleanup_pending", "complete", "uncertain"}):
        raise ImportUnresolved("Portable-import operation digest or state is invalid")
    items = value.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= 1000:
        raise ImportUnresolved("Portable-import item inventory is invalid")
    for index, item in enumerate(items):
        if (not isinstance(item, dict) or item.get("index") != index
                or item.get("identity") != _identity(value, value["token"], value["archive_sha256"], index)
                or not isinstance(item.get("bundle_id"), str) or not item["bundle_id"]
                or item.get("state") not in {"planned", "publishing", "committed", "rolled_back"}
                or (item["state"] == "committed") != isinstance(item.get("receipt"), dict)):
            raise ImportUnresolved("Portable-import item identity or receipt is inconsistent")
    if value["state"] in {"complete", "cleanup_pending"} and any(item["state"] != "committed" for item in items):
        raise ImportUnresolved("Portable-import completion state conflicts with item receipts")
    return value


def _write(path, value):
    parent = path.parent
    if parent.is_symlink():
        raise ImportUnresolved("Portable-import operation storage is unsafe")
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    atomic_json(path, value)


def _stage(app, token):
    stage = Path(app._portable_quiz_bundle_service.portable_quiz_bundle_stage_path(
        token, staging_folder=app.PORTABLE_QUIZ_BUNDLE_STAGING_FOLDER))
    if stage.is_symlink() or stage.parent.is_symlink():
        raise ImportUnresolved("Portable-import stage path is unsafe")
    return stage


def stamp_stage(app, token):
    profile, identity = _profile()
    stage = _stage(app, token)
    metadata = _read_stage(stage)
    metadata["desktop_import"] = {"version": 1, "profile_uuid": identity["uuid"],
                                  "epoch": identity["epoch"], "started": False}
    atomic_json(stage / "stage.json", metadata)


def _read_stage(stage):
    assert_safe_leaf(stage / "stage.json")
    data = json.loads((stage / "stage.json").read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ImportUnresolved("Portable-import stage metadata is invalid")
    return data


def _bound_stage(app, token, identity):
    stage = _stage(app, token)
    metadata = _read_stage(stage)
    stamp = metadata.get("desktop_import")
    if (not isinstance(stamp, dict) or stamp.get("version") != 1
            or stamp.get("profile_uuid") != identity["uuid"] or stamp.get("epoch") != identity["epoch"]):
        raise ImportUnresolved("This older or different-dataset import has no trustworthy item identity; evidence is retained")
    _, archive, verified, report = app._load_staged_portable_quiz_bundle(token)
    if metadata != verified:
        raise ImportUnresolved("Portable-import stage identity changed after review")
    return stage, Path(archive), metadata, report


def _identity(profile_identity, token, archive_sha, index):
    profile_uuid = profile_identity.get("uuid", profile_identity.get("profile_uuid"))
    digest = hashlib.sha256(f'{profile_uuid}:{profile_identity["epoch"]}:{token}:{archive_sha}:{index}'.encode()).hexdigest()
    return f"{int(digest[:18], 16)}_{digest[18:26]}"


def _prepared(app, token, profile, identity, stage, metadata, report):
    path = _file(profile, identity["epoch"], token)
    if path.exists():
        op = _read(path)
        if (op.get("token") != token or op.get("profile_uuid") != identity["uuid"]
                or op.get("epoch") != identity["epoch"]
                or op.get("archive_sha256") != metadata["archive_sha256"]
                or len(op.get("items", [])) != report["quiz_count"]):
            raise ImportUnresolved("Portable-import identity conflicts with reviewed input")
    else:
        if metadata["desktop_import"]["started"]:
            raise ImportUnresolved("Started import has no durable operation record; evidence is retained")
        plans = app._portable_quiz_bundle_service.plan_portable_quiz_bundle_import(
            report["manifest"], app._portable_quiz_existing_titles())
        items = []
        for index, plan in enumerate(plans):
            items.append({"index": index, "bundle_id": plan["bundle_id"],
                          "source_title": plan["source_title"],
                          "title": plan["import_title"], "folder": plan["folder"],
                          "exam_minutes": plan["exam_minutes"], "renamed": plan["renamed"],
                          "identity": _identity(identity, token, metadata["archive_sha256"], index),
                          "state": "planned", "receipt": None})
        op = {"version": 1, "token": token, "profile_uuid": identity["uuid"],
              "epoch": identity["epoch"], "archive_sha256": metadata["archive_sha256"],
              "state": "prepared", "items": items}
        _write(path, op)  # First durable acceptance, before any item mutation.
    if not metadata["desktop_import"]["started"]:
        metadata["desktop_import"]["started"] = True
        atomic_json(stage / "stage.json", metadata)
    return path, op


def _managed(item, op):
    return {"token": op["token"], "item": item["index"], "identity": item["identity"],
            "archive_sha256": op["archive_sha256"], "profile_uuid": op["profile_uuid"],
            "epoch": op["epoch"]}


def _exact_item(op, managed):
    if not isinstance(managed, dict) or any(op.get(key) != managed.get(key) for key in ("token", "profile_uuid", "epoch", "archive_sha256")):
        raise ImportUnresolved("Publication journal does not match the Desktop operation")
    index = managed.get("item")
    if not isinstance(index, int) or isinstance(index, bool) or index < 0 or index >= len(op["items"]):
        raise ImportUnresolved("Publication journal item index is invalid")
    item = op["items"][index]
    if item["identity"] != managed.get("identity"):
        raise ImportUnresolved("Publication journal item identity conflicts")
    return item


def _assets(quiz):
    return {asset["path"]: asset["sha256"] for asset in quiz["assets"]}


def _expected_questions(app, quiz, bucket):
    urls = {path: f"/quiz-assets/{bucket}/{path[len('assets/') :]}" for path in _assets(quiz)}
    value = app._portable_quiz_bundle_service._publication_questions(quiz, urls)
    return app._normalize_quiz_question_ordinals(value, value)[0]


def _semantic(payload):
    """Fields that source DB serialization must preserve exactly, in order."""
    result = []
    for question in payload:
        value = {key: copy.deepcopy(question.get(key)) for key in
                 ("number", "type", "question", "explanation", "choices", "correct", "pairs",
                  "round_size", "direction", "source_number", "image_url", "image_alt", "image_edits", "image_source", "concepts")
                 if key in question}
        source = question.get("source") or {}
        if any(source.values()):
            value["source"] = {key: source[key] for key in sorted(source) if source[key]}
        result.append(value)
    return result


def _verify_committed(app, op, item, journal, paths, *, report_override=None):
    quiz_id = journal["quiz"]["id"]
    html = journal["registry"]["html"]
    bucket = journal["artifacts"]["assets"]["name"]
    if quiz_id is None or html != "portable_quiz_" + item["identity"] + ".html":
        raise ImportUnresolved("Published quiz ID or artifact identity differs from the planned item")
    registry = [entry for entry in app.load_registry() if str(entry.get("id")) == str(quiz_id) or entry.get("html") == html]
    if len(registry) != 1 or str(registry[0].get("id")) != str(quiz_id) or registry[0].get("html") != html:
        raise ImportUnresolved("Published registry identity is missing or conflicting")
    entry = registry[0]
    if (entry.get("title") != item["title"] or entry.get("folder") != item["folder"]
            or entry.get("exam_minutes") != item["exam_minutes"]):
        raise ImportUnresolved("Published registry semantics differ from the reviewed item")
    if report_override is None:
        _, _, _, report = _bound_stage(app, op["token"], {"uuid": op["profile_uuid"], "epoch": op["epoch"]})
    else:
        report = report_override
    quiz = report["manifest"]["quizzes"][item["index"]]
    if quiz["bundle_id"] != item["bundle_id"]:
        raise ImportUnresolved("Reviewed bundle item identity changed")
    expected = _expected_questions(app, quiz, bucket)
    json_path = Path(paths["json"])
    assert_safe_leaf(json_path)
    actual = json.loads(json_path.read_text(encoding="utf-8"))
    if actual != expected:
        raise ImportUnresolved("Published JSON differs from the frozen reviewed questions")
    conn = app.get_db()
    try:
        row = conn.execute("SELECT title,source_file FROM quizzes WHERE id=?", (quiz_id,)).fetchone()
        if row is None or row["title"] != item["title"] or row["source_file"] != html:
            raise ImportUnresolved("Published database quiz differs from the reviewed item")
        db_payload = app._quiz_json_payload_from_db(conn.cursor(), quiz_id)
        identities = []
        for question_id, number in conn.execute(
            "SELECT id,question_number FROM questions WHERE quiz_id=? ORDER BY question_number,id", (quiz_id,)
        ):
            choices = [list(row) for row in conn.execute(
                "SELECT id,label,text,is_correct,choice_order FROM choices WHERE question_id=? ORDER BY choice_order,id", (question_id,))]
            pairs = [list(row) for row in conn.execute(
                "SELECT id,pair_order,left_text,right_text FROM matching_pairs WHERE question_id=? ORDER BY pair_order,id", (question_id,))]
            identities.append([question_id, number, choices, pairs])
    finally:
        conn.close()
    if _semantic(db_payload) != _semantic(expected):
        raise ImportUnresolved("Published database answers or matching content differ from the reviewed item")
    html_path = Path(paths["html"])
    assert_safe_leaf(html_path)
    hashes = {"json": _sha(json_path), "html": _sha(html_path)}
    logo_source = (app._portable_quiz_bundle_service._asset_path_from_ref(quiz["logo"], label="Quiz logo")
                   if quiz.get("logo") else None)
    final_assets = {}
    for source, digest in _assets(quiz).items():
        if source == logo_source:
            continue  # Logos are copied to the separately journaled logo folder.
        relative = source[len("assets/"):]
        final_assets[relative] = digest
        hashes["asset:" + relative] = digest
    _verify_tree(Path(paths["assets"]), final_assets, "Published media",
                 base=Path(app.QUIZ_ASSET_FOLDER), allow_missing_empty=True)
    if quiz.get("logo"):
        logo = entry.get("logo")
        if isinstance(logo, str):
            assert_safe_leaf(Path(app.LOGO_FOLDER) / logo)
        if (not isinstance(logo, str) or logo != journal.get("owned_logo")
                or _sha(Path(app.LOGO_FOLDER) / logo) != _assets(quiz)[logo_source]):
            raise ImportUnresolved("Published logo differs from the reviewed bundle")
        hashes["logo"] = _sha(Path(app.LOGO_FOLDER) / logo)
    return {"quiz_id": quiz_id, "html": html, "logo": entry.get("logo"), "title": item["title"],
            "source_title": item["source_title"], "folder": item["folder"],
            "renamed": item["renamed"], "hashes": hashes, "record_ids": identities}


def record_publication_outcome(app, journal, outcome, paths):
    managed = journal.get("desktop_import")
    if managed is None:
        return
    if (os.environ.get("DLMS_DESKTOP_AUTOMATED") == "1"
            and os.environ.get("DLMS_DESKTOP_TEST_FAIL_IMPORT_RECEIPT") == "1"):
        raise OSError("Synthetic Desktop item-receipt storage failure")
    with _MUTEX:
        profile, identity = _profile()
        if identity["uuid"] != managed.get("profile_uuid") or identity["epoch"] != managed.get("epoch"):
            raise ImportUnresolved("Publication journal belongs to another Desktop dataset")
        path = _file(profile, identity["epoch"], managed["token"])
        op = _read(path)
        item = _exact_item(op, managed)
        if outcome == "committed":
            receipt = _verify_committed(app, op, item, journal, paths)
            if item["state"] == "committed" and item["receipt"] != receipt:
                raise ImportUnresolved("Committed item receipt changed after publication")
            item.update(state="committed", receipt=receipt)
        elif outcome == "rolled_back":
            if item["state"] == "committed":
                raise ImportUnresolved("A committed item cannot be marked rolled back")
            quiz_id = journal["quiz"]["id"]
            if quiz_id is not None:
                conn = app.get_db()
                try:
                    if conn.execute("SELECT 1 FROM quizzes WHERE id=?", (quiz_id,)).fetchone():
                        raise ImportUnresolved("Rolled-back publication still has a database quiz")
                finally:
                    conn.close()
            if any(str(entry.get("id")) == str(quiz_id) or entry.get("html") == journal["registry"]["html"]
                   for entry in app.load_registry()):
                raise ImportUnresolved("Rolled-back publication still has a registry entry")
            if any(path and Path(path).exists() for key, path in paths.items() if key != "stage"):
                raise ImportUnresolved("Rolled-back publication still has output artifacts")
            item.update(state="rolled_back", receipt=None)
        else:
            raise ValueError("Unknown managed publication outcome")
        _write(path, op)  # Must precede publication-journal removal.


def _prepare_media(app, op, report):
    bucket = "portable_import_" + op["token"]
    root = Path(app.QUIZ_ASSET_FOLDER) / bucket
    if root.is_symlink():
        raise ImportUnresolved("Import temporary media directory is unsafe")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    assets = {path: digest for quiz in report["manifest"]["quizzes"] for path, digest in _assets(quiz).items()}
    with zipfile.ZipFile(_stage(app, op["token"]) / "bundle.zip") as archive:
        for path, digest in sorted(assets.items()):
            relative = path[len("assets/"):]
            target = root / relative
            if not target.resolve().is_relative_to(root.resolve()) or target.is_symlink():
                raise ImportUnresolved("Import temporary media path is unsafe")
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if target.exists():
                if not target.is_file() or _sha(target) != digest:
                    raise ImportUnresolved("Import temporary media changed after preparation")
                continue
            data = archive.read(path)
            if hashlib.sha256(data).hexdigest() != digest:
                raise ImportUnresolved("Reviewed media bytes changed")
            temporary = target.with_name(target.name + ".tmp")
            assert_safe_leaf(temporary)
            if temporary.exists():
                # A crash can leave this unpublished, import-owned temporary
                # file. Only an exact prefix of the reviewed member is safe
                # to discard and rewrite; changed bytes retain the evidence.
                details = temporary.lstat()
                if (not stat.S_ISREG(details.st_mode) or details.st_nlink != 1
                        or not data.startswith(temporary.read_bytes())):
                    raise ImportUnresolved("Import temporary media differs from reviewed input")
                temporary.unlink()
            with temporary.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            app._decode_raster_image(str(target), app.PASSIVE_PACK_IMAGE_EXTENSIONS)
    return bucket, root


def _verify_tree(root, expected, label, *, base=None, allow_missing_empty=False):
    if base is not None and (root.parent != base or base.is_symlink() or not base.is_dir()):
        raise ImportUnresolved(f"{label} bucket is outside its owned directory")
    if allow_missing_empty and not expected and not root.exists() and not root.is_symlink():
        return
    if root.is_symlink() or not root.is_dir() or not stat.S_ISDIR(root.lstat().st_mode):
        raise ImportUnresolved(f"{label} directory is unavailable")
    allowed_dirs = {parent.as_posix() for name in expected for parent in Path(name).parents
                    if parent.as_posix() != "."}
    found = set()
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise ImportUnresolved(f"{label} contains a symlink")
        if stat.S_ISDIR(info.st_mode):
            if relative not in allowed_dirs:
                raise ImportUnresolved(f"{label} contains an unexpected directory")
        elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
            if relative not in expected or _sha(path) != expected[relative]:
                raise ImportUnresolved(f"{label} contains changed or unexpected bytes")
            found.add(relative)
        else:
            raise ImportUnresolved(f"{label} contains an unsafe entry")
    if found != set(expected):
        raise ImportUnresolved(f"{label} is missing reviewed files")


def _cleanup_media(root, op, report):
    if (os.environ.get("DLMS_DESKTOP_AUTOMATED") == "1"
            and os.environ.get("DLMS_DESKTOP_TEST_FAIL_IMPORT_CLEANUP") == "1"):
        raise OSError("Synthetic Desktop temporary-media cleanup failure")
    expected = {path[len("assets/"):]: digest for quiz in report["manifest"]["quizzes"]
                for path, digest in _assets(quiz).items()}
    _verify_tree(root, expected, "Import temporary media")
    shutil.rmtree(root)
    if root.exists():
        raise ImportUnresolved("Import temporary media cleanup did not finish")


def _remove_stage(stage):
    if stage.parent.is_symlink() or stage.is_symlink() or not stage.is_dir():
        raise ImportUnresolved("Import stage changed before cleanup")
    entries = {path.name: path for path in stage.iterdir()}
    if set(entries) != {"bundle.zip", "stage.json"}:
        raise ImportUnresolved("Import stage contains unexpected entries; cleanup is blocked")
    for path in entries.values():
        details = path.lstat()
        if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
            raise ImportUnresolved("Import stage contains an unsafe entry")
    shutil.rmtree(stage)


def install(app, token):
    with app._profile_snapshot.access(app.APP_DATA_DIR, exclusive=True), _MUTEX, app.registry_lock:
        profile, identity = _profile()
        existing_path = _file(profile, identity["epoch"], token)
        if existing_path.exists():
            previous = _read(existing_path)
            if (previous.get("token") != token or previous.get("profile_uuid") != identity["uuid"]
                    or previous.get("epoch") != identity["epoch"]):
                raise ImportUnresolved("Import receipt belongs to a different Desktop dataset")
            if previous["state"] == "complete":
                if _stage(app, token).exists():
                    completed_stage, _, metadata, _ = _bound_stage(app, token, identity)
                    if metadata["archive_sha256"] != previous["archive_sha256"]:
                        raise ImportUnresolved("Completed import token was reused with changed input")
                    _remove_stage(completed_stage)
                return {"published": [item["receipt"] for item in previous["items"]],
                        "metadata": {"token": token}, "replayed": True}
        stage, archive, metadata, report = _bound_stage(app, token, identity)
        path, op = _prepared(app, token, profile, identity, stage, metadata, report)
        if op["state"] == "uncertain":
            raise ImportUnresolved("Import outcome is uncertain; retained evidence needs inspection")
        checkpoint("before_mutation")
        for item in op["items"]:
            if item["state"] == "publishing":
                html = f"portable_quiz_{item['identity']}.html"
                journal_root = Path(app._quiz_publication_staging_root())
                pending = [p for p in journal_root.glob("publication_*.json") if not p.is_symlink()
                           and json.loads(p.read_text(encoding="utf-8")).get("desktop_import") == _managed(item, op)] if journal_root.exists() else []
                if pending:
                    recovery = app.reconcile_quiz_publications()
                    if recovery["unsafe"] or recovery["failed"]:
                        raise ImportUnresolved("Publication recovery is unresolved; no second copy was started")
                    op = _read(path)
                    item = op["items"][item["index"]]
                if item["state"] == "publishing":
                    conn = app.get_db()
                    try:
                        rows = conn.execute("SELECT id FROM quizzes WHERE source_file=?", (html,)).fetchall()
                    finally:
                        conn.close()
                    if rows or (Path(app.DATA_FOLDER) / html.replace(".html", ".json")).exists() or (Path(app.QUIZ_FOLDER) / html).exists() or (Path(app.QUIZ_ASSET_FOLDER) / html[:-5]).exists():
                        raise ImportUnresolved("Item publication has output without a conclusive receipt")
                    item["state"] = "rolled_back"
                    _write(path, op)
            if item["state"] == "committed":
                receipt = item["receipt"]
                html = receipt["html"]
                journal = {"quiz": {"id": receipt["quiz_id"]}, "registry": {"html": html},
                           "artifacts": {"assets": {"name": html[:-5]}}, "owned_logo": receipt.get("logo")}
                paths = {"json": str(Path(app.DATA_FOLDER) / (html[:-5] + ".json")),
                         "html": str(Path(app.QUIZ_FOLDER) / html),
                         "assets": str(Path(app.QUIZ_ASSET_FOLDER) / html[:-5])}
                try:
                    unchanged = _verify_committed(app, op, item, journal, paths) == receipt
                except ImportUnresolved as exc:
                    raise ImportUnresolved(
                        f"Previously committed quiz changed or was removed; no automatic recreation is permitted. {exc}"
                    ) from exc
                if not unchanged:
                    raise ImportUnresolved("Previously committed quiz changed; no automatic recreation is permitted")
                continue
            if item["state"] not in {"planned", "rolled_back"}:
                raise ImportUnresolved("Unknown item state; import evidence retained")
            bucket, root = _prepare_media(app, op, report)
            quiz = report["manifest"]["quizzes"][item["index"]]
            urls = {source: f"/quiz-assets/{bucket}/{source[len('assets/') :]}" for source in _assets(quiz)}
            questions = app._portable_quiz_bundle_service._publication_questions(quiz, urls)
            logo = None
            if quiz.get("logo"):
                source = app._portable_quiz_bundle_service._asset_path_from_ref(quiz["logo"], label="Quiz logo")
                extension = Path(source).suffix.lower()
                logo = f"logo_1_{hashlib.sha256(item['identity'].encode()).hexdigest()[:8]}{extension}"
                destination = Path(app.LOGO_FOLDER) / logo
                assert_safe_leaf(destination)
                if destination.exists():
                    if _sha(destination) != _assets(quiz)[source]:
                        raise ImportUnresolved("Import-owned logo path changed")
                else:
                    shutil.copy2(root / source[len("assets/"):], destination)
            item["state"] = "publishing"
            op["state"] = "running"
            _write(path, op)
            checkpoint("item_intent_" + str(item["index"]))
            app._publish_quiz(item["title"], questions, filename_prefix="portable_quiz",
                              exam_minutes=item["exam_minutes"], logo_filename=logo,
                              snapshot_existing_assets=True, rollback_logo_filename=logo,
                              managed_item=_managed(item, op), artifact_identity=lambda: item["identity"],
                              registry_folder=item["folder"])
            op = _read(path)
            if op["items"][item["index"]]["state"] != "committed":
                raise ImportUnresolved("Publisher returned without a durable item receipt")
            checkpoint("after_item_" + str(item["index"]))
        checkpoint("after_all_receipts")
        op["state"] = "cleanup_pending"
        _write(path, op)
        bucket, root = _prepare_media(app, op, report)
        _cleanup_media(root, op, report)
        checkpoint("after_temporary_cleanup")
        op["state"] = "complete"
        _write(path, op)
        checkpoint("after_complete_receipt")
        # A successful receipt is durable before stage cleanup. Stage removal
        # failure leaves a repeatable completed result with no republishing.
        _remove_stage(stage)
        return {"published": [item["receipt"] for item in op["items"]], "metadata": metadata}


def cancel(app, token):
    with app._profile_snapshot.access(app.APP_DATA_DIR, exclusive=True), _MUTEX:
        profile, identity = _profile()
        stage, _, metadata, _ = _bound_stage(app, token, identity)
        path = _file(profile, identity["epoch"], token)
        if path.exists() or metadata["desktop_import"]["started"]:
            raise ImportUnresolved("This import has accepted work; cancellation cannot undo it. Review and resume its progress")
        _remove_stage(stage)


def progress(app, token):
    profile, identity = _profile()
    path = _file(profile, identity["epoch"], token)
    if not path.exists():
        return {"committed": 0, "remaining": None, "state": "new", "items": []}
    op = _read(path)
    if (op.get("token") != token or op.get("profile_uuid") != identity["uuid"]
            or op.get("epoch") != identity["epoch"]):
        raise ImportUnresolved("Import operation belongs to another dataset")
    completed = sum(item["state"] == "committed" for item in op["items"])
    return {"committed": completed, "remaining": len(op["items"]) - completed,
            "state": op["state"], "items": op["items"]}


def unresolved_count(profile, epoch):
    root = _root(profile, epoch)
    count = 0
    if root.exists():
        for path in root.iterdir():
            if path.is_symlink() or not path.is_file() or path.suffix != ".json":
                raise ImportUnresolved("Portable-import operation storage contains unexpected evidence")
            if _read(path)["state"] != "complete":
                count += 1
    stage_root = profile / "backend" / "uploads" / "quiz_bundles"
    if stage_root.is_symlink() or (stage_root.exists() and not stage_root.is_dir()):
        raise ImportUnresolved("Portable-import staging root is unsafe")
    if stage_root.exists():
        for stage in stage_root.iterdir():
            if stage.name == "exports":
                continue
            if stage.is_symlink() or not stage.is_dir():
                raise ImportUnresolved("Portable-import staging contains unexpected evidence")
            metadata = stage / "stage.json"
            if metadata.exists():
                stamp = _read_stage(stage).get("desktop_import")
                if stamp and stamp.get("started"):
                    if stamp.get("epoch") != epoch or not _file(profile, epoch, stage.name).exists():
                        raise ImportUnresolved("Started stage has no matching current operation record")
                    count += 1
    return count

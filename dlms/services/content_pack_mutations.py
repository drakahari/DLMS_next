"""Content-pack staging, installation, asset migration, and removal services."""

import io
import json
import os
import re
import shutil
import tempfile
import zipfile


class ContentPackInstallError(Exception):
    """Carry the original install failure and its staged workflow metadata."""

    def __init__(self, original, metadata):
        super().__init__(str(original))
        self.original = original
        self.metadata = metadata


class InvalidContentPackFolderError(ValueError):
    pass


class ContentPackFolderNotFoundError(FileNotFoundError):
    pass


class ProtectedContentPackError(ValueError):
    pass


def _snapshot_one_pack_asset(
    pack_id,
    asset_url,
    bucket,
    *,
    destination_root=None,
    created_assets=None,
    get_content_pack,
    safe_pack_child,
    decode_raster_image,
    passive_pack_image_extensions,
    quiz_asset_folder,
    quiz_asset_url,
    copy_file=shutil.copy2,
    replace_file=os.replace,
):
    """Copy one content-pack asset into quiz-owned storage and return its stable runtime URL."""
    asset_url = str(asset_url or "")
    prefix = f"/content-packs/{pack_id}/assets/"
    if not asset_url.startswith(prefix):
        return asset_url, False

    pack = get_content_pack(pack_id)
    if not pack:
        raise FileNotFoundError(f"Content pack {pack_id!r} is not installed")

    rel = asset_url[len(prefix):].lstrip("/")
    src = safe_pack_child(pack["_root"], rel)
    if not os.path.isfile(src):
        raise FileNotFoundError(f"Content-pack asset not found: {rel}")

    ext = os.path.splitext(src)[1].lower()
    if ext not in passive_pack_image_extensions:
        raise ValueError(f"Unsupported quiz asset type: {ext}")
    decode_raster_image(src, passive_pack_image_extensions)

    dest_root = destination_root or os.path.join(quiz_asset_folder, bucket)
    dest = safe_pack_child(dest_root, rel)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if not os.path.isfile(dest):
        descriptor, temporary_path = tempfile.mkstemp(
            prefix=f".{os.path.basename(dest)}.", suffix=ext,
            dir=os.path.dirname(dest),
        )
        os.close(descriptor)
        try:
            copy_file(src, temporary_path)
            decode_raster_image(temporary_path, passive_pack_image_extensions)
            replace_file(temporary_path, dest)
            if created_assets is not None:
                created_assets.add(dest)
        finally:
            try:
                os.remove(temporary_path)
            except FileNotFoundError:
                pass
    return quiz_asset_url(bucket, rel), True


def _snapshot_pack_refs_recursive(
    pack_id,
    value,
    bucket,
    *,
    destination_root=None,
    created_assets=None,
    snapshot_one_pack_asset,
):
    """Recursively rewrite any runtime content-pack asset URLs to quiz-owned copies."""
    changed = 0
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            new_item, n = _snapshot_pack_refs_recursive(
                pack_id,
                item,
                bucket,
                destination_root=destination_root,
                created_assets=created_assets,
                snapshot_one_pack_asset=snapshot_one_pack_asset,
            )
            out[key] = new_item
            changed += n
        return out, changed
    if isinstance(value, list):
        out = []
        for item in value:
            new_item, n = _snapshot_pack_refs_recursive(
                pack_id,
                item,
                bucket,
                destination_root=destination_root,
                created_assets=created_assets,
                snapshot_one_pack_asset=snapshot_one_pack_asset,
            )
            out.append(new_item)
            changed += n
        return out, changed
    if isinstance(value, str):
        new_value, did_change = snapshot_one_pack_asset(
            pack_id,
            value,
            bucket,
            destination_root=destination_root,
            created_assets=created_assets,
        )
        return new_value, int(did_change)
    return value, 0


def _cleanup_new_pack_migration_assets(created_assets, *, quiz_asset_folder):
    """Best-effort rollback limited to files created by one migration step."""
    asset_root = os.path.realpath(quiz_asset_folder)
    for path in sorted(created_assets, key=lambda item: item.count(os.sep), reverse=True):
        candidate = os.path.realpath(path)
        if not candidate.startswith(asset_root + os.sep):
            continue
        try:
            if os.path.isfile(candidate) and not os.path.islink(candidate):
                os.remove(candidate)
            parent = os.path.dirname(candidate)
            while parent != asset_root and parent.startswith(asset_root + os.sep):
                try:
                    os.rmdir(parent)
                except OSError:
                    break
                parent = os.path.dirname(parent)
        except OSError as exc:
            print(f"[CONTENT PACK MIGRATION CLEANUP ERROR] {candidate}: {exc}")


def _snapshot_runtime_questions(
    pack_id,
    runtime_questions,
    db_questions,
    bucket,
    *,
    destination_root=None,
    snapshot_pack_refs_recursive,
):
    """Make generated image quizzes independent of the source content pack."""
    runtime_copy, runtime_count = snapshot_pack_refs_recursive(
        pack_id, runtime_questions, bucket, destination_root=destination_root
    )
    db_copy, db_count = snapshot_pack_refs_recursive(
        pack_id, db_questions, bucket, destination_root=destination_root
    )
    return runtime_copy, db_copy, runtime_count + db_count


def _snapshot_existing_pack_dependencies(
    pack_id,
    *,
    data_folder,
    snapshot_pack_refs_recursive,
    atomic_write_json,
    get_db,
    cleanup_new_pack_migration_assets,
    row_factory,
):
    """Migrate legacy pack asset references into quiz-owned snapshots."""
    migrated_files = 0
    migrated_refs = 0

    if os.path.isdir(data_folder):
        for name in os.listdir(data_folder):
            if not name.lower().endswith(".json"):
                continue
            path = os.path.join(data_folder, name)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
            except Exception:
                continue
            bucket = "legacy_" + re.sub(
                r"[^A-Za-z0-9_.-]+", "_", os.path.splitext(name)[0]
            )[:110]
            created_assets = set()
            try:
                new_payload, count = snapshot_pack_refs_recursive(
                    pack_id, payload, bucket, created_assets=created_assets
                )
                if count:
                    atomic_write_json(
                        path, new_payload, indent=4, ensure_ascii=False,
                        expected_type=type(payload),
                    )
                    migrated_files += 1
                    migrated_refs += count
            except Exception:
                cleanup_new_pack_migration_assets(created_assets)
                raise

    conn = get_db()
    conn.row_factory = row_factory
    cur = conn.cursor()
    created_assets = set()
    try:
        columns = {
            row["name"] for row in cur.execute("PRAGMA table_info(questions)").fetchall()
        }
        if "media_json" in columns:
            rows = cur.execute("""
                SELECT q.id AS question_id, q.quiz_id, q.media_json
                FROM questions q
                WHERE q.media_json IS NOT NULL AND q.media_json != ''
            """).fetchall()
            for row in rows:
                try:
                    payload = json.loads(row["media_json"])
                except Exception:
                    continue
                bucket = f"legacy_quiz_{row['quiz_id']}"
                new_payload, count = snapshot_pack_refs_recursive(
                    pack_id, payload, bucket, created_assets=created_assets
                )
                if count:
                    cur.execute(
                        "UPDATE questions SET media_json = ? WHERE id = ?",
                        (json.dumps(new_payload, ensure_ascii=False), row["question_id"]),
                    )
                    migrated_refs += count

        answer_columns = {
            row["name"]
            for row in cur.execute("PRAGMA table_info(attempt_answers)").fetchall()
        }
        if "response_json" in answer_columns:
            rows = cur.execute("""
                SELECT id, attempt_id, response_json
                FROM attempt_answers
                WHERE response_json IS NOT NULL AND response_json != ''
            """).fetchall()
            for row in rows:
                try:
                    payload = json.loads(row["response_json"])
                except Exception:
                    continue
                bucket = "legacy_attempt_" + re.sub(
                    r"[^A-Za-z0-9_.-]+", "_", str(row["attempt_id"])
                )[:100]
                new_payload, count = snapshot_pack_refs_recursive(
                    pack_id, payload, bucket, created_assets=created_assets
                )
                if count:
                    cur.execute(
                        "UPDATE attempt_answers SET response_json = ? WHERE id = ?",
                        (json.dumps(new_payload, ensure_ascii=False), row["id"]),
                    )
                    migrated_refs += count

        conn.commit()
    except Exception:
        conn.rollback()
        cleanup_new_pack_migration_assets(created_assets)
        raise
    finally:
        conn.close()
    return {"files": migrated_files, "references": migrated_refs}


def _randomize_staged_ai_answer_positions(
    pack_root,
    manifest,
    *,
    safe_pack_child,
    answer_position_concentration,
    rng_factory,
    replace_file=os.replace,
):
    """Repair pathological AI MCQ answer-position distributions in staged JSON."""
    corrections = []
    rng = rng_factory()
    for descriptor in manifest.get("quiz_datasets") or []:
        if not isinstance(descriptor, dict):
            continue
        rel_path = str(descriptor.get("path") or "").strip()
        if not rel_path:
            continue
        dataset_path = safe_pack_child(pack_root, rel_path)
        with open(dataset_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        questions = data.get("questions") if isinstance(data, dict) else None
        skew = answer_position_concentration(questions)
        if not skew:
            continue

        position_counts = {}
        randomized = 0
        for question in questions:
            if not isinstance(question, dict):
                continue
            if str(question.get("type") or "choice").strip().lower() != "choice":
                continue
            choices = question.get("choices")
            if not isinstance(choices, list) or len(choices) < 2:
                continue
            correct_choices = [
                choice for choice in choices
                if isinstance(choice, dict) and choice.get("is_correct") is True
            ]
            if len(correct_choices) != 1:
                continue

            shuffled = list(choices)
            rng.shuffle(shuffled)
            least_used = min(
                position_counts.get(index, 0) for index in range(len(shuffled))
            )
            candidates = [
                index for index in range(len(shuffled))
                if position_counts.get(index, 0) == least_used
            ]
            target = rng.choice(candidates)
            current = next(
                index for index, choice in enumerate(shuffled)
                if isinstance(choice, dict) and choice.get("is_correct") is True
            )
            shuffled[current], shuffled[target] = shuffled[target], shuffled[current]
            question["choices"] = shuffled
            position_counts[target] = position_counts.get(target, 0) + 1
            randomized += 1

        if not randomized:
            continue
        temporary_path = dataset_path + ".answer-position.tmp"
        try:
            with open(temporary_path, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
            replace_file(temporary_path, dataset_path)
        finally:
            if os.path.exists(temporary_path):
                os.remove(temporary_path)
        corrections.append(
            f"{rel_path}: DLMS detected {skew['count']} of {skew['total']} correct answers "
            f"in position {skew['label']} ({skew['percentage']}%) and safely randomized "
            f"the choices for {randomized} single-select questions."
        )
    return corrections


def _extract_content_pack_zip(zip_path, stage_root, *, safe_zip_member_name):
    """Safely extract a previously inspected Study Pack ZIP."""
    os.makedirs(stage_root, exist_ok=False)
    real_stage = os.path.realpath(stage_root)
    with zipfile.ZipFile(zip_path, "r") as archive:
        for info in archive.infolist():
            normalized = safe_zip_member_name(info.filename)
            target = os.path.realpath(os.path.join(stage_root, normalized))
            if target != real_stage and not target.startswith(real_stage + os.sep):
                raise ValueError("ZIP path escapes staging directory")
            if info.is_dir():
                os.makedirs(target, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with archive.open(info, "r") as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)


def _content_pack_stage_path(token, *, token_pattern, staging_folder):
    if not token_pattern.fullmatch(str(token or "")):
        raise ValueError("Invalid import token")
    return os.path.join(staging_folder, token)


def _load_staged_content_pack(token, *, content_pack_stage_path, safe_pack_child):
    stage_dir = content_pack_stage_path(token)
    metadata_path = os.path.join(stage_dir, "stage.json")
    if not os.path.isfile(metadata_path):
        raise FileNotFoundError("Staged Content Pack was not found or has expired")
    with open(metadata_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)
    pack_root = safe_pack_child(stage_dir, metadata["root_name"])
    if not os.path.isdir(pack_root):
        raise FileNotFoundError("Staged Content Pack root folder is missing")
    return stage_dir, pack_root, metadata


def _remove_content_pack_stage(token, *, content_pack_stage_path, remove_tree=shutil.rmtree):
    try:
        stage_dir = content_pack_stage_path(token)
    except Exception:
        return
    remove_tree(stage_dir, ignore_errors=True)


def stage_content_pack_upload(
    upload,
    *,
    workflow,
    allowed_workflow,
    content_length,
    upload_max_bytes,
    multipart_overhead_bytes,
    upload_too_large_error,
    token_hex,
    content_pack_stage_path,
    bounded_save_upload,
    inspect_content_pack_zip,
    extract_content_pack_zip,
    safe_pack_child,
    validate_staged_content_pack,
    randomize_staged_ai_answer_positions,
    secure_filename,
    now,
):
    """Stage and independently validate a Study Pack ZIP before installation."""
    if workflow not in {None, allowed_workflow}:
        raise ValueError("Unsupported Study Pack workflow")
    if not upload or not upload.filename:
        raise ValueError("Choose a DLMS Study Pack ZIP to validate")
    if not str(upload.filename).lower().endswith(".zip"):
        raise ValueError("Content Packs must be uploaded as ZIP files")
    if content_length and content_length > upload_max_bytes + multipart_overhead_bytes:
        raise upload_too_large_error(
            "Study Pack ZIP is too large. Maximum upload size is 256 MB."
        )

    token = token_hex(16)
    stage_dir = content_pack_stage_path(token)
    os.makedirs(stage_dir, exist_ok=False)
    zip_path = os.path.join(stage_dir, "upload.zip")

    try:
        bounded_save_upload(upload, zip_path, upload_max_bytes, "Study Pack ZIP")
        if not zipfile.is_zipfile(zip_path):
            raise ValueError("uploaded file is not a valid ZIP archive")
        inspection = inspect_content_pack_zip(zip_path)
        extract_root = os.path.join(stage_dir, "extracted")
        extract_content_pack_zip(zip_path, extract_root)
        pack_root = safe_pack_child(extract_root, inspection["root_name"])
        report = validate_staged_content_pack(
            pack_root,
            normalize_images=True,
            require_single_select=(workflow == allowed_workflow),
        )
        answer_position_corrections = []
        if workflow == allowed_workflow and report["valid"]:
            answer_position_corrections = randomize_staged_ai_answer_positions(
                pack_root, report["manifest"]
            )
            if answer_position_corrections:
                report = validate_staged_content_pack(
                    pack_root, require_single_select=True
                )
                report["warnings"].extend(answer_position_corrections)

        metadata = {
            "token": token,
            "root_name": f"extracted/{inspection['root_name']}",
            "extract_root": "extracted",
            "uploaded_name": secure_filename(upload.filename) or "study_pack.zip",
            "file_count": inspection["file_count"],
            "uncompressed_bytes": inspection["uncompressed_bytes"],
            "report": report,
            "created_at": now().isoformat(timespec="seconds"),
        }
        if answer_position_corrections:
            metadata["answer_position_corrections"] = answer_position_corrections
        if workflow:
            metadata["workflow"] = workflow
        with open(os.path.join(stage_dir, "stage.json"), "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        return token
    except Exception:
        shutil.rmtree(stage_dir, ignore_errors=True)
        raise


def install_staged_content_pack(
    token,
    *,
    load_staged_content_pack,
    validate_staged_content_pack,
    workflow_for_metadata,
    ai_workflow,
    discover_content_packs,
    content_pack_folder,
    remove_content_pack_stage,
    move=shutil.move,
):
    """Validate, promote, verify, and clean one staged Study Pack."""
    destination = None
    pack_root = None
    metadata = {}
    try:
        _stage_dir, pack_root, metadata = load_staged_content_pack(token)
        report = validate_staged_content_pack(
            pack_root,
            require_single_select=(workflow_for_metadata(metadata) == ai_workflow),
        )
        if not report["valid"]:
            return {"status": "invalid", "metadata": metadata, "report": report}

        manifest = report["manifest"]
        pack_id = str(manifest.get("id") or "").strip().lower()
        current = discover_content_packs()
        if pack_id in current:
            raise ValueError(f"a Study Pack with id '{pack_id}' is already installed")

        folder_name = os.path.basename(pack_root)
        destination = os.path.realpath(os.path.join(content_pack_folder, folder_name))
        if os.path.dirname(destination) != os.path.realpath(content_pack_folder):
            raise ValueError("Study Pack destination is unsafe")
        if os.path.exists(destination):
            raise ValueError(f"destination folder '{folder_name}' already exists")

        move(pack_root, destination)
        installed = discover_content_packs().get(pack_id)
        if not installed:
            raise ValueError("DLMS could not discover the pack after installation")

        remove_content_pack_stage(token)
        return {
            "status": "installed",
            "metadata": metadata,
            "pack_id": pack_id,
            "installed": installed,
        }
    except Exception as exc:
        try:
            if destination and os.path.isdir(destination) and pack_root:
                os.makedirs(os.path.dirname(pack_root), exist_ok=True)
                if not os.path.exists(pack_root):
                    move(destination, pack_root)
        except Exception as rollback_exc:
            print(f"[CONTENT PACKS] Import rollback failed: {rollback_exc}")
        raise ContentPackInstallError(exc, metadata) from exc


def cancel_staged_content_pack(
    token, *, load_staged_content_pack, remove_content_pack_stage
):
    metadata = {}
    try:
        _, _, metadata = load_staged_content_pack(token)
    except Exception:
        pass
    remove_content_pack_stage(token)
    return metadata


def build_content_pack_export(folder, *, content_pack_folder_report):
    report = content_pack_folder_report(folder)
    if not report.get("valid"):
        raise ValueError(
            "invalid Study Packs cannot be exported until validation errors are corrected"
        )
    pack_root = report["root"]
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for walk_root, dirs, files in os.walk(pack_root):
            dirs[:] = [
                directory for directory in dirs
                if not os.path.islink(os.path.join(walk_root, directory))
            ]
            for name in files:
                source = os.path.join(walk_root, name)
                if os.path.islink(source) or not os.path.isfile(source):
                    continue
                relative = os.path.relpath(source, pack_root).replace(os.sep, "/")
                zf.write(source, arcname=f"{folder}/{relative}")
    archive.seek(0)
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", folder).strip("._") or "DLMS_Study_Pack"
    return archive.getvalue(), safe_name


def delete_content_pack_folder(
    folder,
    *,
    content_pack_folder,
    get_content_pack,
    snapshot_existing_pack_dependencies,
    remove_tree=shutil.rmtree,
):
    folder = str(folder or "").strip()
    if not folder or folder in {".", ".."} or os.path.basename(folder) != folder:
        raise InvalidContentPackFolderError("Invalid Content Pack folder")

    pack_root = os.path.realpath(os.path.join(content_pack_folder, folder))
    content_root = os.path.realpath(content_pack_folder)
    if os.path.dirname(pack_root) != content_root or not os.path.isdir(pack_root):
        raise ContentPackFolderNotFoundError("Content Pack folder was not found")

    manifest_path = os.path.join(pack_root, "manifest.json")
    pack_id = ""
    protected = False
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f) or {}
        pack_id = str(manifest.get("id") or "").strip().lower()
        protected = bool(manifest.get("protected"))
    except Exception:
        manifest = {}

    if protected:
        raise ProtectedContentPackError(
            "This Content Pack declares itself protected and cannot be deleted here."
        )

    migration = {"files": 0, "references": 0}
    if pack_id and get_content_pack(pack_id):
        migration = snapshot_existing_pack_dependencies(pack_id)
    remove_tree(pack_root)
    return {"folder": folder, "pack_id": pack_id, "migration": migration}


def remove_unprotected_content_packs(
    *,
    content_pack_folder,
    get_content_pack,
    snapshot_existing_pack_dependencies,
    remove_tree=shutil.rmtree,
):
    entries = list(os.listdir(content_pack_folder)) if os.path.isdir(content_pack_folder) else []
    for folder_name in entries:
        pack_root = os.path.join(content_pack_folder, folder_name)
        if not os.path.isdir(pack_root):
            continue
        manifest = {}
        try:
            with open(os.path.join(pack_root, "manifest.json"), "r", encoding="utf-8") as f:
                manifest = json.load(f) or {}
        except Exception:
            manifest = {}
        if bool(manifest.get("protected")):
            continue
        pack_id = str(manifest.get("id") or "").strip().lower()
        if pack_id and get_content_pack(pack_id):
            snapshot_existing_pack_dependencies(pack_id)
        remove_tree(pack_root)


def create_image_study_pack(
    *,
    draft_root,
    title,
    subject,
    description,
    source_note,
    images_payload,
    questions_payload,
    artifact_identity,
    exam_minutes,
    content_pack_folder,
    safe_pack_child,
    secure_filename,
    validate_hotspot_shape,
    now,
    load_content_pack_quiz_dataset,
    quiz_dataset_runtime,
    publish_quiz,
    copy_file=shutil.copy2,
    remove_tree=shutil.rmtree,
):
    """Create a user image Study Pack and publish its generated quiz atomically."""
    title_slug = re.sub(r"[^A-Za-z0-9]+", "_", title).strip("_")[:60] or "Image_Study"
    pack_id = f"user_{title_slug.lower()}_{artifact_identity}"
    pack_root = os.path.join(
        content_pack_folder, f"DLMS_Study_{title_slug}_{artifact_identity}"
    )
    images_root = os.path.join(pack_root, "images")
    data_root = os.path.join(pack_root, "data")

    try:
        os.makedirs(images_root, exist_ok=False)
        os.makedirs(data_root, exist_ok=True)
        image_records, image_map = [], {}
        for n, raw in enumerate(images_payload, 1):
            image_id = str(raw.get("id") or f"image_{n}").strip()
            filename = secure_filename(str(raw.get("filename") or ""))
            src = safe_pack_child(draft_root, filename)
            if not filename or not os.path.isfile(src):
                raise FileNotFoundError(f"Draft image missing: {filename}")
            copy_file(src, os.path.join(images_root, filename))
            record = {
                "id": image_id,
                "file": f"images/{filename}",
                "alt_text": str(
                    raw.get("alt_text") or raw.get("original_name") or title
                ).strip(),
                "edits": [],
                "hotspots": [],
                "source": {
                    "organization": "User supplied",
                    "work": str(raw.get("original_name") or filename),
                    "attribution": source_note or "User-supplied image for personal study",
                    "license": "User-supplied; redistribution rights not asserted by DLMS",
                    "redistribution_status": "not-cleared-for-redistribution",
                },
            }
            image_records.append(record)
            image_map[image_id] = record

        cleaned, question_number = [], 1
        for raw in questions_payload:
            if not isinstance(raw, dict):
                continue
            question_type = str(raw.get("type") or "choice").strip().lower()
            question = str(raw.get("question") or "").strip()
            image_id = str(raw.get("image_id") or "").strip()
            explanation = str(raw.get("explanation") or "").strip()
            if (
                question_type not in {"choice", "matching", "hotspot"}
                or not question
                or image_id not in image_map
            ):
                continue

            if question_type == "matching":
                pairs = []
                for pair in raw.get("pairs") or []:
                    left = str((pair or {}).get("left") or "").strip()
                    right = str((pair or {}).get("right") or "").strip()
                    if left and right:
                        pairs.append({"left": left, "right": right})
                if len(pairs) < 2:
                    raise ValueError(
                        f"Question {question_number} needs at least two complete matching pairs"
                    )
                cleaned.append({
                    "id": f"q{question_number}",
                    "type": "matching",
                    "question": question,
                    "image_id": image_id,
                    "pairs": pairs,
                    "direction": "term_to_definition",
                    "explanation": explanation,
                })
            elif question_type == "hotspot":
                shape = validate_hotspot_shape(raw.get("shape"))
                label = str(raw.get("target_label") or "").strip()
                if not label:
                    raise ValueError(
                        f"Question {question_number} needs a hotspot target label"
                    )
                hotspot_id = f"hotspot_{question_number}"
                image_map[image_id]["hotspots"].append({
                    "id": hotspot_id,
                    "label": label,
                    "prompt": question,
                    "shape": shape,
                    "explanation": explanation,
                    "calibration": {
                        "tool": "DLMS Build from Images",
                        "updated_at": now().isoformat(timespec="seconds"),
                    },
                })
                cleaned.append({
                    "id": f"q{question_number}",
                    "type": "hotspot",
                    "question": question,
                    "image_id": image_id,
                    "hotspot_id": hotspot_id,
                    "target_label": label,
                    "explanation": explanation,
                })
            else:
                choices = []
                for choice in raw.get("choices") or []:
                    text = str((choice or {}).get("text") or "").strip()
                    if text:
                        choices.append({
                            "label": chr(65 + len(choices)),
                            "text": text,
                            "is_correct": bool((choice or {}).get("is_correct")),
                        })
                if len(choices) < 2 or not any(choice["is_correct"] for choice in choices):
                    raise ValueError(
                        f"Question {question_number} needs at least two choices and one correct answer"
                    )
                cleaned.append({
                    "id": f"q{question_number}",
                    "type": "choice",
                    "question": question,
                    "image_id": image_id,
                    "choices": choices,
                    "explanation": explanation,
                })
            question_number += 1

        if not cleaned:
            raise ValueError("No usable questions were submitted")

        dataset_id = (
            re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")[:64]
            or "image_questions"
        )
        dataset = {
            "schema_version": 1,
            "id": dataset_id,
            "title": title,
            "type": "quiz",
            "category": subject or "General",
            "description": description or f"User-created image-supported question set for {title}.",
            "source": {
                "organization": "User supplied",
                "dataset": title,
                "license": "User-supplied study material",
                "notes": source_note,
            },
            "images": image_records,
            "questions": cleaned,
        }
        dataset_rel = f"data/{dataset_id}.json"
        with open(os.path.join(pack_root, dataset_rel), "w", encoding="utf-8") as f:
            json.dump(dataset, f, indent=2, ensure_ascii=False)
            f.write("\n")
        manifest = {
            "schema_version": 1,
            "id": pack_id,
            "name": title,
            "version": "1.0.0",
            "publisher": "DLMS user",
            "content_domain": subject or "General",
            "description": dataset["description"],
            "datasets": [],
            "image_datasets": [],
            "quiz_datasets": [{
                "id": dataset_id,
                "title": title,
                "type": "quiz",
                "path": dataset_rel,
                "description": dataset["description"],
            }],
            "user_supplied_assets": True,
            "redistribution_status": "not-cleared-for-redistribution",
        }
        with open(os.path.join(pack_root, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
            f.write("\n")

        data = load_content_pack_quiz_dataset(pack_id, dataset_id)
        runtime, db_questions = quiz_dataset_runtime(pack_id, data)
        _, html_name = publish_quiz(
            f"{title} — Practice",
            runtime,
            db_questions,
            filename_prefix=f"user_image_{dataset_id}",
            exam_minutes=exam_minutes,
            source_pack_id=pack_id,
            source_dataset_id=dataset_id,
        )
        remove_tree(draft_root, ignore_errors=True)
        return {
            "pack_id": pack_id,
            "pack_root": pack_root,
            "dataset_id": dataset_id,
            "html_name": html_name,
        }
    except Exception:
        remove_tree(pack_root, ignore_errors=True)
        raise

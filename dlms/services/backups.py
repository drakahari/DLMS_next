"""Portable backup creation, inspection, and isolated staging services."""

import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from dlms.persistence import json_files


# Keep the filename contract scoped to roots that the repository actually
# writes atomically. Installed content packs may legitimately contain arbitrary
# similarly named files and must remain portable.
_ATOMIC_JSON_BACKUP_ROOTS = frozenset({
    "data",
    "pdf_import_drafts",
    "pdf_question_banks",
    "pdf_terminology_banks",
})


def _is_repository_atomic_persistence_temp(parts):
    target_name = json_files._atomic_persistence_target_name(parts[-1])
    if target_name is None:
        return False

    root = parts[0].casefold()
    if root == "config":
        return len(parts) == 2 and target_name.casefold() in {
            "law.json", "portal.json", "quizzes.json"
        }
    if root in _ATOMIC_JSON_BACKUP_ROOTS:
        return target_name.lower().endswith(".json")
    if root == "law" and len(parts) >= 3:
        if parts[1].casefold() == "cases":
            return target_name.lower().endswith(".json")
        if parts[1].casefold() == "imports":
            return target_name.lower().endswith(".txt")
    return False


def backup_rel_is_excluded(
    rel_path,
    *,
    data_root_marker,
    excluded_top_level,
):
    rel = str(rel_path or "").replace("\\", "/").strip("/")
    if not rel:
        return True
    parts = rel.split("/")
    if len(parts) == 1 and parts[0].casefold() in {
        data_root_marker.casefold(), ".secret_key"
    }:
        return True
    if parts[0].casefold() in excluded_top_level:
        return True
    if len(parts) >= 3 and parts[0].casefold() == "static" and parts[1].casefold() == "logos" and parts[2] == "_temp":
        return True
    if parts[0].casefold() in {"results.db-wal", "results.db-shm", "results.db-journal"}:
        return True
    return False


def backup_file_inventory(
    app_data_dir,
    db_path,
    *,
    rel_is_excluded,
):
    """Return stable runtime files to include in a portable DLMS backup."""
    files = []
    for root_dir, dirs, names in os.walk(app_data_dir, followlinks=False):
        rel_root = os.path.relpath(root_dir, app_data_dir)
        if rel_root == ".":
            rel_root = ""

        # Never descend into excluded or symbolic-link directories.
        kept_dirs = []
        for dirname in dirs:
            full = os.path.join(root_dir, dirname)
            rel = os.path.join(rel_root, dirname) if rel_root else dirname
            if os.path.islink(full) or rel_is_excluded(rel):
                continue
            kept_dirs.append(dirname)
        dirs[:] = kept_dirs

        for name in names:
            full = os.path.join(root_dir, name)
            if os.path.islink(full):
                continue
            rel = os.path.join(rel_root, name) if rel_root else name
            rel = rel.replace("\\", "/")
            if rel_is_excluded(rel) or _is_repository_atomic_persistence_temp(
                rel.split("/")
            ):
                continue
            # results.db is added from SQLite's online backup API for consistency.
            if os.path.normcase(os.path.realpath(full)) == os.path.normcase(os.path.realpath(db_path)):
                continue
            if os.path.isfile(full):
                files.append((full, rel))
    files.sort(key=lambda item: item[1].casefold())
    return files


def backup_summary(
    *,
    db_path,
    content_pack_folder,
    pdf_question_bank_folder,
    pdf_terminology_bank_folder,
    load_registry,
    sqlite_module=sqlite3,
):
    summary = {
        "quizzes": 0,
        "attempts": 0,
        "content_packs": 0,
        "pdf_question_banks": 0,
        "pdf_terminology_banks": 0,
    }
    try:
        summary["quizzes"] = len(load_registry())
    except Exception:
        pass
    conn = None
    try:
        conn = sqlite_module.connect(db_path)
        row = conn.execute("SELECT COUNT(*) FROM attempts").fetchone()
        summary["attempts"] = int(row[0] or 0) if row else 0
    except Exception:
        pass
    finally:
        if conn is not None:
            conn.close()
    try:
        summary["content_packs"] = sum(
            1 for name in os.listdir(content_pack_folder)
            if os.path.isdir(os.path.join(content_pack_folder, name))
        )
    except Exception:
        pass
    for key, folder in [
        ("pdf_question_banks", pdf_question_bank_folder),
        ("pdf_terminology_banks", pdf_terminology_bank_folder),
    ]:
        try:
            summary[key] = sum(
                1 for name in os.listdir(folder) if name.lower().endswith(".json")
            )
        except Exception:
            pass
    return summary


def create_dlms_backup(
    label="manual",
    *,
    ensure_runtime_data_dirs,
    backup_folder,
    app_data_dir,
    db_path,
    app_version,
    backup_schema_version,
    backup_manifest,
    backup_data_prefix,
    file_inventory,
    summary,
    now=datetime.now,
    platform=None,
    sqlite_module=sqlite3,
):
    """Create a portable ZIP snapshot without mutating the live data set."""
    ensure_runtime_data_dirs()
    stamp = now().strftime("%Y%m%d-%H%M%S")
    safe_label = re.sub(r"[^A-Za-z0-9_-]+", "-", str(label or "manual")).strip("-")[:40] or "manual"
    filename = f"DLMS-backup-{stamp}-{safe_label}.zip"
    final_path = os.path.join(backup_folder, filename)
    temp_path = final_path + ".tmp"

    inventory = file_inventory()
    total_bytes = sum(os.path.getsize(path) for path, _ in inventory if os.path.isfile(path))
    included_roots = sorted({rel.split("/", 1)[0] for _, rel in inventory})

    db_temp = None
    try:
        if os.path.isfile(db_path):
            fd, db_temp = tempfile.mkstemp(prefix="dlms-db-snapshot-", suffix=".db")
            os.close(fd)
            src_conn = sqlite_module.connect(db_path)
            dst_conn = sqlite_module.connect(db_temp)
            try:
                src_conn.backup(dst_conn)
            finally:
                dst_conn.close()
                src_conn.close()
            total_bytes += os.path.getsize(db_temp)
            if "results.db" not in included_roots:
                included_roots.append("results.db")
                included_roots.sort()

        manifest = {
            "schema_version": backup_schema_version,
            "kind": "dlms-portable-backup",
            "created_at": now().astimezone().isoformat(timespec="seconds"),
            "dlms_version": app_version,
            "platform": sys.platform if platform is None else platform,
            "data_root_name": os.path.basename(os.path.normpath(app_data_dir)) or "DLMS",
            "file_count": len(inventory) + (1 if db_temp else 0),
            "total_uncompressed_bytes": total_bytes,
            "included_roots": included_roots,
            "excluded_runtime_paths": [".restore_operations/", "backups/", "uploads/", "content_pack_staging/", "static/logos/_temp/", "results.db-wal", "results.db-shm", "results.db-journal"],
            "summary": summary(),
        }

        with zipfile.ZipFile(temp_path, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            archive.writestr(backup_manifest, json.dumps(manifest, indent=2, ensure_ascii=False))
            for full, rel in inventory:
                archive.write(full, backup_data_prefix + rel)
            if db_temp:
                archive.write(db_temp, backup_data_prefix + "results.db")

        os.replace(temp_path, final_path)
        return final_path, manifest
    finally:
        if db_temp and os.path.exists(db_temp):
            try:
                os.remove(db_temp)
            except OSError:
                pass
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def safe_backup_member_name(name):
    raw = str(name or "").replace("\\", "/")
    if not raw or raw.startswith("/") or re.match(r"^[A-Za-z]:/", raw):
        raise ValueError("Backup contains an absolute or empty path")
    parts = [p for p in raw.split("/") if p not in {"", "."}]
    if not parts or any(p == ".." for p in parts):
        raise ValueError("Backup contains an unsafe relative path")
    return "/".join(parts)


def validate_dlms_backup(
    zip_path,
    *,
    backup_manifest,
    backup_data_prefix,
    backup_schema_version,
    max_files,
    max_uncompressed,
    max_compressed,
    max_single_file,
    max_compression_ratio,
    ratio_min_uncompressed,
    rel_is_excluded,
    safe_member_name=safe_backup_member_name,
):
    """Validate archive structure, CRCs, limits, and the DLMS backup manifest."""
    if not zipfile.is_zipfile(zip_path):
        raise ValueError("Selected file is not a valid ZIP archive")

    total_size = 0
    total_compressed = 0
    file_count = 0
    seen = set()
    data_members = []
    data_roots = {}

    with zipfile.ZipFile(zip_path, "r") as archive:
        manifest_member = None
        infos = archive.infolist()
        if len(infos) > max_files:
            raise ValueError(f"Backup contains more than {max_files} members")

        for info in infos:
            normalized = safe_member_name(info.filename)
            key = normalized.casefold()
            if key in seen:
                raise ValueError(f"Backup contains duplicate path: {normalized}")
            seen.add(key)

            unix_mode = (info.external_attr >> 16) & 0xFFFF
            unix_type = unix_mode & 0o170000
            if unix_type == 0o120000:
                raise ValueError(f"Backup contains a symbolic link: {normalized}")
            if unix_type not in {0, 0o040000, 0o100000}:
                raise ValueError(f"Backup contains an unsupported special file: {normalized}")
            if normalized.startswith(backup_data_prefix):
                rel = normalized[len(backup_data_prefix):]
                if rel:
                    root = rel.split("/", 1)[0]
                    root_key = root.casefold()
                    previous = data_roots.setdefault(root_key, root)
                    if previous != root:
                        raise ValueError(
                            "Backup contains case-colliding top-level roots: "
                            f"{previous} and {root}"
                        )
            if info.is_dir():
                continue

            file_count += 1
            uncompressed_size = int(info.file_size or 0)
            compressed_size = int(info.compress_size or 0)
            if uncompressed_size < 0 or compressed_size < 0:
                raise ValueError(f"Backup contains invalid member sizes: {normalized}")
            total_size += uncompressed_size
            total_compressed += compressed_size
            if file_count > max_files:
                raise ValueError(f"Backup contains more than {max_files} files")
            if compressed_size > max_compressed or total_compressed > max_compressed:
                raise ValueError("Backup compressed data exceeds the permitted restore safety limit")
            if uncompressed_size > max_single_file:
                raise ValueError(f"Backup contains an oversized single file: {normalized}")
            if total_size > max_uncompressed:
                raise ValueError("Backup expands beyond the permitted restore safety limit")
            if uncompressed_size >= ratio_min_uncompressed:
                if compressed_size == 0 or uncompressed_size / compressed_size > max_compression_ratio:
                    raise ValueError(f"Backup member has a suspicious compression ratio: {normalized}")

            if normalized == backup_manifest:
                manifest_member = info
                continue
            if not normalized.startswith(backup_data_prefix):
                raise ValueError(f"Unexpected file outside DLMS_DATA/: {normalized}")
            rel = normalized[len(backup_data_prefix):]
            if not rel:
                continue
            if rel_is_excluded(rel):
                raise ValueError(f"Backup attempts to restore a protected runtime path: {rel}")
            data_members.append((info, rel))

        if total_size >= ratio_min_uncompressed:
            if total_compressed == 0 or total_size / total_compressed > max_compression_ratio:
                raise ValueError("Backup has a suspicious overall compression ratio")

        if manifest_member is None:
            raise ValueError("Backup is missing DLMS_BACKUP_MANIFEST.json")

        # CRC validation decompresses archive members. It must remain after all
        # central-directory path, type, count, size, and expansion checks.
        try:
            bad_crc = archive.testzip()
        except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
            raise ValueError(f"Backup integrity check failed: {exc}") from exc
        if bad_crc:
            raise ValueError(f"Backup integrity check failed near {bad_crc}")

        try:
            manifest = json.loads(archive.read(manifest_member).decode("utf-8"))
        except Exception as exc:
            raise ValueError(f"Backup manifest is not valid JSON: {exc}") from exc

        if not isinstance(manifest, dict):
            raise ValueError("Backup manifest must be a JSON object")
        if manifest.get("kind") != "dlms-portable-backup":
            raise ValueError("This ZIP is not a DLMS portable backup")
        if int(manifest.get("schema_version", 0)) != backup_schema_version:
            raise ValueError(f"Unsupported backup schema_version {manifest.get('schema_version')!r}")

        declared_count = manifest.get("file_count")
        if isinstance(declared_count, int) and declared_count != len(data_members):
            raise ValueError("Backup manifest file count does not match archive contents")

    return {
        "manifest": manifest,
        "file_count": len(data_members),
        "uncompressed_bytes": sum(int(info.file_size or 0) for info, _ in data_members),
        "members": [(info.filename, rel) for info, rel in data_members],
    }


def extract_validated_backup(
    zip_path,
    target_root,
    report,
    *,
    backup_data_prefix,
    safe_member_name=safe_backup_member_name,
):
    os.makedirs(target_root, exist_ok=True)
    if os.listdir(target_root):
        raise ValueError("Restore staging directory is not empty")
    real_root = os.path.realpath(target_root)
    allowed = {name for name, _ in report.get("members", [])}
    with zipfile.ZipFile(zip_path, "r") as archive:
        for info in archive.infolist():
            if info.filename not in allowed or info.is_dir():
                continue
            normalized = safe_member_name(info.filename)
            rel = normalized[len(backup_data_prefix):]
            target = os.path.realpath(os.path.join(target_root, rel))
            if target != real_root and not target.startswith(real_root + os.sep):
                raise ValueError("Backup extraction path escapes the restore staging directory")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with archive.open(info, "r") as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)


def validate_restored_sqlite(
    path,
    relative_path="results.db",
    *,
    core_db_schema,
    sqlite_module=sqlite3,
):
    """Validate a restored DLMS database without running writable migrations."""
    try:
        uri = Path(os.path.abspath(path)).as_uri() + "?mode=ro"
        conn = sqlite_module.connect(uri, uri=True)
    except sqlite_module.Error as exc:
        raise ValueError(f"{relative_path} is not a readable SQLite database") from exc
    try:
        integrity_rows = conn.execute("PRAGMA integrity_check").fetchall()
        if integrity_rows != [("ok",)]:
            detail = str(integrity_rows[0][0]) if integrity_rows else "no result"
            raise ValueError(f"{relative_path} failed SQLite integrity_check: {detail[:160]}")
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()}
        for table, required_columns in core_db_schema.items():
            if table not in tables:
                raise ValueError(f"{relative_path} is missing required table {table}")
            columns = {row[1] for row in conn.execute(
                f'PRAGMA table_info("{table}")'
            ).fetchall()}
            missing = sorted(required_columns - columns)
            if missing:
                raise ValueError(
                    f"{relative_path} table {table} is missing required column(s): {', '.join(missing)}"
                )
    except sqlite_module.DatabaseError as exc:
        raise ValueError(f"{relative_path} is corrupt or not a DLMS SQLite database") from exc
    finally:
        conn.close()
    return {"path": relative_path, "integrity": "ok", "schema": "compatible"}


def validate_restored_json(
    path,
    relative_path,
    *,
    critical_json_types,
    raster_image_formats,
    canonical_law_case_id,
):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{relative_path} is not valid JSON") from exc

    normalized = relative_path.replace("\\", "/")
    expected_type = critical_json_types.get(normalized)
    if expected_type is not None and not isinstance(value, expected_type):
        kind = "object" if expected_type is dict else "list"
        raise ValueError(f"{relative_path} must contain a JSON {kind}")
    if normalized == "config/portal.json" and isinstance(value, dict):
        for key in ("title", "theme", "background_image"):
            if key in value and value[key] is not None and not isinstance(value[key], str):
                raise ValueError(f"config/portal.json field {key} has an incompatible value")
        background = value.get("background_image")
        if background and (
            os.path.basename(background) != background
            or os.path.splitext(background)[1].lower() not in raster_image_formats
        ):
            raise ValueError("config/portal.json background_image is not a safe raster filename")
    elif normalized == "config/quizzes.json" and isinstance(value, list):
        if any(not isinstance(item, dict) for item in value):
            raise ValueError("config/quizzes.json entries must be objects")
        for item in value:
            for key in ("title", "html", "logo", "folder"):
                if key in item and item[key] is not None and not isinstance(item[key], str):
                    raise ValueError(f"config/quizzes.json field {key} has an incompatible value")
            quiz_html = item.get("html")
            if quiz_html and (os.path.basename(quiz_html) != quiz_html or not quiz_html.lower().endswith(".html")):
                raise ValueError("config/quizzes.json contains an unsafe quiz HTML filename")
            logo = item.get("logo")
            if logo and (
                os.path.basename(logo) != logo
                or os.path.splitext(logo)[1].lower() not in raster_image_formats
            ):
                raise ValueError("config/quizzes.json contains an unsafe logo filename")
    elif normalized == "config/law.json" and isinstance(value, dict):
        for key in ("cases", "folders"):
            if key in value and not isinstance(value[key], list):
                raise ValueError(f"config/law.json field {key} must be a list")
        seen_case_ids = set()
        for case in value.get("cases", []):
            if not isinstance(case, dict):
                raise ValueError("config/law.json case entries must be objects")
            case_id = case.get("id")
            if canonical_law_case_id(case_id) != case_id:
                raise ValueError("config/law.json contains a noncanonical Law case ID")
            if case_id in seen_case_ids:
                raise ValueError("config/law.json contains a duplicate Law case ID")
            seen_case_ids.add(case_id)
    elif normalized.startswith("law/cases/") and normalized.endswith(".json"):
        if not isinstance(value, dict):
            raise ValueError(f"{relative_path} must contain a JSON object")
        case_id = value.get("id")
        if canonical_law_case_id(case_id) != case_id:
            raise ValueError(f"{relative_path} contains a noncanonical Law case ID")
    return value


def validate_restored_law_imports(
    staged_data_root,
    *,
    canonical_law_import_filename,
):
    """Require restored raw Law imports to be canonical top-level files."""
    imports_root = os.path.join(staged_data_root, "law", "imports")
    if not os.path.lexists(imports_root):
        return []
    if os.path.islink(imports_root) or not os.path.isdir(imports_root):
        raise ValueError("Restored Law imports path is not a safe directory")

    validated = []
    with os.scandir(imports_root) as entries:
        for entry in entries:
            relative_path = f"law/imports/{entry.name}"
            if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                raise ValueError(
                    "Restored Law imports must contain only top-level files"
                )
            if canonical_law_import_filename(entry.name) != entry.name:
                raise ValueError(
                    f"Restored Law import has a noncanonical filename: {relative_path}"
                )
            validated.append(relative_path)
    return sorted(validated, key=str.casefold)


def validate_restored_browser_data(
    staged_data_root,
    *,
    browser_served_data_extensions,
):
    """Allow only the runtime JSON and parser logs served beneath /data."""
    data_root = os.path.join(staged_data_root, "data")
    if not os.path.lexists(data_root):
        return []
    if os.path.islink(data_root) or not os.path.isdir(data_root):
        raise ValueError("Restored browser data path is not a safe directory")

    validated = []
    for current_root, _dirs, filenames in os.walk(data_root, followlinks=False):
        for filename in filenames:
            path = os.path.join(current_root, filename)
            relative_path = os.path.relpath(path, staged_data_root).replace("\\", "/")
            extension = os.path.splitext(filename)[1].lower()
            if extension not in browser_served_data_extensions:
                allowed = ", ".join(sorted(browser_served_data_extensions))
                raise ValueError(
                    f"Unsafe restored browser-served file {relative_path}: "
                    f"only {allowed} files are supported beneath data/"
                )
            validated.append(relative_path)
    return sorted(validated, key=str.casefold)


def normalize_restored_portal_custom_ai_url(
    staged_data_root,
    *,
    validate_restored_json,
    validate_custom_ai_url,
    atomic_write_json,
):
    """Clear an unsafe optional AI URL without rejecting an otherwise safe backup."""
    portal_path = os.path.join(staged_data_root, "config", "portal.json")
    if not os.path.exists(portal_path):
        return {"status": "absent"}
    portal = validate_restored_json(portal_path, "config/portal.json")
    if "ai_custom_url" not in portal:
        return {"status": "absent"}

    raw_url = portal.get("ai_custom_url")
    try:
        safe_url = validate_custom_ai_url(raw_url)
        status = "valid"
    except ValueError:
        safe_url = ""
        status = "normalized"

    if raw_url != safe_url:
        status = "normalized"
        portal["ai_custom_url"] = safe_url
        atomic_write_json(portal_path, portal, indent=4, expected_type=dict)
    return {"status": status}


def validate_restored_assets(
    staged_data_root,
    *,
    raster_image_formats,
    passive_pack_image_extensions,
    decode_raster_image,
    validate_staged_content_pack,
):
    validated = []
    for relative_root, extensions in [
        ("static/bg", raster_image_formats),
        ("static/logos", raster_image_formats),
        ("quiz_assets", passive_pack_image_extensions),
        ("image_builder_drafts", passive_pack_image_extensions),
    ]:
        root = os.path.join(staged_data_root, *relative_root.split("/"))
        if not os.path.isdir(root):
            continue
        for current_root, dirs, filenames in os.walk(root, followlinks=False):
            dirs[:] = [name for name in dirs if name != "_temp"]
            for filename in filenames:
                path = os.path.join(current_root, filename)
                relative_path = os.path.relpath(path, staged_data_root).replace("\\", "/")
                try:
                    decode_raster_image(path, extensions)
                except ValueError as exc:
                    raise ValueError(f"Unsafe restored image asset {relative_path}: {exc}") from exc
                validated.append(relative_path)

    packs_root = os.path.join(staged_data_root, "content_packs")
    if os.path.isdir(packs_root):
        for name in sorted(os.listdir(packs_root), key=str.casefold):
            pack_root = os.path.join(packs_root, name)
            if not os.path.isdir(pack_root):
                raise ValueError(f"Content Pack entry {name} is not a directory")
            result = validate_staged_content_pack(pack_root)
            if not result.get("valid"):
                details = "; ".join(result.get("errors") or ["invalid Content Pack"])
                raise ValueError(f"Restored Content Pack {name} is invalid: {details}")
    return validated


def validate_backup_manifest_semantics(
    manifest,
    staged_data_root,
    *,
    backup_schema_version,
):
    if not isinstance(manifest, dict):
        raise ValueError("Backup manifest must be a JSON object")
    if manifest.get("kind") != "dlms-portable-backup":
        raise ValueError("Backup manifest kind is incompatible with DLMS")
    schema_version = manifest.get("schema_version")
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != backup_schema_version
    ):
        raise ValueError(f"Unsupported backup schema_version {manifest.get('schema_version')!r}")
    for field, expected in (("created_at", str), ("dlms_version", str), ("included_roots", list), ("summary", dict)):
        if field in manifest and not isinstance(manifest[field], expected):
            raise ValueError(f"Backup manifest field {field} has an incompatible value")
    if (
        "file_count" not in manifest
        or not isinstance(manifest["file_count"], int)
        or isinstance(manifest["file_count"], bool)
        or manifest["file_count"] < 0
    ):
        raise ValueError("Backup manifest file_count is missing or invalid")
    if isinstance(manifest.get("included_roots"), list):
        declared = manifest["included_roots"]
        if any(not isinstance(item, str) or not item or "/" in item or "\\" in item for item in declared):
            raise ValueError("Backup manifest included_roots contains an invalid root")
        actual = sorted(os.listdir(staged_data_root), key=str.casefold)
        declared_keys = [item.casefold() for item in declared]
        actual_keys = [item.casefold() for item in actual]
        if len(declared_keys) != len(set(declared_keys)):
            raise ValueError("Backup manifest included_roots contains duplicate roots")
        if len(actual_keys) != len(set(actual_keys)):
            raise ValueError("Restored data contains case-colliding top-level roots")
        if set(declared_keys) != set(actual_keys):
            raise ValueError("Backup manifest included_roots does not match restored data")


def validate_staged_backup_semantics(
    staged_data_root,
    manifest,
    *,
    validate_manifest_semantics,
    validate_restored_sqlite,
    validate_restored_json,
    validate_restored_browser_data,
    normalize_restored_portal_custom_ai_url,
    validate_restored_assets,
    validate_restored_law_imports,
):
    """Validate extracted backup data completely before any live-data mutation."""
    if not os.path.isdir(staged_data_root):
        raise ValueError("Backup staging data is missing")
    validate_manifest_semantics(manifest, staged_data_root)

    json_files = []
    sqlite_files = []
    for current_root, dirs, filenames in os.walk(staged_data_root, followlinks=False):
        for dirname in dirs:
            if os.path.islink(os.path.join(current_root, dirname)):
                raise ValueError("Backup staging contains an unexpected symbolic link")
        for filename in filenames:
            path = os.path.join(current_root, filename)
            relative_path = os.path.relpath(path, staged_data_root).replace("\\", "/")
            if os.path.islink(path):
                raise ValueError(f"Backup staging contains an unexpected symbolic link: {relative_path}")
            extension = os.path.splitext(filename)[1].lower()
            if extension in {".db", ".sqlite", ".sqlite3"}:
                sqlite_files.append(validate_restored_sqlite(path, relative_path))
            elif extension == ".json":
                validate_restored_json(path, relative_path)
                json_files.append(relative_path)

    if not any(item["path"] == "results.db" for item in sqlite_files):
        raise ValueError("Backup is missing required DLMS database results.db")

    browser_data = validate_restored_browser_data(staged_data_root)
    portal_config = normalize_restored_portal_custom_ai_url(staged_data_root)
    assets = validate_restored_assets(staged_data_root)
    law_imports = validate_restored_law_imports(staged_data_root)
    return {
        "status": "valid",
        "sqlite": sqlite_files,
        "json_files": json_files,
        "browser_data": browser_data,
        "portal_config": portal_config,
        "assets": assets,
        "law_imports": law_imports,
        "compatibility": "schema-version-1; optional descriptive manifest fields may be absent",
    }


def restore_staging_dir(token, *, token_pattern, restore_staging_folder):
    if not token_pattern.fullmatch(str(token or "")):
        raise ValueError("Invalid restore token")
    return os.path.join(restore_staging_folder, token)


def create_backup_restore_stage(stage_dir):
    os.makedirs(stage_dir, exist_ok=False)


def stage_backup_restore(
    upload,
    token,
    *,
    stage_dir,
    upload_max_bytes,
    bounded_save_upload,
    validate_backup,
    extract_backup,
    validate_semantics,
    atomic_write_json,
    staging_state_filename,
    staging_marker,
    staging_version,
    now=datetime.now,
):
    """Validate one uploaded archive entirely inside a helper-owned stage."""
    upload_path = os.path.join(stage_dir, "restore.zip")
    try:
        bounded_save_upload(upload, upload_path, upload_max_bytes, "Backup ZIP")
        report = validate_backup(upload_path)
        semantic_root = os.path.join(stage_dir, "semantic_check")
        extract_backup(upload_path, semantic_root, report)
        try:
            semantic_result = validate_semantics(semantic_root, report["manifest"])
        finally:
            shutil.rmtree(semantic_root, ignore_errors=True)
        with open(os.path.join(stage_dir, "report.json"), "w", encoding="utf-8") as handle:
            saved_report = {key: value for key, value in report.items() if key != "members"}
            saved_report["semantic_validation"] = semantic_result
            json.dump(saved_report, handle, indent=2)
        atomic_write_json(
            os.path.join(stage_dir, staging_state_filename),
            {
                "marker": staging_marker,
                "schema_version": staging_version,
                "token": token,
                "created_at": now().astimezone().isoformat(timespec="seconds"),
            },
            expected_type=dict,
        )
    except Exception:
        shutil.rmtree(stage_dir, ignore_errors=True)
        raise
    return report, semantic_result

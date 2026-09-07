"""Atomic quiz publication, rollback, and crash-reconciliation services."""

import copy
import json
import os
import re
import secrets
import shutil
from datetime import datetime


QUIZ_PUBLICATION_JOURNAL_MARKER = "dlms-quiz-publication"
QUIZ_PUBLICATION_JOURNAL_VERSION = 1
QUIZ_PUBLICATION_STATES = {
    "staging",
    "db_commit_pending",
    "db_committed",
    "artifacts_promoted",
    "registry_published",
    "complete",
    "rollback_pending",
}
QUIZ_PUBLICATION_ID_RE = re.compile(r"^[0-9a-f]{32}$")
QUIZ_PUBLICATION_ARTIFACT_RE = re.compile(
    r"^[a-z0-9_]+_[0-9]{10,}_[0-9a-f]{8}\.(?:json|html)$"
)
QUIZ_PUBLICATION_LOGO_RE = re.compile(
    r"^logo_[0-9]+_[0-9a-f]{8}\.(?:png|jpe?g|webp)$"
)


def quiz_publication_staging_root(app_data_dir, *, join_path=os.path.join):
    return join_path(app_data_dir, ".quiz_publications")


def fsync_quiz_publication_directory(
    path,
    *,
    open_descriptor=os.open,
    fsync=os.fsync,
    close_descriptor=os.close,
    read_only_flag=os.O_RDONLY,
):
    """Best-effort directory durability for journal create/replace/remove."""
    descriptor = None
    try:
        descriptor = open_descriptor(path, read_only_flag)
        fsync(descriptor)
    except OSError:
        # Some supported platforms do not allow opening/fsyncing directories.
        pass
    finally:
        if descriptor is not None:
            close_descriptor(descriptor)


def write_quiz_publication_journal(
    path,
    journal,
    *,
    fsync_directory,
    open_file=open,
    json_module=json,
    fsync=os.fsync,
    replace_file=os.replace,
    dirname=os.path.dirname,
):
    """Atomically and durably replace one helper-owned publication journal."""
    temp_path = path + ".tmp"
    with open_file(temp_path, "w", encoding="utf-8") as handle:
        json_module.dump(journal, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
        handle.flush()
        fsync(handle.fileno())
    with open_file(temp_path, "r", encoding="utf-8") as handle:
        validated = json_module.load(handle)
    if not isinstance(validated, dict):
        raise ValueError("Quiz publication journal must contain an object")
    replace_file(temp_path, path)
    fsync_directory(dirname(path))


def update_quiz_publication_journal(
    path,
    journal,
    *,
    state=None,
    states=QUIZ_PUBLICATION_STATES,
    write_journal,
    now=datetime.now,
):
    if state is not None:
        if state not in states:
            raise ValueError(f"Unsupported quiz publication state: {state}")
        journal["state"] = state
    journal["updated_at"] = now().astimezone().isoformat(timespec="seconds")
    write_journal(path, journal)


def remove_quiz_publication_journal(
    path,
    *,
    fsync_directory,
    lexists=os.path.lexists,
    islink=os.path.islink,
    remove_file=os.remove,
    dirname=os.path.dirname,
    print_message=print,
):
    try:
        if lexists(path):
            if islink(path):
                return False
            remove_file(path)
            fsync_directory(dirname(path))
        temp_path = path + ".tmp"
        if lexists(temp_path) and not islink(temp_path):
            remove_file(temp_path)
            fsync_directory(dirname(path))
        return True
    except Exception as exc:
        print_message(f"[QUIZ PUBLICATION JOURNAL CLEANUP ERROR] {path}: {exc}")
        return False


def quiz_publication_checkpoint(_stage, _journal):
    """No-op durable-boundary hook used by crash-simulation tests."""
    return None


def commit_quiz_publication(conn):
    """Commit boundary kept separate for deterministic fault-injection tests."""
    conn.commit()


def promote_quiz_artifact(
    staged_path,
    final_path,
    *,
    makedirs=os.makedirs,
    dirname=os.path.dirname,
    lexists=os.path.lexists,
    replace_file=os.replace,
):
    """Atomically promote a helper-owned staged file or directory."""
    makedirs(dirname(final_path), exist_ok=True)
    if lexists(final_path):
        raise FileExistsError(f"Quiz publication target already exists: {final_path}")
    replace_file(staged_path, final_path)


def remove_quiz_publication_path(
    path,
    *,
    isdir=os.path.isdir,
    islink=os.path.islink,
    remove_tree=shutil.rmtree,
    lexists=os.path.lexists,
    remove_file=os.remove,
    print_message=print,
):
    """Best-effort removal limited to one explicitly owned publication path."""
    try:
        if isdir(path) and not islink(path):
            remove_tree(path)
        elif lexists(path):
            if islink(path):
                return False
            remove_file(path)
        return True
    except Exception as exc:
        print_message(f"[QUIZ PUBLICATION CLEANUP ERROR] {path}: {exc}")
        return False


def delete_published_quiz_rows(quiz_id, *, get_db):
    """Compensate for a committed publication without touching files or logos."""
    conn = get_db()
    try:
        conn.execute("DELETE FROM quizzes WHERE id = ?", (quiz_id,))
        conn.commit()
    finally:
        conn.close()


def remove_exact_quiz_registry_entry(
    quiz_id,
    html_name,
    *,
    registry_lock,
    load_registry,
    save_registry,
):
    """Remove only registry rows matching both recorded publication keys."""
    with registry_lock:
        registry = load_registry()
        kept = []
        removed = False
        for entry in registry:
            same_id = str(entry.get("id")) == str(quiz_id)
            same_html = entry.get("html") == html_name
            if same_id and same_html:
                removed = True
                continue
            kept.append(entry)
        if removed:
            save_registry(kept)
    return True


def safe_quiz_publication_name(
    value,
    *,
    label,
    pattern=None,
    isabs=os.path.isabs,
    basename=os.path.basename,
):
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    if isabs(value) or value != basename(value):
        raise ValueError(f"{label} must be one safe filename")
    if "/" in value or "\\" in value or value in {".", ".."}:
        raise ValueError(f"{label} contains an unsafe path")
    if pattern is not None and not pattern.fullmatch(value):
        raise ValueError(f"{label} does not match a DLMS publication name")
    return value


def safe_quiz_publication_target(
    root,
    name,
    *,
    label,
    app_data_dir,
    canonical_data_root,
    is_same_path_or_ancestor,
    abspath=os.path.abspath,
    realpath=os.path.realpath,
    lexists=os.path.lexists,
    islink=os.path.islink,
    join_path=os.path.join,
    dirname=os.path.dirname,
):
    app_root = canonical_data_root(app_data_dir)
    root_path = abspath(root)
    root_real = realpath(root_path)
    if not is_same_path_or_ancestor(app_root, root_real):
        raise ValueError(f"{label} root escapes the DLMS application-data directory")
    if lexists(root_path) and islink(root_path):
        raise ValueError(f"{label} root must not be a symlink")
    target = join_path(root_path, name)
    if lexists(target) and islink(target):
        raise ValueError(f"{label} must not be a symlink")
    parent_real = realpath(dirname(target))
    if parent_real != root_real:
        raise ValueError(f"{label} parent escapes its expected directory")
    return target


def validate_quiz_publication_journal(
    journal,
    journal_path,
    *,
    staging_root,
    data_folder,
    quiz_folder,
    quiz_asset_folder,
    logo_folder,
    safe_name,
    safe_target,
    journal_marker=QUIZ_PUBLICATION_JOURNAL_MARKER,
    journal_version=QUIZ_PUBLICATION_JOURNAL_VERSION,
    states=QUIZ_PUBLICATION_STATES,
    publication_id_re=QUIZ_PUBLICATION_ID_RE,
    artifact_re=QUIZ_PUBLICATION_ARTIFACT_RE,
    logo_re=QUIZ_PUBLICATION_LOGO_RE,
    basename=os.path.basename,
    splitext=os.path.splitext,
):
    """Validate an untrusted local journal before deriving destructive paths."""
    if not isinstance(journal, dict):
        raise ValueError("journal must contain an object")
    if journal.get("marker") != journal_marker:
        raise ValueError("unsupported publication journal marker")
    if journal.get("schema_version") != journal_version:
        raise ValueError("unsupported publication journal version")
    publication_id = journal.get("publication_id")
    if not isinstance(publication_id, str) or not publication_id_re.fullmatch(publication_id):
        raise ValueError("invalid publication ID")
    expected_names = {
        f"publication_{publication_id}.json",
        f"publication_{publication_id}.json.tmp",
    }
    if basename(journal_path) not in expected_names:
        raise ValueError("journal filename does not match its publication ID")
    if journal.get("state") not in states:
        raise ValueError("unsupported publication state")

    stage_name = safe_name(journal.get("stage_dir"), label="staging directory")
    if stage_name != f"publish_{publication_id}":
        raise ValueError("staging directory does not match its publication ID")

    artifacts = journal.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ValueError("journal artifacts must contain an object")
    json_record = artifacts.get("json")
    html_record = artifacts.get("html")
    asset_record = artifacts.get("assets")
    if not all(isinstance(item, dict) for item in (json_record, html_record, asset_record)):
        raise ValueError("journal artifact records are malformed")
    json_name = safe_name(
        json_record.get("name"), label="JSON artifact", pattern=artifact_re
    )
    html_name = safe_name(
        html_record.get("name"), label="HTML artifact", pattern=artifact_re
    )
    if not json_name.endswith(".json") or not html_name.endswith(".html"):
        raise ValueError("journal artifact extensions are invalid")
    if splitext(json_name)[0] != splitext(html_name)[0]:
        raise ValueError("journal JSON and HTML names do not share one publication identity")
    asset_name = safe_name(asset_record.get("name"), label="asset bucket")
    if asset_name != splitext(html_name)[0]:
        raise ValueError("journal asset bucket does not match its publication identity")
    for label, record in (
        ("JSON artifact", json_record),
        ("HTML artifact", html_record),
        ("asset bucket", asset_record),
    ):
        if not isinstance(record.get("attempted"), bool) or not isinstance(record.get("promoted"), bool):
            raise ValueError(f"{label} promotion flags must be boolean")
        if record["promoted"] and not record["attempted"]:
            raise ValueError(f"{label} cannot be promoted without an attempt")
    if not isinstance(asset_record.get("required"), bool):
        raise ValueError("asset bucket required flag must be boolean")

    quiz = journal.get("quiz")
    if not isinstance(quiz, dict):
        raise ValueError("journal quiz record is malformed")
    quiz_id = quiz.get("id")
    if quiz_id is not None and (isinstance(quiz_id, bool) or not isinstance(quiz_id, int) or quiz_id < 1):
        raise ValueError("journal quiz ID must be a positive integer")
    source_file = quiz.get("source_file")
    if not isinstance(source_file, str) or not source_file or len(source_file) > 512:
        raise ValueError("journal quiz source file is invalid")

    registry = journal.get("registry")
    if not isinstance(registry, dict) or registry.get("html") != html_name:
        raise ValueError("journal registry key is invalid")
    if not isinstance(registry.get("attempted"), bool) or not isinstance(registry.get("published"), bool):
        raise ValueError("journal registry flags must be boolean")
    if registry["published"] and not registry["attempted"]:
        raise ValueError("registry cannot be published without an attempt")

    state = journal["state"]
    db_states = {
        "db_commit_pending", "db_committed", "artifacts_promoted",
        "registry_published", "complete",
    }
    if state in db_states and quiz_id is None:
        raise ValueError(f"publication state {state} requires a quiz ID")
    if state in {"staging", "db_commit_pending"}:
        if any(record["attempted"] for record in (json_record, html_record, asset_record)):
            raise ValueError(f"publication state {state} cannot contain artifact promotion attempts")
        if registry["attempted"]:
            raise ValueError(f"publication state {state} cannot contain a registry attempt")
    if state in {"artifacts_promoted", "registry_published", "complete"}:
        if not json_record["promoted"] or not html_record["promoted"]:
            raise ValueError(f"publication state {state} requires promoted JSON and HTML")
        if asset_record["required"] and not asset_record["promoted"]:
            raise ValueError(f"publication state {state} requires its promoted asset bucket")
    if state in {"registry_published", "complete"} and not registry["published"]:
        raise ValueError(f"publication state {state} requires a published registry entry")

    owned_logo = journal.get("owned_logo")
    if owned_logo is not None:
        safe_name(owned_logo, label="publication-owned logo", pattern=logo_re)

    paths = {
        "stage": safe_target(staging_root(), stage_name, label="staging directory"),
        "json": safe_target(data_folder, json_name, label="JSON artifact"),
        "html": safe_target(quiz_folder, html_name, label="HTML artifact"),
        "assets": safe_target(quiz_asset_folder, asset_name, label="asset bucket"),
    }
    if owned_logo:
        paths["logo"] = safe_target(
            logo_folder, owned_logo, label="publication-owned logo"
        )
    return paths


def quiz_publication_db_status(journal, *, get_db):
    quiz_id = journal["quiz"]["id"]
    if quiz_id is None:
        return "missing"
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT source_file FROM quizzes WHERE id = ?", (quiz_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return "missing"
    return "match" if row["source_file"] == journal["quiz"]["source_file"] else "conflict"


def quiz_publication_registry_status(journal, *, load_registry):
    quiz_id = journal["quiz"]["id"]
    html_name = journal["registry"]["html"]
    exact = False
    conflict = False
    for entry in load_registry():
        same_id = quiz_id is not None and str(entry.get("id")) == str(quiz_id)
        same_html = entry.get("html") == html_name
        if same_id and same_html:
            exact = True
        elif same_id or same_html:
            conflict = True
    if conflict:
        return "conflict"
    return "exact" if exact else "missing"


def quiz_publication_artifacts_valid(
    journal,
    paths,
    *,
    open_file=open,
    json_module=json,
    isfile=os.path.isfile,
    getsize=os.path.getsize,
    isdir=os.path.isdir,
    islink=os.path.islink,
):
    try:
        with open_file(paths["json"], "r", encoding="utf-8") as handle:
            if not isinstance(json_module.load(handle), list):
                return False
        if not isfile(paths["html"]) or getsize(paths["html"]) == 0:
            return False
        if journal["artifacts"]["assets"]["required"]:
            if not isdir(paths["assets"]) or islink(paths["assets"]):
                return False
        return True
    except (OSError, UnicodeError, json_module.JSONDecodeError):
        return False


def delete_recorded_quiz_rows(journal, *, get_db):
    quiz_id = journal["quiz"]["id"]
    if quiz_id is None:
        return True
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT source_file FROM quizzes WHERE id = ?", (quiz_id,)
        ).fetchone()
        if row is None:
            return True
        if row["source_file"] != journal["quiz"]["source_file"]:
            return False
        conn.execute("DELETE FROM quizzes WHERE id = ?", (quiz_id,))
        conn.commit()
        return True
    finally:
        conn.close()


def rollback_recorded_quiz_publication(
    journal,
    paths,
    *,
    db_status,
    registry_status,
    remove_registry_entry,
    remove_path,
    delete_rows,
):
    """Idempotently remove only state explicitly owned by one valid journal."""
    current_db_status = db_status(journal)
    current_registry_status = registry_status(journal)
    if current_db_status == "conflict" or current_registry_status == "conflict":
        return False
    if current_registry_status == "exact":
        remove_registry_entry(
            journal["quiz"]["id"], journal["registry"]["html"]
        )

    success = True
    for key in ("assets", "html", "json"):
        record = journal["artifacts"][key]
        if record["attempted"] or record["promoted"]:
            success = remove_path(paths[key]) and success
    success = delete_rows(journal) and success
    if "logo" in paths:
        success = remove_path(paths["logo"]) and success
    success = remove_path(paths["stage"]) and success
    return success


def reconcile_quiz_publication_journal(
    journal_path,
    *,
    validate_journal,
    db_status,
    registry_status,
    artifacts_valid,
    remove_path,
    remove_journal,
    update_journal,
    rollback_publication,
    open_file=open,
    json_module=json,
    islink=os.path.islink,
    print_message=print,
):
    if islink(journal_path):
        raise ValueError("publication journal must not be a symlink")
    with open_file(journal_path, "r", encoding="utf-8") as handle:
        journal = json_module.load(handle)
    paths = validate_journal(journal, journal_path)
    current_db_status = db_status(journal)
    current_registry_status = registry_status(journal)

    if current_registry_status == "conflict" or current_db_status == "conflict":
        raise ValueError("publication journal conflicts with existing DB or registry state")

    if (
        current_registry_status == "exact"
        and current_db_status == "match"
        and artifacts_valid(journal, paths)
    ):
        if not remove_path(paths["stage"]):
            return "failed"
        if not remove_journal(journal_path.removesuffix(".tmp")):
            return "failed"
        return "preserved"

    try:
        update_journal(
            journal_path.removesuffix(".tmp"), journal, state="rollback_pending"
        )
        journal_path = journal_path.removesuffix(".tmp")
    except Exception as exc:
        print_message(
            f"[QUIZ PUBLICATION RECOVERY ERROR] could not mark rollback pending: {exc}"
        )
        return "failed"
    if not rollback_publication(journal, paths):
        return "failed"
    if not remove_journal(journal_path):
        return "failed"
    return "rolled_back"


def reconcile_quiz_publications(
    *,
    app_data_dir,
    read_data_root_marker,
    staging_root,
    is_same_path_or_ancestor,
    canonical_data_root,
    reconcile_journal,
    remove_journal,
    exists=os.path.exists,
    realpath=os.path.realpath,
    islink=os.path.islink,
    listdir=os.listdir,
    join_path=os.path.join,
    print_message=print,
):
    """Reconcile only validated helper-owned journals beneath the owned data root."""
    report = {"processed": 0, "preserved": 0, "rolled_back": 0, "unsafe": 0, "failed": 0}
    if read_data_root_marker(app_data_dir) is None:
        print_message("[QUIZ PUBLICATION RECOVERY] skipped: application-data ownership is not verified")
        return report
    root = staging_root()
    if not exists(root):
        return report
    try:
        root_real = realpath(root)
        if islink(root) or not is_same_path_or_ancestor(canonical_data_root(app_data_dir), root_real):
            raise ValueError("publication journal root is unsafe")
        names = sorted(listdir(root))
    except Exception as exc:
        print_message(f"[QUIZ PUBLICATION RECOVERY] unsafe journal root: {exc}")
        report["unsafe"] += 1
        return report

    grouped = {}
    journal_name_re = re.compile(r"^publication_([0-9a-f]{32})\.json(?:\.tmp)?$")
    for name in names:
        match = journal_name_re.fullmatch(name)
        if match:
            grouped.setdefault(match.group(1), []).append(name)
    for publication_id, candidates in grouped.items():
        canonical = f"publication_{publication_id}.json"
        selected = canonical if canonical in candidates else f"{canonical}.tmp"
        journal_path = join_path(root, selected)
        report["processed"] += 1
        try:
            outcome = reconcile_journal(journal_path)
            if outcome in report:
                report[outcome] += 1
            else:
                report["failed"] += 1
            if outcome in {"preserved", "rolled_back"}:
                remove_journal(join_path(root, canonical))
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            report["unsafe"] += 1
            print_message(
                f"[QUIZ PUBLICATION RECOVERY] left {selected} for inspection: {exc}"
            )
        except Exception as exc:
            report["failed"] += 1
            print_message(
                f"[QUIZ PUBLICATION RECOVERY] retry required for {selected}: "
                f"{type(exc).__name__}: {exc}"
            )
    if report["processed"] or report["unsafe"] or report["failed"]:
        print_message(
            "[QUIZ PUBLICATION RECOVERY] "
            f"processed={report['processed']} preserved={report['preserved']} "
            f"rolled_back={report['rolled_back']} unsafe={report['unsafe']} "
            f"failed={report['failed']}"
        )
    return report


def normalize_quiz_question_ordinals(runtime_questions, db_questions):
    """Return publication copies with one deterministic 1-based identity.

    Source documents may number questions from an arbitrary starting point or
    repeat a number. Runtime attempts use list position, so publication owns a
    canonical ordinal while retaining a meaningful positive source number as
    metadata when it differs.
    """
    if len(runtime_questions) != len(db_questions):
        raise ValueError("Runtime and database question lists must have the same length")

    runtime_payload = copy.deepcopy(runtime_questions)
    db_payload = runtime_payload if db_questions is runtime_questions else copy.deepcopy(db_questions)

    for ordinal, (runtime_question, db_question) in enumerate(
        zip(runtime_payload, db_payload), start=1
    ):
        if not isinstance(runtime_question, dict) or not isinstance(db_question, dict):
            raise ValueError(f"Question {ordinal} must be an object")
        for question in (runtime_question, db_question):
            original = question.get("number")
            if (
                not isinstance(original, bool)
                and isinstance(original, int)
                and original > 0
                and original != ordinal
            ):
                question.setdefault("source_number", original)
            question["number"] = ordinal

    return runtime_payload, db_payload


def publish_quiz(
    quiz_title,
    runtime_questions,
    db_questions=None,
    *,
    filename_prefix="quiz",
    exam_minutes=90,
    logo_filename=None,
    source_file=None,
    source_pack_id=None,
    source_dataset_id=None,
    snapshot_existing_assets=False,
    rollback_logo_filename=None,
    generated_artifact_names,
    staging_root,
    normalize_ordinals,
    write_journal,
    remove_journal,
    fsync_directory,
    checkpoint,
    snapshot_runtime_questions,
    snapshot_existing_quiz_asset_refs,
    write_staged_quiz_json,
    get_db,
    insert_quiz_rows,
    update_journal,
    build_quiz_html,
    get_portal_title,
    normalize_exam_minutes,
    commit_publication,
    promote_artifact,
    add_quiz_to_registry,
    remove_path,
    remove_registry_entry,
    delete_recorded_rows,
    data_folder,
    quiz_folder,
    quiz_asset_folder,
    logo_folder,
    logo_re=QUIZ_PUBLICATION_LOGO_RE,
    token_hex=secrets.token_hex,
    splitext=os.path.splitext,
    makedirs=os.makedirs,
    mkdir=os.mkdir,
    join_path=os.path.join,
    isdir=os.path.isdir,
    isfile=os.path.isfile,
    getsize=os.path.getsize,
    basename=os.path.basename,
    now=datetime.now,
    print_message=print,
):
    """Stage and publish one quiz with handled rollback and crash recovery."""
    if not runtime_questions:
        raise ValueError("No usable questions were produced")
    db_questions = runtime_questions if db_questions is None else db_questions
    if not db_questions:
        raise ValueError("No database questions were produced")
    runtime_questions, db_questions = normalize_ordinals(
        runtime_questions, db_questions
    )

    html_name, json_name = generated_artifact_names(filename_prefix)
    asset_bucket = re.sub(r"[^A-Za-z0-9_.-]+", "_", splitext(html_name)[0])[:120]
    publication_staging_root = staging_root()
    makedirs(publication_staging_root, exist_ok=True)
    publication_id = token_hex(16)
    stage_name = f"publish_{publication_id}"
    stage_dir = join_path(publication_staging_root, stage_name)
    journal_path = join_path(
        publication_staging_root, f"publication_{publication_id}.json"
    )
    staged_json = join_path(stage_dir, json_name)
    staged_html = join_path(stage_dir, html_name)
    staged_assets = join_path(stage_dir, "assets")
    final_json = join_path(data_folder, json_name)
    final_html = join_path(quiz_folder, html_name)
    final_assets = join_path(quiz_asset_folder, asset_bucket)
    conn = None
    quiz_id = None
    effective_source_file = source_file or html_name
    owned_logo = None
    if (
        rollback_logo_filename
        and rollback_logo_filename == logo_filename
        and isinstance(rollback_logo_filename, str)
        and logo_re.fullmatch(rollback_logo_filename)
    ):
        owned_logo = rollback_logo_filename
    timestamp = now().astimezone().isoformat(timespec="seconds")
    journal = {
        "marker": QUIZ_PUBLICATION_JOURNAL_MARKER,
        "schema_version": QUIZ_PUBLICATION_JOURNAL_VERSION,
        "publication_id": publication_id,
        "created_at": timestamp,
        "updated_at": timestamp,
        "state": "staging",
        "stage_dir": stage_name,
        "quiz": {"id": None, "source_file": effective_source_file},
        "artifacts": {
            "json": {"name": json_name, "attempted": False, "promoted": False},
            "html": {"name": html_name, "attempted": False, "promoted": False},
            "assets": {
                "name": asset_bucket,
                "required": False,
                "attempted": False,
                "promoted": False,
            },
        },
        "registry": {"html": html_name, "attempted": False, "published": False},
        "owned_logo": owned_logo,
    }
    try:
        write_journal(journal_path, journal)
    except Exception:
        remove_journal(journal_path)
        raise

    try:
        mkdir(stage_dir)
        fsync_directory(publication_staging_root)
        checkpoint("journal_created", journal)

        runtime_payload, db_payload = runtime_questions, db_questions
        if source_pack_id:
            runtime_payload, db_payload, _ = snapshot_runtime_questions(
                str(source_pack_id).strip().lower(),
                runtime_payload,
                db_payload,
                asset_bucket,
                destination_root=staged_assets,
            )
        if snapshot_existing_assets:
            runtime_payload = snapshot_existing_quiz_asset_refs(
                runtime_payload,
                asset_bucket,
                destination_root=staged_assets,
                strict=True,
            )
            db_payload = (
                runtime_payload
                if db_questions is runtime_questions
                else snapshot_existing_quiz_asset_refs(
                    db_payload,
                    asset_bucket,
                    destination_root=staged_assets,
                    strict=True,
                )
            )

        journal["artifacts"]["assets"]["required"] = isdir(staged_assets)
        update_journal(journal_path, journal)

        write_staged_quiz_json(staged_json, runtime_payload)

        conn = get_db()
        conn.execute("BEGIN")
        quiz_id = insert_quiz_rows(
            conn,
            quiz_title,
            effective_source_file,
            db_payload,
            logo_filename,
        )
        journal["quiz"]["id"] = quiz_id
        update_journal(journal_path, journal, state="db_commit_pending")

        build_quiz_html(
            html_name,
            json_name,
            staged_html,
            get_portal_title(),
            quiz_title,
            logo_filename,
            quiz_id,
            normalize_exam_minutes(exam_minutes),
        )
        if not isfile(staged_html) or getsize(staged_html) == 0:
            raise ValueError("Generated quiz HTML is empty")

        commit_publication(conn)
        conn.close()
        conn = None
        update_journal(journal_path, journal, state="db_committed")
        checkpoint("db_committed", journal)

        journal["artifacts"]["json"]["attempted"] = True
        update_journal(journal_path, journal)
        promote_artifact(staged_json, final_json)
        journal["artifacts"]["json"]["promoted"] = True
        update_journal(journal_path, journal)
        checkpoint("json_promoted", journal)

        journal["artifacts"]["html"]["attempted"] = True
        update_journal(journal_path, journal)
        promote_artifact(staged_html, final_html)
        journal["artifacts"]["html"]["promoted"] = True
        update_journal(journal_path, journal)
        checkpoint("html_promoted", journal)

        if isdir(staged_assets):
            journal["artifacts"]["assets"]["attempted"] = True
            update_journal(journal_path, journal)
            promote_artifact(staged_assets, final_assets)
            journal["artifacts"]["assets"]["promoted"] = True
            update_journal(journal_path, journal)
            checkpoint("assets_promoted", journal)

        update_journal(journal_path, journal, state="artifacts_promoted")
        checkpoint("artifacts_promoted", journal)

        journal["registry"]["attempted"] = True
        update_journal(journal_path, journal)
        add_quiz_to_registry(
            quiz_id=quiz_id,
            html=html_name,
            title=quiz_title,
            logo=logo_filename,
            exam_minutes=normalize_exam_minutes(exam_minutes),
            source_pack_id=source_pack_id,
            source_dataset_id=source_dataset_id,
        )
        # Once registry publication returns successfully, the quiz is live.
        # Journal-finalization failures are left for idempotent reconciliation
        # and must never trigger compensation of a coherent published quiz.
        try:
            journal["registry"]["published"] = True
            update_journal(journal_path, journal, state="registry_published")
            checkpoint("registry_published", journal)
            if not remove_path(stage_dir):
                raise OSError("could not remove publication staging directory")
            update_journal(journal_path, journal, state="complete")
            checkpoint("complete", journal)
            if not remove_journal(journal_path):
                raise OSError("could not remove completed publication journal")
        except Exception as exc:
            print_message(
                f"[QUIZ PUBLICATION FINALIZATION ERROR] quiz_id={quiz_id}: "
                f"{type(exc).__name__}: {exc}; startup reconciliation will retry"
            )
        return quiz_id, html_name
    except Exception:
        cleanup_ok = True
        try:
            update_journal(journal_path, journal, state="rollback_pending")
        except Exception as exc:
            cleanup_ok = False
            print_message(
                f"[QUIZ PUBLICATION JOURNAL ERROR] could not record rollback: {exc}"
            )
        if conn is not None:
            try:
                conn.rollback()
            except Exception as exc:
                cleanup_ok = False
                print_message(f"[QUIZ PUBLICATION DB ROLLBACK ERROR] {exc}")
            try:
                conn.close()
            except Exception as exc:
                cleanup_ok = False
                print_message(f"[QUIZ PUBLICATION DB CLOSE ERROR] {exc}")

        if journal["registry"]["attempted"] and quiz_id is not None:
            try:
                remove_registry_entry(quiz_id, html_name)
            except Exception as exc:
                cleanup_ok = False
                print_message(
                    f"[QUIZ PUBLICATION REGISTRY CLEANUP ERROR] quiz_id={quiz_id}: {exc}"
                )

        for key, path in (
            ("assets", final_assets),
            ("html", final_html),
            ("json", final_json),
        ):
            record = journal["artifacts"][key]
            if record["attempted"] or record["promoted"]:
                cleanup_ok = remove_path(path) and cleanup_ok
        if quiz_id is not None:
            try:
                cleanup_ok = delete_recorded_rows(journal) and cleanup_ok
            except Exception as exc:
                cleanup_ok = False
                print_message(
                    f"[QUIZ PUBLICATION DB CLEANUP ERROR] quiz_id={quiz_id}: {exc}"
                )
        if rollback_logo_filename:
            safe_logo = basename(str(rollback_logo_filename))
            if safe_logo == rollback_logo_filename and safe_logo == logo_filename:
                cleanup_ok = remove_path(join_path(logo_folder, safe_logo)) and cleanup_ok
        cleanup_ok = remove_path(stage_dir) and cleanup_ok
        if cleanup_ok:
            remove_journal(journal_path)
        raise

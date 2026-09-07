"""Law Study case, raw-import, mutation, and export domain services."""

import copy
import json
import os
import re


def _law_registry_case_for_mutation(registry, case_id):
    """Return the current mutable case entry or fail before durable changes."""
    for case in registry.get("cases", []):
        if str(case.get("id")) == str(case_id):
            return case
    raise ValueError("Law case registry entry changed before the operation completed")


def _commit_law_case_and_registry(
    case_path,
    case_data,
    registry,
    *,
    previous_case_data=None,
    new_case=False,
    atomic_write_json,
    save_law_registry,
    lexists=os.path.lexists,
    isfile=os.path.isfile,
    remove_file=os.remove,
):
    """Commit one case file and its registry metadata with narrow rollback."""
    if new_case and lexists(case_path):
        raise FileExistsError("Law case file already exists")
    if not new_case and not isinstance(previous_case_data, dict):
        raise ValueError("Existing Law case data is required for rollback")

    atomic_write_json(case_path, case_data, expected_type=dict)
    try:
        save_law_registry(registry)
    except Exception:
        try:
            if new_case:
                if lexists(case_path):
                    if not isfile(case_path):
                        raise RuntimeError("New Law case path is no longer a regular file")
                    remove_file(case_path)
            else:
                atomic_write_json(case_path, previous_case_data, expected_type=dict)
        except Exception as rollback_error:
            raise RuntimeError(
                "Law registry save failed and the case-file rollback also failed"
            ) from rollback_error
        raise


def _delete_law_case_and_registry(
    case_path,
    registry,
    case_id,
    *,
    registry_case_for_mutation=_law_registry_case_for_mutation,
    save_law_registry,
    lexists=os.path.lexists,
    isfile=os.path.isfile,
    remove_file=os.remove,
):
    """Remove a case without deleting its file before registry durability."""
    cases = registry.get("cases", [])
    registry_case_for_mutation(registry, case_id)
    if lexists(case_path) and not isfile(case_path):
        raise ValueError("Law case path is not a regular file")

    previous_registry = copy.deepcopy(registry)
    registry["cases"] = [
        case for case in cases if str(case.get("id")) != str(case_id)
    ]
    save_law_registry(registry)

    try:
        if isfile(case_path):
            remove_file(case_path)
    except Exception:
        try:
            save_law_registry(previous_registry)
        except Exception as rollback_error:
            raise RuntimeError(
                "Law case removal failed and the registry rollback also failed"
            ) from rollback_error
        raise


def save_law_raw_packet(
    raw_packet,
    case_slug="",
    *,
    imports_folder,
    safe_law_import_filename,
    now,
    makedirs=os.makedirs,
    join_path=os.path.join,
    open_file=open,
):
    """Save one raw Law packet using the durable import-file convention."""
    timestamp = now().strftime("%Y%m%d_%H%M%S")
    slug = str(case_slug or "").strip()
    saved_file = (
        f"law_import_{timestamp}_{slug}.txt"
        if slug else f"law_import_{timestamp}.txt"
    )
    safe_name = safe_law_import_filename(saved_file)

    if not safe_name:
        raise ValueError("Could not create a safe Law import filename.")

    makedirs(imports_folder, exist_ok=True)
    save_path = join_path(imports_folder, safe_name)

    with open_file(save_path, "w", encoding="utf-8") as f:
        f.write(raw_packet)

    return safe_name


def list_law_raw_imports(
    imports_folder,
    *,
    from_timestamp,
    imports=None,
    makedirs=os.makedirs,
    listdir=os.listdir,
    join_path=os.path.join,
    isfile=os.path.isfile,
    stat_file=os.stat,
):
    """List saved raw Law packets in the legacy newest-filename-first order."""
    imports = [] if imports is None else imports
    makedirs(imports_folder, exist_ok=True)

    for name in sorted(listdir(imports_folder), reverse=True):
        if not name.lower().endswith(".txt"):
            continue

        path = join_path(imports_folder, name)
        if not isfile(path):
            continue

        stat = stat_file(path)
        imports.append({
            "filename": name,
            "size": stat.st_size,
            "modified": from_timestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        })

    return imports


def load_law_raw_packet(path, *, open_file=open):
    """Read one already-validated raw Law packet as UTF-8 text."""
    with open_file(path, "r", encoding="utf-8") as f:
        return f.read()


def delete_law_raw_packet(
    path, *, exists=os.path.exists, isfile=os.path.isfile, remove_file=os.remove
):
    """Delete one already-validated saved raw packet if it is a regular file."""
    if exists(path) and isfile(path):
        remove_file(path)


def get_law_case_by_id(case_id, *, load_law_registry):
    """Look up a Law Study case review by ID from the live registry."""
    case_id = str(case_id or "").strip()

    if not case_id:
        return None

    registry = load_law_registry()
    for case in registry.get("cases", []):
        if str(case.get("id")) == case_id:
            return case

    return None


def load_law_case_data(case_path, *, open_file=open, json_module=json):
    """Load one already-validated Law case JSON file using legacy semantics."""
    with open_file(case_path, "r", encoding="utf-8") as f:
        return json_module.load(f) or {}


def start_pending_case_workflow(
    registry,
    *,
    case_name,
    case_slug,
    course,
    created_at,
    save_law_registry,
):
    registry["pending_case_workflow"] = {
        "case_name": case_name,
        "case_slug": case_slug,
        "course": course,
        "created_at": created_at,
    }
    save_law_registry(registry)


def cancel_pending_case_workflow(registry, *, save_law_registry):
    if "pending_case_workflow" in registry:
        registry.pop("pending_case_workflow", None)
        save_law_registry(registry)


def create_law_case_from_import(
    safe_name,
    raw_packet,
    parsed_sections,
    *,
    cases_folder,
    load_law_registry,
    extract_law_slug_from_import_filename,
    extract_law_case_title,
    secure_filename,
    now,
    commit_law_case_and_registry,
    makedirs=os.makedirs,
    join_path=os.path.join,
    isfile=os.path.isfile,
):
    """Create the registry/file pair for one validated saved Law packet."""
    registry = load_law_registry()

    for existing_case in registry.get("cases", []):
        if str(existing_case.get("source_import", "")) != safe_name:
            continue

        existing_id = str(existing_case.get("id", "")).strip()
        existing_file = secure_filename(str(existing_case.get("file", "")))
        existing_path = join_path(cases_folder, existing_file)

        if existing_id and existing_file.lower().endswith(".json") and isfile(existing_path):
            return existing_id

    ts = now().strftime("%Y%m%d_%H%M%S")
    case_slug = extract_law_slug_from_import_filename(safe_name)

    if case_slug:
        case_id = f"law_case_{ts}_{case_slug}"
    else:
        case_id = f"law_case_{ts}"

    case_file = f"{case_id}.json"
    case_path = join_path(cases_folder, case_file)
    section_map = {section["key"]: section["content"] for section in parsed_sections}

    title = extract_law_case_title(raw_packet, safe_name)
    course = "Uncategorized"
    pending_workflow = registry.get("pending_case_workflow", {}) or {}
    pending_slug = str(pending_workflow.get("case_slug", "")).strip()
    pending_case_name = str(pending_workflow.get("case_name", "")).strip()
    pending_course = str(pending_workflow.get("course", "")).strip()

    if case_slug and pending_slug and case_slug == pending_slug:
        if pending_case_name:
            title = pending_case_name
        if pending_course:
            course = pending_course

    case_data = {
        "id": case_id,
        "type": "law_case_review",
        "title": title,
        "course": course,
        "source_import": safe_name,
        "created_at": now().isoformat(timespec="seconds"),
        "updated_at": now().isoformat(timespec="seconds"),
        "verified": False,
        "sources_used": section_map.get("sources_used", ""),
        "sections": {
            "case_brief": section_map.get("case_brief", ""),
            "socratic_review": section_map.get("socratic_review", ""),
            "socratic_answer_key": section_map.get("socratic_answer_key", ""),
            "irac_drill": section_map.get("irac_drill", ""),
            "rule_flashcards": section_map.get("rule_flashcards", "")
        },
        "student_notes": ""
    }

    makedirs(cases_folder, exist_ok=True)
    cases = list(registry.get("cases", []))
    cases.append({
        "id": case_id,
        "title": title,
        "course": course,
        "file": case_file,
        "source_import": safe_name,
        "created_at": case_data["created_at"],
        "updated_at": case_data["updated_at"],
        "hidden": False
    })
    registry["cases"] = cases

    if "pending_case_workflow" in registry:
        registry.pop("pending_case_workflow", None)

    commit_law_case_and_registry(case_path, case_data, registry, new_case=True)
    return case_id


def update_law_case_details(
    case_path,
    case_id,
    case_entry,
    new_title,
    new_course,
    *,
    now,
    load_law_registry,
    registry_case_for_mutation,
    commit_law_case_and_registry,
    load_case_data=load_law_case_data,
):
    case_data = load_case_data(case_path)
    previous_case_data = copy.deepcopy(case_data)
    now_value = now().isoformat(timespec="seconds")

    case_data["title"] = new_title or case_entry.get("title") or "Untitled Case Review"
    case_data["course"] = new_course or "Uncategorized"
    case_data["updated_at"] = now_value

    registry = load_law_registry()
    registry_case = registry_case_for_mutation(registry, case_id)
    registry_case["title"] = case_data["title"]
    registry_case["course"] = case_data["course"]
    registry_case["updated_at"] = now_value

    commit_law_case_and_registry(
        case_path, case_data, registry, previous_case_data=previous_case_data
    )


def update_law_case_notes(
    case_path,
    case_id,
    student_notes,
    *,
    now,
    load_law_registry,
    registry_case_for_mutation,
    commit_law_case_and_registry,
    load_case_data=load_law_case_data,
):
    case_data = load_case_data(case_path)
    previous_case_data = copy.deepcopy(case_data)
    now_value = now().isoformat(timespec="seconds")
    case_data["student_notes"] = student_notes
    case_data["updated_at"] = now_value

    registry = load_law_registry()
    registry_case = registry_case_for_mutation(registry, case_id)
    registry_case["updated_at"] = now_value
    commit_law_case_and_registry(
        case_path, case_data, registry, previous_case_data=previous_case_data
    )


def update_law_case_socratic_answers(
    case_path,
    case_id,
    form_values,
    *,
    now,
    parse_socratic_questions,
    load_law_registry,
    registry_case_for_mutation,
    commit_law_case_and_registry,
    load_case_data=load_law_case_data,
):
    case_data = load_case_data(case_path)
    previous_case_data = copy.deepcopy(case_data)
    sections = case_data.get("sections", {}) or {}
    socratic_questions = parse_socratic_questions(sections.get("socratic_review", ""))
    answers = {}

    for question in socratic_questions:
        qid = question.get("id")
        if not qid:
            continue
        answers[qid] = str(form_values.get(f"answer_{qid}", "")).strip()

    now_value = now().isoformat(timespec="seconds")
    case_data["socratic_student_answers"] = answers
    case_data["updated_at"] = now_value

    registry = load_law_registry()
    registry_case = registry_case_for_mutation(registry, case_id)
    registry_case["updated_at"] = now_value
    commit_law_case_and_registry(
        case_path, case_data, registry, previous_case_data=previous_case_data
    )


def update_law_case_irac_response(
    case_path,
    case_id,
    irac_response,
    *,
    now,
    load_law_registry,
    registry_case_for_mutation,
    commit_law_case_and_registry,
    load_case_data=load_law_case_data,
):
    case_data = load_case_data(case_path)
    previous_case_data = copy.deepcopy(case_data)
    now_value = now().isoformat(timespec="seconds")
    case_data["irac_student_response"] = irac_response
    case_data["updated_at"] = now_value

    registry = load_law_registry()
    registry_case = registry_case_for_mutation(registry, case_id)
    registry_case["updated_at"] = now_value
    commit_law_case_and_registry(
        case_path, case_data, registry, previous_case_data=previous_case_data
    )


def build_law_case_export(case_data, case_id, *, app_version, exported_on):
    """Build the exact legacy Law text export payload and download filename."""
    sections = case_data.get("sections", {}) or {}
    title = case_data.get("title") or "Untitled Case Review"
    course = case_data.get("course") or "Uncategorized"
    source_import = case_data.get("source_import") or ""
    created_at = case_data.get("created_at") or ""
    updated_at = case_data.get("updated_at") or ""
    lines = []

    lines.append("# DLMS Law Case Review Export")
    lines.append(f"# Exported from DLMS v{app_version}")
    lines.append(f"# Exported on: {exported_on}")
    lines.append("# Format: DLMS Law Study text")
    lines.append("")
    lines.append("=" * 60)
    lines.append(f"CASE REVIEW: {title}")
    lines.append(f"COURSE: {course}")
    lines.append(f"SOURCE IMPORT: {source_import}")
    lines.append(f"CREATED: {created_at}")
    lines.append(f"UPDATED: {updated_at}")
    lines.append("=" * 60)
    lines.append("")

    section_order = [
        ("1. Case Brief", sections.get("case_brief", "")),
        ("2. Socratic Review", sections.get("socratic_review", "")),
        ("2A. Socratic Answer Key", sections.get("socratic_answer_key", "")),
        ("3. IRAC Drill", sections.get("irac_drill", "")),
        ("4. Rule Flashcards", sections.get("rule_flashcards", "")),
    ]

    for heading, content in section_order:
        if not content:
            continue
        lines.append(heading)
        lines.append("-" * len(heading))
        lines.append(content.strip())
        lines.append("")
        lines.append("")

    student_notes = case_data.get("student_notes", "")
    if student_notes:
        lines.append("Student Notes")
        lines.append("-------------")
        lines.append(student_notes.strip())
        lines.append("")
        lines.append("")

    lines.append("Verification Reminder")
    lines.append("---------------------")
    lines.append(
        "Verify citations, holdings, quotations, and procedural history against "
        "the original opinion or an approved legal research source."
    )
    lines.append("")

    export_text = "\n".join(lines)
    safe_title = re.sub(r"[^A-Za-z0-9_-]+", "_", title).strip("_")
    if not safe_title:
        safe_title = case_id
    return export_text, f"dlms_law_case_{safe_title}.txt"

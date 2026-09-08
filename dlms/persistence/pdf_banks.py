"""Persistence helpers for Smart PDF drafts and source banks."""

from datetime import datetime
import json
import os
import re

from dlms.persistence import json_files


def _safe_child(root, relative_path):
    root = os.path.realpath(root)
    candidate = os.path.realpath(os.path.join(root, relative_path))
    if candidate != root and not candidate.startswith(root + os.sep):
        raise ValueError("Content pack path escapes its pack directory")
    return candidate


def _timestamp_now():
    return datetime.now().isoformat(timespec="seconds")


def _default_atomic_write_json(path, payload, **kwargs):
    return json_files._atomic_write_json(path, payload, **kwargs)


def _pdf_bank_safe_id(value):
    value = re.sub(r"[^A-Za-z0-9_-]+", "", str(value or ""))
    return value[:80]


def _pdf_bank_path(
    folder,
    bank_id,
    *,
    safe_id=None,
    safe_child=None,
):
    safe_id = safe_id or _pdf_bank_safe_id
    safe_child = safe_child or _safe_child
    bank_id = safe_id(bank_id)
    if not bank_id:
        raise ValueError("Invalid PDF question-bank id")
    return safe_child(folder, f"{bank_id}.json")


def _save_pdf_question_bank(
    folder,
    bank,
    *,
    safe_id=None,
    path_for_id=None,
    timestamp_now=None,
    atomic_write_json=None,
    os_module=None,
):
    safe_id = safe_id or _pdf_bank_safe_id
    if path_for_id is None:
        path_for_id = lambda bank_id: _pdf_bank_path(folder, bank_id)
    timestamp_now = timestamp_now or _timestamp_now
    atomic_write_json = atomic_write_json or _default_atomic_write_json
    os_module = os_module or os

    bank_id = safe_id(bank.get("id"))
    if not bank_id:
        raise ValueError("Question bank is missing an id")
    os_module.makedirs(folder, exist_ok=True)
    bank["updated_at"] = timestamp_now()
    atomic_write_json(
        path_for_id(bank_id), bank, ensure_ascii=False, expected_type=dict
    )


def _load_pdf_question_bank(
    folder,
    bank_id,
    *,
    path_for_id=None,
    os_module=None,
    json_module=None,
    open_file=None,
):
    if path_for_id is None:
        path_for_id = lambda value: _pdf_bank_path(folder, value)
    os_module = os_module or os
    json_module = json_module or json
    open_file = open_file or open

    path = path_for_id(bank_id)
    if not os_module.path.isfile(path):
        raise FileNotFoundError("PDF question bank not found")
    with open_file(path, "r", encoding="utf-8") as f:
        bank = json_module.load(f) or {}
    if not isinstance(bank.get("questions"), list):
        raise ValueError("PDF question bank is malformed")
    return bank


def _list_pdf_question_banks(
    folder,
    *,
    os_module=None,
    json_module=None,
    open_file=None,
    print_message=None,
):
    os_module = os_module or os
    json_module = json_module or json
    open_file = open_file or open
    print_message = print_message or print

    os_module.makedirs(folder, exist_ok=True)
    banks = []
    for name in sorted(os_module.listdir(folder)):
        if not name.endswith(".json"):
            continue
        try:
            with open_file(os_module.path.join(folder, name), "r", encoding="utf-8") as f:
                bank = json_module.load(f) or {}
            questions = bank.get("questions") or []
            active = [q for q in questions if isinstance(q, dict) and q.get("active", True)]
            banks.append({
                "id": bank.get("id") or os_module.path.splitext(name)[0],
                "title": bank.get("title") or "PDF Question Bank",
                "source_name": bank.get("source_name") or "",
                "question_count": len(questions),
                "active_count": len(active),
                "used_count": len(set(bank.get("used_question_numbers") or [])),
                "generated_count": len(bank.get("generated_quizzes") or []),
                "created_at": bank.get("created_at") or "",
                "updated_at": bank.get("updated_at") or "",
            })
        except Exception as exc:
            print_message(f"[PDF BANKS] Skipping invalid bank {name!r}: {exc}")
    return banks


def _delete_pdf_question_bank(
    folder,
    bank_id,
    *,
    load_bank=None,
    path_for_id=None,
    os_module=None,
):
    if load_bank is None:
        load_bank = lambda value: _load_pdf_question_bank(folder, value)
    if path_for_id is None:
        path_for_id = lambda value: _pdf_bank_path(folder, value)
    os_module = os_module or os

    bank = load_bank(bank_id)
    path = path_for_id(bank_id)
    title = str(bank.get("title") or "PDF Question Bank").strip()
    os_module.remove(path)
    return title


def _pdf_term_bank_safe_id(value):
    value = re.sub(r"[^A-Za-z0-9_-]+", "", str(value or ""))
    return value[:80]


def _pdf_term_bank_path(
    folder,
    bank_id,
    *,
    safe_id=None,
    safe_child=None,
):
    safe_id = safe_id or _pdf_term_bank_safe_id
    safe_child = safe_child or _safe_child
    bank_id = safe_id(bank_id)
    if not bank_id:
        raise ValueError("Invalid PDF terminology-bank id")
    return safe_child(folder, f"{bank_id}.json")


def _save_pdf_terminology_bank(
    folder,
    bank,
    *,
    safe_id=None,
    path_for_id=None,
    timestamp_now=None,
    atomic_write_json=None,
    os_module=None,
):
    safe_id = safe_id or _pdf_term_bank_safe_id
    if path_for_id is None:
        path_for_id = lambda bank_id: _pdf_term_bank_path(folder, bank_id)
    timestamp_now = timestamp_now or _timestamp_now
    atomic_write_json = atomic_write_json or _default_atomic_write_json
    os_module = os_module or os

    bank_id = safe_id(bank.get("id"))
    if not bank_id:
        raise ValueError("Terminology bank is missing an id")
    os_module.makedirs(folder, exist_ok=True)
    bank["updated_at"] = timestamp_now()
    atomic_write_json(
        path_for_id(bank_id), bank, ensure_ascii=False, expected_type=dict
    )


def _load_pdf_terminology_bank(
    folder,
    bank_id,
    *,
    path_for_id=None,
    os_module=None,
    json_module=None,
    open_file=None,
):
    if path_for_id is None:
        path_for_id = lambda value: _pdf_term_bank_path(folder, value)
    os_module = os_module or os
    json_module = json_module or json
    open_file = open_file or open

    path = path_for_id(bank_id)
    if not os_module.path.isfile(path):
        raise FileNotFoundError("PDF terminology bank not found")
    with open_file(path, "r", encoding="utf-8") as f:
        bank = json_module.load(f) or {}
    if not isinstance(bank.get("terms"), list):
        raise ValueError("PDF terminology bank is malformed")
    return bank


def _list_pdf_terminology_banks(
    folder,
    *,
    os_module=None,
    json_module=None,
    open_file=None,
    print_message=None,
):
    os_module = os_module or os
    json_module = json_module or json
    open_file = open_file or open
    print_message = print_message or print

    os_module.makedirs(folder, exist_ok=True)
    banks = []
    for name in sorted(os_module.listdir(folder)):
        if not name.endswith(".json"):
            continue
        try:
            with open_file(os_module.path.join(folder, name), "r", encoding="utf-8") as f:
                bank = json_module.load(f) or {}
            terms = bank.get("terms") or []
            active = [t for t in terms if isinstance(t, dict) and t.get("active", True)]
            banks.append({
                "id": bank.get("id") or os_module.path.splitext(name)[0],
                "kind": "terminology",
                "title": bank.get("title") or "PDF Terminology Bank",
                "source_name": bank.get("source_name") or "",
                "term_count": len(terms),
                "active_count": len(active),
                "used_count": len(set(bank.get("used_term_numbers") or [])),
                "generated_count": len(bank.get("generated_quizzes") or []),
                "created_at": bank.get("created_at") or "",
                "updated_at": bank.get("updated_at") or "",
            })
        except Exception as exc:
            print_message(f"[PDF TERMS] Skipping invalid bank {name!r}: {exc}")
    return banks


def _delete_pdf_terminology_bank(
    folder,
    bank_id,
    *,
    load_bank=None,
    path_for_id=None,
    os_module=None,
):
    if load_bank is None:
        load_bank = lambda value: _load_pdf_terminology_bank(folder, value)
    if path_for_id is None:
        path_for_id = lambda value: _pdf_term_bank_path(folder, value)
    os_module = os_module or os

    bank = load_bank(bank_id)
    path = path_for_id(bank_id)
    title = str(bank.get("title") or "PDF Terminology Bank").strip()
    os_module.remove(path)
    return title


def _pdf_import_safe_id(value):
    value = re.sub(r"[^A-Za-z0-9_-]+", "", str(value or ""))
    return value[:80]


def _pdf_import_draft_path(
    folder,
    draft_id,
    *,
    safe_id=None,
    safe_child=None,
):
    safe_id = safe_id or _pdf_import_safe_id
    safe_child = safe_child or _safe_child
    draft_id = safe_id(draft_id)
    if not draft_id:
        raise ValueError("Invalid PDF import draft id")
    return safe_child(folder, f"{draft_id}.json")


def _save_pdf_import_draft(
    folder,
    draft,
    *,
    safe_id=None,
    path_for_id=None,
    os_module=None,
    atomic_write_json=None,
):
    safe_id = safe_id or _pdf_import_safe_id
    if path_for_id is None:
        path_for_id = lambda draft_id: _pdf_import_draft_path(folder, draft_id)
    os_module = os_module or os
    atomic_write_json = atomic_write_json or _default_atomic_write_json

    draft_id = safe_id(draft.get("id"))
    if not draft_id:
        raise ValueError("PDF import draft is missing an id")
    os_module.makedirs(folder, exist_ok=True)
    atomic_write_json(
        path_for_id(draft_id), draft, ensure_ascii=False, expected_type=dict
    )


def _load_pdf_import_draft(
    folder,
    draft_id,
    *,
    path_for_id=None,
    os_module=None,
    json_module=None,
    open_file=None,
):
    if path_for_id is None:
        path_for_id = lambda value: _pdf_import_draft_path(folder, value)
    os_module = os_module or os
    json_module = json_module or json
    open_file = open_file or open

    path = path_for_id(draft_id)
    if not os_module.path.isfile(path):
        raise FileNotFoundError("PDF import draft not found")
    with open_file(path, "r", encoding="utf-8") as f:
        return json_module.load(f) or {}

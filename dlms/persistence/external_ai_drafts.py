"""Transient persistence for External AI structured review drafts."""

from __future__ import annotations

import json
import os
import re
import secrets
import time
from datetime import datetime, timezone

from dlms.persistence import json_files


EXTERNAL_AI_DRAFT_MARKER = "dlms-external-ai-review-draft"
EXTERNAL_AI_DRAFT_SCHEMA_VERSION = 1
EXTERNAL_AI_DRAFT_STALE_SECONDS = 24 * 60 * 60
EXTERNAL_AI_DRAFT_MAX_CLEANUP_ENTRIES = 1000
EXTERNAL_AI_DRAFT_MAX_FILE_BYTES = 4 * 1024 * 1024
EXTERNAL_AI_DRAFT_MAX_RAW_BYTES = 1024 * 1024
_OPAQUE_DRAFT_ID_RE = re.compile(r"^[a-f0-9]{32}$")


def _validated_draft_path(folder, draft_id):
    draft_id = str(draft_id or "")
    if not _OPAQUE_DRAFT_ID_RE.fullmatch(draft_id):
        raise ValueError("Invalid External AI draft id")
    root = os.path.realpath(os.path.abspath(os.fspath(folder)))
    candidate = os.path.abspath(os.path.join(root, f"{draft_id}.json"))
    resolved = os.path.realpath(candidate)
    if os.path.commonpath([root, resolved]) != root:
        raise ValueError("External AI draft path escapes its staging directory")
    return candidate


def _timestamp_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create_external_ai_draft(
    folder,
    review_draft,
    raw_response,
    *,
    token_hex=secrets.token_hex,
    timestamp_now=_timestamp_now,
    atomic_write_json=json_files._atomic_write_json,
):
    """Create one opaque, temporary draft without accepting a caller path."""
    if not isinstance(review_draft, dict):
        raise ValueError("External AI review draft must be an object")
    if not isinstance(raw_response, str):
        raise ValueError("External AI raw response must be text")
    if len(raw_response.encode("utf-8")) > EXTERNAL_AI_DRAFT_MAX_RAW_BYTES:
        raise ValueError("External AI raw response exceeds the 1 MiB limit")
    os.makedirs(folder, exist_ok=True)

    for _attempt in range(10):
        draft_id = token_hex(16)
        path = _validated_draft_path(folder, draft_id)
        if os.path.lexists(path):
            continue
        payload = {
            "marker": EXTERNAL_AI_DRAFT_MARKER,
            "schema_version": EXTERNAL_AI_DRAFT_SCHEMA_VERSION,
            "id": draft_id,
            "created_at": timestamp_now(),
            "raw_response": raw_response,
            "review_draft": review_draft,
        }
        serialized_size = len(
            json.dumps(payload, ensure_ascii=False).encode("utf-8")
        )
        if serialized_size > EXTERNAL_AI_DRAFT_MAX_FILE_BYTES:
            raise ValueError("External AI draft exceeds its storage limit")
        atomic_write_json(
            path,
            payload,
            ensure_ascii=False,
            expected_type=dict,
        )
        return draft_id
    raise RuntimeError("Could not allocate an External AI draft id")


def load_external_ai_draft(folder, draft_id):
    """Load one validated regular draft file without following draft symlinks."""
    path = _validated_draft_path(folder, draft_id)
    if os.path.islink(path) or not os.path.isfile(path):
        raise FileNotFoundError("External AI draft not found")
    if os.path.getsize(path) > EXTERNAL_AI_DRAFT_MAX_FILE_BYTES:
        raise ValueError("External AI draft exceeds its storage limit")
    try:
        with open(path, "r", encoding="utf-8") as draft_file:
            payload = json.load(draft_file)
    except (json.JSONDecodeError, UnicodeError, OSError) as exc:
        raise ValueError("External AI draft is malformed") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("marker") != EXTERNAL_AI_DRAFT_MARKER
        or payload.get("schema_version") != EXTERNAL_AI_DRAFT_SCHEMA_VERSION
        or payload.get("id") != draft_id
        or not isinstance(payload.get("raw_response"), str)
        or not isinstance(payload.get("review_draft"), dict)
    ):
        raise ValueError("External AI draft is malformed")
    return payload


def update_external_ai_review_draft(
    folder,
    draft_id,
    review_draft,
    *,
    atomic_write_json=json_files._atomic_write_json,
):
    """Replace only normalized review data while preserving transient raw text."""
    if not isinstance(review_draft, dict):
        raise ValueError("External AI review draft must be an object")
    payload = load_external_ai_draft(folder, draft_id)
    payload["review_draft"] = review_draft
    serialized_size = len(
        json.dumps(payload, ensure_ascii=False).encode("utf-8")
    )
    if serialized_size > EXTERNAL_AI_DRAFT_MAX_FILE_BYTES:
        raise ValueError("External AI draft exceeds its storage limit")
    atomic_write_json(
        _validated_draft_path(folder, draft_id),
        payload,
        ensure_ascii=False,
        expected_type=dict,
    )
    return payload


def delete_external_ai_draft(folder, draft_id):
    """Delete one explicitly addressed draft; missing drafts are harmless."""
    path = _validated_draft_path(folder, draft_id)
    if os.path.islink(path):
        raise ValueError("External AI draft path is not a regular file")
    try:
        os.remove(path)
    except FileNotFoundError:
        return False
    return True


def prune_external_ai_drafts(
    folder,
    *,
    stale_seconds=EXTERNAL_AI_DRAFT_STALE_SECONDS,
    max_cleanup_entries=EXTERNAL_AI_DRAFT_MAX_CLEANUP_ENTRIES,
    now=time.time,
):
    """Remove at most a bounded number of abandoned 24-hour draft files."""
    if stale_seconds < 0 or max_cleanup_entries < 1:
        raise ValueError("Invalid External AI draft cleanup bounds")
    os.makedirs(folder, exist_ok=True)
    cutoff = now() - stale_seconds
    removed = 0
    checked = 0
    for name in sorted(os.listdir(folder)):
        if checked >= max_cleanup_entries:
            break
        match = re.fullmatch(r"([a-f0-9]{32})\.json", name)
        if match is None:
            continue
        checked += 1
        path = _validated_draft_path(folder, match.group(1))
        if os.path.islink(path) or not os.path.isfile(path):
            continue
        try:
            modified = os.path.getmtime(path)
        except OSError:
            continue
        if modified <= cutoff:
            try:
                os.remove(path)
            except FileNotFoundError:
                continue
            removed += 1
    return removed

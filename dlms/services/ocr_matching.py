"""Transient bridge from local OCR observations to matching Review & Repair."""

from __future__ import annotations

import copy

from dlms.parsing.ocr_matching import OCR_MATCHING_MAX_PAIRS
from dlms.persistence.external_ai_drafts import (
    create_external_ai_draft,
    prune_external_ai_drafts,
)


OCR_MATCHING_DEFAULT_QUESTION = "Match each term to its definition."
OCR_MATCHING_MAX_TITLE_CHARS = 240
OCR_MATCHING_MAX_QUESTION_CHARS = 10_000


def _bounded_text(value, *, fallback, limit):
    value = str(value or "").strip() or fallback
    if len(value) > limit:
        raise ValueError(f"OCR matching text exceeds its {limit:,}-character limit.")
    return value


def build_ocr_matching_review_draft(
    processing_draft,
):
    """Combine ordered OCR results into the canonical matching review shape."""
    if not isinstance(processing_draft, dict):
        raise ValueError("OCR matching processing data is malformed.")
    results = processing_draft.get("matching_results")
    if not isinstance(results, list):
        raise ValueError("OCR matching processing results are malformed.")

    pairs = []
    unassigned = []
    diagnostics = []
    truncated_pairs = 0
    for result in results:
        if not isinstance(result, dict):
            continue
        for pair in result.get("pairs") or []:
            if isinstance(pair, dict):
                if len(pairs) < OCR_MATCHING_MAX_PAIRS:
                    pairs.append(copy.deepcopy(pair))
                else:
                    truncated_pairs += 1
        for item in result.get("unassigned") or []:
            if isinstance(item, dict) and len(unassigned) < 100:
                unassigned.append(copy.deepcopy(item))
        diagnostics.extend(
            copy.deepcopy(item)
            for item in (result.get("diagnostics") or [])
            if isinstance(item, dict)
        )
        truncated_pairs += max(0, int(result.get("truncated_pairs") or 0))

    if truncated_pairs:
        diagnostics.append({
            "severity": "warning",
            "code": "ocr_pair_limit",
            "path": "questions[0].pairs",
            "message": (
                f"{truncated_pairs} additional candidate pair(s) exceeded the "
                f"{OCR_MATCHING_MAX_PAIRS}-pair review limit and were not imported."
            ),
        })

    validation_issues = []
    if len(pairs) < 2:
        validation_issues.append({
            "severity": "error",
            "code": "too_few_ocr_pairs",
            "path": "questions[0].pairs",
            "message": "OCR found fewer than two complete or repairable pair candidates.",
        })
    for index, pair in enumerate(pairs):
        if (
            not str(pair.get("left") or "").strip()
            or not str(pair.get("right") or "").strip()
        ):
            validation_issues.append({
                "severity": "error",
                "code": "incomplete_ocr_pair",
                "path": f"questions[0].pairs[{index}]",
                "message": f"Pair {index + 1} needs both a term and definition.",
            })

    seen_left = {}
    seen_right = {}
    for index, pair in enumerate(pairs):
        for field, seen in (("left", seen_left), ("right", seen_right)):
            value = " ".join(str(pair.get(field) or "").split()).casefold()
            if not value:
                continue
            if value in seen:
                validation_issues.append({
                    "severity": "error",
                    "code": "duplicate_ocr_pair_side",
                    "path": f"questions[0].pairs[{index}].{field}",
                    "message": (
                        f"Pairs {seen[value] + 1} and {index + 1} repeat the same "
                        f"{'term' if field == 'left' else 'definition'}."
                    ),
                })
            else:
                seen[value] = index

    source_names = [
        str(source.get("original_name") or "").strip()
        for source in processing_draft.get("ocr_batch", {}).get("sources", [])
        if isinstance(source, dict) and str(source.get("original_name") or "").strip()
    ]
    unique_names = list(dict.fromkeys(source_names))
    dataset = "; ".join(unique_names) or "Local OCR terminology import"
    title = _bounded_text(
        processing_draft.get("quiz_title"),
        fallback="OCR Terminology Matching",
        limit=OCR_MATCHING_MAX_TITLE_CHARS,
    )
    question = _bounded_text(
        processing_draft.get("matching_question"),
        fallback=OCR_MATCHING_DEFAULT_QUESTION,
        limit=OCR_MATCHING_MAX_QUESTION_CHARS,
    )
    direction = str(processing_draft.get("matching_direction") or "term_to_definition")
    if direction not in {"term_to_definition", "definition_to_term", "random"}:
        raise ValueError("OCR matching direction is unsupported.")
    question_record = {
        "source_index": 0,
        "number": 1,
        "question": question,
        "direction": direction,
        "round_size": max(2, min(10, len(pairs))),
        "pairs": pairs,
        "explanation": "",
        "concepts": [],
        "review_confirmation_required": True,
        "review_confirmed": False,
        "excluded": False,
        "validation_issues": validation_issues,
        "validation_state": "needs_repair" if validation_issues else "ready_for_review",
    }
    return {
        "draft_type": "ocr_matching",
        "schema_version": 1,
        "content_type": "matching",
        "origin": "ocr_matching",
        "title": title,
        "source": {
            "organization": "",
            "dataset": dataset[:1000],
            "version": "",
            "url": "",
            "license": "",
        },
        "questions": [question_record],
        "diagnostics": diagnostics,
        "unassigned_text": unassigned,
        "validation_state": "needs_repair" if validation_issues else "ready_for_review",
        "correctness_confirmation_required": False,
        "review_confirmation_required": True,
    }


def stage_ocr_matching_review(folder, processing_draft):
    """Persist an OCR-derived matching draft in the existing transient store."""
    review_draft = build_ocr_matching_review_draft(processing_draft)
    prune_external_ai_drafts(folder)
    draft_id = create_external_ai_draft(folder, review_draft, "")
    return draft_id, review_draft

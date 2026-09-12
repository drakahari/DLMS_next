"""Bounded OCR augmentation for raster content inside known PDF questions."""

from __future__ import annotations

from collections import Counter
import math
import re
from typing import Any, Iterable

from dlms.parsing.ocr_questions import observations_to_lines


PDF_TARGETED_OCR_MAX_REGIONS = 50
PDF_TARGETED_OCR_MIN_WIDTH_POINTS = 36.0
PDF_TARGETED_OCR_MIN_HEIGHT_POINTS = 18.0
PDF_TARGETED_OCR_MIN_PAGE_AREA_RATIO = 0.004


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _question_heading_positions(pages, question_start_match):
    positions = []
    for page in pages:
        page_number = int(page.get("page") or 0)
        for line in page.get("styled_lines") or []:
            if not isinstance(line, dict):
                continue
            match = question_start_match(line.get("text"))
            if match and match.get("kind") in {"heading", "extended_heading"}:
                try:
                    y = float(line.get("y"))
                except (TypeError, ValueError):
                    continue
                positions.append({"page": page_number, "y": y, "match": match})
    return positions


def _matched_question_positions(questions, headings):
    matched = []
    cursor = 0
    for question in questions:
        number = int(question.get("number") or 0)
        found = None
        for index in range(cursor, len(headings)):
            if int(headings[index]["match"].get("number") or 0) == number:
                found = headings[index]
                cursor = index + 1
                break
        matched.append(found)
    return matched


def _raster_signature(page, region):
    width = float(page.get("page_width") or 0)
    height = float(page.get("page_height") or 0)
    if width <= 0 or height <= 0:
        return None
    return (
        round(float(region.get("left") or 0) / width, 2),
        round(float(region.get("bottom") or 0) / height, 2),
        round(float(region.get("right") or 0) / width, 2),
        round(float(region.get("top") or 0) / height, 2),
        int(region.get("pixel_width") or 0),
        int(region.get("pixel_height") or 0),
    )


def _shared_raster_signatures(pages):
    occurrences = Counter()
    for page in pages:
        seen = set()
        for region in page.get("raster_regions") or []:
            signature = _raster_signature(page, region)
            if signature is not None:
                seen.add(signature)
        occurrences.update(seen)
    minimum_pages = max(3, int(math.ceil(len(pages) * 0.25)))
    return {
        signature
        for signature, count in occurrences.items()
        if count >= minimum_pages
    }


def _substantive_region(page, region, shared_signatures):
    if int(page.get("page_rotation") or 0) != 0:
        return False
    width = float(page.get("page_width") or 0)
    height = float(page.get("page_height") or 0)
    left = float(region.get("left") or 0)
    bottom = float(region.get("bottom") or 0)
    right = float(region.get("right") or 0)
    top = float(region.get("top") or 0)
    painted_width = right - left
    painted_height = top - bottom
    if width <= 0 or height <= 0:
        return False
    if (
        painted_width < PDF_TARGETED_OCR_MIN_WIDTH_POINTS
        or painted_height < PDF_TARGETED_OCR_MIN_HEIGHT_POINTS
        or painted_width * painted_height
        < width * height * PDF_TARGETED_OCR_MIN_PAGE_AREA_RATIO
    ):
        return False
    return _raster_signature(page, region) not in shared_signatures


def _region_within_question(region, start, following, page_number):
    tolerance = 5.0
    if page_number < start["page"]:
        return False
    if following is not None and page_number > following["page"]:
        return False
    top = float(region.get("top") or 0)
    bottom = float(region.get("bottom") or 0)
    if page_number == start["page"] and top > start["y"] + tolerance:
        return False
    if (
        following is not None
        and page_number == following["page"]
        and bottom < following["y"] - tolerance
    ):
        return False
    return True


def targeted_ocr_candidates(pages, question_result, *, question_start_match):
    """Find nonshared raster bounds inside already-validated question spans."""
    questions = (
        question_result.get("questions")
        if isinstance(question_result, dict)
        else []
    )
    if not isinstance(questions, list) or not questions:
        return []
    headings = _question_heading_positions(pages, question_start_match)
    positions = _matched_question_positions(questions, headings)
    shared_signatures = _shared_raster_signatures(pages)
    unassigned_pages = {
        int(value) for value in (question_result.get("unassigned_pages") or [])
    }
    page_map = {int(page.get("page") or 0): page for page in pages}
    candidates = []

    for index, question in enumerate(questions):
        start = positions[index]
        following = positions[index + 1] if index + 1 < len(positions) else None
        if start is None or question.get("source_question_type") == "fill_in":
            continue
        choices = [
            choice
            for choice in (question.get("choices") or [])
            if isinstance(choice, dict) and _clean(choice.get("text"))
        ]
        missing_choices = len(choices) < 2
        missing_support = any(
            "may not be present in extracted text" in str(issue).casefold()
            for issue in (question.get("issues") or [])
        )
        if not _clean(question.get("question")) or not (
            missing_choices or missing_support
        ):
            continue

        last_page = following["page"] if following is not None else max(page_map, default=0)
        for page_number in range(start["page"], last_page + 1):
            if page_number in unassigned_pages:
                continue
            page = page_map.get(page_number)
            if not page:
                continue
            regions = [
                region
                for region in (page.get("raster_regions") or [])
                if isinstance(region, dict)
                and _substantive_region(page, region, shared_signatures)
                and _region_within_question(region, start, following, page_number)
            ]
            if not regions:
                continue
            candidates.append({
                "question_index": index,
                "question_number": int(question.get("number") or index + 1),
                "question_start_page": int(start["page"]),
                "page": page_number,
                "kind": "choices" if missing_choices else "supporting_text",
                "bbox": {
                    "left": min(float(region["left"]) for region in regions),
                    "bottom": min(float(region["bottom"]) for region in regions),
                    "right": max(float(region["right"]) for region in regions),
                    "top": max(float(region["top"]) for region in regions),
                },
                "region_count": len(regions),
            })
            if len(candidates) >= PDF_TARGETED_OCR_MAX_REGIONS:
                return candidates
    return candidates


_STANDALONE_LABEL_RE = re.compile(r"^([A-Z])\s*[.):]?$", re.ASCII)
_INLINE_LABEL_RE = re.compile(r"^([A-Z])[.)]\s+(.+)$", re.ASCII)


def parse_targeted_raster_choices(observations: Iterable[Any]):
    """Parse source-labelled, multiline choices without inferring missing labels."""
    observations = tuple(observations)
    lines = observations_to_lines(observations)
    source_width = int(
        (observations[0].get("source_width") if isinstance(observations[0], dict)
         else getattr(observations[0], "source_width", 0))
        if observations
        else 0
    )
    raw_starts = []
    for index, line in enumerate(lines):
        standalone = _STANDALONE_LABEL_RE.fullmatch(line.text.strip())
        inline = _INLINE_LABEL_RE.fullmatch(line.text.strip())
        if standalone:
            raw_starts.append((index, standalone.group(1).upper(), "", line.left))
        elif inline:
            raw_starts.append((index, inline.group(1).upper(), inline.group(2).strip(), line.left))

    alignment_tolerance = max(14, int(source_width * 0.04))
    starts = raw_starts
    if len(raw_starts) >= 2:
        clusters = []
        for candidate in raw_starts:
            cluster = [
                item
                for item in raw_starts
                if abs(item[3] - candidate[3]) <= alignment_tolerance
            ]
            labels = [item[1] for item in cluster]
            ordered = all(
                ord(current) > ord(previous)
                for previous, current in zip(labels, labels[1:])
            )
            clusters.append((len(cluster), labels[:1] == ["A"], ordered, cluster))
        starts = max(clusters, key=lambda item: item[:3])[3]

    choices = []
    unassigned = [line.text for line in lines[: starts[0][0]]] if starts else [line.text for line in lines]
    for position, (line_index, label, inline_text, label_left) in enumerate(starts[:26]):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        body = ([inline_text] if inline_text else []) + [
            line.text for line in lines[line_index + 1:end]
        ]
        choices.append({
            "label": label,
            "text": "\n".join(text for text in body if _clean(text)).strip(),
            "label_origin": "source",
            "_label_left": label_left,
        })

    issues = []
    labels = [choice["label"] for choice in choices]
    if len(starts) > 26:
        issues.append("More than 26 source answer labels were detected in the raster region.")
        unassigned.extend(line.text for line in lines[starts[26][0]:])
    ordered = all(ord(current) > ord(previous) for previous, current in zip(labels, labels[1:]))
    contiguous = labels == [chr(ord("A") + index) for index in range(len(labels))]
    aligned = not choices or (
        max(choice["_label_left"] for choice in choices)
        - min(choice["_label_left"] for choice in choices)
        <= alignment_tolerance
    )
    if labels and not ordered:
        issues.append("Raster answer labels are duplicated or out of order.")
    if labels and not contiguous:
        issues.append("Raster answer labels are missing or noncontiguous; source labels were preserved.")
    if choices and not aligned:
        issues.append("Raster answer labels are not consistently aligned.")
    if any(not _clean(choice["text"]) for choice in choices):
        issues.append("One or more raster answer labels have no detected choice body.")
    if len(choices) < 2:
        issues.append("Fewer than two source-labelled raster choices were detected.")

    for choice in choices:
        choice.pop("_label_left", None)
    complete_structure = (
        2 <= len(choices) <= 26
        and contiguous
        and aligned
        and all(_clean(choice["text"]) for choice in choices)
    )
    confidence = (
        sum(
            float(
                item.get("confidence", 0.0)
                if isinstance(item, dict)
                else getattr(item, "confidence", 0.0)
            )
            for item in observations
        )
        / len(observations)
        if observations
        else 0.0
    )
    return {
        "choices": choices,
        "status": "review" if complete_structure else "incomplete",
        "issues": issues,
        "raw_text": "\n".join(line.text for line in lines).strip(),
        "unassigned_text": "\n".join(dict.fromkeys(unassigned)).strip(),
        "text_confidence": "high" if confidence >= 85 else "medium" if confidence >= 65 else "low",
    }


def _comparison_key(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def merge_targeted_raster_result(question, recovered, source):
    """Merge OCR content into one known question without replacing direct text."""
    merged = dict(question or {})
    merged["choices"] = [
        dict(choice) for choice in (merged.get("choices") or []) if isinstance(choice, dict)
    ]
    issues = list(merged.get("issues") or [])
    recovered_issues = list(recovered.get("issues") or [])
    unassigned = str(recovered.get("unassigned_text") or "").strip()

    if source.get("kind") == "supporting_text":
        supporting_text = str(recovered.get("raw_text") or "").strip()
        if (
            supporting_text
            and _comparison_key(supporting_text)
            not in _comparison_key(merged.get("question"))
        ):
            merged["ocr_supporting_text"] = supporting_text
        issues.append("OCR recovered supporting raster text; compare it with the source before saving.")
    else:
        by_label = {
            str(choice.get("label") or "").upper(): choice
            for choice in merged["choices"]
        }
        by_text = {
            _comparison_key(choice.get("text"))
            for choice in merged["choices"]
            if _comparison_key(choice.get("text"))
        }
        for choice in recovered.get("choices") or []:
            label = str(choice.get("label") or "").upper()
            text = str(choice.get("text") or "").strip()
            key = _comparison_key(text)
            if label in by_label:
                if key != _comparison_key(by_label[label].get("text")):
                    recovered_issues.append(
                        f"Raster choice {label} conflicts with authoritative selectable text."
                    )
                continue
            if key and key in by_text:
                continue
            merged["choices"].append({
                "label": label,
                "text": text,
                "label_origin": "source",
            })
            by_label[label] = merged["choices"][-1]
            if key:
                by_text.add(key)
        merged["choices"].sort(key=lambda choice: str(choice.get("label") or ""))
        if len([choice for choice in merged["choices"] if _clean(choice.get("text"))]) >= 2:
            issues = [
                issue
                for issue in issues
                if issue != "Fewer than two answer choices were detected."
            ]

    issues.extend(recovered_issues)
    merged["issues"] = list(dict.fromkeys(issues))
    pages = []
    for value in [*(merged.get("pages") or []), source.get("page")]:
        try:
            page = int(value)
        except (TypeError, ValueError):
            continue
        if page not in pages:
            pages.append(page)
    merged["pages"] = sorted(pages)
    merged["correctness_confirmation_required"] = True
    merged["correctness_confirmed"] = False
    merged["ocr_metadata"] = {
        "source_id": source.get("id"),
        "source_type": "pdf_question_region",
        "page_number": source.get("page"),
        "question_number": source.get("question_number"),
        "selectable_text_authoritative": True,
        "label_origin": "source" if recovered.get("choices") else "unknown",
        "text_confidence": recovered.get("text_confidence") or "low",
        "structure_confidence": (
            "medium" if recovered.get("status") == "review" else "low"
        ),
        "correctness_evidence": "unknown",
        "unassigned_text": unassigned,
    }
    if source.get("kind") == "supporting_text":
        merged["status"] = "review"
    elif recovered.get("status") == "incomplete":
        merged["status"] = "incomplete"
    else:
        merged["status"] = "review"
    return merged

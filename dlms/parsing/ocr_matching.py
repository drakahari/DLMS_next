"""Conservative OCR layout parsing for terminology and matching content."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from statistics import median
from typing import Any, Iterable


OCR_MATCHING_MAX_PAIRS = 100
OCR_MATCHING_MAX_UNASSIGNED = 100
OCR_MATCHING_MIN_COLUMN_CONFIDENCE = 70.0

_DASH_PAIR_RE = re.compile(r"^(.{1,240}?)\s+[\-\u2013\u2014]\s+(.+)$")
_COLON_PAIR_RE = re.compile(r"^(.{1,240}?):\s+(.+)$")
_TERM_LABEL_RE = re.compile(
    r"^\s*(?:term|concept|word)\s*[:\-\u2013\u2014]\s*(.*)$", re.IGNORECASE
)
_DEFINITION_LABEL_RE = re.compile(
    r"^\s*(?:definition|meaning)\s*[:\-\u2013\u2014]\s*(.*)$", re.IGNORECASE
)
_COLUMN_HEADER_RE = re.compile(
    r"^\s*(?:term|concept|word)\s*(?:\||:|[\-\u2013\u2014]|\s)\s*"
    r"(?:definition|meaning)\s*$",
    re.IGNORECASE,
)
_INLINE_FIELD_NAMES = {
    "answer", "chapter", "definition", "example", "meaning", "page",
    "question", "source", "term", "title",
}


@dataclass(frozen=True)
class OCRMatchingWord:
    text: str
    left: int
    top: int
    width: int
    height: int
    confidence: float

    @property
    def right(self) -> int:
        return self.left + self.width


@dataclass(frozen=True)
class OCRMatchingLine:
    text: str
    words: tuple[OCRMatchingWord, ...]
    page_index: int
    line_number: int
    left: int
    top: int
    width: int
    height: int
    confidence: float
    source_width: int

    @property
    def right(self) -> int:
        return self.left + self.width


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _box_field(observation: Any, name: str) -> int:
    box = _field(observation, "bounding_box")
    if isinstance(box, dict):
        return int(box.get(name, 0))
    return int(getattr(box, name, 0))


def _clean_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"\s+([,.;:!?])", r"\1", text)


def observations_to_matching_lines(
    observations: Iterable[Any] | dict[str, Any],
) -> list[OCRMatchingLine]:
    """Group bounded OCR words into deterministic visual lines."""
    if isinstance(observations, dict):
        observations = observations.get("observations") or ()
    groups: dict[tuple[str, int, int, int, int], list[Any]] = {}
    for observation in observations or ():
        text = _clean_text(_field(observation, "text", ""))
        if not text:
            continue
        key = (
            str(_field(observation, "source_id", "") or ""),
            int(_field(observation, "page_index", 0)),
            int(_field(observation, "block_id", 0)),
            int(_field(observation, "paragraph_id", 0)),
            int(_field(observation, "line_id", 0)),
        )
        groups.setdefault(key, []).append(observation)

    lines = []
    for key, observations_in_line in groups.items():
        observations_in_line.sort(
            key=lambda item: (_box_field(item, "left"), _box_field(item, "top"))
        )
        words = tuple(
            OCRMatchingWord(
                text=_clean_text(_field(item, "text", "")),
                left=_box_field(item, "left"),
                top=_box_field(item, "top"),
                width=max(1, _box_field(item, "width")),
                height=max(1, _box_field(item, "height")),
                confidence=float(_field(item, "confidence", 0.0)),
            )
            for item in observations_in_line
        )
        left = min(word.left for word in words)
        top = min(word.top for word in words)
        right = max(word.right for word in words)
        bottom = max(word.top + word.height for word in words)
        lines.append(
            OCRMatchingLine(
                text=_clean_text(" ".join(word.text for word in words)),
                words=words,
                page_index=key[1],
                line_number=key[4],
                left=left,
                top=top,
                width=max(1, right - left),
                height=max(1, bottom - top),
                confidence=sum(word.confidence for word in words) / len(words),
                source_width=max(
                    1,
                    max(
                        int(_field(item, "source_width", 0) or 0)
                        for item in observations_in_line
                    ),
                ),
            )
        )
    return sorted(lines, key=lambda line: (line.page_index, line.top, line.left))


def _inline_pair(text: str) -> tuple[str, str, str] | None:
    match = _DASH_PAIR_RE.fullmatch(text)
    pattern = "inline_dash"
    if match is None:
        match = _COLON_PAIR_RE.fullmatch(text)
        pattern = "inline_colon"
    if match is None:
        return None
    left, right = (_clean_text(match.group(1)), _clean_text(match.group(2)))
    if (
        not left
        or not right
        or len(left.split()) > 12
        or left.casefold() in _INLINE_FIELD_NAMES
        or left.endswith((".", "?", "!"))
    ):
        return None
    return left, right, pattern


def _column_split(line: OCRMatchingLine):
    if len(line.words) < 2 or line.confidence < OCR_MATCHING_MIN_COLUMN_CONFIDENCE:
        return None
    gaps = [
        (line.words[index + 1].left - line.words[index].right, index)
        for index in range(len(line.words) - 1)
    ]
    gap, index = max(gaps)
    if gap < max(32, int(line.source_width * 0.055)):
        return None
    left = _clean_text(" ".join(word.text for word in line.words[: index + 1]))
    right = _clean_text(" ".join(word.text for word in line.words[index + 1 :]))
    if not left or not right or len(left) > 240:
        return None
    split_x = (line.words[index].right + line.words[index + 1].left) / 2
    return left, right, split_x


def _metadata(
    line, *, source_id, source_index, source_name, source_page_number, pattern
):
    return {
        "source_id": str(source_id or ""),
        "source_index": int(source_index),
        "source_name": str(source_name or ""),
        "page_number": (
            int(source_page_number) if source_page_number is not None else None
        ),
        "line_number": line.line_number,
        "confidence": round(line.confidence, 1),
        "pattern": pattern,
    }


def _pair(
    left,
    right,
    line,
    *,
    source_id,
    source_index,
    source_name,
    source_page_number,
    pattern,
):
    return {
        "left": _clean_text(left),
        "right": _clean_text(right),
        "category": "",
        "explanation": "",
        "ocr_metadata": _metadata(
            line,
            source_id=source_id,
            source_index=source_index,
            source_name=source_name,
            source_page_number=source_page_number,
            pattern=pattern,
        ),
    }


def extract_ocr_matching_pairs(
    observations,
    *,
    source_id="",
    source_index=1,
    source_name="OCR source",
    source_page_number=None,
):
    """Extract only structurally supported pairs; retain every other OCR line."""
    lines = observations_to_matching_lines(observations)
    used: set[int] = set()
    pairs = []
    diagnostics = []

    # Explicit two-line fields are the strongest signal and may preserve one
    # missing side as a repairable record rather than guessing its partner.
    for index, line in enumerate(lines):
        if index in used:
            continue
        term_match = _TERM_LABEL_RE.fullmatch(line.text)
        definition_match = _DEFINITION_LABEL_RE.fullmatch(line.text)
        if term_match:
            left = _clean_text(term_match.group(1))
            following = lines[index + 1] if index + 1 < len(lines) else None
            following_match = (
                _DEFINITION_LABEL_RE.fullmatch(following.text)
                if following is not None and following.page_index == line.page_index
                else None
            )
            right = _clean_text(following_match.group(1)) if following_match else ""
            pairs.append(
                _pair(
                    left,
                    right,
                    line,
                    source_id=source_id,
                    source_index=source_index,
                    source_name=source_name,
                    source_page_number=source_page_number,
                    pattern="labeled_lines",
                )
            )
            used.add(index)
            if following_match:
                used.add(index + 1)
            else:
                diagnostics.append({
                    "severity": "warning",
                    "code": "incomplete_ocr_pair",
                    "path": f"source[{source_index}].line[{line.line_number}]",
                    "message": "A labeled term had no following labeled definition.",
                })
            continue
        if definition_match:
            pairs.append(
                _pair(
                    "",
                    definition_match.group(1),
                    line,
                    source_id=source_id,
                    source_index=source_index,
                    source_name=source_name,
                    source_page_number=source_page_number,
                    pattern="labeled_lines",
                )
            )
            used.add(index)
            diagnostics.append({
                "severity": "warning",
                "code": "incomplete_ocr_pair",
                "path": f"source[{source_index}].line[{line.line_number}]",
                "message": "A labeled definition had no preceding labeled term.",
            })

    for index, line in enumerate(lines):
        if index in used or _COLUMN_HEADER_RE.fullmatch(line.text):
            continue
        matched = _inline_pair(line.text)
        if matched is None:
            continue
        left, right, pattern = matched
        pairs.append(
            _pair(
                left,
                right,
                line,
                source_id=source_id,
                source_index=source_index,
                source_name=source_name,
                source_page_number=source_page_number,
                pattern=pattern,
            )
        )
        used.add(index)

    # A single large gap can be ordinary prose. Require at least two rows with
    # a consistent split on the same page before trusting a two-column layout.
    column_candidates = []
    for index, line in enumerate(lines):
        if index in used or _COLUMN_HEADER_RE.fullmatch(line.text):
            continue
        split = _column_split(line)
        if split is not None:
            column_candidates.append((index, line, *split))
    for page_index in sorted({item[1].page_index for item in column_candidates}):
        page_candidates = [
            item for item in column_candidates if item[1].page_index == page_index
        ]
        if len(page_candidates) < 2:
            continue
        center = median(item[4] for item in page_candidates)
        width = max(item[1].source_width for item in page_candidates)
        aligned = [
            item
            for item in page_candidates
            if abs(item[4] - center) <= max(24, width * 0.05)
        ]
        if len(aligned) < 2:
            continue
        for index, line, left, right, _split_x in aligned:
            pairs.append(
                _pair(
                    left,
                    right,
                    line,
                    source_id=source_id,
                    source_index=source_index,
                    source_name=source_name,
                    source_page_number=source_page_number,
                    pattern="aligned_columns",
                )
            )
            used.add(index)

    unassigned_lines = []
    for index, line in enumerate(lines):
        if index in used or _COLUMN_HEADER_RE.fullmatch(line.text):
            continue
        unassigned_lines.append({
            "text": line.text[:1000],
            "source_id": str(source_id or ""),
            "source_index": int(source_index),
            "source_name": str(source_name or ""),
            "page_number": (
                int(source_page_number) if source_page_number is not None else None
            ),
            "line_number": line.line_number,
            "confidence": round(line.confidence, 1),
        })
    unassigned = unassigned_lines[:OCR_MATCHING_MAX_UNASSIGNED]
    if unassigned_lines:
        diagnostics.append({
            "severity": "warning",
            "code": "unassigned_ocr_text",
            "path": f"source[{source_index}]",
            "message": (
                f"{len(unassigned)} OCR line(s) were retained as unassigned text "
                "because their pairing was not structurally clear."
            ),
        })
    if len(unassigned_lines) > OCR_MATCHING_MAX_UNASSIGNED:
        diagnostics.append({
            "severity": "warning",
            "code": "unassigned_ocr_text_limit",
            "path": f"source[{source_index}]",
            "message": (
                f"{len(unassigned_lines) - OCR_MATCHING_MAX_UNASSIGNED} additional "
                "unassigned OCR line(s) exceeded the diagnostic display limit."
            ),
        })
    if any(float(pair["ocr_metadata"]["confidence"]) < 65 for pair in pairs):
        diagnostics.append({
            "severity": "warning",
            "code": "low_ocr_confidence",
            "path": f"source[{source_index}]",
            "message": "One or more extracted pairs have low OCR confidence.",
        })
    pairs.sort(key=lambda pair: (
        int(pair["ocr_metadata"]["page_number"] or 0),
        int(pair["ocr_metadata"]["line_number"]),
    ))
    return {
        "pairs": pairs[:OCR_MATCHING_MAX_PAIRS],
        "unassigned": unassigned,
        "diagnostics": diagnostics,
        "line_count": len(lines),
        "truncated_pairs": max(0, len(pairs) - OCR_MATCHING_MAX_PAIRS),
    }

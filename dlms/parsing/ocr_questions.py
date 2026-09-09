"""Conservative layout inference for screenshot OCR observations.

The OCR engine deliberately returns only untrusted word observations.  This
module turns those observations into *review drafts*, never authoritative quiz
records.  Every OCR-derived question requires explicit correctness
confirmation before the Smart PDF workflow can save it as active content.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
import re
from typing import Any, Iterable


OCR_QUESTION_MAX_CHOICES = 26
OCR_QUESTION_MAX_RECORDS = 50
OCR_QUESTION_MAX_TEXT_CHARS = 250_000
OCR_LABELS = tuple(chr(ord("A") + index) for index in range(26))

_QUESTION_MARKER_RE = re.compile(
    r"^\s*(?:question|q)\s*(\d+)\s*[:.)-]?\s*(.*)$", re.IGNORECASE
)
_EXPLICIT_CHOICE_RE = re.compile(
    r"^\s*([A-Z]|\d{1,2})\s*[.)\]:-]\s+(.+?)\s*$", re.IGNORECASE
)
_ANSWER_KEY_RE = re.compile(
    r"\bcorrect\s+answers?\s*[:\-]\s*([^\n]+)", re.IGNORECASE
)
_FEEDBACK_KEY_RE = re.compile(
    r"\b(?:the\s+)?correct\s+answers?\s+(?:is|are)\s+([^.;\n]+)",
    re.IGNORECASE,
)
_MULTIPLE_MODE_RE = re.compile(
    r"\b(?:select|choose)\s+(?:all(?:\s+that\s+apply)?|two|three|multiple|\d+)\b|"
    r"\bmultiple\s+(?:answers?|responses?)\b",
    re.IGNORECASE,
)
_EXPLANATION_HEADING_RE = re.compile(
    r"^\s*(explanation|rationale|feedback|why\s+this\s+is\s+correct|"
    r"why\s+the\s+other\s+options\s+are\s+incorrect)\s*[:\-]?\s*(.*)$",
    re.IGNORECASE,
)
_CHOICE_FEEDBACK_RE = re.compile(
    r"^\s*([A-Z])\s*(?:feedback|explanation)\s*[:\-]\s*(.+)$",
    re.IGNORECASE,
)
_OBVIOUS_CHROME_RE = re.compile(
    r"^\s*(?:next|previous|back|submit|continue|explain\s+this\s+further|"
    r"menu|navigation|home)\s*[>»→]?\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class OCRLine:
    text: str
    left: int
    top: int
    width: int
    height: int
    confidence: float

    @property
    def bottom(self) -> int:
        return self.top + self.height


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _box_field(observation: Any, name: str) -> int:
    box = _field(observation, "bounding_box")
    if isinstance(box, dict):
        return int(box.get(name, 0))
    return int(getattr(box, name, 0))


def observations_to_lines(observations: Iterable[Any]) -> list[OCRLine]:
    """Combine bounded word observations into stable visual lines."""

    groups: dict[tuple[int, int, int, int], list[Any]] = {}
    for observation in observations:
        text = str(_field(observation, "text", "") or "").strip()
        if not text:
            continue
        key = (
            int(_field(observation, "page_index", 0)),
            int(_field(observation, "block_id", 0)),
            int(_field(observation, "paragraph_id", 0)),
            int(_field(observation, "line_id", 0)),
        )
        groups.setdefault(key, []).append(observation)

    lines: list[OCRLine] = []
    for words in groups.values():
        words.sort(key=lambda item: (_box_field(item, "left"), _box_field(item, "top")))
        left = min(_box_field(item, "left") for item in words)
        top = min(_box_field(item, "top") for item in words)
        right = max(_box_field(item, "left") + _box_field(item, "width") for item in words)
        bottom = max(_box_field(item, "top") + _box_field(item, "height") for item in words)
        confidences = [float(_field(item, "confidence", 0.0)) for item in words]
        text = " ".join(str(_field(item, "text", "") or "").strip() for item in words)
        text = re.sub(r"\s+([,.;:!?])", r"\1", text).strip()
        lines.append(
            OCRLine(
                text=text,
                left=left,
                top=top,
                width=max(1, right - left),
                height=max(1, bottom - top),
                confidence=sum(confidences) / len(confidences),
            )
        )
    return sorted(lines, key=lambda line: (line.top, line.left))


def _confidence_label(value: float) -> str:
    if value >= 85:
        return "high"
    if value >= 65:
        return "medium"
    return "low"


def _segment_lines(lines: list[OCRLine]) -> list[list[OCRLine]]:
    marker_indexes = [
        index for index, line in enumerate(lines) if _QUESTION_MARKER_RE.match(line.text)
    ]
    if len(marker_indexes) < 2:
        return [lines]
    segments = []
    for position, start in enumerate(marker_indexes):
        end = marker_indexes[position + 1] if position + 1 < len(marker_indexes) else len(lines)
        segments.append(lines[start:end])
    return segments


def _answer_labels(text: str) -> list[str]:
    answers = []
    for token in re.findall(r"\b([A-Z])\b", str(text or "").upper()):
        if token in OCR_LABELS and token not in answers:
            answers.append(token)
    return answers


def _looks_like_question(text: str) -> bool:
    normalized = text.strip().lower()
    return (
        normalized.endswith("?")
        or normalized.startswith(("which ", "what ", "who ", "when ", "where ", "why ", "how "))
        or bool(_MULTIPLE_MODE_RE.search(normalized))
    )


def _aligned_choice_block(lines: list[OCRLine], source_width: int) -> bool:
    if not 2 <= len(lines) <= OCR_QUESTION_MAX_CHOICES:
        return False
    lefts = [line.left for line in lines]
    if max(lefts) - min(lefts) > max(60, int(source_width * 0.08)):
        return False
    if len(lines) >= 3:
        gaps = [max(0, lines[index + 1].top - lines[index].bottom) for index in range(len(lines) - 1)]
        typical = median(gaps)
        tolerance = max(20, typical * 1.8)
        if any(abs(gap - typical) > tolerance for gap in gaps):
            return False
    return True


def _source_label(raw_label: str, expected: str) -> tuple[str, str | None]:
    label = raw_label.upper()
    if label == expected:
        return label, None
    if label == "8" and expected == "B":
        return expected, "OCR may have read source label B as 8."
    if label.isdigit():
        return expected, f"Numeric or ambiguous source label {label} was normalized by position."
    return expected, f"Source label {label} was normalized to positional label {expected}."


def _infer_one_question(
    lines: list[OCRLine], *, source_id: str, source_index: int, source_width: int
) -> dict[str, Any] | None:
    if not lines:
        return None
    issues: list[str] = []
    unassigned: list[str] = []
    content_lines: list[OCRLine] = []
    for line in lines:
        if _OBVIOUS_CHROME_RE.match(line.text):
            unassigned.append(line.text)
        else:
            content_lines.append(line)
    if not content_lines:
        return None

    marker = _QUESTION_MARKER_RE.match(content_lines[0].text)
    if marker:
        remainder = marker.group(2).strip()
        if remainder:
            content_lines[0] = OCRLine(
                remainder,
                content_lines[0].left,
                content_lines[0].top,
                content_lines[0].width,
                content_lines[0].height,
                content_lines[0].confidence,
            )
        else:
            unassigned.append(content_lines.pop(0).text)

    key_texts: list[str] = []
    explanation_lines: list[str] = []
    choice_feedback: dict[str, str] = {}
    body_lines: list[OCRLine] = []
    in_explanation = False
    for line in content_lines:
        feedback_match = _CHOICE_FEEDBACK_RE.match(line.text)
        heading_match = _EXPLANATION_HEADING_RE.match(line.text)
        if feedback_match:
            choice_feedback[feedback_match.group(1).upper()] = feedback_match.group(2).strip()
            continue
        if heading_match:
            in_explanation = True
            remainder = heading_match.group(2).strip()
            if remainder:
                explanation_lines.append(remainder)
            continue
        if _ANSWER_KEY_RE.search(line.text):
            key_texts.append(line.text)
            continue
        if in_explanation:
            explanation_lines.append(line.text)
        else:
            body_lines.append(line)

    explicit: list[tuple[OCRLine, str, str]] = []
    for line in body_lines:
        match = _EXPLICIT_CHOICE_RE.match(line.text)
        if match:
            explicit.append((line, match.group(1), match.group(2).strip()))

    question_lines: list[OCRLine] = []
    choice_texts: list[str] = []
    label_origin = "unknown"
    structure_confidence = "low"
    if len(explicit) >= 2:
        first_choice = body_lines.index(explicit[0][0])
        explicit_lines = {id(item[0]) for item in explicit}
        question_lines = body_lines[:first_choice]
        for index, (_line, raw_label, text) in enumerate(explicit):
            if index < OCR_QUESTION_MAX_CHOICES:
                expected = OCR_LABELS[index]
                _label, warning = _source_label(raw_label, expected)
                if warning:
                    issues.append(warning)
            choice_texts.append(text)
        for line in body_lines[first_choice:]:
            if id(line) not in explicit_lines:
                unassigned.append(line.text)
        label_origin = "source"
        structure_confidence = "high" if not issues else "medium"
    else:
        question_end = next(
            (index for index, line in enumerate(body_lines) if _looks_like_question(line.text)),
            0,
        )
        question_end += 1
        question_lines = body_lines[:question_end]
        candidates = body_lines[question_end:]
        if _looks_like_question(" ".join(line.text for line in question_lines)) and _aligned_choice_block(
            candidates, source_width
        ):
            choice_texts = [line.text.lstrip("•◦○◉□☐☑- ").strip() for line in candidates]
            label_origin = "inferred"
            structure_confidence = "medium"
            issues.append("Answer labels were inferred from aligned answer rows and require review.")
        else:
            unassigned.extend(line.text for line in candidates)
            issues.append("DLMS could not confidently identify separate answer rows.")

    if len(choice_texts) > OCR_QUESTION_MAX_CHOICES:
        unassigned.extend(choice_texts)
        choice_texts = []
        label_origin = "unknown"
        structure_confidence = "low"
        issues.append(
            "More than 26 likely answer rows were detected; none were truncated. "
            "Reconstruct this question with no more than 26 choices."
        )

    question_text = " ".join(line.text for line in question_lines).strip()
    if not question_text and body_lines:
        question_text = body_lines[0].text
        if body_lines[0].text in unassigned:
            unassigned.remove(body_lines[0].text)

    all_text = "\n".join(line.text for line in content_lines)
    explicit_answers: list[str] = []
    correctness_evidence = "unknown"
    for value in key_texts:
        match = _ANSWER_KEY_RE.search(value)
        if match:
            explicit_answers.extend(_answer_labels(match.group(1)))
    if explicit_answers:
        correctness_evidence = "explicit_source"
    else:
        feedback_match = _FEEDBACK_KEY_RE.search("\n".join(explanation_lines))
        if feedback_match:
            explicit_answers = _answer_labels(feedback_match.group(1))
            if explicit_answers:
                correctness_evidence = "explicit_feedback"
    explicit_answers = list(dict.fromkeys(explicit_answers))
    valid_labels = set(OCR_LABELS[: len(choice_texts)])
    correct_answers = [answer for answer in explicit_answers if answer in valid_labels]
    if len(correct_answers) != len(explicit_answers):
        issues.append("The detected answer key referenced a label outside the detected choices.")

    multiple_wording = bool(_MULTIPLE_MODE_RE.search(all_text))
    answer_mode = "multiple" if multiple_wording or len(correct_answers) > 1 else "single"
    answer_mode_evidence = (
        "explicit_instruction"
        if multiple_wording
        else ("explicit_answer_key" if correct_answers else "unknown")
    )
    if answer_mode_evidence == "unknown":
        issues.append("Answer mode was not explicit; verify single-answer or multiple-answer mode.")

    text_confidence = _confidence_label(
        sum(line.confidence for line in content_lines) / len(content_lines)
    )
    if text_confidence == "low":
        issues.append("OCR text confidence is low; compare every field with the source image.")

    complete_structure = bool(question_text and 2 <= len(choice_texts) <= 26)
    status = "review" if complete_structure else "incomplete"
    if not complete_structure:
        structure_confidence = "low"

    return {
        "number": source_index,
        "question": question_text,
        "choices": [
            {
                "label": OCR_LABELS[index],
                "text": text,
                "label_origin": label_origin,
            }
            for index, text in enumerate(choice_texts)
        ],
        "correct_answers": correct_answers,
        "answer_mode": answer_mode,
        "answer_mode_evidence": answer_mode_evidence,
        "correctness_confirmation_required": True,
        "correctness_confirmed": False,
        "correctness_evidence": correctness_evidence,
        "declared_answer_text": "\n".join(key_texts),
        "explanation": "\n".join(explanation_lines).strip(),
        "choice_feedback": choice_feedback,
        "pages": [source_index],
        "status": status,
        "issues": list(dict.fromkeys(issues)),
        "ocr_metadata": {
            "source_id": source_id,
            "source_index": source_index,
            "label_origin": label_origin,
            "text_confidence": text_confidence,
            "structure_confidence": structure_confidence,
            "correctness_evidence": correctness_evidence,
            "unassigned_text": "\n".join(dict.fromkeys(unassigned)).strip(),
        },
    }


def infer_screenshot_questions(
    observations: Iterable[Any], *, source_id: str, source_index: int
) -> dict[str, Any]:
    """Return bounded Smart PDF review records for one screenshot."""

    observations = tuple(observations)
    if not observations:
        return {"questions": [], "raw_text": "", "warnings": ["No readable OCR text was detected."]}
    source_width = int(_field(observations[0], "source_width", 0))
    lines = observations_to_lines(observations)
    raw_text = "\n".join(line.text for line in lines)
    if len(raw_text) > OCR_QUESTION_MAX_TEXT_CHARS:
        raise ValueError("OCR text exceeds the screenshot review limit.")

    questions = []
    segments = _segment_lines(lines)
    for segment in segments[:OCR_QUESTION_MAX_RECORDS]:
        question = _infer_one_question(
            segment,
            source_id=source_id,
            source_index=source_index,
            source_width=source_width,
        )
        if question:
            question["number"] = len(questions) + 1
            questions.append(question)
    warnings = []
    if len(segments) > OCR_QUESTION_MAX_RECORDS:
        overflow = "\n".join(
            line.text
            for segment in segments[OCR_QUESTION_MAX_RECORDS:]
            for line in segment
        )
        warning = (
            f"More than {OCR_QUESTION_MAX_RECORDS} clear question regions were detected. "
            "The remaining OCR text was preserved for manual review rather than truncated."
        )
        warnings.append(warning)
        if questions:
            questions[-1].setdefault("issues", []).append(warning)
            metadata = questions[-1].setdefault("ocr_metadata", {})
            existing = str(metadata.get("unassigned_text") or "").strip()
            metadata["unassigned_text"] = "\n".join(
                part for part in (existing, overflow) if part
            )
    return {"questions": questions, "raw_text": raw_text, "warnings": warnings}

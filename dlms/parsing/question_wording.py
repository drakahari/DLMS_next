"""Shared, explicit wording signals for choice-question semantics."""

import re


_MULTIPLE_ANSWER_WORDING_RE = re.compile(
    r"\b(?:select|choose)\s+(?:all(?:\s+that\s+apply)?|two|three|multiple|\d+)\b|"
    r"\bmultiple\s+(?:answers?|responses?)\b",
    re.IGNORECASE,
)


def question_wording_selects_multiple(text):
    """Return true only for an explicit multiple-answer instruction."""
    return bool(_MULTIPLE_ANSWER_WORDING_RE.search(str(text or "")))

"""Pure parsing and filename normalization for DLMS Law Study packets."""

import os
import re

from werkzeug.utils import secure_filename as _secure_filename


def make_law_case_slug(case_name):
    """
    Create a safe, readable slug from a case name for filenames.
    Example: Hadley v. Baxendale -> hadley_v_baxendale
    """
    slug = str(case_name or "").strip().lower()

    # Normalize common case-name punctuation/spacing
    slug = slug.replace(" v. ", " v ")
    slug = slug.replace(" vs. ", " v ")
    slug = slug.replace(" versus ", " v ")

    # Keep only letters, numbers, and underscores
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = re.sub(r"_+", "_", slug).strip("_")

    return slug[:80] or "untitled_case"


def extract_law_slug_from_import_filename(filename, *, secure_filename=_secure_filename):
    """
    Extract the case slug from a raw Law import filename.

    Example:
    law_import_20260510_133709_hadley_v_baxendale.txt
    -> hadley_v_baxendale
    """
    name = secure_filename(filename or "")
    base = os.path.splitext(name)[0]

    match = re.match(r"^law_import_\d{8}_\d{6}_(.+)$", base)

    if match:
        slug = match.group(1).strip("_")
        return slug[:80] or ""

    return ""


def safe_law_import_filename(filename, *, secure_filename=_secure_filename):
    """
    Restrict Law import filenames to saved .txt files in the Law imports folder.
    Prevents path traversal.
    """
    filename = secure_filename(filename or "")

    if not filename.lower().endswith(".txt"):
        return ""

    return filename


def parse_law_packet_sections(raw_text):
    """
    Lightweight parser for previewing DLMS Law Study import sections.
    Does not save anything. It only splits recognized headings.
    """
    headings = [
        ("sources_used", "Sources Used"),
        ("case_brief", "1. Case Brief"),
        ("socratic_review", "2. Socratic Review"),
        ("socratic_answer_key", "2A. Socratic Answer Key"),
        ("irac_drill", "3. IRAC Drill"),
        ("rule_flashcards", "4. Rule Flashcards"),
    ]

    found = []

    for key, title in headings:
        pattern = re.compile(rf"(?im)^\s*{re.escape(title)}\s*$")
        match = pattern.search(raw_text)

        if match:
            found.append({
                "key": key,
                "title": title,
                "start": match.start(),
                "end": match.end()
            })

    found.sort(key=lambda x: x["start"])

    sections = []

    for idx, item in enumerate(found):
        content_start = item["end"]
        content_end = found[idx + 1]["start"] if idx + 1 < len(found) else len(raw_text)
        content = raw_text[content_start:content_end].strip()

        sections.append({
            "key": item["key"],
            "title": item["title"],
            "content": content,
            "char_count": len(content),
            "line_count": len(content.splitlines()) if content else 0
        })

    return sections


def extract_law_case_title(raw_text, fallback_filename="Untitled Case Review"):
    """Best-effort title extraction from a Law Study import packet."""
    patterns = [
        r"(?im)^\s*Full case name and citation\s*:\s*(.+)$",
        r"(?im)^\s*Case\s*:\s*(.+)$",
        r"(?im)^\s*Case Name\s*:\s*(.+)$",
        r"(?im)^\s*#\s*(.+)$",
    ]

    for pattern in patterns:
        match = re.search(pattern, raw_text)
        if match:
            title = match.group(1).strip()
            if title:
                return title[:160]

    name = os.path.splitext(fallback_filename)[0]
    name = name.replace("law_import_", "Case Review ")
    name = name.replace("_", " ")
    return name.strip() or "Untitled Case Review"


def parse_socratic_questions(socratic_text):
    """
    Best-effort parser for Socratic questions.
    Supports the legacy numbered and bullet formats accepted by DLMS.
    """
    questions = []

    if not socratic_text:
        return questions

    text = socratic_text.strip()

    pattern = re.compile(
        r"""(?imsx)
        ^\s*
        (?:
            Question\s+(\d+)\s*[:\.\)]      # Question 1:
            |
            Q?(\d+)\s*[\.\)]                # 1. / 1) / Q1.
        )
        \s+
        (.*?)
        (?=
            ^\s*(?:Question\s+\d+\s*[:\.\)]|Q?\d+\s*[\.\)])\s+
            |
            \Z
        )
        """
    )

    for match in pattern.finditer(text):
        number = match.group(1) or match.group(2)
        question_text = match.group(3).strip()

        question_text = re.sub(r"^\*+", "", question_text).strip()
        question_text = re.sub(r"\*+$", "", question_text).strip()

        if number and question_text:
            questions.append({
                "id": f"q{number}",
                "number": number,
                "text": question_text
            })

    if not questions:
        bullet_pattern = re.compile(r"(?im)^\s*[-*]\s+(.+\?)\s*$")

        for idx, match in enumerate(bullet_pattern.finditer(text), start=1):
            question_text = match.group(1).strip()

            if question_text:
                questions.append({
                    "id": f"q{idx}",
                    "number": str(idx),
                    "text": question_text
                })

    return questions

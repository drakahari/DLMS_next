"""Legacy plain-text quiz parsing and confidence analysis."""

import os
import re


def parse_questions(source, *, parse_log=None, debug_log=None):
    if parse_log is None:
        parse_log = []
    if debug_log is None:
        debug_log = lambda *msg: None

    parse_log.clear()
    debug_log("=== NEW PARSE SESSION STARTED ===")

    # Allow BOTH: file paths OR already-loaded quiz text
    if isinstance(source, str) and os.path.isfile(source):
        debug_log("Input detected as FILE path → reading file")
        with open(source, "r", encoding="utf-8", errors="ignore") as f:
            raw = f.read()
    else:
        debug_log("Input detected as RAW TEXT → using directly")
        raw = source

    # Normalize newlines
    text = raw.replace("\r\n", "\n").replace("\r", "\n")

    # Remove UTF-8 BOM if present
    text = text.lstrip("\ufeff")
    debug_log("BOM stripped (if present)")

    # Split into question blocks
    blocks = re.split(
        r"(?=^\s*(?:Question\s*#?\s*\d+|\d+\s*[.) ]))",
        text,
        flags=re.IGNORECASE | re.MULTILINE
    )

    debug_log("Total detected blocks:", len(blocks))

    questions = []
    fallback_number = 1

    for block in blocks:
        original_block = block
        block = block.strip()
        if not block:
            debug_log("Skipped: empty block")
            continue

        lines = [l.strip() for l in block.split("\n") if l.strip()]
        if len(lines) < 2:
            debug_log("Skipped: too few lines:", repr(lines))
            continue

        qnum_match = re.match(
            r'^\s*(?:Question\s*#?\s*(\d+)|(\d+)\s*[.)])',
            lines[0],
            re.IGNORECASE
        )

        source_number = None
        if qnum_match:
            source_number = int(qnum_match.group(1) or qnum_match.group(2))

        q_number = source_number if source_number is not None else fallback_number

        debug_log(f"\n--- Parsing Question Candidate #{q_number} ---")
        debug_log(lines[0])

        q_lines = []
        raw_choices = []
        correct_letters = []
        choices_started = False

        for line in lines:
            lower = line.lower()

            # -------- Detect Choices --------
            mchoice = re.match(r"^\s*([A-Za-z])[\.\)]\s+(.*)", line)
            if mchoice:
                label = mchoice.group(1).upper()
                text_choice = mchoice.group(2).strip()
                debug_log(f"Choice detected: {label} → {text_choice}")
                choices_started = True

                raw_choices.append({
                    "label": label,
                    "text": text_choice
                })
                continue

            # -------- Detect Correct Answer --------
            if "correct answer" in lower or "suggested answer" in lower:
                debug_log("Found answer line:", line)

                m = re.search(r"[:\-]\s*([A-Za-z]+)", line)
                if m:
                    ans = re.sub(r"[^A-Za-z]", "", m.group(1)).upper()
                    if ans:
                        correct_letters = list(dict.fromkeys(list(ans)))
                        debug_log("Parsed correct letters:", correct_letters)
                continue

            # -------- Question Text --------
            if not choices_started:
                if not (
                    lower.startswith("correct answer")
                    or lower.startswith("suggested answer")
                ):
                    q_lines.append(line)

        # ================================
        # VALIDATION
        # ================================
        if not correct_letters:
            debug_log("!! Skipped: NO correct answer found")
            debug_log(original_block[:200])
            continue

        if len(raw_choices) < 2:
            debug_log("!! Skipped: Not enough choices:", raw_choices)
            continue

        # Build question text
        question_text = " ".join(q_lines)
        question_text = re.sub(
            r'^(?:Question\s*#?\s*\d+[\).\s-]*|\d+[\).\s-]*)\s*',
            '',
            question_text,
            flags=re.IGNORECASE
        ).strip()

        # ================================
        # FINALIZE CHOICES (ADD is_correct)
        # ================================
        choices = []
        for c in raw_choices:
            choices.append({
                "label": c["label"],
                "text": c["text"],
                "is_correct": c["label"] in correct_letters
            })

        debug_log("Final Question Built:", question_text[:150])

        questions.append({
            "number": q_number,
            "question": question_text,
            "choices": choices,
            "correct": correct_letters
        })

        debug_log("✓ Question Accepted\n")
        fallback_number += 1

    debug_log("\n==== PARSE COMPLETE ====")
    debug_log("Total questions parsed:", len(questions))

    return questions


def analyze_confidence(clean_text):
    """
    Heuristic pre-check of the raw text BEFORE parsing.
    Used only for preview so the user can see if their input
    looks parse-friendly.
    """
    blocks = re.split(
        r"(?=^\s*(?:Question\s*#?\s*\d+|\d+\s*[.) ]))",
        clean_text,
        flags=re.IGNORECASE | re.MULTILINE
    )

    details = []
    high = med = low = 0
    idx = 0

    for raw in blocks:
        block = raw.strip()
        if not block:
            continue

        idx += 1
        lines = [l.strip() for l in block.split("\n") if l.strip()]
        txt = " ".join(lines)

        # Basic signals
        # Detect ANY lettered choices A–Z
        has_choice = any(re.match(r"^[A-Za-z][\.\)]\s+", l) for l in lines)

        has_answer_line = any(
            ("correct answer" in l.lower()) or ("suggested answer" in l.lower())
            for l in lines
        )
        num_choices = sum(
            1 for l in lines if re.match(r"^[A-Za-z][\.\)]\s+", l)

        )

        score = 0
        reason = []

        if has_choice:
            score += 1
            reason.append("Found A–Z answer choices")
        else:
            reason.append("No A–Z answer choices found")

        if has_answer_line:
            score += 1
            reason.append("Found 'Correct/Suggested Answer' line")
        else:
            reason.append("No explicit correct-answer line found")

        if num_choices >= 2:

            score += 1
            reason.append(f"{num_choices} choices detected")
        else:
            reason.append(f"{num_choices} choices detected (unusual count)")

        if score == 3:
            conf = "high"
            high += 1
        elif score == 2:
            conf = "medium"
            med += 1
        else:
            conf = "low"
            low += 1

        title = lines[0][:80] if lines else "[empty]"

        details.append({
            "index": idx,
            "title": title,
            "confidence": conf,
            "reason": "; ".join(reason),
        })

    summary = {
        "high": high,
        "medium": med,
        "low": low,
        "total": len(details),
    }
    return summary, details

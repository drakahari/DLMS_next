"""Smart PDF text extraction and parsing engine."""

import re


PDF_IMPORT_MAX_PAGES = 2000
PDF_IMPORT_MAX_EXTRACTED_TEXT_BYTES = 16 * 1024 * 1024
PDF_IMPORT_MAX_PAGE_TEXT_BYTES = 2 * 1024 * 1024


class PDFResourceLimitError(ValueError):
    pass


def _format_bytes(value):
    value = float(value or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024


def _pdf_clean_line(line):
    line = str(line or "").replace("\u00ad", "").replace("\u200b", "")
    line = line.replace("\ufeff", "").replace("\u00a0", " ")
    line = re.sub(r"[ \t]+", " ", line).strip()
    return line


def _pdf_page_has_images(page, *, max_depth=4):
    """Inspect direct and form-nested XObjects without decoding image data."""

    visited = set()

    def _resolve(value):
        return value.get_object() if hasattr(value, "get_object") else value

    def _contains_image(value, depth):
        if depth > max_depth:
            return False
        value = _resolve(value)
        identity = id(value)
        if identity in visited:
            return False
        visited.add(identity)
        if not hasattr(value, "get"):
            return False
        if str(value.get("/Subtype")) == "/Image":
            return True
        resources = _resolve(value.get("/Resources") or {})
        xobjects = _resolve(resources.get("/XObject") or {})
        return bool(hasattr(xobjects, "values")) and any(
            _contains_image(item, depth + 1) for item in xobjects.values()
        )

    return _contains_image(page, 0)

def _pdf_extract_pages(
    pdf_path,
    *,
    max_pages=PDF_IMPORT_MAX_PAGES,
    max_extracted_text_bytes=PDF_IMPORT_MAX_EXTRACTED_TEXT_BYTES,
    max_page_text_bytes=PDF_IMPORT_MAX_PAGE_TEXT_BYTES,
    resource_limit_error=PDFResourceLimitError,
    format_bytes=_format_bytes,
    clean_line=_pdf_clean_line,
):
    """Extract selectable PDF text within explicit page and text work limits."""
    try:
        from pypdf import PdfReader
    except Exception as exc:
        raise RuntimeError(
            "Smart PDF Import requires the 'pypdf' package. Install project requirements and rebuild the binary."
        ) from exc

    try:
        reader = PdfReader(pdf_path)
    except Exception as exc:
        raise ValueError("PDF is malformed or cannot be read.") from exc
    if reader.is_encrypted:
        raise ValueError("Encrypted PDFs are not supported. Remove encryption and try again.")
    try:
        page_count = len(reader.pages)
    except Exception as exc:
        raise ValueError("PDF page structure is malformed or cannot be read.") from exc
    if page_count > max_pages:
        raise resource_limit_error(f"PDF exceeds the {max_pages:,}-page limit.")

    pages = []
    total_text_bytes = 0
    total_styled_text_bytes = 0
    for page_number, page in enumerate(reader.pages, 1):
        fragments = []
        page_styled_text_bytes = 0

        def _visitor_text(fragment_text, cm, tm, font_dict, font_size):
            nonlocal page_styled_text_bytes, total_styled_text_bytes
            cleaned = clean_line(str(fragment_text or "").replace("\\n", " "))
            if not cleaned:
                return
            fragment_bytes = len(cleaned.encode("utf-8"))
            page_styled_text_bytes += fragment_bytes
            total_styled_text_bytes += fragment_bytes
            if page_styled_text_bytes > max_page_text_bytes:
                raise resource_limit_error(
                    f"PDF page {page_number} exceeds the {format_bytes(max_page_text_bytes)} extracted-text limit."
                )
            if total_styled_text_bytes > max_extracted_text_bytes:
                raise resource_limit_error(
                    f"PDF exceeds the {format_bytes(max_extracted_text_bytes)} extracted-text limit."
                )
            font_name = str((font_dict or {}).get("/BaseFont") or "")
            fragments.append({
                "text": cleaned,
                "x": float(tm[4]) if tm and len(tm) > 4 else 0.0,
                "y": float(tm[5]) if tm and len(tm) > 5 else 0.0,
                "font": font_name,
                "bold": bool(re.search(r"(?:bold|black|heavy|demi|semibold)", font_name, re.I)),
            })

        try:
            text = page.extract_text(visitor_text=_visitor_text) or ""
        except resource_limit_error:
            raise
        except Exception:
            # Style metadata is optional. Retry plain extraction only when the
            # visitor interface itself is incompatible with an otherwise valid PDF.
            fragments = []
            total_styled_text_bytes -= page_styled_text_bytes
            page_styled_text_bytes = 0
            try:
                text = page.extract_text() or ""
            except Exception as exc:
                raise ValueError(f"PDF page {page_number} could not be parsed.") from exc

        page_text_bytes = len(text.encode("utf-8"))
        if page_text_bytes > max_page_text_bytes:
            raise resource_limit_error(
                f"PDF page {page_number} exceeds the {format_bytes(max_page_text_bytes)} extracted-text limit."
            )
        total_text_bytes += page_text_bytes
        if total_text_bytes > max_extracted_text_bytes:
            raise resource_limit_error(
                f"PDF exceeds the {format_bytes(max_extracted_text_bytes)} extracted-text limit."
            )

        lines = [clean_line(line) for line in text.splitlines()]
        page_record = {"page": page_number, "lines": [line for line in lines if line]}
        # This is only a preflight signal.  Inspect the page resource dictionary
        # without decoding images so normal selectable-text extraction stays
        # lightweight and the OCR offer can distinguish obvious blank pages.
        try:
            page_record["has_images"] = _pdf_page_has_images(page)
        except Exception:
            page_record["has_images"] = False
        try:
            styled_lines = []
            for fragment in fragments:
                if styled_lines and abs(float(styled_lines[-1]["y"]) - float(fragment["y"])) <= 1.25:
                    styled_lines[-1]["fragments"].append(fragment)
                else:
                    styled_lines.append({"y": fragment["y"], "fragments": [fragment]})
            normalized_styled = []
            for styled in styled_lines:
                parts = sorted(styled["fragments"], key=lambda item: float(item.get("x") or 0.0))
                text_parts = [str(item.get("text") or "").strip() for item in parts if str(item.get("text") or "").strip()]
                line_text = clean_line(" ".join(text_parts))
                if line_text:
                    normalized_styled.append({"text": line_text, "y": styled["y"], "fragments": parts})
            if normalized_styled:
                page_record["styled_lines"] = normalized_styled
        except Exception:
            page_record.pop("styled_lines", None)
        pages.append(page_record)
    return pages

def _pdf_suppress_repeated_margins(pages):
    """
    Suppress likely repeated headers/footers/watermarks before semantic parsing.

    We intentionally do not delete arbitrary repeated body text. A line must either:
    - repeat in page margins on at least half the pages, or
    - repeat on at least half the pages and look watermark-like (short brand text,
      not question/choice/answer content).
    """
    if len(pages) < 2:
        return pages, []

    occurrences = {}
    margin_occurrences = {}
    locations = {}

    def _is_structural(line):
        return bool(re.match(
            r"^(?:question\s*#?\s*\d+|[A-Z]\.\s+|correct\s+answer:|why\s+the\s+other\s+options)",
            line,
            re.I,
        ))

    for page in pages:
        lines = page["lines"]
        margin_indexes = set(range(min(3, len(lines))))
        margin_indexes.update(range(max(0, len(lines) - 3), len(lines)))

        seen_on_page = set()
        seen_margin_on_page = set()
        for idx, line in enumerate(lines):
            if not line or _is_structural(line):
                continue
            norm = re.sub(r"\s+", " ", line).strip().casefold()
            if not norm:
                continue
            if norm not in seen_on_page:
                occurrences[norm] = occurrences.get(norm, 0) + 1
                locations.setdefault(norm, set()).add(page["page"])
                seen_on_page.add(norm)
            if idx in margin_indexes and norm not in seen_margin_on_page:
                margin_occurrences[norm] = margin_occurrences.get(norm, 0) + 1
                seen_margin_on_page.add(norm)

    threshold = max(2, (len(pages) + 1) // 2)
    repeated = set()

    for norm, count in occurrences.items():
        if count < threshold or len(locations.get(norm, ())) < threshold:
            continue

        # Strong case: repeated in page margins.
        if margin_occurrences.get(norm, 0) >= threshold:
            repeated.add(norm)
            continue

        # Watermark-like repeated brand text anywhere on the page.
        # Keep this conservative: short, no sentence punctuation, and not study prose.
        if (
            len(norm) <= 48
            and not re.search(r"[?.!,:;]", norm)
            and len(norm.split()) <= 5
            and not re.search(
                r"\b(?:question|answer|correct|incorrect|tester|application|security|penetration|which|following)\b",
                norm,
                re.I,
            )
        ):
            repeated.add(norm)

    removed = sorted({
        line
        for page in pages
        for line in page["lines"]
        if re.sub(r"\s+", " ", line).strip().casefold() in repeated
    })

    cleaned = []
    for page in pages:
        item = {
            "page": page["page"],
            "lines": [
                line for line in page["lines"]
                if re.sub(r"\s+", " ", line).strip().casefold() not in repeated
            ],
            "has_images": bool(page.get("has_images")),
        }
        if isinstance(page.get("styled_lines"), list):
            item["styled_lines"] = [
                line for line in page["styled_lines"]
                if re.sub(r"\s+", " ", str(line.get("text") or "")).strip().casefold() not in repeated
            ]
        cleaned.append(item)
    return cleaned, removed

def _pdf_lines_to_stream(pages):
    records = []
    for page in pages:
        for line in page["lines"]:
            records.append({"page": page["page"], "text": line})
    return records

def _pdf_join_wrapped(lines):
    """Join wrapped PDF lines while preserving structural markers."""
    if not lines:
        return ""
    out = ""
    structural = re.compile(
        r"^(?:Question\s*#?\s*\d+|[A-Z]\.\s+|Correct Answer:|Why The Other Options Are Incorrect)",
        re.I,
    )
    for raw in lines:
        line = _pdf_clean_line(raw)
        if not line:
            continue
        if not out:
            out = line
            continue
        if out.endswith("-") and line[:1].islower():
            out = out[:-1] + line
        elif structural.match(line):
            out += "\n" + line
        else:
            out += " " + line
    return out.strip()

def _pdf_parse_question_chunk(number, records):
    lines = [r["text"] for r in records if r.get("text")]
    pages = sorted({int(r["page"]) for r in records if r.get("page")})
    if not lines:
        return None

    answer_idx = None
    answer_match = None
    for i, line in enumerate(lines):
        m = re.search(r"Correct\s+Answer:\s*([A-Z])(?:\s*[—–-]\s*(.*?))?\s*✅?\s*$", line, re.I)
        if m:
            answer_idx = i
            answer_match = m
            break

    choice_scan_end = answer_idx if answer_idx is not None else len(lines)
    choice_starts = []
    for i in range(choice_scan_end):
        m = re.match(r"^([A-Z])\.\s+(.+)$", lines[i])
        if m:
            choice_starts.append((i, m.group(1).upper(), m.group(2).strip()))

    # Keep a contiguous A/B/C... option run. Explanatory A./B. lines occur after the answer marker.
    choices = []
    if choice_starts:
        run = [choice_starts[0]]
        for item in choice_starts[1:]:
            prev_label = run[-1][1]
            if ord(item[1]) == ord(prev_label) + 1:
                run.append(item)
            elif len(run) < 2:
                run = [item]
            else:
                break
        if len(run) >= 2:
            for pos, (line_idx, label, first_text) in enumerate(run):
                end = run[pos + 1][0] if pos + 1 < len(run) else choice_scan_end
                extra = lines[line_idx + 1:end]
                text = _pdf_join_wrapped([first_text] + extra)
                choices.append({"label": label, "text": text})

    first_choice_index = choice_starts[0][0] if choices else choice_scan_end
    stem_lines = lines[:first_choice_index]
    question_text = _pdf_join_wrapped(stem_lines)

    correct_label = answer_match.group(1).upper() if answer_match else ""
    declared_answer_text = (answer_match.group(2) or "").strip(" ✅") if answer_match else ""

    # Some PDFs wrap the printed "Correct Answer: X — answer text" across lines.
    # Reconstruct that wrapped answer text before we decide where the explanation begins.
    answer_continuation_count = 0
    if answer_idx is not None and declared_answer_text and correct_label:
        selected_choice_text = next(
            (c["text"] for c in choices if c.get("label") == correct_label),
            "",
        )

        def _answer_cmp(value):
            return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())

        selected_norm = _answer_cmp(selected_choice_text)
        declared_norm = _answer_cmp(declared_answer_text)

        if selected_norm and declared_norm and selected_norm.startswith(declared_norm):
            candidate = declared_answer_text
            for next_line in lines[answer_idx + 1:]:
                if re.match(r"^Why The Other Options Are Incorrect", next_line, re.I):
                    break
                candidate_next = _pdf_join_wrapped([candidate, next_line])
                candidate_norm = _answer_cmp(candidate_next)

                # Consume only lines that continue to be a prefix of the already-detected
                # correct choice. This prevents explanation prose from being swallowed.
                if candidate_norm and selected_norm.startswith(candidate_norm):
                    candidate = candidate_next
                    answer_continuation_count += 1
                    if candidate_norm == selected_norm:
                        break
                else:
                    break

            declared_answer_text = candidate

    explanation = ""
    feedback = {}
    if answer_idx is not None:
        after = lines[answer_idx + 1 + answer_continuation_count:]
        why_idx = next(
            (i for i, line in enumerate(after) if re.match(r"^Why The Other Options Are Incorrect", line, re.I)),
            None,
        )
        explanation_lines = after if why_idx is None else after[:why_idx]
        explanation = _pdf_join_wrapped(explanation_lines)
        feedback_lines = [] if why_idx is None else after[why_idx + 1:]
        current = None
        buffer = []
        for line in feedback_lines:
            # PDF extraction sometimes collapses "C. A true..." into "C.A true..."
            # or "/etc" examples into "A./etc...". Accept both forms here only.
            m = re.match(r"^([A-Z])\.\s*(.+)$", line)
            if m:
                if current:
                    feedback[current] = _pdf_join_wrapped(buffer)
                current = m.group(1).upper()
                buffer = [m.group(2)]
            elif current:
                buffer.append(line)
        if current:
            feedback[current] = _pdf_join_wrapped(buffer)

    issues = []
    status = "complete"
    labels = {c["label"] for c in choices}
    if not question_text:
        issues.append("Question text was not detected.")
    if len(choices) < 2:
        issues.append("Fewer than two answer choices were detected.")
    if not correct_label:
        issues.append("A correct-answer marker was not detected.")
    elif correct_label not in labels:
        issues.append(f"Correct answer {correct_label} does not match a detected choice.")
    if declared_answer_text and correct_label in labels:
        selected = next((c["text"] for c in choices if c["label"] == correct_label), "")
        a = re.sub(r"\W+", "", selected).casefold()
        b = re.sub(r"\W+", "", declared_answer_text).casefold()
        if a and b and a != b:
            issues.append("Correct-answer text does not exactly match the selected choice; review recommended.")

    embedded_cue = re.search(
        r"""(?ix)
        \b(
            refer\s+to\s+(?:the\s+)?(?:exhibit|image|figure|diagram|screenshot|output|result)
          | review\s+(?:the\s+)?(?:exhibit|image|figure|diagram|screenshot|output|result)
          | shown\s+below
          | displayed\s+below
          | based\s+on\s+(?:the\s+)?(?:output|result|scan|report|exhibit)
          | see\s+(?:the\s+)?following\s+(?:code|command|snippet|payload|output|result|diagram|image|figure|screenshot)
          | given\s+(?:the\s+)?following\s+(?:code|command|snippet|payload|output|result|diagram|image|figure|screenshot)
          | following\s+(?:code\s+snippet|code|command|payload|output|result|diagram|image|figure|screenshot|vulnerability)
          | analyze\s+(?:the\s+)?(?:following\s+)?(?:code|command|payload|output|result|diagram|image|figure|screenshot)
        )\b
        """,
        question_text,
    )

    # Evidence that the referenced material actually survived text extraction.
    # Do not treat a mere word such as "Nmap" as proof that its output table is present.
    embedded_material_present = re.search(
        r"""(?ix)
        <\?xml
        | <!DOCTYPE
        | </?\s*script\b
        | </?\s*[a-z][a-z0-9:_-]*\b[^>]*>
        | \b(?:powershell|cmd|bash|sh|python)\b[^\n]{0,40}[>$#]
        | \b[a-z]:\\[^\s]+
        | \\\\[a-z0-9_.-]+
        | \b(?:tcp|udp)/\d+\b
        | \b\d{1,5}/(?:tcp|udp)\b
        | \b(?:open|filtered|closed)\s+(?:ssh|smtp|http|https|nfs|rpcbind|ftp|telnet)\b
        | \bSELECT\b.+\bFROM\b
        | \bcurl\b\s+\S+
        | \bnmap\b\s+-\S+
        | \bfindstr\b\s+/
        | \bpsexec(?:\.exe)?\b
        | \bsc\s+config\b
        | \bfor\s+\w+\s+in\s+
        | \bif\s+.+:
        """,
        question_text,
    )

    # Some scanner/result blocks are plain prose rather than code. If the cue is followed
    # by several distinct data-looking clauses before the actual question, treat that as
    # preserved embedded material (for example cloud scanner findings).
    if embedded_cue and not embedded_material_present:
        cue_tail = question_text[embedded_cue.end():]
        before_question = re.split(
            r"\bWhich\s+of\s+the\s+following\b|\bWhat\s+should\b|\bBased\s+on\b",
            cue_tail,
            maxsplit=1,
            flags=re.I,
        )[0]
        data_tokens = re.findall(
            r"\b(?:vulnerability|port\s+\d+|publicly\s+accessible|server-side|cross-site|storage|ssh|http|metadata|severity|issue\s+\d+)\b",
            before_question,
            re.I,
        )
        if len(data_tokens) >= 3 and len(before_question.split()) >= 12:
            embedded_material_present = True

    if embedded_cue and not embedded_material_present:
        issues.append("Prompt references embedded/code/visual content that may not be present in extracted text.")

    if issues:
        status = "review" if question_text and len(choices) >= 2 else "incomplete"

    return {
        "number": int(number),
        "question": question_text,
        "choices": choices,
        "correct": correct_label,
        "declared_answer_text": declared_answer_text,
        "explanation": explanation,
        "choice_feedback": feedback,
        "pages": pages,
        "status": status,
        "issues": issues,
        "keep": True,
    }


def _pdf_glossary_term_like(text):
    text = _pdf_clean_line(text)
    if not text or len(text) < 2 or len(text) > 120:
        return False
    if re.search(r"[.!?;:]$", text):
        return False
    if re.match(r"^(?:question|correct answer|why the other options|chapter|page)\b", text, re.I):
        return False
    words = text.split()
    if len(words) > 14:
        return False

    significant = [re.sub(r"^[^A-Za-z0-9]+|[^A-Za-z0-9)]+$", "", w) for w in words]
    significant = [w for w in significant if w]
    if not significant:
        return False

    titleish = 0
    for word in significant:
        raw = word.strip("()")
        if not raw:
            continue
        if raw.isupper() or raw[:1].isupper() or re.fullmatch(r"[A-Z][A-Za-z0-9+/#.-]*", raw):
            titleish += 1
    return titleish >= max(1, int(len(significant) * 0.65))

def _pdf_glossary_definition_like(text):
    text = _pdf_clean_line(text)
    if not text or len(text) < 18:
        return False
    words = text.split()
    if len(words) < 4:
        return False
    return bool(
        re.search(r"[.!?]$", text)
        or re.match(r"^(?:\(\d+\)\s*)?(?:A|An|The|Any|Evidence|Process|Method|Technique|System|Tool|Software|Hardware)\b", text)
        or re.search(r"\b(?:is|are|refers to|used to|means|describes|consists of|provides|allows|supports)\b", text, re.I)
    )

def _pdf_split_glossary_line(line):
    """
    Split a same-line 'Term Definition...' record conservatively.
    Candidate term prefixes must look heading-like and the remaining text must
    look like substantive definition prose.
    """
    line = _pdf_clean_line(line)
    words = line.split()
    if len(words) < 6:
        return None

    # Try short prefixes first so "Admissible Evidence Evidence that..." becomes
    # "Admissible Evidence" + "Evidence that..." rather than swallowing prose.
    max_prefix = min(12, len(words) - 4)
    for cut in range(1, max_prefix + 1):
        term = " ".join(words[:cut]).strip()
        definition = " ".join(words[cut:]).strip()
        if not _pdf_glossary_term_like(term):
            continue
        if not _pdf_glossary_definition_like(definition):
            continue

        # Avoid splitting multi-word terms after their first title-cased word.
        # A plausible definition normally starts with prose (A/An/The/This/etc.),
        # a numbered sense marker, or a repetition of the term's final word such
        # as "Admissible Evidence Evidence that...".
        first_token = definition.split()[0]
        first = first_token.strip("()")
        last_term = term.split()[-1].strip("()")
        prose_starters = {
            "a", "an", "the", "this", "these", "those", "it", "they", "any",
            "one", "two", "evidence", "information", "data", "software", "hardware",
            "process", "method", "technique", "system", "tool", "practice", "capability",
        }
        numbered = bool(re.fullmatch(r"\(?\d+[.)]?\)?", first_token))
        repeated_last_word = bool(first and last_term and first.casefold() == last_term.casefold())
        if not numbered and first.casefold() not in prose_starters and not repeated_last_word:
            if first[:1].isupper():
                continue
        return term, definition
    return None


def _pdf_styled_glossary_header(text):
    """Return True for common glossary running headers and A-Z section dividers."""
    text = _pdf_clean_line(text)
    return bool(
        re.fullmatch(r"(?:\d+\s+Glossary|Glossary\s+\d+)", text, re.I)
        or re.fullmatch(r"[A-Z]", text)
    )


def _pdf_style_glossary_line(line):
    """Return (term, first_definition_text) for a bold-term/regular-definition line."""
    if not isinstance(line, dict):
        return None
    text = _pdf_clean_line(line.get("text"))
    if not text or _pdf_styled_glossary_header(text):
        return None
    fragments = line.get("fragments") or []
    if not isinstance(fragments, list) or len(fragments) < 2:
        return None

    term_parts, definition_parts = [], []
    saw_regular = False
    for frag in fragments:
        frag_text = _pdf_clean_line(frag.get("text"))
        if not frag_text:
            continue
        if not saw_regular and bool(frag.get("bold")):
            term_parts.append(frag_text)
            continue
        saw_regular = True
        definition_parts.append(frag_text)

    term = _pdf_clean_line(" ".join(term_parts))
    definition = _pdf_clean_line(" ".join(definition_parts))
    if not term or not definition or len(term) > 180:
        return None
    return term, definition


def _pdf_parse_glossary_styled(pages):
    """
    Use PDF font/style information when a source reliably distinguishes bold
    glossary terms from regular definition prose. Returns None if the style
    signal is too weak, leaving the existing heuristic parser as fallback.
    """
    styled_stream = []
    styled_pages = 0
    for page in pages:
        styled_lines = page.get("styled_lines")
        if not isinstance(styled_lines, list) or not styled_lines:
            continue
        styled_pages += 1
        for line in styled_lines:
            if isinstance(line, dict):
                styled_stream.append({
                    "page": int(page.get("page") or 0),
                    "line": line,
                    "text": _pdf_clean_line(line.get("text")),
                })
    if not styled_stream or not styled_pages:
        return None

    starts = []
    for idx, rec in enumerate(styled_stream):
        parsed = _pdf_style_glossary_line(rec["line"])
        if parsed:
            starts.append((idx, parsed[0], parsed[1], rec["page"]))
    if len(starts) < 4:
        return None

    terms = []
    for pos, (start_idx, term, first_definition, start_page) in enumerate(starts):
        end_idx = starts[pos + 1][0] if pos + 1 < len(starts) else len(styled_stream)
        definition_lines = [first_definition]
        pages_used = {start_page}
        for rec in styled_stream[start_idx + 1:end_idx]:
            text = rec["text"]
            if not text or _pdf_styled_glossary_header(text):
                continue
            definition_lines.append(text)
            pages_used.add(rec["page"])
        definition = _pdf_join_wrapped(definition_lines).strip()
        issues = []
        status = "complete"
        if not definition:
            status = "incomplete"
            issues.append("No definition text was confidently associated with this term.")
        terms.append({
            "number": len(terms) + 1,
            "term": term,
            "definition": definition,
            "pages": sorted(p for p in pages_used if p),
            "status": status,
            "issues": issues,
        })

    complete = sum(1 for item in terms if item["status"] == "complete")
    if not terms or complete / max(1, len(terms)) < 0.90:
        return None
    return {
        "terms": terms,
        "summary": {
            "detected": len(terms),
            "complete": complete,
            "review": sum(1 for item in terms if item["status"] == "review"),
            "incomplete": sum(1 for item in terms if item["status"] == "incomplete"),
        },
        "parser_mode": "style-aware",
    }


def _pdf_parse_glossary(
    pages,
    *,
    parse_glossary_styled=None,
    lines_to_stream=None,
    split_glossary_line=None,
    glossary_term_like=None,
    glossary_definition_like=None,
    join_wrapped=None,
):
    """
    Deterministic glossary/terminology parser.

    Supported patterns:
    - standalone heading followed by definition prose
    - term and definition beginning on the same extracted line
    - definition paragraph immediately preceding a standalone term (flagged REVIEW)

    It intentionally keeps uncertain records editable instead of inventing content.
    """
    parse_glossary_styled = parse_glossary_styled or _pdf_parse_glossary_styled
    lines_to_stream = lines_to_stream or _pdf_lines_to_stream
    split_glossary_line = split_glossary_line or _pdf_split_glossary_line
    glossary_term_like = glossary_term_like or _pdf_glossary_term_like
    glossary_definition_like = glossary_definition_like or _pdf_glossary_definition_like
    join_wrapped = join_wrapped or _pdf_join_wrapped

    styled_result = parse_glossary_styled(pages)
    if isinstance(styled_result, dict) and styled_result.get("terms"):
        return styled_result

    stream = lines_to_stream(pages)
    if not stream:
        return {"terms": [], "summary": {"detected": 0, "complete": 0, "review": 0, "incomplete": 0}}

    events = []
    for idx, rec in enumerate(stream):
        text = rec["text"]
        split = split_glossary_line(text)

        # Distinguish a real inline glossary record such as:
        #   "Access Control A process used to restrict access..."
        # from a normal definition sentence such as:
        #   "A chronological record of system activities and events."
        #
        # Looking at the whole line with _pdf_glossary_definition_like() was too
        # aggressive because valid inline glossary records naturally contain
        # definition-style prose after the term. Instead, only suppress splitting
        # when the line itself begins like ordinary definition prose.
        prose_definition_start = bool(re.match(
            r"^(?:A|An|The|Any)\s+[a-z]|"
            r"^(?:Evidence|Process|Method|Technique|System|Tool|Software|Hardware)\s+"
            r"(?:that|which|used|designed|intended|provides|allows|supports)\b",
            text,
        ))

        if split and not prose_definition_start:
            events.append({
                "index": idx,
                "page": rec["page"],
                "kind": "inline",
                "term": split[0],
                "inline_definition": split[1],
            })
        elif glossary_term_like(text) and not glossary_definition_like(text):
            events.append({
                "index": idx,
                "page": rec["page"],
                "kind": "standalone",
                "term": text,
                "inline_definition": "",
            })

    # Detect the less-common PDF reading order where a definition paragraph is
    # emitted immediately before its standalone bold term. Claim that tail for
    # the later term so it is not also swallowed by the previous entry.
    reverse_claims = {}
    claimed_indices = set()
    for epos, event in enumerate(events):
        if event["kind"] != "standalone":
            continue
        idx = event["index"]
        next_idx = events[epos + 1]["index"] if epos + 1 < len(events) else len(stream)
        forward = [r for r in stream[idx + 1:next_idx] if r.get("text")]
        if forward:
            continue
        prev_event_idx = events[epos - 1]["index"] if epos > 0 else -1
        j = idx - 1
        tail_indices = []
        while j > prev_event_idx and len(tail_indices) < 6:
            text = str(stream[j].get("text") or "").strip()
            if not text:
                j -= 1
                continue
            tail_indices.append(j)
            prev_j = j - 1
            if prev_j <= prev_event_idx:
                break
            prev_text = str(stream[prev_j].get("text") or "").strip()
            # A sentence-ending line before the collected tail is a reasonable
            # paragraph boundary in selectable-text glossary PDFs.
            if re.search(r"[.!?]$", prev_text):
                break
            j -= 1
        tail_indices = sorted(tail_indices)
        tail_text = join_wrapped([stream[i]["text"] for i in tail_indices]).strip()
        if glossary_definition_like(tail_text):
            reverse_claims[idx] = tail_indices
            claimed_indices.update(tail_indices)

    terms = []
    for epos, event in enumerate(events):
        idx = event["index"]
        next_idx = events[epos + 1]["index"] if epos + 1 < len(events) else len(stream)
        between = [
            r for i, r in enumerate(stream[idx + 1:next_idx], start=idx + 1)
            if r.get("text") and i not in claimed_indices
        ]

        definition_lines = []
        issues = []
        pages_used = {int(event["page"])}

        if event["inline_definition"]:
            definition_lines.append(event["inline_definition"])
            definition_lines.extend(r["text"] for r in between)
            pages_used.update(int(r["page"]) for r in between)
        elif between:
            definition_lines.extend(r["text"] for r in between)
            pages_used.update(int(r["page"]) for r in between)

        definition = join_wrapped(definition_lines).strip()

        # If a standalone term has no following definition, inspect the unclaimed
        # prose immediately before it. This handles PDF reading order where the
        # definition is emitted before the bold glossary heading.
        if not definition and event["kind"] == "standalone" and idx in reverse_claims:
            tail = [stream[i] for i in reverse_claims[idx]]
            definition = join_wrapped([r["text"] for r in tail]).strip()
            pages_used.update(int(r["page"]) for r in tail)
            issues.append("Definition appeared before the term in PDF reading order; review recommended.")

        if not definition:
            issues.append("No definition text was confidently associated with this term.")

        status = "complete" if definition and not issues else ("review" if definition else "incomplete")
        terms.append({
            "number": len(terms) + 1,
            "term": event["term"],
            "definition": definition,
            "pages": sorted(pages_used),
            "status": status,
            "issues": issues,
        })

    # Remove obvious false-positive headings and duplicate term records.
    cleaned = []
    seen = set()
    for item in terms:
        term = str(item.get("term") or "").strip()
        definition = str(item.get("definition") or "").strip()
        key = term.casefold()
        if not term or key in seen:
            continue
        if term.casefold() in {"glossary", "terms", "definitions", "index"}:
            continue
        # A useful glossary record needs either a definition or a reviewable term.
        if len(term) < 2:
            continue
        seen.add(key)
        cleaned.append(item)

    for n, item in enumerate(cleaned, 1):
        item["number"] = n

    summary = {
        "detected": len(cleaned),
        "complete": sum(1 for t in cleaned if t["status"] == "complete"),
        "review": sum(1 for t in cleaned if t["status"] == "review"),
        "incomplete": sum(1 for t in cleaned if t["status"] == "incomplete"),
    }
    return {"terms": cleaned, "summary": summary}

def _pdf_question_start_match(text):
    """Recognize conservative question-start formats used by common PDF banks."""
    text = _pdf_clean_line(text)
    m = re.match(r"^Question\s*#?\s*(\d{1,6})\s*$", text, re.I)
    if m:
        return {"number": int(m.group(1)), "inline_stem": "", "kind": "heading"}

    # Numbered stems are accepted only after structural validation in
    # _pdf_parse_question_bank(). Keeping this matcher narrow avoids treating
    # arbitrary numbered prose or glossary lists as question starts.
    m = re.match(r"^(\d{1,6})\s*[.)]\s+(.+)$", text)
    if m:
        stem = _pdf_clean_line(m.group(2))
        if stem:
            return {"number": int(m.group(1)), "inline_stem": stem, "kind": "numbered"}
    return None


def _pdf_question_chunk_structure(records):
    """Return evidence that a candidate chunk really looks like MCQ content."""
    lines = [_pdf_clean_line(r.get("text")) for r in records if _pdf_clean_line(r.get("text"))]
    labels = []
    for line in lines:
        m = re.match(r"^([A-Z])\.\s+.+$", line)
        if m:
            labels.append(m.group(1).upper())
    contiguous = 0
    if labels:
        run = 1
        contiguous = 1
        for prev, current in zip(labels, labels[1:]):
            if ord(current) == ord(prev) + 1:
                run += 1
                contiguous = max(contiguous, run)
            else:
                run = 1
    answer_marker = any(re.search(r"Correct\s+Answer:\s*[A-Z]", line, re.I) for line in lines)
    return {"choice_run": contiguous, "answer_marker": answer_marker}


def _pdf_add_question_review_slots(question, minimum_labels=("A", "B", "C", "D")):
    """Ensure Review & Repair always has editable choice slots for reconstruction."""
    question = dict(question or {})
    choices = [dict(c) for c in (question.get("choices") or []) if isinstance(c, dict)]
    existing = {str(c.get("label") or "").upper() for c in choices}
    for label in minimum_labels:
        if label not in existing:
            choices.append({"label": label, "text": ""})
    choices.sort(key=lambda c: str(c.get("label") or ""))
    question["choices"] = choices
    return question


def _pdf_question_recovery_result(pages):
    """Build low-confidence, reviewable question records instead of hard-failing."""
    stream = _pdf_lines_to_stream(pages)
    candidates = []
    for idx, record in enumerate(stream):
        match = _pdf_question_start_match(record.get("text"))
        if match:
            candidates.append((idx, match))

    questions = []
    if candidates:
        for pos, (start_idx, match) in enumerate(candidates):
            end_idx = candidates[pos + 1][0] if pos + 1 < len(candidates) else len(stream)
            records = list(stream[start_idx + 1:end_idx])
            if match.get("inline_stem"):
                records.insert(0, {"page": stream[start_idx]["page"], "text": match["inline_stem"]})
            q = _pdf_parse_question_chunk(match["number"], records)
            if q:
                q = _pdf_add_question_review_slots(q)
                q["status"] = "incomplete"
                issues = list(q.get("issues") or [])
                recovery_issue = "Low-confidence recovery record. Verify/reconstruct the question, choices, correct answer, and explanation before keeping it."
                if recovery_issue not in issues:
                    issues.insert(0, recovery_issue)
                q["issues"] = issues
                questions.append(q)

    # If there are no usable question boundaries at all, preserve extracted text
    # page-by-page so the user still reaches Review & Repair and can reconstruct it.
    if not questions:
        for page in pages:
            text = _pdf_join_wrapped(page.get("lines") or [])
            if not text:
                continue
            questions.append({
                "number": len(questions) + 1,
                "question": text,
                "choices": [{"label": x, "text": ""} for x in ("A", "B", "C", "D")],
                "correct": "",
                "declared_answer_text": "",
                "explanation": "",
                "choice_feedback": {},
                "pages": [page.get("page")],
                "status": "incomplete",
                "issues": [
                    "Unstructured recovery record. DLMS preserved this page's extracted text for manual reconstruction.",
                    "Enter at least two answer choices and select a correct answer, or exclude this record.",
                ],
                "keep": True,
            })

    return {
        "type": "multiple_choice_question_bank",
        "questions": questions,
        "summary": {
            "detected": len(questions),
            "complete": 0,
            "review": 0,
            "incomplete": len(questions),
        },
        "recovery_mode": True,
    }


def _pdf_glossary_recovery_result(pages):
    """Preserve selectable text as editable terminology recovery records."""
    terms = []
    for page in pages:
        text = _pdf_join_wrapped(page.get("lines") or [])
        if not text:
            continue
        terms.append({
            "number": len(terms) + 1,
            "term": "",
            "definition": text,
            "pages": [page.get("page")],
            "status": "incomplete",
            "issues": [
                "Unstructured recovery record. Enter the term and repair the definition, or exclude this record."
            ],
            "keep": True,
        })
    return {
        "type": "glossary",
        "terms": terms,
        "summary": {
            "detected": len(terms),
            "complete": 0,
            "review": 0,
            "incomplete": len(terms),
        },
        "recovery_mode": True,
    }


def _pdf_detect_document_type(pages, question_result=None, glossary_result=None):
    question_result = question_result if isinstance(question_result, dict) else _pdf_parse_question_bank(pages)
    glossary_result = glossary_result if isinstance(glossary_result, dict) else _pdf_parse_glossary(pages)

    stream = _pdf_lines_to_stream(pages)
    question_markers = sum(1 for r in stream if _pdf_question_start_match(r["text"]))
    answer_markers = sum(1 for r in stream if re.search(r"Correct\s+Answer:", r["text"], re.I))
    q_detected = int((question_result.get("summary") or {}).get("detected") or 0)
    g_detected = int((glossary_result.get("summary") or {}).get("detected") or 0)

    # Parsed question records are stronger evidence than glossary-like prose. This
    # prevents numbered MCQ banks from being misclassified as glossaries merely
    # because their question-start format differs from "Question N".
    structured_single = (
        q_detected == 1
        and question_markers >= 1
        and answer_markers >= 1
        and len(question_result.get("questions") or []) == 1
        and (question_result.get("questions") or [{}])[0].get("status") == "complete"
    )
    if (q_detected >= 2 and answer_markers >= 1) or structured_single:
        return "question_bank", {
            "question_markers": question_markers,
            "answer_markers": answer_markers,
            "question_records": q_detected,
            "glossary_records": g_detected,
        }

    if g_detected >= 4:
        return "glossary", {
            "question_markers": question_markers,
            "answer_markers": answer_markers,
            "question_records": q_detected,
            "glossary_records": g_detected,
        }

    return "unknown", {
        "question_markers": question_markers,
        "answer_markers": answer_markers,
        "question_records": q_detected,
        "glossary_records": g_detected,
    }

def _pdf_parse_question_bank(
    pages,
    *,
    lines_to_stream=None,
    question_start_match=None,
    question_chunk_structure=None,
    parse_question_chunk=None,
):
    lines_to_stream = lines_to_stream or _pdf_lines_to_stream
    question_start_match = question_start_match or _pdf_question_start_match
    question_chunk_structure = question_chunk_structure or _pdf_question_chunk_structure
    parse_question_chunk = parse_question_chunk or _pdf_parse_question_chunk

    stream = lines_to_stream(pages)
    raw_starts = []
    for idx, record in enumerate(stream):
        match = question_start_match(record.get("text"))
        if match:
            raw_starts.append((idx, match))

    # Standalone "Question N" headings remain trusted boundaries. Numbered stems
    # such as "1. ..." or "1) ..." must have nearby A/B/... choices plus a
    # Correct Answer marker before being promoted to structured questions.
    starts = []
    for pos, (start_idx, match) in enumerate(raw_starts):
        end_idx = raw_starts[pos + 1][0] if pos + 1 < len(raw_starts) else len(stream)
        if match.get("kind") == "numbered":
            # A numbered line inside a conventional question is supporting stem
            # material, not a new boundary. The conventional record remains open
            # until its Correct Answer marker, so do not let later choices make
            # the embedded numbered line look like a standalone question.
            if starts and starts[-1][1].get("kind") == "heading":
                prior_structure = question_chunk_structure(
                    stream[starts[-1][0] + 1:start_idx]
                )
                if not prior_structure["answer_marker"]:
                    continue
            evidence = question_chunk_structure(stream[start_idx + 1:end_idx])
            if evidence["choice_run"] < 2 or not evidence["answer_marker"]:
                continue
        starts.append((start_idx, match))

    questions = []
    for pos, (start_idx, match) in enumerate(starts):
        end_idx = starts[pos + 1][0] if pos + 1 < len(starts) else len(stream)
        records = list(stream[start_idx + 1:end_idx])
        if match.get("inline_stem"):
            records.insert(0, {"page": stream[start_idx]["page"], "text": match["inline_stem"]})
        q = parse_question_chunk(match["number"], records)
        if q:
            questions.append(q)

    complete = sum(q["status"] == "complete" for q in questions)
    review = sum(q["status"] == "review" for q in questions)
    incomplete = sum(q["status"] == "incomplete" for q in questions)
    return {
        "type": "multiple_choice_question_bank",
        "questions": questions,
        "summary": {
            "detected": len(questions),
            "complete": complete,
            "review": review,
            "incomplete": incomplete,
        }
    }

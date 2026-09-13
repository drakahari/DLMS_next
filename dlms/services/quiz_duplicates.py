"""Derived, advisory duplicate-question reporting for the Quiz Library."""

from collections import Counter, defaultdict
from difflib import SequenceMatcher
import re
import unicodedata

from .learning import _is_generated_review_source
from .quiz_composition import canonical_question_identity


# These deliberately conservative thresholds identify only very close wording
# variants. Exact response structure, question type, numbers, and negation must
# also agree before two source questions can be reported as possible duplicates.
NEAR_DUPLICATE_SEQUENCE_THRESHOLD = 0.92
NEAR_DUPLICATE_TOKEN_THRESHOLD = 0.82
NEAR_DUPLICATE_MIN_TOKENS = 6
NEAR_DUPLICATE_MIN_SHARED_SIGNIFICANT_TOKENS = 3

_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
_NEGATION_WORDS = frozenset({"except", "false", "incorrect", "least", "never", "not"})
_CANDIDATE_STOP_WORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "how", "in", "is", "it", "of", "on", "or", "that", "the", "this",
    "to", "what", "when", "where", "which", "who", "why", "with",
})


def _normalized_content(value):
    """Normalize case and spacing without discarding meaningful wording."""
    value = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", " ", value.strip()).casefold()


def _word_tokens(value):
    return tuple(_WORD_RE.findall(_normalized_content(value)))


def _choice_response_fingerprint(choices):
    # Labels and presentation order do not change the educational response set.
    return (
        "choice",
        tuple(sorted(
            (_normalized_content(choice["text"]), bool(choice["is_correct"]))
            for choice in choices
        )),
    )


def _matching_response_fingerprint(pairs, direction):
    # Pair order is randomized during normal matching play. Direction remains a
    # meaningful distinction between otherwise identical matching activities.
    return (
        "matching",
        _normalized_content(direction or "term_to_definition"),
        tuple(sorted(
            (
                _normalized_content(pair["left"]),
                _normalized_content(pair["right"]),
            )
            for pair in pairs
        )),
    )


def _response_fingerprint(record):
    if record["question_type"] == "matching":
        return _matching_response_fingerprint(
            record["pairs"], record["matching_direction"]
        )
    return _choice_response_fingerprint(record["choices"])


def _has_complete_response(record):
    if record["question_type"] == "matching":
        return len(record["pairs"]) >= 2 and all(
            _normalized_content(pair["left"])
            and _normalized_content(pair["right"])
            for pair in record["pairs"]
        )
    return len(record["choices"]) >= 2 and all(
        _normalized_content(choice["text"]) for choice in record["choices"]
    )


def _near_duplicate_similarity(left_text, right_text):
    """Return strong wording evidence, or ``None`` when evidence is insufficient."""
    left_tokens = _word_tokens(left_text)
    right_tokens = _word_tokens(right_text)
    if min(len(left_tokens), len(right_tokens)) < NEAR_DUPLICATE_MIN_TOKENS:
        return None

    left_set = set(left_tokens)
    right_set = set(right_tokens)
    if {token for token in left_set if token in _NEGATION_WORDS} != {
        token for token in right_set if token in _NEGATION_WORDS
    }:
        return None
    if {token for token in left_set if token.isdigit()} != {
        token for token in right_set if token.isdigit()
    }:
        return None

    token_similarity = len(left_set & right_set) / len(left_set | right_set)
    left_normalized = " ".join(left_tokens)
    right_normalized = " ".join(right_tokens)
    length_ratio = min(len(left_normalized), len(right_normalized)) / max(
        len(left_normalized), len(right_normalized)
    )
    if length_ratio < 0.80:
        return None
    sequence_similarity = SequenceMatcher(
        None, left_normalized, right_normalized, autojunk=False
    ).ratio()
    if (
        sequence_similarity < NEAR_DUPLICATE_SEQUENCE_THRESHOLD
        or token_similarity < NEAR_DUPLICATE_TOKEN_THRESHOLD
    ):
        return None
    return {
        "sequence_similarity": sequence_similarity,
        "token_similarity": token_similarity,
    }


def _registry_index(registry):
    by_id = {}
    order = {}
    for index, item in enumerate(registry or []):
        try:
            quiz_id = int(item.get("id"))
        except (AttributeError, TypeError, ValueError):
            continue
        by_id.setdefault(quiz_id, item)
        order.setdefault(quiz_id, index)
    return by_id, order


def _source_records(cur, registry, *, is_generated_source):
    registry_by_id, registry_order = _registry_index(registry)
    rows = cur.execute("""
        SELECT q.id, q.quiz_id, q.question_number, q.question_text,
               COALESCE(q.question_type, 'choice') AS question_type,
               COALESCE(q.matching_direction, 'term_to_definition') AS matching_direction,
               z.title AS quiz_title, COALESCE(z.source_file, '') AS source_file
        FROM questions q
        JOIN quizzes z ON z.id = q.quiz_id
        ORDER BY q.quiz_id, q.question_number, q.id
    """).fetchall()

    choices = defaultdict(list)
    for row in cur.execute("""
        SELECT question_id, label, text, is_correct
        FROM choices
        ORDER BY question_id, label, id
    """).fetchall():
        choices[row["question_id"]].append({
            "label": row["label"] or "",
            "text": row["text"] or "",
            "is_correct": bool(row["is_correct"]),
        })

    pairs = defaultdict(list)
    for row in cur.execute("""
        SELECT question_id, left_text, right_text
        FROM matching_pairs
        ORDER BY question_id, pair_order, id
    """).fetchall():
        pairs[row["question_id"]].append({
            "left": row["left_text"] or "",
            "right": row["right_text"] or "",
        })

    records = []
    excluded_generated_count = 0
    for row in rows:
        registry_item = registry_by_id.get(row["quiz_id"])
        if registry_item is None:
            continue
        if is_generated_source(row["source_file"], row["quiz_title"]):
            excluded_generated_count += 1
            continue
        record = {
            "question_id": row["id"],
            "quiz_id": row["quiz_id"],
            "question_number": row["question_number"],
            "question_text": row["question_text"] or "",
            "question_type": (row["question_type"] or "choice").casefold(),
            "matching_direction": row["matching_direction"],
            "quiz_title": row["quiz_title"],
            "folder": str(registry_item.get("folder") or "Uncategorized"),
            "choices": choices.get(row["id"], []),
            "pairs": pairs.get(row["id"], []),
            "edit_url": f"/edit_quiz/{row['quiz_id']}",
            "_registry_order": registry_order[row["quiz_id"]],
        }
        record["_canonical_identity"] = canonical_question_identity(
            record["question_type"], record["question_text"], record["question_id"]
        )
        record["_response_fingerprint"] = _response_fingerprint(record)
        record["_tokens"] = _word_tokens(record["question_text"])
        records.append(record)

    records.sort(key=lambda record: (
        record["_registry_order"],
        record["question_number"] if record["question_number"] is not None else 10**9,
        record["question_id"],
    ))
    return records, excluded_generated_count


def _public_record(record):
    return {
        key: value for key, value in record.items() if not key.startswith("_")
    }


def _unit_sort_key(unit):
    first = unit["records"][0]
    return (
        first["_registry_order"],
        first["question_number"] if first["question_number"] is not None else 10**9,
        first["question_id"],
    )


def _near_duplicate_pairs(units):
    """Compare only structurally compatible candidates selected by an index."""
    by_response = defaultdict(list)
    for unit in units:
        representative = unit["records"][0]
        if _has_complete_response(representative):
            by_response[representative["_response_fingerprint"]].append(unit)

    results = []
    for compatible_units in by_response.values():
        if len(compatible_units) < 2:
            continue

        document_frequency = Counter()
        significant_by_index = {}
        for index, unit in enumerate(compatible_units):
            significant = {
                token for token in unit["records"][0]["_tokens"]
                if len(token) >= 3 and token not in _CANDIDATE_STOP_WORDS
            }
            significant_by_index[index] = significant
            document_frequency.update(significant)

        # Very common terms do not create useful candidate pairs. This keeps
        # the expensive similarity comparison bounded for large source banks.
        max_frequency = max(20, len(compatible_units) // 2)
        postings = defaultdict(list)
        seen_pairs = set()
        for right_index, right_unit in enumerate(compatible_units):
            candidate_counts = Counter()
            for token in significant_by_index[right_index]:
                if document_frequency[token] <= max_frequency:
                    candidate_counts.update(postings[token])
            for left_index, shared_count in candidate_counts.items():
                if shared_count < NEAR_DUPLICATE_MIN_SHARED_SIGNIFICANT_TOKENS:
                    continue
                pair_key = (left_index, right_index)
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)
                left_unit = compatible_units[left_index]
                similarity = _near_duplicate_similarity(
                    left_unit["records"][0]["question_text"],
                    right_unit["records"][0]["question_text"],
                )
                if similarity is None:
                    continue
                results.append({
                    "left": {
                        "questions": [
                            _public_record(record) for record in left_unit["records"]
                        ],
                    },
                    "right": {
                        "questions": [
                            _public_record(record) for record in right_unit["records"]
                        ],
                    },
                    "sequence_similarity": similarity["sequence_similarity"],
                    "token_similarity": similarity["token_similarity"],
                    "reason": "Very similar wording with the same answer structure",
                })
            for token in significant_by_index[right_index]:
                if document_frequency[token] <= max_frequency:
                    postings[token].append(right_index)

    results.sort(key=lambda result: (
        -result["sequence_similarity"],
        result["left"]["questions"][0]["quiz_title"].casefold(),
        result["left"]["questions"][0]["question_id"],
        result["right"]["questions"][0]["quiz_title"].casefold(),
        result["right"]["questions"][0]["question_id"],
    ))
    return results


def build_quiz_duplicate_report(
    cur, registry, *, is_generated_source=_is_generated_review_source
):
    """Build a deterministic, read-only duplicate report for source questions."""
    records, excluded_generated_count = _source_records(
        cur, registry, is_generated_source=is_generated_source
    )

    exact_buckets = defaultdict(list)
    for record in records:
        exact_buckets[(
            record["_canonical_identity"], record["_response_fingerprint"]
        )].append(record)

    units = [
        {"records": bucket}
        for bucket in exact_buckets.values()
    ]
    units.sort(key=_unit_sort_key)
    exact_groups = [
        {
            "question_type": unit["records"][0]["question_type"],
            "questions": [_public_record(record) for record in unit["records"]],
        }
        for unit in units if len(unit["records"]) > 1
    ]
    near_groups = _near_duplicate_pairs(units)

    return {
        "scanned_question_count": len(records),
        "scanned_quiz_count": len({record["quiz_id"] for record in records}),
        "excluded_generated_count": excluded_generated_count,
        "exact_groups": exact_groups,
        "near_groups": near_groups,
        "exact_group_count": len(exact_groups),
        "near_group_count": len(near_groups),
    }

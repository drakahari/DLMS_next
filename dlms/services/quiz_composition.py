"""Question-bank catalog and filtering for mixed-quiz composition."""

import re

from .learning import (
    _canonical_question_identity,
    _deduplicated_learning_answer_events,
    _is_generated_review_source,
)


def canonical_question_identity(question_type, question_text, question_id=None):
    """Match the exact cross-quiz identity already used by learning analytics."""
    return _canonical_question_identity(
        question_type, question_text, question_id
    )


def build_mixed_quiz_catalog(
    cur,
    registry,
    *,
    answer_events=_deduplicated_learning_answer_events,
    is_generated_source=_is_generated_review_source,
):
    """Build a deterministic, de-duplicated catalog of original quiz questions.

    Registry membership defines which quizzes are currently available in the
    Quiz Library. Generated review/composition quizzes remain normal runnable
    quizzes, but never become recursive source banks.
    """
    registry_by_id = {}
    registry_order = {}
    for index, item in enumerate(registry or []):
        try:
            quiz_id = int(item.get("id"))
        except (AttributeError, TypeError, ValueError):
            continue
        registry_by_id.setdefault(quiz_id, item)
        registry_order.setdefault(quiz_id, index)

    rows = cur.execute("""
        SELECT q.id, q.quiz_id, q.question_number, q.question_text,
               COALESCE(q.question_type, 'choice') AS question_type,
               z.title AS quiz_title, COALESCE(z.source_file, '') AS source_file,
               (SELECT COUNT(*) FROM choices c WHERE c.question_id = q.id) AS choice_count,
               (SELECT COUNT(*) FROM matching_pairs m WHERE m.question_id = q.id) AS pair_count
        FROM questions q
        JOIN quizzes z ON z.id = q.quiz_id
        ORDER BY q.quiz_id, q.question_number, q.id
    """).fetchall()

    concepts_by_question = {}
    for row in cur.execute("""
        SELECT qc.question_id, c.name
        FROM question_concepts qc
        JOIN concepts c ON c.id = qc.concept_id
        ORDER BY c.name COLLATE NOCASE, c.id
    """).fetchall():
        concepts_by_question.setdefault(row["question_id"], []).append(row["name"])

    choices_by_question = {}
    for row in cur.execute("""
        SELECT question_id, label, text
        FROM choices
        ORDER BY question_id, label, id
    """).fetchall():
        choices_by_question.setdefault(row["question_id"], []).append({
            "label": row["label"], "text": row["text"] or ""
        })
    pairs_by_question = {}
    for row in cur.execute("""
        SELECT question_id, left_text, right_text
        FROM matching_pairs
        ORDER BY question_id, pair_order, id
    """).fetchall():
        pairs_by_question.setdefault(row["question_id"], []).append({
            "left": row["left_text"] or "", "right": row["right_text"] or ""
        })

    groups = {}
    question_to_identity = {}
    for row in rows:
        identity = canonical_question_identity(
            row["question_type"], row["question_text"], row["id"]
        )
        question_to_identity[row["id"]] = identity
        group = groups.setdefault(identity, {"source_rows": [], "concepts": {}})

        registry_item = registry_by_id.get(row["quiz_id"])
        if registry_item is None or is_generated_source(
            row["source_file"], row["quiz_title"]
        ):
            continue
        group["source_rows"].append(row)
        for concept in concepts_by_question.get(row["id"], []):
            group["concepts"].setdefault(concept.casefold(), concept)

    missed_identities = set()
    for event in answer_events(cur):
        identity = question_to_identity.get(event["question_id"])
        if identity in groups and not bool(event["was_correct"]):
            missed_identities.add(identity)

    catalog = []
    for identity, group in groups.items():
        source_rows = group["source_rows"]
        if not source_rows:
            continue
        source_rows.sort(key=lambda row: (
            registry_order.get(row["quiz_id"], len(registry_order)),
            row["question_number"] if row["question_number"] is not None else 10**9,
            row["id"],
        ))
        representative = source_rows[0]
        sources = []
        seen_quizzes = set()
        for row in source_rows:
            if row["quiz_id"] in seen_quizzes:
                continue
            seen_quizzes.add(row["quiz_id"])
            registry_item = registry_by_id[row["quiz_id"]]
            sources.append({
                "quiz_id": row["quiz_id"],
                "quiz_title": row["quiz_title"],
                "folder": str(registry_item.get("folder") or "Uncategorized"),
                "question_number": row["question_number"],
            })

        concepts = sorted(group["concepts"].values(), key=str.casefold)
        catalog.append({
            "question_id": representative["id"],
            "question_type": representative["question_type"],
            "question_text": representative["question_text"] or "",
            "question_number": representative["question_number"],
            "choice_count": int(representative["choice_count"] or 0),
            "pair_count": int(representative["pair_count"] or 0),
            "choice_preview": choices_by_question.get(representative["id"], []),
            "pair_preview": pairs_by_question.get(representative["id"], []),
            "concepts": concepts,
            "concept_keys": [name.casefold() for name in concepts],
            "ever_missed": identity in missed_identities,
            "sources": sources,
            "source_quiz_ids": [source["quiz_id"] for source in sources],
            "source_quiz_titles": [source["quiz_title"] for source in sources],
            "folders": sorted({source["folder"] for source in sources}, key=str.casefold),
            "duplicate_count": len(source_rows),
        })

    catalog.sort(key=lambda item: (
        min(registry_order.get(qid, len(registry_order)) for qid in item["source_quiz_ids"]),
        item["question_number"] if item["question_number"] is not None else 10**9,
        item["question_id"],
    ))
    return catalog


def filter_mixed_quiz_catalog(
    catalog, *, folder="", source_quiz_id=None, concept="", missed="", search=""
):
    """Apply the builder's user-visible filters without changing the catalog."""
    folder_key = str(folder or "").strip().casefold()
    concept_key = str(concept or "").strip().casefold()
    search_key = re.sub(r"\s+", " ", str(search or "").strip()).casefold()
    try:
        source_id = int(source_quiz_id) if source_quiz_id not in (None, "") else None
    except (TypeError, ValueError):
        return []
    missed_key = str(missed or "").strip().casefold()
    if missed_key not in {"", "missed", "not-missed"}:
        return []

    filtered = []
    for item in catalog:
        if folder_key and not any(
            str(value).casefold() == folder_key for value in item["folders"]
        ):
            continue
        if source_id is not None and source_id not in item["source_quiz_ids"]:
            continue
        if concept_key and concept_key not in item["concept_keys"]:
            continue
        if missed_key == "missed" and not item["ever_missed"]:
            continue
        if missed_key == "not-missed" and item["ever_missed"]:
            continue
        if search_key:
            haystack = " ".join([
                item["question_text"],
                *item["source_quiz_titles"],
                *item["folders"],
                *item["concepts"],
            ]).casefold()
            if search_key not in haystack:
                continue
        filtered.append(item)
    return filtered


def mixed_quiz_filter_options(catalog):
    """Return stable display options derived only from canonical catalog data."""
    quizzes = {}
    folders = {}
    concepts = {}
    for item in catalog:
        for source in item["sources"]:
            quizzes.setdefault(source["quiz_id"], source["quiz_title"])
            folders.setdefault(source["folder"].casefold(), source["folder"])
        for concept in item["concepts"]:
            concepts.setdefault(concept.casefold(), concept)
    return {
        "quizzes": [
            {"id": quiz_id, "title": title}
            for quiz_id, title in sorted(
                quizzes.items(), key=lambda pair: (pair[1].casefold(), pair[0])
            )
        ],
        "folders": sorted(folders.values(), key=str.casefold),
        "concepts": sorted(concepts.values(), key=str.casefold),
    }

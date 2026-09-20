"""Request-local source-quiz scope for current learning recommendations.

An absent scope is represented by ``None`` so existing all-library paths keep
their historical behavior.  This module never changes stored learning evidence.
"""

from dataclasses import dataclass

from dlms.services.question_identity import (
    is_generated_question, is_generated_quiz, valid_question_uid,
)
from dlms.services.quiz_mutations import (
    build_quiz_folder_identity, quiz_folder_identity_key,
)


@dataclass(frozen=True)
class LearningScope:
    excluded_folder_keys: frozenset[str]
    included_quiz_ids: frozenset[int]
    source_question_ids: frozenset[int]
    generated_question_ids: frozenset[int]
    included_lineage_uids: frozenset[str]
    ambiguous_lineage_uids: frozenset[str]
    eligible_question_ids: frozenset[int]

    def allows_source(self, row):
        return not is_generated_question(row) and row["id"] in self.source_question_ids

    def allows_question(self, row):
        """Generated copies need explicit, unambiguous source lineage.

        Legacy generated rows have only text identity.  With exclusions active,
        guessing their source would risk including excluded material.
        """
        if not is_generated_question(row):
            return row["id"] in self.source_question_ids
        uid = row["canonical_question_uid"]
        return (
            valid_question_uid(uid)
            and uid in self.included_lineage_uids
            and uid not in self.ambiguous_lineage_uids
        )


def build_learning_scope(cur, registry, excluded_folders):
    """Resolve source ownership in one DB scan and one registry snapshot."""
    excluded = frozenset(
        quiz_folder_identity_key(name)
        for name in excluded_folders
        if isinstance(name, str) and name.strip()
    )
    if not excluded:
        return None

    folders_by_quiz = {
        str(item.get("id")): quiz_folder_identity_key(item.get("folder"))
        for item in registry if isinstance(item, dict)
    }
    rows = cur.execute("""
        SELECT q.id, q.quiz_id, q.question_uid, q.canonical_question_uid,
               COALESCE(q.is_generated_copy, 0) AS is_generated_copy,
               z.generation_kind, COALESCE(z.source_file, '') AS source_file,
               COALESCE(z.title, '') AS quiz_title
        FROM questions q JOIN quizzes z ON z.id = q.quiz_id
    """).fetchall()
    included_quizzes = set()
    source_ids = set()
    generated_ids = set()
    lineage_sources = {}
    for row in rows:
        if is_generated_question(row):
            generated_ids.add(row["id"])
            continue
        if folders_by_quiz.get(str(row["quiz_id"]), "uncategorized") not in excluded:
            included_quizzes.add(row["quiz_id"])
            source_ids.add(row["id"])
        uid = row["canonical_question_uid"]
        if valid_question_uid(uid):
            lineage_sources.setdefault(uid, set()).add(row["id"])
    included_uids = {
        uid for uid, ids in lineage_sources.items()
        if len(ids) == 1 and next(iter(ids)) in source_ids
    }
    ambiguous_uids = {uid for uid, ids in lineage_sources.items() if len(ids) != 1}
    eligible_ids = source_ids | {
        row["id"] for row in rows
        if row["id"] in generated_ids
        and valid_question_uid(row["canonical_question_uid"])
        and row["canonical_question_uid"] in included_uids
    }
    return LearningScope(
        excluded, frozenset(included_quizzes), frozenset(source_ids),
        frozenset(generated_ids), frozenset(included_uids), frozenset(ambiguous_uids),
        frozenset(eligible_ids),
    )


def learning_scope_summary(cur, registry, configured_folders, excluded_folders, hidden_folders):
    """Small UI summary from the same folder catalog used by Quiz Library."""
    identity = build_quiz_folder_identity(configured_folders, registry)
    excluded_keys = {quiz_folder_identity_key(name) for name in excluded_folders}
    hidden_keys = {quiz_folder_identity_key(name) for name in hidden_folders}
    folder_by_quiz = {
        str(item.get("id")): quiz_folder_identity_key(item.get("folder"))
        for item in registry if isinstance(item, dict)
    }
    counts = {key: 0 for key in identity.names_by_key}
    included = 0
    for quiz in cur.execute(
        "SELECT id, title, source_file, generation_kind FROM quizzes"
    ).fetchall():
        if is_generated_quiz(
            generation_kind=quiz["generation_kind"], source_file=quiz["source_file"],
            title=quiz["title"],
        ):
            continue
        key = folder_by_quiz.get(str(quiz["id"]), "uncategorized")
        counts[key] = counts.get(key, 0) + 1
        if key not in excluded_keys:
            included += 1
    folders = [{
        "name": name,
        "key": quiz_folder_identity_key(name),
        "source_quizzes": counts.get(quiz_folder_identity_key(name), 0),
        "excluded": quiz_folder_identity_key(name) in excluded_keys,
        "hidden": quiz_folder_identity_key(name) in hidden_keys,
    } for name in identity.folders]
    return {
        "included_source_quizzes": included,
        "excluded_folders": sum(item["excluded"] for item in folders),
        "folders": folders,
    }

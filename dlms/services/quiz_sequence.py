"""Read-only continuation in the Quiz Library's persisted per-folder order."""

from .generated_practice_lifecycle import quiz_is_transient
from .quiz_mutations import build_quiz_folder_identity
from .study_sessions import StudyConflict, artifact, assessment_revision, public_session, regular_continuity


def quiz_sequence(cur, registry, *, configured_folders, hidden_folders, scope,
                  data_folder, quiz_folder, artifact_names, context):
    """Use factual regular Study activity, never browser openings or coverage alone.

    Registry insertion order is the order saved by save_quiz_order_in_folder
    and rendered by the ordinary Library. Do not sort filenames or skip a
    reviewed, hidden, excluded or unavailable next regular quiz.
    """
    anchor = regular_continuity(cur, registry, data_folder=data_folder,
                                quiz_folder=quiz_folder, artifact_names=artifact_names)
    result = {"state": "empty", "anchor": anchor, "next": None, "folder": None}
    if not anchor:
        return result
    entries = {entry.get("id"): entry for entry in registry}
    entry = entries.get(anchor["quiz_id"])
    if not entry or not anchor["url"]:
        return {**result, "state": "unavailable"}
    identity = build_quiz_folder_identity(configured_folders, registry)
    folder = identity.resolve(entry.get("folder"))
    result["folder"] = folder
    folder_key = identity.key(folder)
    if folder_key in {identity.key(name) for name in hidden_folders} or entry.get("hidden"):
        return {**result, "state": "hidden"}
    if scope is not None and folder_key in scope.excluded_folder_keys:
        return {**result, "state": "excluded"}
    if not anchor["unchanged"]:
        return {**result, "state": "changed"}
    if not anchor["sequence_complete"] or anchor["coverage_incomplete"]:
        return {**result, "state": "incomplete_saves"}
    if not anchor["completed_at"]:
        return {**result, "state": "unfinished"}

    metadata = {row["id"]: row for row in cur.execute(
        "SELECT id, title, source_file, generation_kind FROM quizzes")}
    after_anchor = False
    for candidate in registry:
        if candidate.get("id") == anchor["quiz_id"]:
            after_anchor = True
            continue
        if not after_anchor or identity.key(candidate.get("folder")) != folder_key:
            continue
        quiz = metadata.get(candidate.get("id"))
        # Missing DB records must remain an unavailable stop in the sequence.
        classified = quiz if quiz is not None else {
            "generation_kind": candidate.get("generation_kind"),
            "source_file": candidate.get("html") or "",
            "title": candidate.get("title") or "",
        }
        if quiz_is_transient(classified):
            continue
        target = dict(context(candidate.get("id"), quiz["title"] if quiz else None))
        target["folder"] = folder
        result["next"] = target
        if candidate.get("hidden"):
            return {**result, "state": "next_hidden"}
        if scope is not None and identity.key(candidate.get("folder")) in scope.excluded_folder_keys:
            return {**result, "state": "next_excluded"}
        if not target["quiz_url"]:
            return {**result, "state": "next_unavailable"}
        if not cur.execute("SELECT 1 FROM questions WHERE quiz_id = ? LIMIT 1", (quiz["id"],)).fetchone():
            target["quiz_url"] = None
            target["availability"] = "Quiz has no current questions"
            return {**result, "state": "next_unavailable"}
        row = cur.execute("""SELECT * FROM study_sessions
            WHERE quiz_id = ? AND purpose = 'regular' AND last_activity_at IS NOT NULL
            ORDER BY last_activity_at DESC, rowid DESC LIMIT 1""", (quiz["id"],)).fetchone()
        target["review_status"] = "No tracked Study review recorded"
        if row:
            session = public_session(cur, row)
            unchanged = row["assessment_revision"] == assessment_revision(cur, quiz["id"])
            # A changed generated page/JSON also invalidates revision coverage.
            if unchanged:
                try:
                    artifact(cur, quiz["id"], row["fingerprint"], registry=registry,
                             data_folder=data_folder, artifact_names=artifact_names)
                except StudyConflict:
                    unchanged = False
            complete_coverage = sum(a["was_correct"] is not None for a in session["answers"].values()) == session["total"]
            if not unchanged:
                target["review_status"] = "Content changed since its saved review"
            elif not session["sequence_complete"] or (row["completed_at"] and not complete_coverage):
                target["review_status"] = "Saved review needs attention"
            elif row["completed_at"]:
                target["review_status"] = "Tracked review finished for current content"
                target["completed_at"] = row["completed_at"]
            else:
                target["review_status"] = "Tracked review unfinished"
        return {**result, "state": "next"}
    return {**result, "state": "end"}

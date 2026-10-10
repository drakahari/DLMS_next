"""Frozen schema-10 revision oracle, independent of the current application.

Copied verbatim (only these three functions) from:
  commit 856131ad333dc8d9fb7b32b010cf96c70dea93e4
  dlms/services/study_sessions.py
  source SHA-256 f63bffca65eb2b2830e54a81811eb3bdcac385c4fbd5878687c7c9cb75fd16db

This is the pre-schema-11 SQL/encoding contract: choices sort by their label,
with SQLite's existing row-ID tie order for equal labels. It deliberately never
uses choice_order, imports production code, or shells out to Git. Keep it frozen:
a future revision-contract change must explicitly address legacy compatibility.
The migration fixture exercises nonalphabetic insertion and duplicate labels.
"""

import hashlib
import json


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def assessment_revision(cur, quiz_id):
    """Exclude presentation/context fields; never infer identity from text."""
    questions = cur.execute("SELECT * FROM questions WHERE quiz_id = ? ORDER BY question_number, id", (quiz_id,)).fetchall()
    identity_metadata = {"question_uid", "canonical_question_uid", "source_question_uid", "is_generated_copy"}
    content = [{**{key: row[key] for key in row.keys() if key not in identity_metadata}, "choices": [], "pairs": []} for row in questions]
    by_id = {row["id"]: row for row in content}
    for row in cur.execute("SELECT c.question_id, c.label, c.text, c.is_correct FROM choices c JOIN questions q ON q.id=c.question_id WHERE q.quiz_id=? ORDER BY c.question_id, c.label", (quiz_id,)):
        by_id[row[0]]["choices"].append(tuple(row)[1:])
    for row in cur.execute("SELECT p.question_id, p.pair_order, p.left_text, p.right_text FROM matching_pairs p JOIN questions q ON q.id=p.question_id WHERE q.quiz_id=? ORDER BY p.question_id, p.pair_order, p.id", (quiz_id,)):
        by_id[row[0]]["pairs"].append(tuple(row)[1:])
    return hashlib.sha256(encode(content).encode()).hexdigest()


def question_revision(cur, question_id):
    row = cur.execute("SELECT question_text, question_type, matching_round_size, matching_direction, explanation, media_json, correct_letters, correct_text FROM questions WHERE id = ?", (question_id,)).fetchone()
    if row is None:
        return None
    content = {"question": tuple(row), "choices": [tuple(r) for r in cur.execute("SELECT label, text, is_correct FROM choices WHERE question_id = ? ORDER BY label", (question_id,))],
               "pairs": [tuple(r) for r in cur.execute("SELECT pair_order, left_text, right_text FROM matching_pairs WHERE question_id = ? ORDER BY pair_order, id", (question_id,))]}
    return hashlib.sha256(encode(content).encode()).hexdigest()

"""Durable review intent, independent of Study facts and learning estimates."""
import re

STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS review_mark_state (
        id INTEGER PRIMARY KEY CHECK(id=1), generation TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0)""",
    "INSERT OR IGNORE INTO review_mark_state(id,generation) VALUES(1,lower(hex(randomblob(16))))",
    """CREATE TABLE IF NOT EXISTS review_marks (
        id TEXT PRIMARY KEY, question_uid TEXT NOT NULL, question_revision TEXT NOT NULL,
        quiz_id INTEGER NOT NULL, question_number INTEGER NOT NULL, title TEXT NOT NULL,
        question_text TEXT NOT NULL, created_at TEXT NOT NULL, marked INTEGER NOT NULL DEFAULT 1,
        UNIQUE(question_uid,question_revision))""",
    """CREATE TABLE IF NOT EXISTS review_mark_actions (
        request_id TEXT PRIMARY KEY, generation TEXT NOT NULL, input_hash TEXT NOT NULL,
        state TEXT NOT NULL, result_json TEXT, quiz_id INTEGER, html TEXT)""",
)
COLUMNS = {
    'review_mark_state': {'id','generation','revision'},
    'review_marks': {'id','question_uid','question_revision','quiz_id','question_number','title','question_text','created_at','marked'},
    'review_mark_actions': {'request_id','generation','input_hash','state','result_json','quiz_id','html'},
}


def migrate(conn):
    for statement in STATEMENTS:
        conn.execute(statement)


def validate_state(conn):
    """Reject an incomplete generation guard; never silently create a replacement."""
    rows = conn.execute('SELECT id,generation,revision FROM review_mark_state').fetchall()
    if (len(rows) != 1 or rows[0][0] != 1
            or not isinstance(rows[0][1], str)
            or not re.fullmatch(r'[0-9a-f]{32}', rows[0][1])
            or type(rows[0][2]) is not int or rows[0][2] < 0):
        raise RuntimeError('DLMS marked-question state is incomplete or invalid. Restore a verified backup; no replacement state was created.')


def invalidate(conn):
    conn.execute("UPDATE review_mark_state SET generation=lower(hex(randomblob(16))),revision=revision+1 WHERE id=1")

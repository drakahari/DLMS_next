"""Additive factual Study history; independent of resettable learning events."""

STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS study_legacy_responses (
        id INTEGER PRIMARY KEY, quiz_id INTEGER, question_id INTEGER,
        attempt_id TEXT, session_id TEXT, mode TEXT, was_correct INTEGER,
        response_json TEXT, occurred_at TEXT,
        FOREIGN KEY(quiz_id) REFERENCES quizzes(id) ON DELETE CASCADE,
        FOREIGN KEY(question_id) REFERENCES questions(id) ON DELETE CASCADE)""",
    "CREATE INDEX IF NOT EXISTS idx_study_legacy_event ON study_legacy_responses(attempt_id)",
    """CREATE TABLE IF NOT EXISTS study_state (
        id INTEGER PRIMARY KEY CHECK(id = 1), generation TEXT NOT NULL,
        learning_reset_at TEXT)""",
    "INSERT OR IGNORE INTO study_state(id, generation) VALUES (1, lower(hex(randomblob(16))))",
    """CREATE TABLE IF NOT EXISTS study_sessions (
        id TEXT PRIMARY KEY, quiz_id INTEGER NOT NULL, purpose TEXT NOT NULL,
        fingerprint TEXT NOT NULL, assessment_revision TEXT NOT NULL,
        manifest_json TEXT NOT NULL, owner TEXT NOT NULL, generation TEXT NOT NULL,
        started_at TEXT NOT NULL, last_activity_at TEXT, completed_at TEXT,
        position INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY(quiz_id) REFERENCES quizzes(id) ON DELETE CASCADE)""",
    """CREATE TABLE IF NOT EXISTS study_responses (
        event_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
        sequence INTEGER NOT NULL CHECK(sequence > 0), question_id INTEGER NOT NULL,
        ordinal INTEGER NOT NULL, kind TEXT NOT NULL, was_correct INTEGER,
        payload_json TEXT NOT NULL, saved_at TEXT NOT NULL,
        UNIQUE(session_id, sequence),
        FOREIGN KEY(session_id) REFERENCES study_sessions(id) ON DELETE CASCADE,
        FOREIGN KEY(question_id) REFERENCES questions(id) ON DELETE CASCADE)""",
    "CREATE INDEX IF NOT EXISTS idx_study_sessions_quiz ON study_sessions(quiz_id, last_activity_at)",
    "CREATE INDEX IF NOT EXISTS idx_study_responses_question ON study_responses(question_id, session_id, sequence)",
)

COLUMNS = {
    "study_legacy_responses": {"id", "quiz_id", "question_id", "attempt_id", "session_id", "mode", "was_correct", "response_json", "occurred_at"},
    "study_state": {"id", "generation", "learning_reset_at"},
    "study_sessions": {"id", "quiz_id", "purpose", "fingerprint", "assessment_revision", "manifest_json", "owner", "generation", "started_at", "last_activity_at", "completed_at", "position"},
    "study_responses": {"event_id", "session_id", "sequence", "question_id", "ordinal", "kind", "was_correct", "payload_json", "saved_at"},
}
INDEXES = {"idx_study_sessions_quiz", "idx_study_responses_question", "idx_study_legacy_event"}


def migrate(conn):
    for statement in STATEMENTS:
        conn.execute(statement)
    # Copy facts verbatim; no session/completion/assistance backfill.
    preserve_legacy(conn)


def preserve_legacy(conn, event_id=None):
    where = " AND id = ?" if event_id is not None else ""
    conn.execute("""INSERT OR IGNORE INTO study_legacy_responses
        SELECT id, quiz_id, question_id, attempt_id, session_id, mode, was_correct, response_json, occurred_at
        FROM learning_events e WHERE event_type = 'study_answer'
        AND NOT EXISTS (SELECT 1 FROM study_responses r WHERE r.event_id = e.attempt_id)""" + where,
                 (event_id,) if event_id is not None else ())


def invalidate_queues(conn, *, reset=False):
    conn.execute("UPDATE study_state SET generation = lower(hex(randomblob(16))) WHERE id = 1")
    if reset:
        conn.execute("UPDATE study_state SET learning_reset_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = 1")

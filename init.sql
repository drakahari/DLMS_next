PRAGMA foreign_keys = ON;

/* =====================================================
   QUIZZES (One record per quiz set)
===================================================== */
CREATE TABLE IF NOT EXISTS quizzes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Human-readable name (NOT unique)
    title TEXT NOT NULL,

    -- Canonical identity (filename or source identifier)
    source_file TEXT NOT NULL UNIQUE,
    registry_id INTEGER,
    -- Explicitly classifies generated quiz families. Legacy rows remain NULL
    -- and continue to use the historical filename/title fallback.
    generation_kind TEXT,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

/* =====================================================
   QUESTIONS (Each quiz question)
===================================================== */
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    quiz_id INTEGER NOT NULL,

    -- Canonical 1-based runtime ordinal. A differing positive source number is
    -- retained as source_number metadata in media_json.
    question_number INTEGER NOT NULL,

    question_text TEXT NOT NULL,
    question_type TEXT NOT NULL DEFAULT 'choice',
    matching_round_size INTEGER,
    matching_direction TEXT NOT NULL DEFAULT 'term_to_definition',
    source_organization TEXT,
    source_dataset TEXT,
    source_version TEXT,
    source_url TEXT,
    source_license TEXT,
    explanation TEXT,
    media_json TEXT,
    correct_letters TEXT,
    correct_text TEXT,
    -- Contract v2 lineage. These installation-local values are intentionally
    -- nullable so legacy rows are not ambiguously backfilled.
    question_uid TEXT,
    canonical_question_uid TEXT,
    source_question_uid TEXT,
    is_generated_copy INTEGER NOT NULL DEFAULT 0,

    -- Prevent accidental duplicate imports of the same question
    UNIQUE (quiz_id, question_number, question_text),

    FOREIGN KEY (quiz_id)
        REFERENCES quizzes(id)
        ON DELETE CASCADE
);

/* =====================================================
   CHOICES (Answer options A–Z)
===================================================== */
CREATE TABLE IF NOT EXISTS choices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    question_id INTEGER NOT NULL,
    label TEXT NOT NULL,          -- "A", "B", "C", etc.
    text TEXT NOT NULL,
    is_correct INTEGER NOT NULL DEFAULT 0,

    FOREIGN KEY (question_id)
        REFERENCES questions(id)
        ON DELETE CASCADE
);

/* =====================================================
   MATCHING PAIRS (Term/prompt -> matching answer)
===================================================== */
CREATE TABLE IF NOT EXISTS matching_pairs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER NOT NULL,
    pair_order INTEGER NOT NULL,
    left_text TEXT NOT NULL,
    right_text TEXT NOT NULL,
    category TEXT,
    explanation TEXT,
    verification_json TEXT,

    FOREIGN KEY (question_id)
        REFERENCES questions(id)
        ON DELETE CASCADE
);

/* =====================================================
   ATTEMPTS (One quiz run — Study or Exam)
===================================================== */
CREATE TABLE IF NOT EXISTS attempts (
    id TEXT PRIMARY KEY,          -- UUID / timestamp-based ID
    quiz_id INTEGER NOT NULL,

    user_name TEXT,
    started_at DATETIME,
    completed_at DATETIME,

    score INTEGER NOT NULL,
    total INTEGER NOT NULL,
    percent INTEGER NOT NULL,
    time_remaining INTEGER,
    mode TEXT NOT NULL,           -- "Exam" or "Study"

    FOREIGN KEY (quiz_id)
        REFERENCES quizzes(id)
        ON DELETE CASCADE
);

/* =====================================================
   ATTEMPT ANSWERS (What user selected)
===================================================== */
CREATE TABLE IF NOT EXISTS attempt_answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    attempt_id TEXT NOT NULL,
    question_id INTEGER NOT NULL,

    selected_labels TEXT,         -- "A" or "A,C"
    was_correct INTEGER NOT NULL,

    FOREIGN KEY (attempt_id)
        REFERENCES attempts(id)
        ON DELETE CASCADE,

    FOREIGN KEY (question_id)
        REFERENCES questions(id)
        ON DELETE CASCADE
);

/* =====================================================
   MISSED QUESTIONS (Analytics convenience table)
===================================================== */
CREATE TABLE IF NOT EXISTS missed_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    attempt_id TEXT NOT NULL,
    question_id INTEGER,
    correct_letters TEXT,
    question_text TEXT,
    choices_text TEXT,
    selected_letters TEXT,
    selected_text TEXT,
    correct_text TEXT,
    attempt_question_number INTEGER,
    question_type TEXT DEFAULT 'choice',
    response_json TEXT,

    FOREIGN KEY (attempt_id)
        REFERENCES attempts(id)
        ON DELETE CASCADE,

    FOREIGN KEY (question_id)
        REFERENCES questions(id)
        ON DELETE CASCADE
);

/* =====================================================
   INDEXES (Performance)
===================================================== */
CREATE INDEX IF NOT EXISTS idx_questions_quiz
    ON questions (quiz_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_questions_question_uid_unique
    ON questions (question_uid) WHERE question_uid IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_questions_canonical_uid
    ON questions (canonical_question_uid);

CREATE INDEX IF NOT EXISTS idx_questions_source_uid
    ON questions (source_question_uid);

CREATE INDEX IF NOT EXISTS idx_choices_question
    ON choices (question_id);

CREATE INDEX IF NOT EXISTS idx_matching_pairs_question
    ON matching_pairs (question_id);

CREATE INDEX IF NOT EXISTS idx_attempts_quiz
    ON attempts (quiz_id);

CREATE INDEX IF NOT EXISTS idx_attempts_completed_id
    ON attempts (completed_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_missed_questions_attempt_number
    ON missed_questions (attempt_id, attempt_question_number);

CREATE INDEX IF NOT EXISTS idx_answers_attempt
    ON attempt_answers (attempt_id);

CREATE INDEX IF NOT EXISTS idx_answers_question
    ON attempt_answers (question_id);

/* =====================================================
   SCHEMA META (Version tracking)
===================================================== */
CREATE TABLE IF NOT EXISTS schema_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    version INTEGER NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO schema_meta (id, version)
VALUES (1, 5);

/* =====================================================
   CONCEPTS / TAGS (DLMS-006)
===================================================== */
CREATE TABLE IF NOT EXISTS concepts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS question_concepts (
    question_id INTEGER NOT NULL,
    concept_id INTEGER NOT NULL,
    PRIMARY KEY (question_id, concept_id),
    FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE,
    FOREIGN KEY (concept_id) REFERENCES concepts(id) ON DELETE CASCADE
);

/* =====================================================
   LEARNING EVENTS (DLMS-007)
===================================================== */
CREATE TABLE IF NOT EXISTS learning_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    quiz_id INTEGER,
    question_id INTEGER,
    attempt_id TEXT,
    session_id TEXT,
    mode TEXT,
    was_correct INTEGER,
    response_json TEXT,
    occurred_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (quiz_id) REFERENCES quizzes(id) ON DELETE CASCADE,
    FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_question_concepts_question ON question_concepts(question_id);
CREATE INDEX IF NOT EXISTS idx_question_concepts_concept ON question_concepts(concept_id);
CREATE INDEX IF NOT EXISTS idx_learning_events_quiz ON learning_events(quiz_id);
CREATE INDEX IF NOT EXISTS idx_learning_events_question ON learning_events(question_id);
CREATE INDEX IF NOT EXISTS idx_learning_events_attempt ON learning_events(attempt_id);
CREATE INDEX IF NOT EXISTS idx_learning_events_session ON learning_events(session_id);
CREATE INDEX IF NOT EXISTS idx_learning_events_occurred ON learning_events(occurred_at);

/* Durable Study history (schema 4). */
CREATE TABLE IF NOT EXISTS study_legacy_responses (
        id INTEGER PRIMARY KEY, quiz_id INTEGER, question_id INTEGER,
        attempt_id TEXT, session_id TEXT, mode TEXT, was_correct INTEGER,
        response_json TEXT, occurred_at TEXT,
        FOREIGN KEY(quiz_id) REFERENCES quizzes(id) ON DELETE CASCADE,
        FOREIGN KEY(question_id) REFERENCES questions(id) ON DELETE CASCADE);
CREATE INDEX IF NOT EXISTS idx_study_legacy_event ON study_legacy_responses(attempt_id);
CREATE TABLE IF NOT EXISTS study_state (
        id INTEGER PRIMARY KEY CHECK(id = 1), generation TEXT NOT NULL,
        learning_reset_at TEXT);
INSERT OR IGNORE INTO study_state(id, generation) VALUES (1, lower(hex(randomblob(16))));
CREATE TABLE IF NOT EXISTS study_sessions (
        id TEXT PRIMARY KEY, quiz_id INTEGER NOT NULL, purpose TEXT NOT NULL,
        fingerprint TEXT NOT NULL, assessment_revision TEXT NOT NULL,
        manifest_json TEXT NOT NULL, owner TEXT NOT NULL, generation TEXT NOT NULL,
        started_at TEXT NOT NULL, last_activity_at TEXT, completed_at TEXT,
        position INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY(quiz_id) REFERENCES quizzes(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS study_responses (
        event_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
        sequence INTEGER NOT NULL CHECK(sequence > 0), question_id INTEGER NOT NULL,
        ordinal INTEGER NOT NULL, kind TEXT NOT NULL, was_correct INTEGER,
        payload_json TEXT NOT NULL, saved_at TEXT NOT NULL,
        UNIQUE(session_id, sequence),
        FOREIGN KEY(session_id) REFERENCES study_sessions(id) ON DELETE CASCADE,
        FOREIGN KEY(question_id) REFERENCES questions(id) ON DELETE CASCADE);
CREATE INDEX IF NOT EXISTS idx_study_sessions_quiz ON study_sessions(quiz_id, last_activity_at);
CREATE INDEX IF NOT EXISTS idx_study_responses_question ON study_responses(question_id, session_id, sequence);

CREATE TABLE IF NOT EXISTS exam_plans (
        id TEXT PRIMARY KEY, config_json TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
        scope_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS exam_plan_state (
        id INTEGER PRIMARY KEY CHECK(id=1), active_plan_id TEXT,
        generation TEXT NOT NULL,
        FOREIGN KEY(active_plan_id) REFERENCES exam_plans(id) ON DELETE SET NULL);
INSERT OR IGNORE INTO exam_plan_state(id,generation) VALUES(1,lower(hex(randomblob(16))));
CREATE TABLE IF NOT EXISTS exam_plan_actions (
        request_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL, generation TEXT NOT NULL,
        input_hash TEXT NOT NULL, quiz_id INTEGER, html TEXT, state TEXT NOT NULL,
        FOREIGN KEY(plan_id) REFERENCES exam_plans(id) ON DELETE CASCADE,
        FOREIGN KEY(quiz_id) REFERENCES quizzes(id) ON DELETE SET NULL);

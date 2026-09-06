"""SQLite connection, schema, and migration foundations for DLMS."""

import os
import sqlite3


DLMS_SCHEMA_VERSION = 2
DLMS_LEGACY_SCHEMA_VERSION = 1

DLMS_SCHEMA_COLUMNS = {
    "quizzes": {"id", "title", "source_file", "registry_id", "created_at"},
    "questions": {
        "id", "quiz_id", "question_number", "question_text", "question_type",
        "matching_round_size", "matching_direction", "source_organization",
        "source_dataset", "source_version", "source_url", "source_license",
        "explanation", "media_json", "correct_letters", "correct_text",
    },
    "choices": {"id", "question_id", "label", "text", "is_correct"},
    "matching_pairs": {
        "id", "question_id", "pair_order", "left_text", "right_text",
        "category", "explanation", "verification_json",
    },
    "attempts": {
        "id", "quiz_id", "user_name", "started_at", "completed_at", "score",
        "total", "percent", "time_remaining", "mode",
    },
    "attempt_answers": {"id", "attempt_id", "question_id", "selected_labels", "was_correct"},
    "missed_questions": {
        "id", "attempt_id", "question_id", "correct_letters", "question_text",
        "choices_text", "selected_letters", "selected_text", "correct_text",
        "attempt_question_number", "question_type", "response_json",
    },
    "concepts": {"id", "name", "created_at"},
    "question_concepts": {"question_id", "concept_id"},
    "learning_events": {
        "id", "event_type", "quiz_id", "question_id", "attempt_id", "session_id",
        "mode", "was_correct", "response_json", "occurred_at",
    },
    "schema_meta": {"id", "version", "created_at"},
}

DLMS_SCHEMA_INDEXES = {
    "idx_questions_quiz",
    "idx_choices_question",
    "idx_matching_pairs_question",
    "idx_attempts_quiz",
    "idx_attempts_completed_id",
    "idx_missed_questions_attempt_number",
    "idx_answers_attempt",
    "idx_answers_question",
    "idx_question_concepts_question",
    "idx_question_concepts_concept",
    "idx_learning_events_quiz",
    "idx_learning_events_question",
    "idx_learning_events_attempt",
    "idx_learning_events_session",
    "idx_learning_events_occurred",
}

DLMS_LEGACY_CORE_TABLES = {
    "quizzes", "questions", "choices", "attempts", "attempt_answers", "missed_questions",
}


class UnsupportedDatabaseSchemaVersionError(RuntimeError):
    """Raised when a database belongs to a newer DLMS schema generation."""


def get_db(db_path, *, sqlite_module=None):
    sqlite_module = sqlite3 if sqlite_module is None else sqlite_module
    conn = sqlite_module.connect(db_path)
    conn.row_factory = sqlite_module.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _database_table_names(conn):
    return {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    }


def _database_column_info(conn, table):
    return {row[1]: row for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()}


def _create_current_database_schema(conn, init_sql_path, *, debug_print=None):
    if debug_print is not None:
        debug_print(f"[DB] init.sql path = {init_sql_path}")
    with open(init_sql_path, "r", encoding="utf-8") as handle:
        sql = handle.read()
    # executescript commits any pending transaction before it starts. Prefixing
    # the script with BEGIN leaves this single fresh-schema transaction open so
    # bootstrap validation can run before the caller commits it.
    conn.executescript("BEGIN IMMEDIATE;\n" + sql)


def _rebuild_legacy_missed_questions(conn, columns):
    def source(name):
        return f'"{name}"' if name in columns else f"NULL AS \"{name}\""

    conn.execute("ALTER TABLE missed_questions RENAME TO missed_questions_legacy_v1")
    conn.execute("""
        CREATE TABLE missed_questions (
            id INTEGER PRIMARY KEY,
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
            response_json TEXT
        )
    """)
    names = [
        "id", "attempt_id", "question_id", "correct_letters", "question_text",
        "choices_text", "selected_letters", "selected_text", "correct_text",
        "attempt_question_number", "question_type", "response_json",
    ]
    conn.execute(
        "INSERT INTO missed_questions (" + ", ".join(f'\"{name}\"' for name in names) + ") "
        "SELECT " + ", ".join(source(name) for name in names) + " FROM missed_questions_legacy_v1"
    )
    conn.execute("DROP TABLE missed_questions_legacy_v1")


def _migrate_schema_to_v2(
    conn,
    *,
    database_column_info=None,
    rebuild_legacy_missed_questions=None,
):
    """Apply the historical repairs formerly run by every get_db() call."""
    if database_column_info is None:
        database_column_info = _database_column_info
    if rebuild_legacy_missed_questions is None:
        rebuild_legacy_missed_questions = _rebuild_legacy_missed_questions

    missed_columns = database_column_info(conn, "missed_questions")
    question_id = missed_columns.get("question_id")
    if question_id is not None and question_id[3] == 1:
        rebuild_legacy_missed_questions(conn, missed_columns)
        missed_columns = database_column_info(conn, "missed_questions")

    missed_additions = {
        "question_id": "INTEGER",
        "question_text": "TEXT",
        "choices_text": "TEXT",
        "correct_letters": "TEXT",
        "selected_letters": "TEXT",
        "selected_text": "TEXT",
        "correct_text": "TEXT",
        "attempt_question_number": "INTEGER",
        "question_type": "TEXT DEFAULT 'choice'",
        "response_json": "TEXT",
    }
    for name, definition in missed_additions.items():
        if name not in missed_columns:
            conn.execute(f'ALTER TABLE missed_questions ADD COLUMN "{name}" {definition}')

    quiz_columns = database_column_info(conn, "quizzes")
    if "registry_id" not in quiz_columns:
        conn.execute("ALTER TABLE quizzes ADD COLUMN registry_id INTEGER")

    question_columns = database_column_info(conn, "questions")
    question_additions = {
        "question_type": "TEXT NOT NULL DEFAULT 'choice'",
        "matching_round_size": "INTEGER",
        "matching_direction": "TEXT NOT NULL DEFAULT 'term_to_definition'",
        "source_organization": "TEXT",
        "source_dataset": "TEXT",
        "source_version": "TEXT",
        "source_url": "TEXT",
        "source_license": "TEXT",
        "explanation": "TEXT",
        "media_json": "TEXT",
    }
    for name, definition in question_additions.items():
        if name not in question_columns:
            conn.execute(f'ALTER TABLE questions ADD COLUMN "{name}" {definition}')

    conn.execute("""
        CREATE TABLE IF NOT EXISTS matching_pairs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER NOT NULL,
            pair_order INTEGER NOT NULL,
            left_text TEXT NOT NULL,
            right_text TEXT NOT NULL,
            category TEXT,
            explanation TEXT,
            verification_json TEXT,
            FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE
        )
    """)
    matching_columns = database_column_info(conn, "matching_pairs")
    for name, definition in {
        "category": "TEXT", "explanation": "TEXT", "verification_json": "TEXT",
    }.items():
        if name not in matching_columns:
            conn.execute(f'ALTER TABLE matching_pairs ADD COLUMN "{name}" {definition}')

    conn.execute("""
        CREATE TABLE IF NOT EXISTS concepts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL COLLATE NOCASE UNIQUE,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS question_concepts (
            question_id INTEGER NOT NULL,
            concept_id INTEGER NOT NULL,
            PRIMARY KEY (question_id, concept_id),
            FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE,
            FOREIGN KEY (concept_id) REFERENCES concepts(id) ON DELETE CASCADE
        )
    """)
    conn.execute("""
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
        )
    """)

    index_statements = [
        "CREATE INDEX IF NOT EXISTS idx_questions_quiz ON questions(quiz_id)",
        "CREATE INDEX IF NOT EXISTS idx_choices_question ON choices(question_id)",
        "CREATE INDEX IF NOT EXISTS idx_matching_pairs_question ON matching_pairs(question_id)",
        "CREATE INDEX IF NOT EXISTS idx_attempts_quiz ON attempts(quiz_id)",
        "CREATE INDEX IF NOT EXISTS idx_attempts_completed_id ON attempts(completed_at DESC, id DESC)",
        "CREATE INDEX IF NOT EXISTS idx_missed_questions_attempt_number ON missed_questions(attempt_id, attempt_question_number)",
        "CREATE INDEX IF NOT EXISTS idx_answers_attempt ON attempt_answers(attempt_id)",
        "CREATE INDEX IF NOT EXISTS idx_answers_question ON attempt_answers(question_id)",
        "CREATE INDEX IF NOT EXISTS idx_question_concepts_question ON question_concepts(question_id)",
        "CREATE INDEX IF NOT EXISTS idx_question_concepts_concept ON question_concepts(concept_id)",
        "CREATE INDEX IF NOT EXISTS idx_learning_events_quiz ON learning_events(quiz_id)",
        "CREATE INDEX IF NOT EXISTS idx_learning_events_question ON learning_events(question_id)",
        "CREATE INDEX IF NOT EXISTS idx_learning_events_attempt ON learning_events(attempt_id)",
        "CREATE INDEX IF NOT EXISTS idx_learning_events_session ON learning_events(session_id)",
        "CREATE INDEX IF NOT EXISTS idx_learning_events_occurred ON learning_events(occurred_at)",
    ]
    for statement in index_statements:
        conn.execute(statement)


DLMS_SCHEMA_MIGRATIONS = {2: _migrate_schema_to_v2}


def _read_database_schema_version(conn, tables, *, database_column_info=None):
    if database_column_info is None:
        database_column_info = _database_column_info
    if "schema_meta" not in tables:
        return None
    columns = database_column_info(conn, "schema_meta")
    if not {"id", "version"}.issubset(columns):
        raise RuntimeError("DLMS schema_meta table is malformed")
    row = conn.execute("SELECT version FROM schema_meta WHERE id = 1").fetchone()
    if row is None:
        return None
    version = row[0]
    if isinstance(version, bool) or not isinstance(version, int):
        raise RuntimeError("DLMS schema version is invalid")
    if version < 1:
        raise RuntimeError(f"Unsupported DLMS schema version: {version}")
    return version


def _validate_current_database_schema(
    conn,
    *,
    schema_columns=None,
    schema_indexes=None,
    database_table_names=None,
    database_column_info=None,
):
    schema_columns = DLMS_SCHEMA_COLUMNS if schema_columns is None else schema_columns
    schema_indexes = DLMS_SCHEMA_INDEXES if schema_indexes is None else schema_indexes
    if database_table_names is None:
        database_table_names = _database_table_names
    if database_column_info is None:
        database_column_info = _database_column_info

    tables = database_table_names(conn)
    missing_tables = sorted(set(schema_columns) - tables)
    if missing_tables:
        raise RuntimeError("DLMS database is missing required tables: " + ", ".join(missing_tables))
    for table, expected in schema_columns.items():
        actual = set(database_column_info(conn, table))
        missing = sorted(expected - actual)
        if missing:
            raise RuntimeError(f"DLMS table {table} is missing required columns: {', '.join(missing)}")
    indexes = {
        row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'").fetchall()
    }
    missing_indexes = sorted(schema_indexes - indexes)
    if missing_indexes:
        raise RuntimeError("DLMS database is missing required indexes: " + ", ".join(missing_indexes))


def bootstrap_database(
    db_path,
    *,
    schema_version,
    legacy_schema_version,
    legacy_core_tables,
    migrations,
    create_current_schema,
    database_table_names,
    read_schema_version,
    validate_current_schema,
    sqlite_module=None,
):
    """Create or migrate one already-validated DLMS database path."""
    sqlite_module = sqlite3 if sqlite_module is None else sqlite_module
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite_module.connect(db_path)
    conn.row_factory = sqlite_module.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        tables = database_table_names(conn)
        if not tables:
            create_current_schema(conn)
            validate_current_schema(conn)
            version = read_schema_version(conn, database_table_names(conn))
            if version != schema_version:
                raise RuntimeError(
                    f"Fresh DLMS schema version {version!r} does not match {schema_version}"
                )
            conn.commit()
            print("[DB] Database schema initialized")
            return {"status": "created", "version": schema_version}

        if not legacy_core_tables.issubset(tables):
            missing = sorted(legacy_core_tables - tables)
            raise RuntimeError("Unsupported incomplete DLMS database; missing: " + ", ".join(missing))

        version = read_schema_version(conn, tables)
        if version is not None and version > schema_version:
            raise UnsupportedDatabaseSchemaVersionError(
                f"Database schema version {version} is newer than this DLMS build "
                f"(supports {schema_version})"
            )
        if version == schema_version:
            validate_current_schema(conn)
            return {"status": "current", "version": version}

        conn.execute("BEGIN IMMEDIATE")
        if "schema_meta" not in tables:
            conn.execute("""
                CREATE TABLE schema_meta (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    version INTEGER NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
        if version is None:
            version = legacy_schema_version
            conn.execute(
                "INSERT OR REPLACE INTO schema_meta (id, version) VALUES (1, ?)", (version,)
            )

        start_version = version
        for target_version in range(version + 1, schema_version + 1):
            migration = migrations.get(target_version)
            if migration is None:
                raise RuntimeError(f"No DLMS migration is available for schema version {target_version}")
            migration(conn)

        validate_current_schema(conn)
        conn.execute("UPDATE schema_meta SET version = ? WHERE id = 1", (schema_version,))
        conn.commit()
        print(f"[DB] Database schema migrated from {start_version} to {schema_version}")
        return {"status": "migrated", "version": schema_version, "from_version": start_version}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

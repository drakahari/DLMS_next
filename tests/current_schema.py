"""Reusable current-schema database fixtures for integration-style tests."""

import json
from dataclasses import dataclass
from pathlib import Path

from dlms.persistence.database import (
    DLMS_SCHEMA_COLUMNS,
    DLMS_SCHEMA_INDEXES,
    DLMS_SCHEMA_VERSION,
    get_db as open_database_connection,
)
from dlms.services.learning import _normalize_concept_names


def assert_current_schema(connection):
    """Fail loudly when an integration fixture is not the supported schema."""
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    }
    missing_tables = set(DLMS_SCHEMA_COLUMNS) - tables
    if missing_tables:
        raise AssertionError(
            "Current-schema fixture is missing tables: "
            + ", ".join(sorted(missing_tables))
        )
    for table, expected_columns in DLMS_SCHEMA_COLUMNS.items():
        actual_columns = {
            row[1]
            for row in connection.execute(
                f'PRAGMA table_info("{table}")'
            ).fetchall()
        }
        missing_columns = expected_columns - actual_columns
        if missing_columns:
            raise AssertionError(
                f"Current-schema fixture table {table} is missing columns: "
                + ", ".join(sorted(missing_columns))
            )

    indexes = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        ).fetchall()
    }
    missing_indexes = DLMS_SCHEMA_INDEXES - indexes
    if missing_indexes:
        raise AssertionError(
            "Current-schema fixture is missing indexes: "
            + ", ".join(sorted(missing_indexes))
        )
    version = connection.execute(
        "SELECT version FROM schema_meta WHERE id = 1"
    ).fetchone()
    if version is None or version[0] != DLMS_SCHEMA_VERSION:
        raise AssertionError("Current-schema fixture has the wrong schema version")


def _insert_question_concepts(cursor, question_id, names):
    for name in _normalize_concept_names(names):
        cursor.execute(
            "INSERT OR IGNORE INTO concepts (name) VALUES (?)",
            (name,),
        )
        concept = cursor.execute(
            "SELECT id FROM concepts WHERE name = ? COLLATE NOCASE",
            (name,),
        ).fetchone()
        cursor.execute(
            """
            INSERT OR IGNORE INTO question_concepts (question_id, concept_id)
            VALUES (?, ?)
            """,
            (question_id, concept[0]),
        )


def seed_current_quiz(
    connection_factory,
    title,
    source_file,
    questions,
    *,
    quiz_id=None,
    registry_id=None,
):
    """Insert representative quiz rows using only supported named columns."""
    connection = connection_factory()
    try:
        assert_current_schema(connection)
        cursor = connection.cursor()
        if quiz_id is None:
            cursor.execute(
                """
                INSERT INTO quizzes (title, source_file, registry_id)
                VALUES (?, ?, ?)
                """,
                (title, source_file, registry_id),
            )
            quiz_id = cursor.lastrowid
        else:
            cursor.execute(
                """
                INSERT INTO quizzes (id, title, source_file, registry_id)
                VALUES (?, ?, ?, ?)
                """,
                (quiz_id, title, source_file, registry_id),
            )

        for question in questions:
            question_type = (question.get("type") or "choice").strip().lower()
            if question_type not in {"choice", "matching"}:
                question_type = "choice"
            media = question.get("media") or {
                key: question.get(key)
                for key in (
                    "image_url", "image_alt", "image_edits", "image_source"
                )
                if question.get(key) is not None
            }
            if question.get("source_number") is not None:
                media = dict(media)
                media["source_number"] = question["source_number"]
            source = question.get("source") or {}
            values = (
                quiz_id,
                question.get("number"),
                question.get("question") or question.get("text") or "",
                question_type,
                question.get("round_size"),
                question.get("direction", "term_to_definition"),
                source.get("organization"),
                source.get("dataset"),
                source.get("version"),
                source.get("url"),
                source.get("license"),
                question.get("explanation") or "",
                json.dumps(media, ensure_ascii=False),
            )
            question_id = question.get("id")
            if question_id is None:
                cursor.execute(
                    """
                    INSERT INTO questions (
                        quiz_id, question_number, question_text, question_type,
                        matching_round_size, matching_direction,
                        source_organization, source_dataset, source_version,
                        source_url, source_license, explanation, media_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
                question_id = cursor.lastrowid
            else:
                cursor.execute(
                    """
                    INSERT INTO questions (
                        id, quiz_id, question_number, question_text,
                        question_type, matching_round_size, matching_direction,
                        source_organization, source_dataset, source_version,
                        source_url, source_license, explanation, media_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (question_id, *values),
                )

            _insert_question_concepts(
                cursor,
                question_id,
                question.get("concepts") or question.get("tags") or [],
            )
            if question_type == "matching":
                for pair_order, pair in enumerate(
                    question.get("pairs", []), start=1
                ):
                    cursor.execute(
                        """
                        INSERT INTO matching_pairs (
                            question_id, pair_order, left_text, right_text,
                            category, explanation, verification_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            question_id,
                            pair_order,
                            pair.get("left", ""),
                            pair.get("right", ""),
                            pair.get("category", ""),
                            pair.get("explanation", ""),
                            json.dumps(
                                pair.get("verification") or {},
                                ensure_ascii=False,
                            ),
                        ),
                    )
            else:
                for choice in question.get("choices", []):
                    cursor.execute(
                        """
                        INSERT INTO choices (
                            question_id, label, text, is_correct
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (
                            question_id,
                            choice.get("label"),
                            choice.get("text"),
                            1 if choice.get("is_correct") else 0,
                        ),
                    )
        connection.commit()
        return quiz_id
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


@dataclass(frozen=True)
class CurrentSchemaDatabase:
    path: Path

    def connect(self):
        return open_database_connection(str(self.path))

    def seed_quiz(self, title, source_file, questions, **kwargs):
        return seed_current_quiz(
            self.connect,
            title,
            source_file,
            questions,
            **kwargs,
        )


def bootstrap_current_schema_database(path, *, bootstrap_database):
    """Bootstrap and validate an isolated supported-schema test database."""
    path = Path(path)
    bootstrap_database(str(path), require_owned_root=False)
    database = CurrentSchemaDatabase(path)
    connection = database.connect()
    try:
        assert_current_schema(connection)
    finally:
        connection.close()
    return database

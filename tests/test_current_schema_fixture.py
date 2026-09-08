"""Guard the supported-schema integration fixture and retired DB seed seam."""

import ast
import json
import tempfile
import unittest
from pathlib import Path

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms
from tests.current_schema import bootstrap_current_schema_database


ROOT = Path(__file__).resolve().parents[1]


class CurrentSchemaFixtureTests(unittest.TestCase):
    def test_bootstrap_and_seed_choice_matching_and_concept_rows(self):
        with tempfile.TemporaryDirectory(
            prefix="dlms-current-schema-fixture-"
        ) as directory:
            database = bootstrap_current_schema_database(
                Path(directory) / "results.db",
                bootstrap_database=dlms.bootstrap_database,
            )
            quiz_id = database.seed_quiz(
                "Representative Quiz",
                "representative.html",
                [
                    {
                        "number": 1,
                        "question": "Which answer is supported?",
                        "choices": [
                            {"label": "A", "text": "Alpha", "is_correct": True},
                            {"label": "B", "text": "Beta", "is_correct": False},
                        ],
                        "concepts": ["Schema", "schema", "Fixtures"],
                        "source": {
                            "organization": "DLMS",
                            "dataset": "Tests",
                            "version": "1",
                            "url": "https://example.invalid/source",
                            "license": "Test",
                        },
                        "explanation": "Alpha is the supported answer.",
                    },
                    {
                        "number": 2,
                        "type": "matching",
                        "question": "Match the terms.",
                        "round_size": 2,
                        "direction": "definition_to_term",
                        "pairs": [
                            {"left": "One", "right": "First"},
                            {
                                "left": "Two",
                                "right": "Second",
                                "category": "Numbers",
                                "explanation": "Ordinal mapping",
                                "verification": {"verified": True},
                            },
                        ],
                    },
                ],
            )

            connection = database.connect()
            try:
                quiz = connection.execute(
                    "SELECT title, source_file FROM quizzes WHERE id = ?",
                    (quiz_id,),
                ).fetchone()
                questions = connection.execute(
                    """
                    SELECT question_number, question_text, question_type,
                           matching_round_size, matching_direction,
                           source_organization, source_dataset, explanation
                    FROM questions WHERE quiz_id = ? ORDER BY question_number
                    """,
                    (quiz_id,),
                ).fetchall()
                choices = connection.execute(
                    """
                    SELECT label, text, is_correct FROM choices
                    WHERE question_id = (
                        SELECT id FROM questions
                        WHERE quiz_id = ? AND question_number = 1
                    ) ORDER BY label
                    """,
                    (quiz_id,),
                ).fetchall()
                pairs = connection.execute(
                    """
                    SELECT left_text, right_text, category, explanation,
                           verification_json
                    FROM matching_pairs
                    WHERE question_id = (
                        SELECT id FROM questions
                        WHERE quiz_id = ? AND question_number = 2
                    ) ORDER BY pair_order
                    """,
                    (quiz_id,),
                ).fetchall()
                concepts = connection.execute(
                    """
                    SELECT c.name FROM concepts c
                    JOIN question_concepts qc ON qc.concept_id = c.id
                    JOIN questions q ON q.id = qc.question_id
                    WHERE q.quiz_id = ? ORDER BY c.name COLLATE NOCASE
                    """,
                    (quiz_id,),
                ).fetchall()
                question_columns = {
                    row[1]
                    for row in connection.execute(
                        'PRAGMA table_info("questions")'
                    ).fetchall()
                }
            finally:
                connection.close()

        self.assertEqual(
            ("Representative Quiz", "representative.html"), tuple(quiz)
        )
        self.assertEqual([1, 2], [row["question_number"] for row in questions])
        self.assertEqual(
            ["choice", "matching"],
            [row["question_type"] for row in questions],
        )
        self.assertIn("question_number", question_columns)
        self.assertIn("question_text", question_columns)
        self.assertNotIn("number", question_columns)
        self.assertNotIn("text", question_columns)
        self.assertEqual((2, "definition_to_term"), tuple(questions[1])[3:5])
        self.assertEqual("DLMS", questions[0]["source_organization"])
        self.assertEqual("Tests", questions[0]["source_dataset"])
        self.assertEqual(
            "Alpha is the supported answer.", questions[0]["explanation"]
        )
        self.assertEqual(
            [("A", "Alpha", 1), ("B", "Beta", 0)],
            [tuple(row) for row in choices],
        )
        self.assertEqual(
            [("One", "First"), ("Two", "Second")],
            [(row["left_text"], row["right_text"]) for row in pairs],
        )
        self.assertEqual("Numbers", pairs[1]["category"])
        self.assertEqual("Ordinal mapping", pairs[1]["explanation"])
        self.assertEqual(
            {"verified": True}, json.loads(pairs[1]["verification_json"])
        )
        self.assertEqual(["Fixtures", "Schema"], [row["name"] for row in concepts])

    def test_save_quiz_to_db_seam_and_active_callers_are_absent(self):
        self.assertFalse(hasattr(dlms, "save_quiz_to_db"))
        paths = [
            ROOT / "app.py",
            *(ROOT / "dlms").rglob("*.py"),
            *(ROOT / "tests").rglob("*.py"),
        ]
        for path in paths:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            active_references = [
                node
                for node in ast.walk(tree)
                if (
                    isinstance(node, ast.Name)
                    and node.id == "save_quiz_to_db"
                ) or (
                    isinstance(node, ast.Attribute)
                    and node.attr == "save_quiz_to_db"
                )
            ]
            self.assertEqual([], active_references, str(path))

    def test_reduced_schemas_are_confined_to_explicit_specialized_fixtures(self):
        schema_token = "CREATE " + "TABLE"
        schema_owners = set()
        for path in (ROOT / "tests").glob("test_*.py"):
            source = path.read_text(encoding="utf-8")
            if schema_token in source:
                schema_owners.add(path.name)
        self.assertEqual(
            {
                "test_anki_temp_cleanup.py",
                "test_backup_semantic_validation.py",
                "test_database_bootstrap.py",
                "test_history_api_pagination.py",
                "test_restore_migration.py",
            },
            schema_owners,
        )


if __name__ == "__main__":
    unittest.main()

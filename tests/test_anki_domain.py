"""Golden characterization coverage for the Anki domain/export helpers."""

import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from tests._isolation import ensure_test_data_isolation

ensure_test_data_isolation()
import app as dlms
from tests.current_schema import bootstrap_current_schema_database
from tests.csrf_test_utils import csrf_token


class AnkiDomainTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dlms-anki-domain-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def _database(self, name):
        return bootstrap_current_schema_database(
            self.root / name,
            bootstrap_database=dlms.bootstrap_database,
        )

    def test_quiz_rows_preserve_schema_field_order_and_card_order(self):
        database = self._database("quiz-rows.db")
        database.seed_quiz(
            "Network Review",
            "network-review.html",
            [
                {"id": 72, "number": 2, "question": " Second? "},
                {
                    "id": 71,
                    "number": 1,
                    "question": " First? ",
                    "choices": [
                        {"label": "B", "text": " Beta ", "is_correct": True},
                        {"label": "A", "text": " Alpha ", "is_correct": False},
                    ],
                },
            ],
            quiz_id=7,
        )

        with mock.patch.object(dlms, "get_db", side_effect=database.connect):
            title, rows = dlms.build_anki_rows_for_quiz("7")

        self.assertEqual("Network Review", title)
        self.assertEqual([1, 2], [row["question_number"] for row in rows])
        self.assertEqual(
            ["front", "back", "question_number", "question_id", "quiz_id"],
            list(rows[0]),
        )
        self.assertEqual("First?\n\nA. Alpha\nB. Beta", rows[0]["front"])
        self.assertEqual("Correct Answer\nB. Beta", rows[0]["back"])
        self.assertEqual("Second?", rows[1]["front"])
        self.assertEqual("Correct Answer", rows[1]["back"])

        self.assertEqual((None, []), dlms.build_anki_rows_for_quiz("not-an-id"))

    def test_missed_rows_preserve_schema_status_text_and_sorting(self):
        database = self._database("missed-rows.db")
        database.seed_quiz(
            "Security Quiz",
            "security-quiz.html",
            [
                {"id": 11, "number": 1, "question": "Recovered?"},
                {"id": 12, "number": 2, "question": "Weak?"},
            ],
            quiz_id=1,
        )
        connection = database.connect()
        try:
            connection.executemany(
                """
                INSERT INTO attempts (
                    id, quiz_id, completed_at, score, total, percent, mode
                ) VALUES (?, ?, ?, 0, 1, 0, 'Exam')
                """,
                [
                    ("a1", 1, "2026-01-01T10:00:00"),
                    ("a2", 1, "2026-01-02T10:00:00"),
                    ("a3", 1, "2026-01-03T10:00:00"),
                ],
            )
            connection.executemany(
                """
                INSERT INTO missed_questions (
                    id, attempt_id, question_id, attempt_question_number,
                    question_text, choices_text, correct_text, correct_letters
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (1, "a1", 11, 1, "Recovered?", "A. No\nB. Yes", "B. Yes", "B"),
                    (2, "a2", 12, 2, "Weak?", "A. No\nB. Yes", "B. Yes", "B"),
                    (3, "a3", 12, 2, "Weak?", "A. No\nB. Yes", "B. Yes", "B"),
                ],
            )
            connection.commit()
        finally:
            connection.close()

        with mock.patch.object(dlms, "get_db", side_effect=database.connect):
            rows = dlms.build_anki_rows_for_missed(None, 1, "all")

        self.assertEqual(["currently_weak", "recovered"], [row["recovery_status"] for row in rows])
        self.assertEqual(
            [
                "front", "back", "quiz_title", "quiz_id", "question_number",
                "question_id", "miss_count", "recovery_status",
            ],
            list(rows[0]),
        )
        self.assertEqual("Weak?\n\nA. No\nB. Yes", rows[0]["front"])
        self.assertEqual(
            "Correct Answer\nB. Yes\n\nMissed in DLMS: 2 times\n"
            "DLMS status: Currently Weak",
            rows[0]["back"],
        )
        self.assertEqual(2, rows[0]["miss_count"])
        self.assertEqual("DLMS status: Recovered Later", rows[1]["back"].splitlines()[-1])

    def test_law_parser_preserves_aliases_headings_unicode_and_schema(self):
        cards = dlms.parse_law_flashcards_text(
            """
            **Flashcard #1:**
            **Front:** Café duty?
            **Back:** Reasonable care & prudence.

            Flashcard 2
            Q: What is consideration?
            Continued question text.
            A: A bargained-for exchange.

            Front: Incomplete card
            """
        )

        self.assertEqual(
            [
                {"front": "** Café duty?", "back": "** Reasonable care & prudence."},
                {
                    "front": "What is consideration?\nContinued question text.",
                    "back": "A bargained-for exchange.",
                },
            ],
            cards,
        )
        self.assertEqual(["front", "back"], list(cards[0]))
        self.assertEqual([], dlms.parse_law_flashcards_text("unlabeled text"))

    def test_law_selection_preserves_case_order_prefixes_and_metadata(self):
        law_cases = [
            {"id": "b", "title": "Beta", "course": "Contracts"},
            {"id": "a", "title": "Alpha", "course": "Contracts"},
        ]
        loaded = {
            "a": ({"id": "a", "title": "Alpha", "course": "Contracts"}, [{"front": "A?", "back": "A."}]),
            "b": ({"id": "b", "title": "Beta", "course": "Contracts"}, [{"front": "B?", "back": "B."}]),
        }

        with mock.patch.object(dlms, "get_anki_law_case_choices", return_value=law_cases), mock.patch.object(
            dlms, "load_law_flashcards_for_case", side_effect=lambda case_id: loaded[case_id]
        ):
            metadata, rows = dlms.load_law_flashcards_for_selection(case_ids=["a", "b"])

        self.assertEqual(
            {"course": None, "case_count": 2, "case_titles": ["Beta", "Alpha"]},
            metadata,
        )
        self.assertEqual(["Beta\n\nB?", "Alpha\n\nA?"], [row["front"] for row in rows])

    def test_custom_rows_preserve_source_order_tokens_and_deduplication(self):
        quiz_card = {"front": "Question?", "back": "Answer", "question_id": 10}
        missed_card = {
            "front": "Question?", "back": "Answer", "quiz_title": "Quiz One",
            "quiz_id": 1, "question_id": 10, "question_number": 1,
        }
        law_card = {"front": "Rule?", "back": "Rule."}

        with mock.patch.object(dlms, "get_anki_quiz_choices", return_value=[{"id": 1}]), mock.patch.object(
            dlms, "build_anki_rows_for_quiz", return_value=("Quiz One", [quiz_card])
        ), mock.patch.object(
            dlms, "build_anki_rows_for_missed", return_value=[missed_card]
        ), mock.patch.object(
            dlms,
            "get_anki_law_case_choices",
            return_value=[{"id": "case", "title": "Case", "course": "Law"}],
        ), mock.patch.object(
            dlms,
            "load_law_flashcards_for_case",
            return_value=({"title": "Case", "course": "Law"}, [law_card]),
        ):
            rows = dlms.build_custom_anki_rows(
                ["quiz:1:10"], ["missed:1:10"], ["law:case:1"]
            )

        self.assertEqual(2, len(rows))
        self.assertEqual("Quiz One\n\nQuestion?", rows[0]["front"])
        self.assertEqual("Law · Case\n\nRule?", rows[1]["front"])
        self.assertEqual([], dlms.build_custom_anki_rows())

    def test_quiz_tsv_preserves_exact_html_tags_delimiters_and_newlines(self):
        database = self._database("quiz-tsv.db")
        database.seed_quiz(
            "Quiz One",
            "quiz-one.html",
            [{
                "id": 31,
                "number": 1,
                "question": "What\tis <x>?",
                "choices": [
                    {"label": "A", "text": "Alpha\tvalue", "is_correct": False},
                    {"label": "B", "text": "Beta", "is_correct": True},
                ],
            }],
            quiz_id=3,
        )

        with mock.patch.object(dlms, "get_db", side_effect=database.connect):
            tsv = dlms.export_anki_tsv_for_quiz(3)

        self.assertEqual(
            "Front\tBack\tTags\n"
            "<b>What is <x>?</b><br><br>A. Alpha value<br>B. Beta\t"
            "<b>Correct answer:</b> B<br><br>B. Beta\tQuiz_One",
            tsv,
        )
        self.assertFalse(tsv.endswith("\n"))

        empty_database = self._database("empty-quiz-tsv.db")
        with mock.patch.object(
            dlms, "get_db", side_effect=empty_database.connect
        ):
            self.assertEqual(
                "Front\tBack\tTags", dlms.export_anki_tsv_for_quiz(99)
            )

    def test_missed_tsv_route_preserves_exact_rows_tags_encoding_and_filename(self):
        database = self._database("missed-tsv.db")
        database.seed_quiz(
            "Café Quiz",
            "cafe-quiz.html",
            [{
                "id": 41,
                "number": 9,
                "question": "Question\tüber?",
                "choices": [
                    {"label": "B", "text": "Beta", "is_correct": True},
                    {"label": "A", "text": "Alpha\tvalue", "is_correct": False},
                ],
            }],
            quiz_id=4,
        )
        connection = database.connect()
        try:
            connection.execute(
                """
                INSERT INTO attempts (
                    id, quiz_id, score, total, percent, mode
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                ("attempt", 4, 0, 1, 0, "Exam"),
            )
            connection.execute(
                """
                INSERT INTO missed_questions (
                    attempt_id, question_id, attempt_question_number
                ) VALUES (?, ?, ?)
                """,
                ("attempt", 41, 1),
            )
            connection.commit()
        finally:
            connection.close()
        client = dlms.app.test_client()

        with mock.patch.object(dlms, "get_db", side_effect=database.connect):
            response = client.post(
                "/export/anki/missed",
                json={"attempt_id": "attempt", "attempt_question_numbers": [1]},
                headers={"X-CSRFToken": csrf_token(client)},
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            "Front\tBack\tTags\n"
            "Question über?\n\nA. Alpha value\nB. Beta\t"
            "Correct: B\nB. Beta\tCafé_Quiz missed",
            response.get_data(as_text=True),
        )
        self.assertEqual(
            "attachment; filename=missed_questions_anki.tsv",
            response.headers["Content-Disposition"],
        )
        self.assertIn("charset=utf-8", response.content_type)

    def test_apkg_generation_preserves_model_deck_notes_and_html_escaping(self):
        observed = {}

        class Model:
            def __init__(self, model_id, name, *, fields, templates):
                observed["model"] = (model_id, name, fields, templates)

        class Deck:
            def __init__(self, deck_id, name):
                observed["deck"] = (deck_id, name)
                self.notes = []

            def add_note(self, note):
                self.notes.append(note)

        class Note:
            def __init__(self, *, model, fields):
                observed.setdefault("notes", []).append((model, fields))

        class Package:
            def __init__(self, deck):
                observed["package_deck"] = deck

            def write_to_file(self, path):
                Path(path).write_bytes(b"representative-apkg")

        fake_genanki = types.SimpleNamespace(
            Model=Model, Deck=Deck, Note=Note, Package=Package
        )

        with mock.patch.object(dlms, "genanki", fake_genanki), mock.patch.object(
            dlms.random, "randrange", return_value=1234567890
        ):
            path = dlms.export_quiz_to_apkg(
                "Deck::Name",
                [{"front": "<b>&\nTwo", "back": '"Answer"'}],
            )

        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        self.assertTrue(path.endswith(".apkg"))
        self.assertEqual(b"representative-apkg", Path(path).read_bytes())
        self.assertEqual(
            (
                1607392319,
                "AutoQuiz Model",
                [{"name": "Front"}, {"name": "Back"}],
                [{"name": "Card 1", "qfmt": "{{Front}}", "afmt": "<hr id='answer'>{{Back}}"}],
            ),
            observed["model"],
        )
        self.assertEqual((1234567890, "Deck::Name"), observed["deck"])
        self.assertEqual(
            ["&lt;b&gt;&amp;<br>Two", "&quot;Answer&quot;"],
            observed["notes"][0][1],
        )
        self.assertIsInstance(observed["package_deck"].notes[0], Note)

        observed.clear()
        with mock.patch.object(dlms, "genanki", fake_genanki), mock.patch.object(
            dlms.random, "randrange", return_value=1234567890
        ):
            empty_path = dlms.export_quiz_to_apkg("Empty Deck", [])
        self.addCleanup(
            lambda: os.path.exists(empty_path) and os.remove(empty_path)
        )
        self.assertEqual([], observed["package_deck"].notes)


if __name__ == "__main__":
    unittest.main()

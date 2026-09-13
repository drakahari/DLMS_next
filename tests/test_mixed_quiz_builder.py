"""DLMS-128 mixed quiz composition regressions."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms
from dlms.services.quiz_composition import (
    build_mixed_quiz_catalog,
    filter_mixed_quiz_catalog,
    mixed_quiz_filter_options,
)
from tests.csrf_test_utils import csrf_headers
from tests.current_schema import seed_current_quiz


class MixedQuizBuilderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dlms-128-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        paths = {
            "APP_DATA_DIR": self.root,
            "DATA_FOLDER": self.root / "data",
            "QUIZ_FOLDER": self.root / "quizzes",
            "CONFIG_FOLDER": self.root / "config",
            "QUIZ_REGISTRY": self.root / "config" / "quizzes.json",
            "DB_PATH": self.root / "results.db",
            "QUIZ_ASSET_FOLDER": self.root / "quiz_assets",
            "LOGO_FOLDER": self.root / "static" / "logos",
        }
        self.patches = [
            mock.patch.object(dlms, name, str(path))
            for name, path in paths.items()
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        for name, path in paths.items():
            if name not in {"QUIZ_REGISTRY", "DB_PATH", "APP_DATA_DIR"}:
                path.mkdir(parents=True, exist_ok=True)
        self.assertTrue(dlms._initialize_data_root_ownership(str(self.root)))
        dlms.ensure_db_initialized()
        dlms.save_registry([])

    @staticmethod
    def _question(text, *, concepts=(), number=1, source=None, matching=False):
        if matching:
            return {
                "number": number,
                "type": "matching",
                "question": text,
                "concepts": list(concepts),
                "pairs": [
                    {"left": "Alpha", "right": "First"},
                    {"left": "Beta", "right": "Second"},
                ],
                "round_size": 2,
                "source": source or {},
            }
        return {
            "number": number,
            "question": text,
            "concepts": list(concepts),
            "explanation": f"Explanation for {text}",
            "source": source or {},
            "choices": [
                {"label": "A", "text": "Expected", "is_correct": True},
                {"label": "B", "text": "Alternative", "is_correct": False},
            ],
        }

    def _seed(self, title, source_file, questions, *, folder="Uncategorized"):
        quiz_id = seed_current_quiz(
            dlms.get_db, title, source_file, questions
        )
        registry = dlms.load_registry()
        registry.append({
            "id": quiz_id,
            "title": title,
            "html": source_file,
            "folder": folder,
            "exam_minutes": 90,
        })
        dlms.save_registry(registry)
        conn = dlms.get_db()
        try:
            question_ids = [
                row[0]
                for row in conn.execute(
                    "SELECT id FROM questions WHERE quiz_id = ? ORDER BY question_number, id",
                    (quiz_id,),
                ).fetchall()
            ]
        finally:
            conn.close()
        return quiz_id, question_ids

    def _catalog(self):
        conn = dlms.get_db()
        try:
            return build_mixed_quiz_catalog(conn.cursor(), dlms.load_registry())
        finally:
            conn.close()

    def test_catalog_combines_sources_and_exposes_supported_filters(self):
        first_quiz, first_questions = self._seed(
            "Networking Bank",
            "networking.html",
            [self._question("Which item routes traffic?", concepts=["Routing"])],
            folder="IT",
        )
        second_quiz, second_questions = self._seed(
            "Policy Bank",
            "policy.html",
            [self._question("Which item states the rule?", concepts=["Policy"])],
            folder="Governance",
        )

        catalog = self._catalog()
        options = mixed_quiz_filter_options(catalog)

        self.assertEqual(first_questions + second_questions, [row["question_id"] for row in catalog])
        self.assertEqual(["Governance", "IT"], options["folders"])
        self.assertEqual(["Policy", "Routing"], options["concepts"])
        self.assertEqual(
            {first_quiz, second_quiz},
            {item["id"] for item in options["quizzes"]},
        )
        self.assertEqual(
            [first_questions[0]],
            [row["question_id"] for row in filter_mixed_quiz_catalog(catalog, folder="it")],
        )
        self.assertEqual(
            [second_questions[0]],
            [row["question_id"] for row in filter_mixed_quiz_catalog(catalog, source_quiz_id=second_quiz)],
        )
        self.assertEqual(
            [first_questions[0]],
            [row["question_id"] for row in filter_mixed_quiz_catalog(catalog, concept="routing")],
        )

    def test_missed_filter_uses_canonical_learning_events_and_untagged_questions_are_safe(self):
        quiz_id, question_ids = self._seed(
            "History Bank",
            "history.html",
            [
                self._question("Previously missed question?"),
                self._question("Question without history?", number=2),
            ],
        )
        conn = dlms.get_db()
        cur = conn.cursor()
        dlms._record_learning_event(
            cur,
            event_type="exam_answer",
            quiz_id=quiz_id,
            question_id=question_ids[0],
            attempt_id="mixed-miss-1",
            mode="Exam",
            was_correct=False,
        )
        conn.commit()
        conn.close()

        catalog = self._catalog()

        self.assertEqual([], catalog[0]["concepts"])
        self.assertEqual(
            [question_ids[0]],
            [row["question_id"] for row in filter_mixed_quiz_catalog(catalog, missed="missed")],
        )
        self.assertEqual(
            [question_ids[1]],
            [row["question_id"] for row in filter_mixed_quiz_catalog(catalog, missed="not-missed")],
        )

    def test_exact_duplicate_is_offered_once_with_all_original_provenance(self):
        _first_quiz, first_questions = self._seed(
            "First Source",
            "first.html",
            [self._question("Shared canonical prompt?", concepts=["Alpha"])],
            folder="One",
        )
        second_quiz, _second_questions = self._seed(
            "Second Source",
            "second.html",
            [self._question("  SHARED   canonical prompt? ", concepts=["Beta"])],
            folder="Two",
        )

        catalog = self._catalog()

        self.assertEqual(1, len(catalog))
        self.assertEqual(first_questions[0], catalog[0]["question_id"])
        self.assertEqual(2, catalog[0]["duplicate_count"])
        self.assertEqual(["Alpha", "Beta"], catalog[0]["concepts"])
        self.assertEqual({"First Source", "Second Source"}, set(catalog[0]["source_quiz_titles"]))
        self.assertIn(second_quiz, catalog[0]["source_quiz_ids"])

    def test_generated_quizzes_are_not_sources_but_their_miss_maps_to_original(self):
        original_quiz, original_questions = self._seed(
            "Original Bank",
            "original.html",
            [self._question("Reusable original prompt?", concepts=["Reuse"])],
        )
        generated_quiz, generated_questions = self._seed(
            "User Named Mix",
            "mixed_quiz_123456.html",
            [self._question("Reusable original prompt?", concepts=["Reuse"])],
        )
        self._seed(
            "Generated Only",
            "adaptive_study_123456.html",
            [self._question("Generated-only prompt?")],
        )
        conn = dlms.get_db()
        cur = conn.cursor()
        dlms._record_learning_event(
            cur,
            event_type="study_answer",
            quiz_id=generated_quiz,
            question_id=generated_questions[0],
            session_id="mixed-copy-study",
            mode="Study",
            was_correct=False,
        )
        conn.commit()
        conn.close()

        catalog = self._catalog()

        self.assertEqual([original_questions[0]], [row["question_id"] for row in catalog])
        self.assertEqual([original_quiz], catalog[0]["source_quiz_ids"])
        self.assertTrue(catalog[0]["ever_missed"])

    def test_builder_page_supports_preview_filters_and_empty_no_match_state(self):
        self._seed(
            "Preview Bank",
            "preview.html",
            [self._question("Preview this neutral question?", concepts=["Previewing"])],
            folder="Preview Folder",
        )
        response = dlms.app.test_client().get("/quiz-composer")
        html = response.get_data(as_text=True)

        self.assertEqual(200, response.status_code)
        self.assertIn("Mixed Quiz Builder", html)
        self.assertIn("Preview this neutral question?", html)
        self.assertIn("Preview answer choices", html)
        self.assertIn("Alternative", html)
        self.assertIn('id="folderFilter"', html)
        self.assertIn('id="sourceFilter"', html)
        self.assertIn('id="conceptFilter"', html)
        self.assertIn('id="missedFilter"', html)
        self.assertIn('id="noQuestionMatches"', html)
        self.assertEqual([], filter_mixed_quiz_catalog(self._catalog(), search="absent phrase"))
        library_html = dlms.app.test_client().get("/library").get_data(as_text=True)
        self.assertIn('href="/quiz-composer">Mix Questions</a>', library_html)

    def test_empty_and_single_source_selections_do_not_publish(self):
        _quiz_id, question_ids = self._seed(
            "Only Bank",
            "only.html",
            [
                self._question("First only-source question?"),
                self._question("Second only-source question?", number=2),
            ],
        )
        client = dlms.app.test_client()
        for selected, message in (
            ([], "Select at least two questions."),
            (question_ids, "Select questions from at least two source quizzes."),
        ):
            with self.subTest(selected=selected), mock.patch.object(
                dlms, "_publish_quiz"
            ) as publisher:
                response = client.post(
                    "/quiz-composer/create",
                    data={"title": "Invalid Mix", "question_ids": [str(value) for value in selected]},
                    headers=csrf_headers(client),
                )
                self.assertEqual(400, response.status_code)
                self.assertIn(message, response.get_data(as_text=True))
                publisher.assert_not_called()

    def test_creation_publishes_normal_quiz_and_preserves_source_rows(self):
        first_quiz, first_questions = self._seed(
            "Source A",
            "source-a.html",
            [self._question(
                "Source A question?",
                concepts=["Shared Topic"],
                source={"organization": "Neutral Organization", "dataset": "Set A"},
            )],
            folder="Course A",
        )
        second_quiz, second_questions = self._seed(
            "Source B",
            "source-b.html",
            [self._question("Source B matching?", concepts=["Pairing"], matching=True)],
            folder="Course B",
        )
        conn = dlms.get_db()
        before = {
            quiz_id: conn.execute(
                "SELECT question_text FROM questions WHERE quiz_id = ? ORDER BY id", (quiz_id,)
            ).fetchall()
            for quiz_id in (first_quiz, second_quiz)
        }
        conn.close()

        client = dlms.app.test_client()
        response = client.post(
            "/quiz-composer/create",
            data={
                "title": "Focused Mixed Quiz",
                "question_ids": [str(first_questions[0]), str(second_questions[0])],
            },
            headers=csrf_headers(client),
        )

        self.assertEqual(302, response.status_code)
        self.assertTrue(response.location.startswith("/quizzes/mixed_quiz_"))
        conn = dlms.get_db()
        try:
            created = conn.execute(
                "SELECT id, source_file FROM quizzes WHERE title = ?",
                ("Focused Mixed Quiz",),
            ).fetchone()
            self.assertIsNotNone(created)
            self.assertTrue(created["source_file"].startswith("mixed_quiz_"))
            copied = conn.execute(
                "SELECT question_text, question_type, source_organization, source_dataset, media_json "
                "FROM questions WHERE quiz_id = ? ORDER BY question_number",
                (created["id"],),
            ).fetchall()
            self.assertEqual(
                [("Source A question?", "choice"), ("Source B matching?", "matching")],
                [(row["question_text"], row["question_type"]) for row in copied],
            )
            self.assertEqual("Neutral Organization", copied[0]["source_organization"])
            self.assertEqual("Set A", copied[0]["source_dataset"])
            composition_sources = json.loads(copied[0]["media_json"])[
                "composition_sources"
            ]
            self.assertEqual(first_quiz, composition_sources[0]["quiz_id"])
            self.assertEqual("Source A", composition_sources[0]["quiz_title"])
            self.assertEqual("Course A", composition_sources[0]["folder"])
            self.assertEqual(2, conn.execute(
                "SELECT COUNT(*) FROM matching_pairs WHERE question_id = ("
                "SELECT id FROM questions WHERE quiz_id = ? AND question_number = 2)",
                (created["id"],),
            ).fetchone()[0])
            for quiz_id in (first_quiz, second_quiz):
                after = conn.execute(
                    "SELECT question_text FROM questions WHERE quiz_id = ? ORDER BY id", (quiz_id,)
                ).fetchall()
                self.assertEqual(before[quiz_id], after)
        finally:
            conn.close()
        self.assertEqual(3, len(dlms.load_registry()))

    def test_stale_or_generated_question_id_is_rejected_server_side(self):
        _first_quiz, first_questions = self._seed(
            "First", "first-source.html", [self._question("First prompt?")]
        )
        _second_quiz, _second_questions = self._seed(
            "Generated", "mixed_quiz_old.html", [self._question("Generated prompt?")]
        )
        client = dlms.app.test_client()
        with mock.patch.object(dlms, "_publish_quiz") as publisher:
            response = client.post(
                "/quiz-composer/create",
                data={"title": "Tampered", "question_ids": [str(first_questions[0]), "999999", "not-an-id"]},
                headers=csrf_headers(client),
            )
        self.assertEqual(400, response.status_code)
        self.assertIn("no longer available", response.get_data(as_text=True))
        publisher.assert_not_called()


if __name__ == "__main__":
    unittest.main()

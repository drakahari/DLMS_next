"""DLMS-127 cross-quiz concept intelligence regressions."""

import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms
from dlms.services.learning import _concept_performance_trend
from tests.csrf_test_utils import csrf_headers
from tests.current_schema import seed_current_quiz


class CrossQuizConceptIntelligenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dlms-127-")
        self.addCleanup(self.temporary.cleanup)
        self.data_root = Path(self.temporary.name)
        self.app_data_patch = mock.patch.object(
            dlms, "APP_DATA_DIR", str(self.data_root)
        )
        self.db_patch = mock.patch.object(
            dlms, "DB_PATH", str(self.data_root / "results.db")
        )
        self.app_data_patch.start()
        self.db_patch.start()
        self.addCleanup(self.app_data_patch.stop)
        self.addCleanup(self.db_patch.stop)
        self.assertTrue(dlms._initialize_data_root_ownership(str(self.data_root)))
        dlms.ensure_db_initialized()

    @staticmethod
    def _question(text, concepts=None):
        return {
            "number": 1,
            "question": text,
            "choices": [
                {"label": "A", "text": "Expected", "is_correct": True},
                {"label": "B", "text": "Alternative", "is_correct": False},
            ],
            "concepts": concepts or [],
        }

    def _seed_quiz(self, title, source_file, text, concepts=None):
        quiz_id = seed_current_quiz(
            dlms.get_db,
            title,
            source_file,
            [self._question(text, concepts)],
        )
        conn = dlms.get_db()
        try:
            question_id = conn.execute(
                "SELECT id FROM questions WHERE quiz_id = ?", (quiz_id,)
            ).fetchone()[0]
        finally:
            conn.close()
        return quiz_id, question_id

    @staticmethod
    def _record(
        cursor,
        *,
        quiz_id,
        question_id,
        correct,
        attempt_id=None,
        session_id=None,
        event_type="exam_answer",
    ):
        dlms._record_learning_event(
            cursor,
            event_type=event_type,
            quiz_id=quiz_id,
            question_id=question_id,
            attempt_id=attempt_id,
            session_id=session_id,
            mode="Study" if event_type == "study_answer" else "Exam",
            was_correct=correct,
        )

    def test_shared_concept_aggregates_across_quiz_and_study_pack_sources(self):
        quiz_a, question_a = self._seed_quiz(
            "Core Quiz",
            "core-quiz.html",
            "First source question?",
            ["Network Access"],
        )
        quiz_b, question_b = self._seed_quiz(
            "Generated Study Pack Quiz",
            "study-pack-network.html",
            "Second source question?",
            ["network access"],
        )
        self._seed_quiz(
            "Untagged Quiz",
            "untagged.html",
            "Question without concept metadata?",
        )

        conn = dlms.get_db()
        cur = conn.cursor()
        self._record(
            cur,
            quiz_id=quiz_a,
            question_id=question_a,
            correct=False,
            attempt_id="exam-one",
        )
        self._record(
            cur,
            quiz_id=quiz_b,
            question_id=question_b,
            correct=True,
            attempt_id="exam-two",
        )
        self._record(
            cur,
            quiz_id=quiz_a,
            question_id=question_a,
            correct=False,
            session_id="study-one",
            event_type="study_answer",
        )
        self._record(
            cur,
            quiz_id=quiz_a,
            question_id=question_a,
            correct=True,
            session_id="study-one",
            event_type="study_answer",
        )
        conn.commit()
        topics = dlms._learning_intelligence_topics(cur)
        conn.close()

        self.assertEqual(1, len(topics))
        topic = topics[0]
        self.assertEqual("Network Access", topic["name"])
        self.assertEqual(2, topic["question_count"])
        self.assertEqual(2, topic["quiz_count"])
        self.assertEqual(2, topic["answered_question_count"])
        self.assertEqual(3, topic["evidence"])
        self.assertEqual(2, topic["correct"])
        self.assertEqual(1, topic["incorrect"])
        self.assertEqual(66.7, topic["accuracy"])
        self.assertEqual(2, topic["attempt_count"])
        self.assertEqual(1, topic["study_session_count"])
        self.assertEqual(3, topic["practice_run_count"])

    def test_limited_evidence_keeps_trend_and_mastery_conservative(self):
        quiz_id, question_id = self._seed_quiz(
            "Limited Evidence",
            "limited.html",
            "Limited evidence question?",
            ["Limited Evidence"],
        )
        conn = dlms.get_db()
        cur = conn.cursor()
        for index, correct in enumerate((True, False), start=1):
            self._record(
                cur,
                quiz_id=quiz_id,
                question_id=question_id,
                correct=correct,
                attempt_id=f"limited-{index}",
            )
        conn.commit()
        topic = next(
            item
            for item in dlms._learning_intelligence_topics(cur)
            if item["name"] == "Limited Evidence"
        )
        conn.close()

        self.assertEqual("insufficient", topic["status"])
        self.assertEqual("insufficient", topic["trend"])
        self.assertEqual("More data needed", topic["trend_label"])
        self.assertIsNone(topic["trend_delta"])
        self.assertEqual(2, topic["recent_evidence"])
        self.assertEqual(50.0, topic["recent_accuracy"])
        self.assertLessEqual(topic["mastery"], 59.0)

    def test_overall_and_recent_accuracy_use_their_documented_windows(self):
        quiz_id, question_id = self._seed_quiz(
            "Changing Performance",
            "changing-performance.html",
            "Changing performance question?",
            ["Changing Performance"],
        )
        conn = dlms.get_db()
        cur = conn.cursor()
        results = (False, False, False, True, True, True, True, True)
        for index, correct in enumerate(results, start=1):
            self._record(
                cur,
                quiz_id=quiz_id,
                question_id=question_id,
                correct=correct,
                attempt_id=f"changing-{index}",
            )
        conn.commit()
        topic = next(
            item
            for item in dlms._learning_intelligence_topics(cur)
            if item["name"] == "Changing Performance"
        )
        conn.close()

        self.assertEqual(62.5, topic["accuracy"])
        self.assertEqual(5, topic["recent_evidence"])
        self.assertEqual(100.0, topic["recent_accuracy"])
        self.assertEqual("improving", topic["trend"])
        self.assertEqual(75.0, topic["trend_delta"])

    def test_trend_compares_bounded_equal_windows(self):
        cases = (
            ([False, False, False, True, True, True], "improving", 100.0),
            ([True, True, True, False, False, False], "declining", -100.0),
            ([True, False, True, False, True, True], "stable", 0.0),
        )
        for results, expected, delta in cases:
            with self.subTest(expected=expected):
                trend = _concept_performance_trend(
                    [{"was_correct": result} for result in results]
                )
                self.assertEqual(expected, trend["trend"])
                self.assertEqual(delta, trend["trend_delta"])
                self.assertEqual(3, trend["trend_window_size"])

        insufficient = _concept_performance_trend(
            [{"was_correct": True}] * 5
        )
        self.assertEqual("insufficient", insufficient["trend"])
        self.assertIsNone(insufficient["trend_delta"])

    def test_generated_concept_review_does_not_expand_source_coverage(self):
        source_quiz, source_question = self._seed_quiz(
            "Original Quiz",
            "original.html",
            "Original concept question?",
            ["Source Boundary"],
        )
        clone_quiz, clone_question = self._seed_quiz(
            "Concept Review — Source Boundary",
            f"concept_review_{uuid.uuid4()}.html",
            "Original concept question?",
            ["Source Boundary"],
        )
        conn = dlms.get_db()
        cur = conn.cursor()
        self._record(
            cur,
            quiz_id=clone_quiz,
            question_id=clone_question,
            correct=True,
            attempt_id="review-attempt",
        )
        conn.commit()
        topic = next(
            item
            for item in dlms._learning_intelligence_topics(cur)
            if item["name"] == "Source Boundary"
        )
        candidates = dlms._review_candidates_for_topics(cur, [topic])
        conn.close()

        self.assertEqual(1, topic["quiz_count"])
        self.assertEqual(1, topic["question_count"])
        self.assertEqual(1, topic["evidence"])
        self.assertEqual([source_question], [item["question_id"] for item in candidates])
        self.assertEqual(source_quiz, candidates[0]["quiz_id"])

    def test_concept_review_generates_from_all_matching_source_quizzes(self):
        concept = "Shared Navigation"
        self._seed_quiz(
            "Navigation One",
            "navigation-one.html",
            "Navigation question one?",
            [concept],
        )
        self._seed_quiz(
            "Navigation Two",
            "navigation-two.html",
            "Navigation question two?",
            [concept.lower()],
        )
        conn = dlms.get_db()
        concept_id = conn.execute(
            "SELECT id FROM concepts WHERE name = ? COLLATE NOCASE", (concept,)
        ).fetchone()[0]
        conn.close()

        client = dlms.app.test_client()
        headers = csrf_headers(client)
        with mock.patch.object(
            dlms, "_publish_quiz", return_value=(127, "concept-review.html")
        ) as publisher:
            response = client.post(
                "/concept-review/generate",
                data={"concept_id": str(concept_id), "question_count": "20"},
                headers=headers,
            )

        self.assertEqual(302, response.status_code)
        self.assertEqual("/quizzes/concept-review.html", response.location)
        args, kwargs = publisher.call_args
        self.assertEqual("Concept Review — Shared Navigation", args[0])
        self.assertEqual(2, len(args[1]))
        self.assertEqual([1, 2], [item["number"] for item in args[1]])
        self.assertEqual("concept_review", kwargs["filename_prefix"])
        self.assertEqual(90, kwargs["exam_minutes"])
        self.assertTrue(kwargs["snapshot_existing_assets"])

    def test_unknown_concept_cannot_publish_a_review(self):
        client = dlms.app.test_client()
        with mock.patch.object(dlms, "_publish_quiz") as publisher:
            response = client.post(
                "/concept-review/generate",
                data={"concept_id": "999999", "question_count": "20"},
                headers=csrf_headers(client),
            )

        self.assertEqual(302, response.status_code)
        self.assertEqual("/learning-intelligence", response.location)
        publisher.assert_not_called()

    def test_learning_intelligence_page_exposes_cross_quiz_metrics_and_action(self):
        page = (Path(dlms.STATIC_ROOT) / "learning-intelligence.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("DLMS-127 · CROSS-QUIZ CONCEPT INTELLIGENCE", page)
        for field in (
            "question_count",
            "quiz_count",
            "answered_question_count",
            "attempt_count",
            "study_session_count",
            "recent_accuracy",
            "trend_label",
        ):
            with self.subTest(field=field):
                self.assertIn(field, page)
        self.assertIn('action="/concept-review/generate"', page)
        self.assertIn("Study concept", page)
        self.assertIn("window.dlmsProtectForm?.(form)", page)


if __name__ == "__main__":
    unittest.main()

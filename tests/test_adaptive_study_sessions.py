"""DLMS-125 adaptive study session regressions."""

import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms
from tests.csrf_test_utils import csrf_headers
from tests.current_schema import seed_current_quiz


class AdaptiveStudySessionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dlms-125-")
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
        self.now = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)

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

    def _seed(self, title, source_file, text, concepts=None):
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
    def _record_results(cur, quiz_id, question_id, results, occurred_at):
        for index, correct in enumerate(results, start=1):
            dlms._record_learning_event(
                cur,
                event_type="exam_answer",
                quiz_id=quiz_id,
                question_id=question_id,
                attempt_id=f"adaptive-{question_id}-{index}-{uuid.uuid4()}",
                mode="Exam",
                was_correct=correct,
            )
            cur.execute(
                "UPDATE learning_events SET occurred_at = ? WHERE id = ?",
                (occurred_at.isoformat(), cur.lastrowid),
            )

    def _candidates(self):
        conn = dlms.get_db()
        try:
            return dlms._adaptive_study_candidates(conn.cursor(), now=self.now)
        finally:
            conn.close()

    def test_weak_concept_is_prioritized_over_strong_concept(self):
        weak_quiz, weak_question = self._seed(
            "Weak Source", "weak-source.html", "Weak source question?", ["Weak Topic"]
        )
        strong_quiz, strong_question = self._seed(
            "Strong Source",
            "strong-source.html",
            "Strong source question?",
            ["Strong Topic"],
        )
        conn = dlms.get_db()
        cur = conn.cursor()
        occurred_at = self.now - timedelta(days=10)
        self._record_results(
            cur, weak_quiz, weak_question, [False, False, True, False, False], occurred_at
        )
        self._record_results(
            cur, strong_quiz, strong_question, [True, True, True, True, True], occurred_at
        )
        conn.commit()
        conn.close()

        candidates = self._candidates()

        self.assertEqual(weak_question, candidates[0]["question_id"])
        self.assertIn("weak_concept", candidates[0]["score_components"])
        self.assertGreater(
            candidates[0]["priority_score"], candidates[1]["priority_score"]
        )

    def test_recent_miss_prioritizes_question_without_concept_or_confidence_metadata(self):
        missed_quiz, missed_question = self._seed(
            "Missed Source", "missed-source.html", "Recently missed question?"
        )
        correct_quiz, correct_question = self._seed(
            "Correct Source", "correct-source.html", "Recently correct question?"
        )
        conn = dlms.get_db()
        cur = conn.cursor()
        occurred_at = self.now - timedelta(days=1)
        self._record_results(cur, missed_quiz, missed_question, [False], occurred_at)
        self._record_results(cur, correct_quiz, correct_question, [True], occurred_at)
        conn.commit()
        conn.close()

        candidates = self._candidates()

        self.assertEqual(missed_question, candidates[0]["question_id"])
        self.assertEqual(35, candidates[0]["score_components"]["recent_miss"])
        self.assertEqual([], candidates[0]["topic_names"])

    def test_repeated_exposure_reduces_question_priority(self):
        lower_quiz, lower_question = self._seed(
            "Lower Exposure", "lower-exposure.html", "Lower exposure question?"
        )
        repeated_quiz, repeated_question = self._seed(
            "Repeated Exposure",
            "repeated-exposure.html",
            "Repeated exposure question?",
        )
        conn = dlms.get_db()
        cur = conn.cursor()
        occurred_at = self.now - timedelta(days=1)
        self._record_results(
            cur, lower_quiz, lower_question, [True, True], occurred_at
        )
        self._record_results(
            cur, repeated_quiz, repeated_question, [True] * 8, occurred_at
        )
        conn.commit()
        conn.close()

        candidates = self._candidates()

        self.assertEqual(lower_question, candidates[0]["question_id"])
        repeated = next(
            row for row in candidates if row["question_id"] == repeated_question
        )
        self.assertEqual(-15, repeated["score_components"]["repeat_penalty"])

    def test_stale_question_is_prioritized_over_recently_seen_question(self):
        stale_quiz, stale_question = self._seed(
            "Stale Source", "stale-source.html", "Stale question?"
        )
        recent_quiz, recent_question = self._seed(
            "Recent Source", "recent-source.html", "Recent question?"
        )
        conn = dlms.get_db()
        cur = conn.cursor()
        self._record_results(
            cur,
            stale_quiz,
            stale_question,
            [True],
            self.now - timedelta(days=40),
        )
        self._record_results(
            cur,
            recent_quiz,
            recent_question,
            [True],
            self.now - timedelta(days=1),
        )
        conn.commit()
        conn.close()

        candidates = self._candidates()

        self.assertEqual(stale_question, candidates[0]["question_id"])
        self.assertEqual(20, candidates[0]["score_components"]["study_recency"])
        self.assertEqual(40, candidates[0]["days_since_activity"])

    def test_no_history_fallback_is_deterministic_without_metadata(self):
        seeded = [
            self._seed(
                f"Fallback {index}",
                f"fallback-{index}.html",
                f"Fallback question {index}?",
            )[1]
            for index in range(1, 4)
        ]

        first = self._candidates()
        second = self._candidates()

        self.assertEqual(seeded, [row["question_id"] for row in first])
        self.assertEqual(
            [(row["question_id"], row["priority_score"]) for row in first],
            [(row["question_id"], row["priority_score"]) for row in second],
        )
        self.assertTrue(all(row["priority_score"] == 20 for row in first))
        self.assertTrue(
            all(row["selection_reasons"] == ["Not studied yet"] for row in first)
        )

    def test_generated_review_copies_are_evidence_but_never_sources(self):
        source_quiz, source_question = self._seed(
            "Original Source",
            "original-source.html",
            "Shared review question?",
            ["Review Boundary"],
        )
        generated = (
            ("Smart Review — Old", "smart_review_old.html"),
            ("Spaced Review — Old", "spaced_review_old.html"),
            ("Concept Review — Old", "concept_review_old.html"),
            ("Adaptive Study — Old", "adaptive_study_old.html"),
        )
        clone_ids = []
        for title, source_file in generated:
            _quiz_id, question_id = self._seed(
                title,
                source_file,
                "Shared review question?",
                ["Review Boundary"],
            )
            clone_ids.append(question_id)
        self._seed(
            "Adaptive Study — Only Clone",
            "adaptive_study_only.html",
            "Generated-only question?",
            ["Review Boundary"],
        )
        conn = dlms.get_db()
        cur = conn.cursor()
        clone_quiz = cur.execute(
            "SELECT quiz_id FROM questions WHERE id = ?", (clone_ids[-1],)
        ).fetchone()[0]
        self._record_results(
            cur,
            clone_quiz,
            clone_ids[-1],
            [False],
            self.now - timedelta(days=1),
        )
        conn.commit()
        topic = next(
            item
            for item in dlms._learning_intelligence_topics(cur, now=self.now)
            if item["name"] == "Review Boundary"
        )
        review_candidates = dlms._review_candidates_for_topics(cur, [topic])
        conn.close()

        candidates = self._candidates()

        self.assertEqual(1, topic["question_count"])
        self.assertEqual(1, topic["quiz_count"])
        self.assertEqual(
            [source_question],
            [candidate["question_id"] for candidate in review_candidates],
        )
        self.assertEqual([source_question], [row["question_id"] for row in candidates])
        self.assertEqual(source_quiz, candidates[0]["quiz_id"])
        self.assertEqual(1, candidates[0]["evidence"])
        self.assertIn("recent_miss", candidates[0]["score_components"])
        self.assertFalse(set(clone_ids) & set(candidates[0]["source_question_ids"]))

    def test_selection_is_deterministic_and_spreads_concepts(self):
        candidates = [
            {"question_id": 1, "concept_ids": [10], "priority_score": 50},
            {"question_id": 2, "concept_ids": [10], "priority_score": 49},
            {"question_id": 3, "concept_ids": [20], "priority_score": 45},
        ]

        first = dlms._adaptive_study_select_candidates(candidates, 3)
        second = dlms._adaptive_study_select_candidates(candidates, 3)

        self.assertEqual([1, 3, 2], [row["question_id"] for row in first])
        self.assertEqual(first, second)

    def test_low_history_selection_spreads_source_quizzes(self):
        candidates = [
            {
                "question_id": 1,
                "quiz_id": 10,
                "concept_ids": [],
                "priority_score": 20,
            },
            {
                "question_id": 2,
                "quiz_id": 10,
                "concept_ids": [],
                "priority_score": 19,
            },
            {
                "question_id": 3,
                "quiz_id": 20,
                "concept_ids": [],
                "priority_score": 18,
            },
        ]

        selected = dlms._adaptive_study_select_candidates(candidates, 3)

        self.assertEqual([1, 3, 2], [row["question_id"] for row in selected])

    def test_route_creates_normal_adaptive_quiz(self):
        _quiz_id, question_id = self._seed(
            "Session Source", "session-source.html", "Session source question?"
        )
        client = dlms.app.test_client()
        with mock.patch.object(
            dlms,
            "_adaptive_study_candidates",
            return_value=[
                {
                    "question_id": question_id,
                    "concept_ids": [],
                    "priority_score": 20,
                }
            ],
        ), mock.patch.object(
            dlms, "_publish_quiz", return_value=(125, "adaptive-session.html")
        ) as publisher:
            response = client.post(
                "/adaptive-study/generate",
                data={"question_count": "20"},
                headers=csrf_headers(client),
            )

        self.assertEqual(302, response.status_code)
        self.assertEqual("/quizzes/adaptive-session.html", response.location)
        args, kwargs = publisher.call_args
        self.assertEqual("Adaptive Study — What I Need Most", args[0])
        self.assertEqual(1, len(args[1]))
        self.assertEqual(1, args[1][0]["number"])
        self.assertEqual("adaptive_study", kwargs["filename_prefix"])
        self.assertTrue(kwargs["snapshot_existing_assets"])

    def test_no_source_questions_returns_to_intelligence_without_publication(self):
        client = dlms.app.test_client()
        with mock.patch.object(dlms, "_publish_quiz") as publisher:
            response = client.post(
                "/adaptive-study/generate",
                data={"question_count": "20"},
                headers=csrf_headers(client),
            )

        self.assertEqual(302, response.status_code)
        self.assertEqual("/learning-intelligence", response.location)
        publisher.assert_not_called()

    def test_learning_intelligence_explains_adaptive_workflow(self):
        page = (Path(dlms.STATIC_ROOT) / "learning-intelligence.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("DLMS-125 · ADAPTIVE STUDY", page)
        self.assertIn("Study What I Need Most", page)
        self.assertIn('action="/adaptive-study/generate"', page)
        for explanation in (
            "Weak and developing concepts receive priority.",
            "Missed questions and low recent accuracy move up.",
            "Overdue, stale, and unseen material is mixed in.",
            "Repeated exposure lowers priority and concept variety is favored.",
        ):
            with self.subTest(explanation=explanation):
                self.assertIn(explanation, page)

        css = (Path(dlms.STATIC_ROOT) / "style.css").read_text(encoding="utf-8")
        self.assertEqual(
            1,
            css.count(
                ".adaptive-study-signals{display:grid;grid-template-columns:repeat(4"
            ),
        )
        self.assertIn("var(--theme-border-soft", css)
        self.assertIn("var(--theme-muted-text", css)


if __name__ == "__main__":
    unittest.main()

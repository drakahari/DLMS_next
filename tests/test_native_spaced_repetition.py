"""DLMS-129 native spaced-repetition scheduling regressions."""

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


class NativeSpacedRepetitionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dlms-129-")
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
    def _record(cur, quiz_id, question_id, correct, occurred_at, index=1):
        dlms._record_learning_event(
            cur,
            event_type="exam_answer",
            quiz_id=quiz_id,
            question_id=question_id,
            attempt_id=f"native-{question_id}-{index}-{uuid.uuid4()}",
            mode="Exam",
            was_correct=correct,
        )
        cur.execute(
            "UPDATE learning_events SET occurred_at = ? WHERE id = ?",
            (occurred_at.isoformat(), cur.lastrowid),
        )

    def _schedule(self):
        conn = dlms.get_db()
        try:
            return dlms._native_spaced_repetition_schedule(
                conn.cursor(), now=self.now
            )
        finally:
            conn.close()

    def test_unseen_question_is_visible_but_not_yet_scheduled(self):
        _quiz_id, question_id = self._seed(
            "Unseen Source", "unseen-source.html", "Unseen source question?"
        )

        payload = self._schedule()

        self.assertEqual(1, payload["summary"]["eligible_questions"])
        self.assertEqual(1, payload["summary"]["unscheduled"])
        self.assertEqual(question_id, payload["questions"][0]["question_id"])
        self.assertEqual("unscheduled", payload["questions"][0]["schedule_state"])
        self.assertIsNone(payload["questions"][0]["next_review"])

    def test_successful_review_streak_progresses_through_bounded_intervals(self):
        expected = {1: 1, 2: 3, 3: 7, 4: 14, 5: 30, 6: 30}
        for streak, interval in expected.items():
            with self.subTest(streak=streak):
                events = [
                    {"was_correct": 1, "occurred_at": self.now.isoformat()}
                    for _ in range(streak)
                ]
                entry = dlms._learning_service._native_question_schedule_entry(
                    events, now=self.now
                )
                self.assertEqual(interval, entry["review_interval_days"])
                self.assertEqual(streak, entry["correct_streak"])
                self.assertEqual("upcoming", entry["schedule_state"])

    def test_failed_review_resets_schedule_to_one_day(self):
        events = [
            {
                "was_correct": 1,
                "occurred_at": (self.now - timedelta(days=5)).isoformat(),
            },
            {"was_correct": 0, "occurred_at": self.now.isoformat()},
        ]

        entry = dlms._learning_service._native_question_schedule_entry(
            events, now=self.now
        )

        self.assertEqual(1, entry["review_interval_days"])
        self.assertEqual(0, entry["correct_streak"])
        self.assertEqual("incorrect", entry["last_result"])
        self.assertEqual("upcoming", entry["schedule_state"])

    def test_exact_review_time_is_due_now(self):
        entry = dlms._learning_service._native_question_schedule_entry(
            [
                {
                    "was_correct": 1,
                    "occurred_at": (self.now - timedelta(days=1)).isoformat(),
                }
            ],
            now=self.now,
        )

        self.assertEqual("due", entry["schedule_state"])
        self.assertEqual("Due now", entry["schedule_state_label"])
        self.assertTrue(entry["is_due"])
        self.assertEqual(0, entry["days_overdue"])

    def test_overdue_and_upcoming_states_are_derived_from_review_date(self):
        overdue_quiz, overdue_question = self._seed(
            "Overdue Source", "overdue-source.html", "Overdue source question?"
        )
        upcoming_quiz, upcoming_question = self._seed(
            "Upcoming Source", "upcoming-source.html", "Upcoming source question?"
        )
        conn = dlms.get_db()
        cur = conn.cursor()
        self._record(
            cur,
            overdue_quiz,
            overdue_question,
            False,
            self.now - timedelta(days=4),
        )
        self._record(
            cur,
            upcoming_quiz,
            upcoming_question,
            True,
            self.now - timedelta(hours=12),
        )
        conn.commit()
        conn.close()

        payload = self._schedule()
        by_id = {item["question_id"]: item for item in payload["questions"]}

        self.assertEqual("overdue", by_id[overdue_question]["schedule_state"])
        self.assertEqual(3, by_id[overdue_question]["days_overdue"])
        self.assertEqual("upcoming", by_id[upcoming_question]["schedule_state"])
        self.assertEqual(1, by_id[upcoming_question]["days_until_review"])
        self.assertEqual(1, payload["summary"]["due_now"])
        self.assertEqual(1, payload["summary"]["due_next_7_days"])

    def test_generated_copy_contributes_history_without_becoming_a_source(self):
        source_quiz, source_question = self._seed(
            "Canonical Source",
            "canonical-source.html",
            "Shared canonical question?",
            ["Shared Concept"],
        )
        generated_quiz, generated_question = self._seed(
            "Spaced Review — Earlier",
            "spaced_review_native_previous.html",
            "  shared   canonical QUESTION? ",
            ["Generated Metadata"],
        )
        conn = dlms.get_db()
        cur = conn.cursor()
        self._record(
            cur,
            generated_quiz,
            generated_question,
            False,
            self.now - timedelta(days=3),
        )
        conn.commit()
        conn.close()

        payload = self._schedule()

        self.assertEqual(1, len(payload["questions"]))
        item = payload["questions"][0]
        self.assertEqual(source_question, item["question_id"])
        self.assertEqual(source_quiz, item["quiz_id"])
        self.assertEqual([source_question], item["source_question_ids"])
        self.assertEqual(1, item["responses"])
        self.assertEqual(["Shared Concept"], item["concepts"])

    def test_question_without_concepts_or_history_is_handled_deterministically(self):
        self._seed(
            "Plain Source", "plain-source.html", "Question without metadata?"
        )

        first = self._schedule()
        second = self._schedule()

        self.assertEqual(first, second)
        self.assertEqual([], first["questions"][0]["concepts"])
        self.assertIsNone(first["questions"][0]["accuracy"])

    def test_review_schedule_api_preserves_concept_schedule_and_adds_questions(self):
        self._seed("API Source", "api-source.html", "API source question?")
        response = dlms.app.test_client().get("/api/review-schedule")

        self.assertEqual(200, response.status_code)
        payload = response.get_json()
        for key in ("topics", "summary", "model"):
            self.assertIn(key, payload)
        for key in ("questions", "question_summary", "question_model"):
            self.assertIn(key, payload)
        self.assertEqual(1, payload["question_summary"]["unscheduled"])

    def test_due_session_creates_a_normal_quiz_in_schedule_order(self):
        first_quiz, first_question = self._seed(
            "First Due", "first-due.html", "First due question?"
        )
        second_quiz, second_question = self._seed(
            "Second Due", "second-due.html", "Second due question?"
        )
        conn = dlms.get_db()
        cur = conn.cursor()
        self._record(
            cur,
            first_quiz,
            first_question,
            False,
            self.now - timedelta(days=3),
        )
        self._record(
            cur,
            second_quiz,
            second_question,
            False,
            self.now - timedelta(days=5),
        )
        conn.commit()
        conn.close()
        schedule = self._schedule()
        self.assertEqual(
            [second_question, first_question],
            [item["question_id"] for item in schedule["questions"]],
        )

        client = dlms.app.test_client()
        with mock.patch.object(
            dlms, "_review_schedule_payload", return_value=schedule
        ), mock.patch.object(
            dlms, "_publish_quiz", return_value=(129, "native-review.html")
        ) as publisher:
            response = client.post(
                "/native-spaced-review/generate",
                data={"question_count": "20"},
                headers=csrf_headers(client),
            )

        self.assertEqual(302, response.status_code)
        self.assertEqual("/quizzes/native-review.html", response.location)
        args, kwargs = publisher.call_args
        self.assertEqual("Spaced Review — Due Questions", args[0])
        self.assertEqual(
            ["Second due question?", "First due question?"],
            [question["question"] for question in args[1]],
        )
        self.assertEqual([1, 2], [question["number"] for question in args[1]])
        self.assertEqual("spaced_review_native", kwargs["filename_prefix"])
        self.assertEqual(90, kwargs["exam_minutes"])
        self.assertTrue(kwargs["snapshot_existing_assets"])

    def test_no_due_questions_returns_without_publication(self):
        self._seed(
            "Unscheduled Source",
            "unscheduled-source.html",
            "Not due source question?",
        )
        client = dlms.app.test_client()
        with mock.patch.object(dlms, "_publish_quiz") as publisher:
            response = client.post(
                "/native-spaced-review/generate",
                data={"question_count": "20"},
                headers=csrf_headers(client),
            )

        self.assertEqual(302, response.status_code)
        self.assertEqual("/review-schedule", response.location)
        publisher.assert_not_called()

    def test_existing_concept_spaced_review_route_remains_available(self):
        rules = {
            (rule.rule, frozenset(rule.methods - {"HEAD", "OPTIONS"}))
            for rule in dlms.app.url_map.iter_rules()
        }
        self.assertIn(("/spaced-review/generate", frozenset({"POST"})), rules)
        self.assertIn(
            ("/native-spaced-review/generate", frozenset({"POST"})), rules
        )

    def test_review_schedule_page_explains_optional_native_workflow(self):
        page = (Path(dlms.STATIC_ROOT) / "review-schedule.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("DLMS-129 · NATIVE SPACED REPETITION", page)
        self.assertIn('action="/native-spaced-review/generate"', page)
        self.assertIn("Start Due Review", page)
        self.assertIn("does not replace Anki export", page)
        self.assertIn('action="/spaced-review/generate"', page)


if __name__ == "__main__":
    unittest.main()

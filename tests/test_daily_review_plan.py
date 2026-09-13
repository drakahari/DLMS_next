"""DLMS-126 unified daily-review queue regressions."""

import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms
from tests.current_schema import seed_current_quiz


class DailyReviewPlanTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dlms-126-")
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
    def _schedule(questions=None):
        return {
            "questions": questions or [],
            "topics": [],
            "summary": {},
            "question_summary": {},
        }

    @staticmethod
    def _topic(concept_id=1, name="Access Control", status="weak"):
        return {
            "concept_id": concept_id,
            "name": name,
            "status": status,
            "evidence": 5,
            "question_count": 3,
            "accuracy": 40.0,
        }

    @staticmethod
    def _adaptive(question_id=10, evidence=4):
        return [{
            "question_id": question_id,
            "source_question_ids": [question_id],
            "evidence": evidence,
            "priority_score": 40,
            "selection_reasons": ["Missed within the last 14 days"],
        }]

    def _plan(
        self,
        *,
        schedule=None,
        topics=None,
        adaptive=None,
        registry=None,
        packs=None,
        cursor=None,
    ):
        owned_connection = None
        if cursor is None:
            owned_connection = dlms.get_db()
            cursor = owned_connection.cursor()
        try:
            return dlms._learning_service._daily_review_plan(
                cursor,
                registry=registry or [],
                installed_content_packs=packs or [],
                now=self.now,
                review_schedule_payload=lambda _cur, now=None: (
                    schedule or self._schedule()
                ),
                learning_intelligence_payload=lambda _cur, now=None: {
                    "topics": topics or []
                },
                adaptive_study_candidates=lambda _cur, now=None: adaptive or [],
            )
        finally:
            if owned_connection is not None:
                owned_connection.close()

    def test_due_and_overdue_questions_are_the_first_action(self):
        plan = self._plan(schedule=self._schedule([
            {
                "question_id": 1,
                "source_question_ids": [1],
                "schedule_state": "overdue",
                "concepts": ["Routing"],
            },
            {
                "question_id": 2,
                "source_question_ids": [2],
                "schedule_state": "due",
                "concepts": [],
            },
        ]))

        item = plan["items"][0]
        self.assertEqual("native_due", item["kind"])
        self.assertEqual(10, item["priority"])
        self.assertIn("2 source questions", item["reason"])
        self.assertIn("1 is overdue", item["reason"])
        self.assertEqual(
            "/native-spaced-review/generate", item["action"]["url"]
        )
        self.assertEqual("POST", item["action"]["method"])
        self.assertEqual(2, plan["summary"]["due_questions"])

    def test_weak_concept_follows_unrelated_due_material(self):
        plan = self._plan(
            schedule=self._schedule([{
                "question_id": 1,
                "source_question_ids": [1],
                "schedule_state": "due",
                "concepts": ["Routing"],
            }]),
            topics=[self._topic()],
            adaptive=self._adaptive(),
        )

        self.assertEqual(
            ["native_due", "weak_concept"],
            [item["kind"] for item in plan["items"]],
        )
        concept = plan["items"][1]
        self.assertEqual("Review Access Control", concept["title"])
        self.assertEqual("/concept-review/generate", concept["action"]["url"])
        self.assertEqual("1", concept["action"]["fields"]["concept_id"])

    def test_adaptive_recommendation_reuses_existing_ranked_signal(self):
        plan = self._plan(adaptive=self._adaptive())

        self.assertEqual(1, len(plan["items"]))
        item = plan["items"][0]
        self.assertEqual("adaptive", item["kind"])
        self.assertIn("Missed within the last 14 days", item["reason"])
        self.assertEqual("/adaptive-study/generate", item["action"]["url"])

    def test_no_history_uses_adaptive_baseline_without_inventing_scores(self):
        plan = self._plan(adaptive=self._adaptive(evidence=0))

        item = plan["items"][0]
        self.assertEqual("Build your learning baseline", item["title"])
        self.assertIn("little recorded history", item["reason"])

    def test_overlapping_due_concept_and_adaptive_cards_are_suppressed(self):
        plan = self._plan(
            schedule=self._schedule([{
                "question_id": 1,
                "source_question_ids": [1, 99],
                "schedule_state": "overdue",
                "concepts": ["Access Control"],
            }]),
            topics=[self._topic()],
            adaptive=self._adaptive(question_id=99),
        )

        self.assertEqual(["native_due"], [item["kind"] for item in plan["items"]])
        self.assertIn("Specific due or concept actions", plan["model"]["deduplication"])

    def test_developing_concept_is_actionable_when_no_weak_concept_exists(self):
        plan = self._plan(
            topics=[self._topic(status="developing")],
            adaptive=self._adaptive(),
        )

        self.assertEqual("weak_concept", plan["items"][0]["kind"])
        self.assertIn("developing concept", plan["items"][0]["reason"])

    def test_recent_study_pack_activity_uses_installed_pack_and_existing_route(self):
        quiz_id = seed_current_quiz(
            dlms.get_db,
            "Pack Practice",
            "study_questions_pack_one.html",
            [{
                "number": 1,
                "question": "Pack practice question?",
                "choices": [
                    {"label": "A", "text": "Expected", "is_correct": True},
                    {"label": "B", "text": "Alternative", "is_correct": False},
                ],
            }],
        )
        conn = dlms.get_db()
        cur = conn.cursor()
        question_id = cur.execute(
            "SELECT id FROM questions WHERE quiz_id = ?", (quiz_id,)
        ).fetchone()[0]
        dlms._record_learning_event(
            cur,
            event_type="exam_answer",
            quiz_id=quiz_id,
            question_id=question_id,
            attempt_id=f"pack-{uuid.uuid4()}",
            mode="Exam",
            was_correct=True,
        )
        cur.execute(
            "UPDATE learning_events SET occurred_at = ? WHERE id = ?",
            ((self.now - timedelta(days=2)).isoformat(), cur.lastrowid),
        )
        conn.commit()

        plan = self._plan(
            cursor=cur,
            registry=[{
                "id": quiz_id,
                "html": "study_questions_pack_one.html",
                "title": "Pack Practice",
                "source_pack_id": "pack_one",
            }],
            packs=[{"id": "pack_one", "name": "Pack One"}],
        )
        conn.close()

        self.assertEqual(["study_pack"], [item["kind"] for item in plan["items"]])
        item = plan["items"][0]
        self.assertEqual("Continue Pack One", item["title"])
        self.assertIn("2 days ago", item["reason"])
        self.assertEqual("/study-packs?installed=pack_one", item["action"]["url"])

    def test_empty_state_is_useful_when_no_source_has_a_recommendation(self):
        plan = self._plan()

        self.assertEqual([], plan["items"])
        self.assertEqual(
            "Nothing needs immediate attention", plan["empty_state"]["title"]
        )
        self.assertEqual("/library", plan["empty_state"]["action"]["url"])

    def test_api_returns_the_composed_plan_and_closes_connection(self):
        expected = {
            "items": [],
            "summary": {},
            "quiz_index": [],
            "empty_state": {},
            "model": {},
        }
        client = dlms.app.test_client()
        with mock.patch.object(dlms, "_daily_review_plan", return_value=expected):
            response = client.get("/api/daily-review-plan")

        self.assertEqual(200, response.status_code)
        self.assertEqual(expected, response.get_json())
        self.assertEqual("no-store", response.headers.get("Cache-Control"))

    def test_dashboard_loads_queue_recovery_and_direct_action_runtime(self):
        response = dlms.app.test_client().get("/")
        page = response.get_data(as_text=True)
        script = (Path(dlms.STATIC_ROOT) / "daily-review.js").read_text(
            encoding="utf-8"
        )

        self.assertEqual(200, response.status_code)
        self.assertIn("Today’s Review", page)
        self.assertIn('id="dailyReviewList"', page)
        self.assertIn('/static/quiz-recovery.js', page)
        self.assertIn('/static/daily-review.js', page)
        self.assertIn('fetch("/api/daily-review-plan"', script)
        self.assertIn("listStoredRecords", script)
        self.assertIn("replacedKinds", script)
        self.assertIn("window.dlmsProtectForm?.(form)", script)
        for route in (
            "/native-spaced-review/generate",
            "/concept-review/generate",
            "/adaptive-study/generate",
        ):
            self.assertIn(route, {
                rule.rule for rule in dlms.app.url_map.iter_rules()
            })


if __name__ == "__main__":
    unittest.main()

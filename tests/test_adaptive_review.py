import os, tempfile, unittest, uuid
from datetime import datetime, timezone, timedelta

_TEMP = tempfile.TemporaryDirectory(prefix="dlms-adaptive-review-tests-")
os.environ["QUIZAPP_DATA_DIR"] = _TEMP.name
import app as dlms


class AdaptiveReviewTests(unittest.TestCase):
    def setUp(self):
        # Keep each adaptive-review test independent. The module uses one
        # temporary DLMS database, so learning data created by an earlier test
        # must not influence recommendation logic in a later test.
        #
        # Clear only tables that actually exist in the current DLMS schema and
        # always close/rollback the connection if cleanup ever fails so one
        # test cannot leave the SQLite database locked for the next test.
        conn = dlms.get_db()
        try:
            cur = conn.cursor()
            existing = {
                row[0]
                for row in cur.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            cleanup_order = [
                "learning_events",
                "question_concepts",
                "attempt_answers",
                "missed_questions",
                "matching_pairs",
                "choices",
                "attempts",
                "questions",
                "quizzes",
                "concepts",
            ]
            for table in cleanup_order:
                if table in existing:
                    cur.execute(f'DELETE FROM "{table}"')
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _tagged_quiz(self, concept, results=None):
        quiz_id = dlms.save_quiz_to_db(f"Adaptive {uuid.uuid4()}", f"adaptive-{uuid.uuid4()}.html", [{
            "number": 1,
            "question": f"Adaptive question {uuid.uuid4()}?",
            "choices": [
                {"label": "A", "text": "Correct", "is_correct": True},
                {"label": "B", "text": "Wrong", "is_correct": False},
            ],
            "concepts": [concept],
        }])
        conn = dlms.get_db(); cur = conn.cursor()
        qid = cur.execute("SELECT id FROM questions WHERE quiz_id=?", (quiz_id,)).fetchone()[0]
        for i, result in enumerate(results or [True, True, True, True, True]):
            dlms._record_learning_event(
                cur, event_type="exam_answer", quiz_id=quiz_id, question_id=qid,
                attempt_id=f"adaptive-{i}-{uuid.uuid4()}", mode="Exam", was_correct=result,
            )
        conn.commit(); conn.close()
        return quiz_id, qid

    def test_retention_interval_expands_with_mastery(self):
        now = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
        base = {"evidence": 8, "last_activity": (now - timedelta(days=1)).isoformat()}
        weak = dlms._retention_schedule_for_topic({**base, "mastery": 55}, now=now)
        developing = dlms._retention_schedule_for_topic({**base, "mastery": 70}, now=now)
        proficient = dlms._retention_schedule_for_topic({**base, "mastery": 82}, now=now)
        strong = dlms._retention_schedule_for_topic({**base, "mastery": 94}, now=now)
        self.assertEqual([weak["review_interval_days"], developing["review_interval_days"], proficient["review_interval_days"], strong["review_interval_days"]], [1, 3, 7, 14])

    def test_retention_decay_starts_only_after_due_date(self):
        now = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
        fresh = dlms._retention_schedule_for_topic({"evidence": 8, "mastery": 82, "last_activity": (now - timedelta(days=6)).isoformat()}, now=now)
        overdue = dlms._retention_schedule_for_topic({"evidence": 8, "mastery": 82, "last_activity": (now - timedelta(days=10)).isoformat()}, now=now)
        self.assertEqual(fresh["decay_points"], 0.0)
        self.assertEqual(fresh["retained_mastery"], 82.0)
        self.assertEqual(overdue["review_state"], "overdue")
        self.assertGreater(overdue["decay_points"], 0.0)
        self.assertLess(overdue["retained_mastery"], 82.0)

    def test_review_schedule_api_shape(self):
        client = dlms.app.test_client()
        response = client.get("/api/review-schedule")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn("topics", payload)
        self.assertIn("summary", payload)
        self.assertIn("model", payload)
        self.assertIn("due_now", payload["summary"])

    def test_learning_profile_recommends_due_review_without_weak_area(self):
        concept = f"Due-{uuid.uuid4()}"
        _, qid = self._tagged_quiz(concept, [True, True, True, True, True])
        old = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
        conn = dlms.get_db(); cur = conn.cursor()
        cur.execute("UPDATE learning_events SET occurred_at=? WHERE question_id=?", (old, qid))
        conn.commit()
        profile = dlms._learning_profile_payload(cur)
        conn.close()
        self.assertEqual(profile["recommendation"]["kind"], "review_due")
        self.assertGreaterEqual(profile["retention"]["due_now"], 1)

    def test_spaced_review_candidates_exclude_review_clones(self):
        concept = f"Clone-{uuid.uuid4()}"
        source_quiz, _ = self._tagged_quiz(concept, [True, True, True, True, True])
        dlms.save_quiz_to_db("Spaced Review — Old", f"spaced_review_{uuid.uuid4()}.html", [{
            "number": 1,
            "question": "Clone-only review question?",
            "choices": [{"label":"A","text":"Correct","is_correct":True},{"label":"B","text":"Wrong","is_correct":False}],
            "concepts": [concept],
        }])
        conn = dlms.get_db(); cur = conn.cursor()
        topics = [t for t in dlms._learning_topics_with_retention(cur) if t["name"] == concept]
        candidates = dlms._review_candidates_for_topics(cur, topics)
        conn.close()
        self.assertTrue(candidates)
        self.assertFalse(any(c["question_text"] == "Clone-only review question?" for c in candidates))
        self.assertTrue(any(c["quiz_id"] == source_quiz for c in candidates))


if __name__ == "__main__":
    unittest.main()

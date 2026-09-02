import os, tempfile, unittest, uuid
from datetime import datetime, timezone

_TEMP = tempfile.TemporaryDirectory(prefix="dlms-learning-intelligence-tests-")
os.environ["QUIZAPP_DATA_DIR"] = _TEMP.name
from tests._isolation import ensure_test_data_isolation
ensure_test_data_isolation()
import app as dlms


class LearningIntelligenceTests(unittest.TestCase):
    def _make_tagged_quiz(self, concept):
        quiz_id = dlms.save_quiz_to_db(f"LI {uuid.uuid4()}", f"li-{uuid.uuid4()}.txt", [{
            "number": 1,
            "question": "Test question",
            "choices": [
                {"label": "A", "text": "Correct", "is_correct": True},
                {"label": "B", "text": "Wrong", "is_correct": False},
            ],
            "concepts": [concept],
        }])
        conn = dlms.get_db()
        qid = conn.execute("SELECT id FROM questions WHERE quiz_id=? AND question_number=1", (quiz_id,)).fetchone()[0]
        conn.close()
        return quiz_id, qid

    def test_study_events_are_deduplicated_per_session_question(self):
        concept = f"Dedup-{uuid.uuid4()}"
        quiz_id, qid = self._make_tagged_quiz(concept)
        conn = dlms.get_db(); cur = conn.cursor()
        dlms._record_learning_event(cur, event_type="study_answer", quiz_id=quiz_id, question_id=qid, session_id="session-a", mode="Study", was_correct=False)
        dlms._record_learning_event(cur, event_type="study_answer", quiz_id=quiz_id, question_id=qid, session_id="session-a", mode="Study", was_correct=True)
        conn.commit()
        topic = next(t for t in dlms._learning_intelligence_topics(cur, now=datetime.now(timezone.utc)) if t["name"] == concept)
        conn.close()
        self.assertEqual(topic["evidence"], 1)
        self.assertEqual(topic["correct"], 1)
        self.assertEqual(topic["accuracy"], 100.0)

    def test_minimum_evidence_prevents_false_high_mastery(self):
        concept = f"Minimum-{uuid.uuid4()}"
        quiz_id, qid = self._make_tagged_quiz(concept)
        conn = dlms.get_db(); cur = conn.cursor()
        for i in range(2):
            dlms._record_learning_event(cur, event_type="exam_answer", quiz_id=quiz_id, question_id=qid, attempt_id=f"attempt-{i}", mode="Exam", was_correct=True)
        conn.commit()
        topic = next(t for t in dlms._learning_intelligence_topics(cur, now=datetime.now(timezone.utc)) if t["name"] == concept)
        conn.close()
        self.assertEqual(topic["status"], "insufficient")
        self.assertLessEqual(topic["mastery"], 59.0)

    def test_weak_area_requires_evidence_and_low_performance(self):
        concept = f"Weak-{uuid.uuid4()}"
        quiz_id, qid = self._make_tagged_quiz(concept)
        conn = dlms.get_db(); cur = conn.cursor()
        results = [False, False, True, False, False]
        for i, result in enumerate(results):
            dlms._record_learning_event(cur, event_type="exam_answer", quiz_id=quiz_id, question_id=qid, attempt_id=f"weak-attempt-{i}", mode="Exam", was_correct=result)
        conn.commit()
        topic = next(t for t in dlms._learning_intelligence_topics(cur, now=datetime.now(timezone.utc)) if t["name"] == concept)
        conn.close()
        self.assertEqual(topic["status"], "weak")
        self.assertTrue(topic["is_weak"])
        self.assertEqual(topic["accuracy"], 20.0)

    def test_learning_intelligence_api_shape(self):
        client = dlms.app.test_client()
        response = client.get("/api/learning-intelligence/topics")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn("topics", payload)
        self.assertIn("summary", payload)
        self.assertIn("model", payload)
        self.assertIn("weak_areas", payload["summary"])


if __name__ == "__main__":
    unittest.main()

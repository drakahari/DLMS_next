import os, tempfile, unittest, uuid

_TEMP = tempfile.TemporaryDirectory(prefix="dlms-learning-tests-")
os.environ["QUIZAPP_DATA_DIR"] = _TEMP.name
import app as dlms


class LearningFoundationTests(unittest.TestCase):
    def test_learning_tables_exist(self):
        conn = dlms.get_db()
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        conn.close()
        self.assertTrue({"concepts", "question_concepts", "learning_events"}.issubset(tables))

    def test_concept_normalization_and_assignment(self):
        conn = dlms.get_db()
        cur = conn.cursor()
        source = f"learning-{uuid.uuid4()}.txt"
        quiz_id = dlms.save_quiz_to_db("Learning Test", source, [{
            "number": 1,
            "question": "Which control limits access?",
            "choices": [
                {"label": "A", "text": "IAM", "is_correct": True},
                {"label": "B", "text": "DNS", "is_correct": False},
            ],
            "concepts": ["IAM", "Authentication", "iam"],
        }])
        conn.close()
        conn = dlms.get_db()
        cur = conn.cursor()
        qid = cur.execute("SELECT id FROM questions WHERE quiz_id=?", (quiz_id,)).fetchone()[0]
        self.assertEqual(dlms._question_concepts(cur, qid), ["Authentication", "IAM"])
        dlms._set_question_concepts(cur, qid, "Least Privilege, IAM, least privilege")
        conn.commit()
        self.assertEqual(dlms._question_concepts(cur, qid), ["IAM", "Least Privilege"])
        conn.close()

    def test_learning_event_insert(self):
        conn = dlms.get_db()
        cur = conn.cursor()
        dlms._record_learning_event(cur, event_type="study_answer", session_id="session-1", mode="Study", was_correct=True, response={"selected": ["A"]})
        conn.commit()
        row = cur.execute("SELECT event_type, session_id, mode, was_correct FROM learning_events ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()
        self.assertEqual(tuple(row), ("study_answer", "session-1", "Study", 1))

    def test_learning_summary_endpoint(self):
        client = dlms.app.test_client()
        response = client.get("/api/learning-foundation/summary")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn("concepts", payload)
        self.assertIn("event_counts", payload)
        self.assertIn("totals", payload)


if __name__ == "__main__":
    unittest.main()

"""DLMS-082 server-side quiz attempt and learning-event validation."""
import tempfile
import unittest
from pathlib import Path

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms
from tests.csrf_test_utils import csrf_headers


class AttemptValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._data = tempfile.TemporaryDirectory(prefix="dlms-attempt-validation-")
        cls._previous_app_data_dir = dlms.APP_DATA_DIR
        cls._previous_db_path = dlms.DB_PATH
        root = Path(cls._data.name)
        dlms._initialize_data_root_ownership(str(root))
        dlms.APP_DATA_DIR = str(root)
        dlms.DB_PATH = str(root / "results.db")
        dlms.ensure_db_initialized()

    @classmethod
    def tearDownClass(cls):
        dlms.APP_DATA_DIR = cls._previous_app_data_dir
        dlms.DB_PATH = cls._previous_db_path
        cls._data.cleanup()

    def setUp(self):
        conn = dlms.get_db()
        for table in (
            "missed_questions", "attempt_answers", "learning_events", "attempts",
            "matching_pairs", "choices", "question_concepts", "questions", "quizzes",
        ):
            conn.execute(f"DELETE FROM {table}")
        conn.execute(
            "INSERT INTO quizzes(title, source_file, registry_id) VALUES (?, ?, ?)",
            ("Validation Quiz", "dlms082-validation.html", 82082),
        )
        self.quiz_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        conn.execute(
            """
            INSERT INTO questions(quiz_id, question_number, question_text, question_type)
            VALUES (?, 1, 'Choice question', 'choice')
            """,
            (self.quiz_id,),
        )
        self.choice_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.executemany(
            "INSERT INTO choices(question_id, label, text, is_correct) VALUES (?, ?, ?, ?)",
            [
                (self.choice_id, "A", "Correct", 1),
                (self.choice_id, "B", "Incorrect", 0),
            ],
        )

        conn.execute(
            """
            INSERT INTO questions(quiz_id, question_number, question_text, question_type)
            VALUES (?, 2, 'Matching question', 'matching')
            """,
            (self.quiz_id,),
        )
        self.matching_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.executemany(
            """
            INSERT INTO matching_pairs(question_id, pair_order, left_text, right_text)
            VALUES (?, ?, ?, ?)
            """,
            [
                (self.matching_id, 1, "Left 1", "Right 1"),
                (self.matching_id, 2, "Left 2", "Right 2"),
            ],
        )

        conn.execute(
            """
            INSERT INTO questions(quiz_id, question_number, question_text, question_type)
            VALUES (?, 3, 'Hotspot question [Image hotspot]', 'choice')
            """,
            (self.quiz_id,),
        )
        self.hotspot_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO choices(question_id, label, text, is_correct) VALUES (?, 'A', 'Target', 1)",
            (self.hotspot_id,),
        )
        conn.commit()
        conn.close()
        self.client = dlms.app.test_client()
        self.headers = csrf_headers(self.client)

    def _payload(self, attempt_id="attempt-1"):
        return {
            "quizId": self.quiz_id,
            "attemptId": attempt_id,
            "score": 1,
            "total": 3,
            "percent": 33,
            "mode": "Exam",
            "startedAt": "2026-09-02T10:00:00+00:00",
            "completedAt": "2026-09-02T10:05:00+00:00",
            "timeRemaining": 300,
            "sessionId": "session-1",
            "responseDetails": [
                {
                    "attemptQuestionNumber": 1,
                    "questionType": "choice",
                    "wasCorrect": True,
                    "selected": ["A"],
                },
                {
                    "attemptQuestionNumber": 2,
                    "questionType": "matching",
                    "wasCorrect": False,
                    "selected": {"0": 1, "1": 0},
                },
                {
                    "attemptQuestionNumber": 3,
                    "questionType": "hotspot",
                    "wasCorrect": False,
                    "selected": {"x": 0.1, "y": 0.2},
                },
            ],
            "missedDetails": [],
        }

    def _post_attempt(self, payload):
        return self.client.post("/record_attempt", json=payload, headers=self.headers)

    def _attempt_write_counts(self, attempt_id):
        conn = dlms.get_db()
        try:
            return {
                "attempts": conn.execute(
                    "SELECT COUNT(*) FROM attempts WHERE id = ?",
                    (attempt_id,),
                ).fetchone()[0],
                "learning_events": conn.execute(
                    "SELECT COUNT(*) FROM learning_events WHERE attempt_id = ?", (attempt_id,)
                ).fetchone()[0],
                "missed_questions": conn.execute(
                    """
                    SELECT COUNT(*) FROM missed_questions
                    WHERE CAST(attempt_id AS TEXT) IN (
                        SELECT CAST(id AS TEXT) FROM attempts WHERE id = ?
                    )
                    """,
                    (attempt_id,),
                ).fetchone()[0],
            }
        finally:
            conn.close()

    def _assert_rejected_without_writes(self, payload):
        response = self._post_attempt(payload)
        self.assertEqual(400, response.status_code, response.get_data(as_text=True))
        self.assertEqual(
            {"attempts": 0, "learning_events": 0, "missed_questions": 0},
            self._attempt_write_counts(payload.get("attemptId")),
        )

    def test_reproduced_malformed_audit_payload_is_rejected_atomically(self):
        payload = self._payload("audit-malformed")
        payload.update({"score": 99, "total": -3, "percent": 987, "mode": "attacker-mode"})
        payload["responseDetails"][0].update({
            "wasCorrect": {"truthy": "not-a-boolean"},
            "selected": {"bad": "shape"},
        })
        self._assert_rejected_without_writes(payload)

    def test_attempt_scalar_types_ranges_and_cross_field_values_are_rejected(self):
        mutations = {
            "negative score": lambda p: p.update(score=-1),
            "boolean score": lambda p: p.update(score=True),
            "score above total": lambda p: p.update(score=4),
            "negative total": lambda p: p.update(total=-1),
            "wrong total": lambda p: p.update(total=2),
            "boolean total": lambda p: p.update(total=True),
            "negative percent": lambda p: p.update(percent=-1),
            "percent above 100": lambda p: p.update(percent=101),
            "string percent": lambda p: p.update(percent="33"),
            "inconsistent percent": lambda p: p.update(percent=34),
            "unknown mode": lambda p: p.update(mode="Practice"),
            "empty mode": lambda p: p.update(mode=""),
            "negative time remaining": lambda p: p.update(timeRemaining=-1),
            "excessive time remaining": lambda p: p.update(timeRemaining=86401),
            "malformed timestamp": lambda p: p.update(startedAt="yesterday"),
            "reversed timestamps": lambda p: p.update(
                startedAt="2026-09-02T11:00:00+00:00",
                completedAt="2026-09-02T10:00:00+00:00",
            ),
        }
        for index, (name, mutate) in enumerate(mutations.items()):
            with self.subTest(name=name):
                payload = self._payload(f"invalid-scalar-{index}")
                mutate(payload)
                self._assert_rejected_without_writes(payload)

    def test_malformed_or_inconsistent_response_details_are_rejected(self):
        def mutate_response(index, **changes):
            return lambda payload: payload["responseDetails"][index].update(changes)

        mutations = {
            "not an array": lambda p: p.update(responseDetails={}),
            "missing response": lambda p: p["responseDetails"].pop(),
            "non-object response": lambda p: p["responseDetails"].__setitem__(0, "bad"),
            "duplicate question": mutate_response(1, attemptQuestionNumber=1),
            "unknown question": mutate_response(1, attemptQuestionNumber=99),
            "unknown type": mutate_response(0, questionType="essay"),
            "mismatched type": mutate_response(0, questionType="matching"),
            "non-boolean correctness": mutate_response(0, wasCorrect="true"),
            "object correctness": mutate_response(0, wasCorrect={"truthy": True}),
            "choice object selection": mutate_response(0, selected={"A": True}),
            "unknown choice": mutate_response(0, selected=["Z"], wasCorrect=False),
            "duplicate choice": mutate_response(0, selected=["A", "A"]),
            "incorrect claimed correct": mutate_response(0, selected=["B"], wasCorrect=True),
            "matching out of range": mutate_response(1, selected={"0": 2}),
            "matching answer reuse": mutate_response(1, selected={"0": 1, "1": 1}),
            "incorrect matching claim": mutate_response(
                1, selected={"0": 0, "1": 1}, wasCorrect=False
            ),
            "hotspot extra field": mutate_response(
                2, selected={"x": 0.1, "y": 0.2, "z": 0.3}
            ),
            "hotspot coordinate out of range": mutate_response(
                2, selected={"x": -0.1, "y": 0.2}
            ),
            "missed details not array": lambda p: p.update(missedDetails={}),
            "correct response listed as missed": lambda p: p.update(missedDetails=[{
                "attemptQuestionNumber": 1, "questionType": "choice",
            }]),
        }
        for index, (name, mutate) in enumerate(mutations.items()):
            with self.subTest(name=name):
                payload = self._payload(f"invalid-response-{index}")
                mutate(payload)
                self._assert_rejected_without_writes(payload)

    def test_valid_exam_attempt_persists_recomputed_summary_and_events(self):
        response = self._post_attempt(self._payload("valid-exam"))
        self.assertEqual(200, response.status_code, response.get_data(as_text=True))
        conn = dlms.get_db()
        try:
            attempt = conn.execute(
                "SELECT score, total, percent, mode FROM attempts WHERE id = ?",
                ("valid-exam",),
            ).fetchone()
            events = conn.execute(
                """
                SELECT event_type, was_correct FROM learning_events
                WHERE attempt_id = ? ORDER BY id
                """,
                ("valid-exam",),
            ).fetchall()
        finally:
            conn.close()
        self.assertEqual((1, 3, 33, "Exam"), tuple(attempt))
        self.assertEqual(
            [("attempt_completed", None), ("exam_answer", 1), ("exam_answer", 0), ("exam_answer", 0)],
            [(row["event_type"], row["was_correct"]) for row in events],
        )

    def test_valid_missed_snapshot_uses_canonical_matching_answers(self):
        payload = self._payload("valid-missed")
        payload["missedDetails"] = [{
            "attemptQuestionNumber": 2,
            "questionType": "matching",
            "correctText": ["attacker supplied"],
            "selectedText": ["attacker supplied"],
        }]
        response = self._post_attempt(payload)
        self.assertEqual(200, response.status_code, response.get_data(as_text=True))

        conn = dlms.get_db()
        try:
            missed = conn.execute(
                """
                SELECT question_type, correct_text, selected_text
                FROM missed_questions WHERE attempt_id = ?
                """,
                ("valid-missed",),
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual("matching", missed["question_type"])
        self.assertEqual("Left 1 ↔ Right 1\nLeft 2 ↔ Right 2", missed["correct_text"])
        self.assertEqual("Left 1 ↔ Right 2\nLeft 2 ↔ Right 1", missed["selected_text"])
        self.assertNotIn("attacker supplied", missed["correct_text"] + missed["selected_text"])

    def test_zero_full_and_study_mode_attempt_boundaries_remain_valid(self):
        zero = self._payload("valid-zero")
        zero.update(score=0, percent=0)
        zero["responseDetails"][0].update(selected=["B"], wasCorrect=False)
        self.assertEqual(200, self._post_attempt(zero).status_code)

        full = self._payload("valid-full")
        full.update(score=3, percent=100)
        full["responseDetails"][1].update(selected={"0": 0, "1": 1}, wasCorrect=True)
        full["responseDetails"][2]["wasCorrect"] = True
        self.assertEqual(200, self._post_attempt(full).status_code)

        study = self._payload("valid-study")
        study["mode"] = "study"
        self.assertEqual(200, self._post_attempt(study).status_code)
        conn = dlms.get_db()
        try:
            modes = [
                row[0] for row in conn.execute(
                    "SELECT mode FROM attempts WHERE id IN (?, ?, ?)",
                    ("valid-zero", "valid-full", "valid-study"),
                ).fetchall()
            ]
        finally:
            conn.close()
        self.assertCountEqual(["Exam", "Exam", "Study"], modes)

    def test_valid_study_response_is_recomputed_and_invalid_followup_does_not_write(self):
        valid = {
            "quizId": self.quiz_id,
            "questionNumber": 1,
            "questionType": "choice",
            "sessionId": "study-session",
            "wasCorrect": False,
            "selected": ["B"],
        }
        response = self.client.post(
            "/api/learning-events/study-response", json=valid, headers=self.headers
        )
        self.assertEqual(200, response.status_code, response.get_data(as_text=True))

        invalid = dict(valid, wasCorrect=True)
        response = self.client.post(
            "/api/learning-events/study-response", json=invalid, headers=self.headers
        )
        self.assertEqual(400, response.status_code, response.get_data(as_text=True))

        conn = dlms.get_db()
        try:
            rows = conn.execute(
                """
                SELECT mode, was_correct, response_json FROM learning_events
                WHERE event_type = 'study_answer' AND session_id = ?
                """,
                ("study-session",),
            ).fetchall()
        finally:
            conn.close()
        self.assertEqual(1, len(rows))
        self.assertEqual(("Study", 0), (rows[0]["mode"], rows[0]["was_correct"]))
        self.assertIn('"selected": ["B"]', rows[0]["response_json"])

    def test_incomplete_matching_study_response_preserves_unknown_correctness(self):
        response = self.client.post(
            "/api/learning-events/study-response",
            json={
                "quizId": self.quiz_id,
                "questionNumber": 2,
                "questionType": "matching",
                "sessionId": "matching-study",
                "wasCorrect": None,
                "selected": {"0": 0},
            },
            headers=self.headers,
        )
        self.assertEqual(200, response.status_code, response.get_data(as_text=True))
        conn = dlms.get_db()
        try:
            correctness = conn.execute(
                "SELECT was_correct FROM learning_events WHERE session_id = 'matching-study'"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertIsNone(correctness)


if __name__ == "__main__":
    unittest.main()

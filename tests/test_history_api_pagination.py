import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock


_TEMP = tempfile.TemporaryDirectory(prefix="dlms-history-api-tests-")
os.environ["QUIZAPP_DATA_DIR"] = _TEMP.name
from tests._isolation import ensure_test_data_isolation
ensure_test_data_isolation()
import app as dlms


class HistoryApiPaginationTests(unittest.TestCase):
    def setUp(self):
        conn = dlms.get_db()
        try:
            cur = conn.cursor()
            for table in ("missed_questions", "attempt_answers", "learning_events", "attempts",
                          "question_concepts", "choices", "matching_pairs", "questions", "quizzes", "concepts"):
                cur.execute(f'DELETE FROM "{table}"')
            columns = {row[1] for row in cur.execute("PRAGMA table_info(attempts)").fetchall()}
            if "attempt_id" not in columns:
                cur.execute("ALTER TABLE attempts ADD COLUMN attempt_id TEXT")
            conn.commit()
        finally:
            conn.close()
        dlms.save_registry([])
        self.client = dlms.app.test_client()

    def _quiz(self, title, source_type=None):
        quiz_id = dlms.save_quiz_to_db(title, f"{title}.txt", [{
            "number": 1,
            "question": "Question?",
            "choices": [
                {"label": "A", "text": "Correct", "is_correct": True},
                {"label": "B", "text": "Wrong", "is_correct": False},
            ],
        }])
        if source_type:
            dlms.save_registry([{"id": quiz_id, "title": title, "source_type": source_type}])
        return quiz_id

    def _attempts(self, quiz_id, count, prefix="attempt", start=None):
        start = start or datetime(2026, 1, 1, 12, 0, 0)
        conn = dlms.get_db()
        try:
            for number in range(count):
                completed = (start + timedelta(minutes=number)).isoformat()
                conn.execute("""
                    INSERT INTO attempts (id, attempt_id, quiz_id, score, total, percent,
                                          started_at, completed_at, time_remaining, mode)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    f"pk-{prefix}-{number}", f"public-{prefix}-{number}", quiz_id,
                    number % 6, 6, (number % 6) * 100 // 6, completed, completed,
                    0, "Study",
                ))
            conn.commit()
        finally:
            conn.close()

    def test_pagination_stable_order_bounds_and_summary_payload(self):
        quiz_id = self._quiz("Paged Quiz")
        self._attempts(quiz_id, 120)

        first = self.client.get("/api/attempts").get_json()
        self.assertEqual((first["page"], first["page_size"], first["total"], first["total_pages"]), (1, 50, 120, 3))
        self.assertTrue(first["has_next"])
        self.assertFalse(first["has_previous"])
        self.assertEqual(len(first["attempts"]), 50)
        self.assertNotIn("missedQuestions", first["attempts"][0])
        self.assertTrue({"id", "attempt_pk", "attempt_id", "quiz_id", "quiz_title", "origin_key", "score", "percent", "completed_at", "mode"}.issubset(first["attempts"][0]))

        middle = self.client.get("/api/attempts?page=2&page_size=50").get_json()
        last = self.client.get("/api/attempts?page=3&page_size=50").get_json()
        self.assertEqual(len(last["attempts"]), 20)
        ids = [row["id"] for row in first["attempts"] + middle["attempts"] + last["attempts"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), {f"public-attempt-{n}" for n in range(120)})
        self.assertEqual(first["attempts"][0]["id"], "public-attempt-119")
        self.assertEqual(first["summary"]["total_attempts"], 120)

        self.assertEqual(self.client.get("/api/attempts?page=0").status_code, 400)
        self.assertEqual(self.client.get("/api/attempts?page=bad").status_code, 400)
        self.assertEqual(self.client.get("/api/attempts?page_size=-2").status_code, 400)
        capped = self.client.get("/api/attempts?page_size=999").get_json()
        self.assertEqual(capped["page_size"], 100)
        beyond = self.client.get("/api/attempts?page=99").get_json()
        self.assertEqual(beyond["attempts"], [])
        self.assertFalse(beyond["has_next"])

    def test_origin_filter_and_tied_ordering(self):
        quiz_id = self._quiz("IT Quiz", "it")
        other_quiz_id = dlms.save_quiz_to_db("Manual Quiz", "manual.txt", [{
            "number": 1, "question": "Question?",
            "choices": [{"label": "A", "text": "Yes", "is_correct": True}, {"label": "B", "text": "No", "is_correct": False}],
        }])
        registry = dlms.load_registry()
        registry.append({"id": other_quiz_id, "title": "Manual Quiz"})
        dlms.save_registry(registry)
        self._attempts(quiz_id, 2, "it")
        self._attempts(other_quiz_id, 2, "manual")

        it_page = self.client.get("/api/attempts?origin=it").get_json()
        quiz_page = self.client.get("/api/attempts?origin=quiz").get_json()
        self.assertEqual((it_page["total"], quiz_page["total"]), (2, 2))
        self.assertTrue(all(row["origin_key"] == "it" for row in it_page["attempts"]))
        self.assertTrue(all(row["origin_key"] == "quiz" for row in quiz_page["attempts"]))
        self.assertEqual(self.client.get("/api/attempts?origin=unknown").status_code, 400)

        conn = dlms.get_db()
        try:
            timestamp = "2026-02-01T00:00:00"
            conn.execute("UPDATE attempts SET completed_at=?", (timestamp,))
            conn.commit()
        finally:
            conn.close()
        tied = self.client.get("/api/attempts?page_size=100").get_json()["attempts"]
        pks = [row["attempt_pk"] for row in tied]
        self.assertEqual(pks, sorted(pks, reverse=True))

    def test_list_uses_no_missed_question_queries_and_indexes_are_used(self):
        quiz_id = self._quiz("Fixed Query Quiz")
        self._attempts(quiz_id, 75)
        conn = dlms.get_db()
        statements = []
        conn.set_trace_callback(statements.append)
        try:
            with mock.patch.object(dlms, "get_db", return_value=conn):
                response = self.client.get("/api/attempts?page=1&page_size=50")
            self.assertEqual(response.status_code, 200)
        finally:
            # The route owns and closes the patched connection.
            pass
        self.assertFalse(any("missed_questions" in statement.lower() for statement in statements))
        self.assertEqual(sum("SELECT" in statement.upper() for statement in statements), 3)

        conn = dlms.get_db()
        try:
            history_plan = " ".join(str(row[3]) for row in conn.execute(
                "EXPLAIN QUERY PLAN SELECT id FROM attempts ORDER BY completed_at DESC, id DESC LIMIT 5"
            ).fetchall())
            missed_plan = " ".join(str(row[3]) for row in conn.execute(
                "EXPLAIN QUERY PLAN SELECT * FROM missed_questions WHERE attempt_id=? ORDER BY attempt_question_number, id", ("x",)
            ).fetchall())
        finally:
            conn.close()
        self.assertIn("idx_attempts_completed_id", history_plan)
        self.assertIn("idx_missed_questions_attempt_number", missed_plan)

    def test_selected_summary_missed_detail_overview_analytics_and_legacy_retirement(self):
        quiz_id = self._quiz("Review Quiz")
        self._attempts(quiz_id, 2, "review")
        conn = dlms.get_db()
        try:
            conn.execute("""
                INSERT INTO missed_questions (attempt_id, attempt_question_number, question_text,
                    correct_letters, correct_text, selected_letters, selected_text, question_type, response_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, ("pk-review-1", 1, "Missed?", "A", "Correct", "B", "Wrong", "choice", ""))
            conn.commit()
        finally:
            conn.close()

        selected = self.client.get("/api/attempts/public-review-1")
        self.assertEqual(selected.status_code, 200)
        self.assertEqual(selected.get_json()["attempt_pk"], "pk-review-1")
        fallback = self.client.get("/api/attempts/pk-review-1")
        self.assertEqual(fallback.status_code, 200)
        missed = self.client.get("/api/missed_questions?attempt=public-review-1")
        self.assertEqual(missed.status_code, 200)
        self.assertEqual(missed.get_json()[0]["question_text"], "Missed?")
        self.assertEqual(self.client.get("/api/attempts/nope").status_code, 404)
        self.assertEqual(self.client.get("/api/missed_questions?attempt=nope").status_code, 404)

        overview = self.client.get("/api/attempts/overview").get_json()
        self.assertEqual(overview["total_attempts"], 2)
        self.assertEqual(len(overview["recent_attempts"]), 2)
        self.assertEqual(overview["latest_attempt"]["id"], "public-review-1")
        analytics = self.client.get("/api/attempts/analytics").get_json()
        self.assertEqual(analytics["summary"]["total_attempts"], 2)
        self.assertEqual(analytics["summary"]["quiz_count"], 1)
        self.assertEqual(analytics["quizzes"][0]["latest_attempt"]["id"], "public-review-1")
        self.assertIsNotNone(analytics["quizzes"][0]["previous_attempt"])
        self.assertEqual(self.client.get("/history_db").status_code, 410)

    def test_empty_overview_and_frontends_use_purpose_specific_endpoints(self):
        overview = self.client.get("/api/attempts/overview").get_json()
        self.assertEqual(overview["total_attempts"], 0)
        self.assertIsNone(overview["latest_attempt"])
        self.assertEqual(self.client.get("/api/attempts").get_json()["attempts"], [])
        root = os.path.dirname(os.path.dirname(__file__))
        with open(os.path.join(root, "static", "history.html"), encoding="utf-8") as f:
            self.assertIn("/api/attempts?${query}", f.read())
        with open(os.path.join(root, "static", "index.html"), encoding="utf-8") as f:
            self.assertIn("/api/attempts/overview", f.read())
        with open(os.path.join(root, "static", "dashboard.html"), encoding="utf-8") as f:
            self.assertIn("/api/attempts/analytics", f.read())
        with open(os.path.join(root, "static", "review.html"), encoding="utf-8") as f:
            self.assertIn("/api/attempts/${encodeURIComponent(attemptId)}", f.read())

    def test_history_empty_states_distinguish_unfiltered_and_empty_origin_filters(self):
        root = os.path.dirname(os.path.dirname(__file__))
        history_path = os.path.join(root, "static", "history.html")
        with open(history_path, encoding="utf-8") as f:
            source = f.read()

        # With no attempts, the unfiltered response remains empty and the UI
        # presents the first-run guidance.
        self.assertEqual(self.client.get("/api/attempts?origin=all").get_json()["total"], 0)
        self.assertIn('if (!dbAttempts.length && historyOriginFilter === "all")', source)
        self.assertIn("No saved attempts yet", source)

        # A saved IT attempt must not make an empty Medical filter claim that
        # no attempts have ever been saved.
        it_quiz_id = self._quiz("IT attempt", "it")
        self._attempts(it_quiz_id, 1, "it")
        self.assertEqual(self.client.get("/api/attempts?origin=medical").get_json()["total"], 0)
        self.assertIn(
            'if (!dbAttempts.length) {\n'
            '        box.innerHTML = `<div class="history-table-empty"><div class="history-table-empty-icon">↶</div><h2>No attempts in this category</h2>',
            source,
        )

    def test_history_renders_hostile_attempt_text_with_safe_dom_properties(self):
        hostile_title = '<img src=x onerror="window.historyXssExecuted=true">'
        quiz_id = self._quiz(hostile_title)
        self._attempts(quiz_id, 1, "hostile")

        attempt = self.client.get("/api/attempts?page_size=1").get_json()["attempts"][0]
        self.assertEqual(attempt["quiz_title"], hostile_title)

        response = self.client.get("/history")
        try:
            page = response.get_data(as_text=True)
        finally:
            response.close()
        self.assertIn('quizTitle.textContent = String(a.quiz_title || "Unknown Quiz")', page)
        self.assertIn('modeBadge.textContent = String(a.mode || "Unknown")', page)
        self.assertIn('originBadge.textContent = String(a.origin || "Quiz")', page)
        self.assertIn('reviewLink.href = `/review?attempt=${encodeURIComponent(attemptId)}`', page)
        self.assertNotIn('${a.quiz_title || "Unknown Quiz"}', page)
        self.assertNotIn('${a.mode || "Unknown"}', page)
        self.assertNotIn(hostile_title, page)


if __name__ == "__main__":
    unittest.main()

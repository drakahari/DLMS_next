"""Durable Generated Practice completion and Library presentation regressions."""

import hashlib
import json
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from tests._isolation import ensure_test_data_isolation

ensure_test_data_isolation()
import app as dlms
from dlms.services.generated_practice_lifecycle import COMPLETION_KEY, completion_metadata
from tests.csrf_test_utils import csrf_headers


class GeneratedPracticeLifecycleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dlms-generated-lifecycle-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        paths = {
            "APP_DATA_DIR": root,
            "DATA_FOLDER": root / "data",
            "QUIZ_FOLDER": root / "quizzes",
            "CONFIG_FOLDER": root / "config",
            "QUIZ_REGISTRY": root / "config" / "quizzes.json",
            "PORTAL_CONFIG": root / "config" / "portal.json",
            "DB_PATH": root / "results.db",
            "QUIZ_ASSET_FOLDER": root / "quiz_assets",
            "LOGO_FOLDER": root / "static" / "logos",
            "BACKUP_FOLDER": root / "backups",
        }
        for name, path in paths.items():
            patcher = mock.patch.object(dlms, name, str(path))
            patcher.start()
            self.addCleanup(patcher.stop)
            if name not in {"APP_DATA_DIR", "DB_PATH", "QUIZ_REGISTRY"}:
                path.mkdir(parents=True, exist_ok=True)
        dlms._initialize_data_root_ownership(str(root))
        dlms.ensure_db_initialized()
        dlms.save_registry([])
        self.client = dlms.app.test_client()
        self.headers = csrf_headers(self.client)

    @staticmethod
    def choice(*, multi=False):
        return {
            "number": 1, "type": "choice", "question": "Review this question.",
            "choices": [
                {"label": "A", "text": "Alpha", "is_correct": True},
                {"label": "B", "text": "Beta", "is_correct": multi},
                {"label": "C", "text": "Gamma", "is_correct": False},
            ],
        }

    @staticmethod
    def matching():
        return {
            "number": 1, "type": "matching", "question": "Match the items.",
            "pairs": [
                {"left": "Alpha", "right": "First"},
                {"left": "Beta", "right": "Second"},
            ],
        }

    def publish(self, title="Due review", questions=None, kind="native_spaced_review"):
        quiz_id, html = dlms._publish_quiz(
            title, questions or [self.choice()],
            filename_prefix="lifecycle_review", generation_kind=kind,
        )
        return quiz_id, html

    def fingerprint(self, quiz_id):
        entry = next(item for item in dlms.load_registry() if item["id"] == quiz_id)
        _, json_name = dlms._quiz_artifact_names(entry)
        raw = (Path(dlms.DATA_FOLDER) / json_name).read_text(encoding="utf-8")
        identity = "\0".join((
            "quiz-recovery-v1", "1", str(quiz_id), f"/data/{json_name}",
            str(entry.get("exam_minutes") or 90), raw,
        ))
        return "sha256:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()

    def completion_payload(self, quiz_id, *, mode="Study", reference="study-run", selected=None):
        return {
            "quizId": quiz_id, "mode": mode, "reference": reference,
            "questionCount": 1, "fingerprint": self.fingerprint(quiz_id),
            "answers": [{"ordinal": 1, "selected": selected if selected is not None else ["A"]}],
        }

    def save_study(self, quiz_id, *, selected, was_correct, question_type="choice", session="study-run"):
        return self.client.post(
            "/api/learning-events/study-response",
            json={
                "quizId": quiz_id, "questionOrdinal": 1,
                "questionType": question_type, "sessionId": session,
                "eventId": f"{session}-{json.dumps(selected, sort_keys=True)}",
                "selected": selected, "wasCorrect": was_correct,
            }, headers=self.headers,
        )

    def complete(self, payload):
        return self.client.post(
            "/api/generated-practice/complete", json=payload, headers=self.headers,
        )

    def marker(self, quiz_id):
        return next(item for item in dlms.load_registry() if item["id"] == quiz_id).get(COMPLETION_KEY)

    def test_study_completion_requires_saved_complete_response_and_is_idempotent(self):
        quiz_id, _ = self.publish()
        payload = self.completion_payload(quiz_id)
        self.assertEqual(400, self.complete(payload).status_code)
        self.assertIsNone(self.marker(quiz_id))
        saved = self.save_study(quiz_id, selected=["A"], was_correct=True)
        self.assertEqual(200, saved.status_code, saved.get_data(as_text=True))
        first = self.complete(payload)
        self.assertEqual(200, first.status_code, first.get_data(as_text=True))
        self.assertTrue(self.marker(quiz_id))
        self.assertTrue(self.complete(payload).get_json()["already_completed"])
        status = self.client.get(f"/api/generated-practice/status/{quiz_id}").get_json()
        self.assertEqual({"is_transient": True, "completed": True}, status)
        library = self.client.get("/library").get_data(as_text=True)
        self.assertIn("Completed Generated Practice", library)
        self.assertIn("Completed <time", library)
        self.assertIn('aria-expanded="false"', library)
        self.assertIn("Due review", library)
        self.assertIn('href="/quizzes/', library)

    def test_partial_multiselect_and_matching_cannot_complete(self):
        for question, selected, finished, question_type in (
            (self.choice(multi=True), ["A"], ["A", "B"], "choice"),
            (self.matching(), {"0": 0}, {"0": 0, "1": 1}, "matching"),
        ):
            with self.subTest(question_type=question_type):
                quiz_id, _ = self.publish(questions=[question])
                saved = self.save_study(
                    quiz_id, selected=selected, was_correct=None,
                    question_type=question_type,
                )
                self.assertEqual(200, saved.status_code, saved.get_data(as_text=True))
                self.assertEqual(400, self.complete(self.completion_payload(quiz_id, selected=selected)).status_code)
                self.assertIsNone(self.marker(quiz_id))
                saved = self.save_study(
                    quiz_id, selected=finished, was_correct=True,
                    question_type=question_type,
                )
                self.assertEqual(200, saved.status_code, saved.get_data(as_text=True))
                self.assertEqual(200, self.complete(self.completion_payload(quiz_id, selected=finished)).status_code)

    def test_failed_marker_write_preserves_study_event_and_can_retry(self):
        quiz_id, _ = self.publish()
        self.assertEqual(200, self.save_study(quiz_id, selected=["A"], was_correct=True).status_code)
        payload = self.completion_payload(quiz_id)
        with mock.patch.object(dlms, "save_registry", side_effect=OSError("disk full")):
            response = self.complete(payload)
        self.assertEqual(500, response.status_code)
        self.assertIsNone(self.marker(quiz_id))
        conn = dlms.get_db()
        try:
            self.assertEqual(1, conn.execute(
                "SELECT COUNT(*) FROM learning_events WHERE quiz_id = ? AND event_type = 'study_answer'",
                (quiz_id,),
            ).fetchone()[0])
        finally:
            conn.close()
        self.assertEqual(200, self.complete(payload).status_code)

    def test_exam_requires_persisted_complete_attempt_evidence(self):
        quiz_id, _ = self.publish()
        payload = self.completion_payload(quiz_id, mode="Exam", reference="exam-run")
        self.assertEqual(400, self.complete(payload).status_code)
        conn = dlms.get_db()
        try:
            question_id = conn.execute("SELECT id FROM questions WHERE quiz_id = ?", (quiz_id,)).fetchone()[0]
            conn.execute(
                "INSERT INTO attempts(id, quiz_id, score, total, percent, completed_at, mode) VALUES (?, ?, 1, 1, 100, ?, 'Exam')",
                ("exam-run", quiz_id, "2026-01-01T12:00:00+00:00"),
            )
            conn.commit()
        finally:
            conn.close()
        self.assertEqual(400, self.complete(payload).status_code)
        conn = dlms.get_db()
        try:
            conn.execute(
                "INSERT INTO learning_events(event_type, quiz_id, question_id, attempt_id, mode, was_correct, response_json) VALUES ('exam_answer', ?, ?, 'exam-run', 'Exam', 1, '{}')",
                (quiz_id, question_id),
            )
            conn.commit()
        finally:
            conn.close()
        self.assertEqual(200, self.complete(payload).status_code)

    def test_malformed_marker_and_nontransient_kinds_remain_active(self):
        for kind in ("source", "mixed_quiz"):
            quiz_id, _ = self.publish(kind=kind)
            self.assertEqual({"is_transient": False, "completed": False},
                             self.client.get(f"/api/generated-practice/status/{quiz_id}").get_json())
            self.assertFalse(self.complete(self.completion_payload(quiz_id)).get_json()["applicable"])
        quiz_id, _ = self.publish()
        registry = dlms.load_registry()
        next(item for item in registry if item["id"] == quiz_id)[COMPLETION_KEY] = {
            "completed_at": [], "mode": [], "reference": [],
        }
        dlms.save_registry(registry)
        self.assertIsNone(completion_metadata(registry[-1], "native_spaced_review"))
        self.assertFalse(self.client.get(f"/api/generated-practice/status/{quiz_id}").get_json()["completed"])

    def test_legacy_generated_fallback_stays_active_without_historical_backfill(self):
        quiz_id, _ = self.publish()
        conn = dlms.get_db()
        try:
            conn.execute(
                "UPDATE quizzes SET generation_kind = NULL, source_file = 'spaced_review_native_legacy.html' WHERE id = ?",
                (quiz_id,),
            )
            conn.commit()
        finally:
            conn.close()
        self.assertEqual(
            {"is_transient": True, "completed": False},
            self.client.get(f"/api/generated-practice/status/{quiz_id}").get_json(),
        )
        self.assertIsNone(self.marker(quiz_id))

    def test_question_edit_invalidates_completion_but_reset_learning_intelligence_does_not(self):
        quiz_id, _ = self.publish()
        self.assertEqual(200, self.save_study(quiz_id, selected=["A"], was_correct=True).status_code)
        self.assertEqual(200, self.complete(self.completion_payload(quiz_id)).status_code)
        before = self.marker(quiz_id)
        dlms._reset_learning_intelligence_core()
        self.assertEqual(before, self.marker(quiz_id))

        conn = dlms.get_db()
        try:
            question_id = conn.execute("SELECT id FROM questions WHERE quiz_id = ?", (quiz_id,)).fetchone()[0]
            choice_ids = conn.execute("SELECT id, label FROM choices WHERE question_id = ? ORDER BY label", (question_id,)).fetchall()
        finally:
            conn.close()
        form = {
            "quiz_title": "Edited review", "exam_minutes": "90",
            f"question_{question_id}": "New question content.",
            f"explanation_{question_id}": "",
            f"concepts_{question_id}": "",
        }
        for choice in choice_ids:
            form[f"choice_{choice['id']}"] = choice["label"]
        form[f"correct_{choice_ids[0]['id']}"] = "on"
        response = self.client.post(
            f"/edit_quiz/{quiz_id}", data=form, headers=self.headers,
        )
        self.assertEqual(302, response.status_code, response.get_data(as_text=True))
        self.assertIsNone(self.marker(quiz_id))
        self.assertFalse(self.client.get(f"/api/generated-practice/status/{quiz_id}").get_json()["completed"])

    def test_full_backup_retains_marker_and_old_registry_defaults_active(self):
        quiz_id, _ = self.publish()
        self.assertEqual(200, self.save_study(quiz_id, selected=["A"], was_correct=True).status_code)
        self.assertEqual(200, self.complete(self.completion_payload(quiz_id)).status_code)
        archive_path, _ = dlms._create_dlms_backup("lifecycle")
        with zipfile.ZipFile(archive_path) as archive:
            registry_member = next(name for name in archive.namelist() if name.endswith("/config/quizzes.json"))
            backed_up = json.loads(archive.read(registry_member))
        restored_entry = next(item for item in backed_up if item["id"] == quiz_id)
        self.assertIsNotNone(completion_metadata(restored_entry, "native_spaced_review"))
        staged_root = Path(dlms.APP_DATA_DIR) / "restore-check"
        report = dlms._validate_dlms_backup(archive_path)
        dlms._extract_validated_backup(archive_path, staged_root, report)
        self.assertEqual(
            backed_up,
            json.loads((staged_root / "config" / "quizzes.json").read_text(encoding="utf-8")),
        )
        restored_entry.pop(COMPLETION_KEY)
        self.assertIsNone(completion_metadata(restored_entry, "native_spaced_review"))

    def test_completion_only_changes_library_metadata_not_learning_or_schedule(self):
        quiz_id, _ = self.publish()
        self.assertEqual(200, self.save_study(quiz_id, selected=["A"], was_correct=True).status_code)
        now = datetime.now(timezone.utc)

        def current_state():
            conn = dlms.get_db()
            try:
                return (
                    dlms._learning_intelligence_payload(conn.cursor(), now=now),
                    dlms._native_spaced_repetition_schedule(conn.cursor(), now=now),
                )
            finally:
                conn.close()

        before = current_state()
        self.assertEqual(200, self.complete(self.completion_payload(quiz_id)).status_code)
        self.assertEqual(before, current_state())

    def test_many_completed_cards_use_a_batched_library_pass(self):
        conn = dlms.get_db()
        try:
            registry = []
            for ordinal in range(300):
                cursor = conn.execute(
                    "INSERT INTO quizzes(title, source_file, generation_kind) VALUES (?, ?, 'smart_review')",
                    (f"Saved review {ordinal}", f"synthetic-review-{ordinal}.html"),
                )
                registry.append({
                    "id": cursor.lastrowid,
                    "title": f"Saved review {ordinal}",
                    "html": f"synthetic-review-{ordinal}.html",
                    COMPLETION_KEY: {
                        "completed_at": "2026-01-01T00:00:00+00:00",
                        "mode": "Study", "reference": f"run-{ordinal}",
                    },
                })
            conn.commit()

            def select_count(entries):
                statements = []
                conn.set_trace_callback(statements.append)
                try:
                    result = dlms._quiz_smart_view_service.build_quiz_smart_views(
                        conn.cursor(), entries,
                        native_schedule=lambda _cur, now=None: {"questions": []},
                        now=datetime(2026, 1, 2, tzinfo=timezone.utc),
                    )
                finally:
                    conn.set_trace_callback(None)
                return len(statements), len(result["completion"])

            one_queries, one_completed = select_count(registry[:1])
            many_queries, many_completed = select_count(registry)
            self.assertEqual((1, 300), (one_completed, many_completed))
            self.assertLessEqual(many_queries, one_queries + 1)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()

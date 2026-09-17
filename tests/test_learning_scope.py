"""Folder Learning Scope preserves history while filtering active source evidence."""

import json
import re
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from tests._isolation import ensure_test_data_isolation

ensure_test_data_isolation()
import app as dlms
from dlms.services import backups as backup_service


NOW = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)


class LearningScopeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dlms-learning-scope-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        paths = {
            "APP_DATA_DIR": self.root,
            "DATA_FOLDER": self.root / "data",
            "QUIZ_FOLDER": self.root / "quizzes",
            "CONFIG_FOLDER": self.root / "config",
            "PORTAL_CONFIG": self.root / "config" / "portal.json",
            "QUIZ_REGISTRY": self.root / "config" / "quizzes.json",
            "DB_PATH": self.root / "results.db",
            "QUIZ_ASSET_FOLDER": self.root / "quiz_assets",
            "LOGO_FOLDER": self.root / "static" / "logos",
        }
        for name, path in paths.items():
            patcher = mock.patch.object(dlms, name, str(path))
            patcher.start()
            self.addCleanup(patcher.stop)
            if name not in {"APP_DATA_DIR", "DB_PATH", "PORTAL_CONFIG", "QUIZ_REGISTRY"}:
                path.mkdir(parents=True, exist_ok=True)
        self.assertTrue(dlms._initialize_data_root_ownership(str(self.root)))
        dlms.ensure_db_initialized()
        dlms.save_registry([])
        dlms.load_portal_config()

    @staticmethod
    def _choice(label, concepts):
        return {
            "number": 1, "type": "choice", "question": f"{label}?",
            "concepts": concepts,
            "choices": [
                {"label": "A", "text": "Correct", "is_correct": True},
                {"label": "B", "text": "Wrong", "is_correct": False},
            ],
        }

    def _publish(self, label, concepts, *, folder="Uncategorized"):
        quiz_id, _html = dlms._publish_quiz(
            label, [self._choice(label, concepts)], filename_prefix="scope_source"
        )
        registry = dlms.load_registry()
        next(item for item in registry if item["id"] == quiz_id)["folder"] = folder
        dlms.save_registry(registry)
        conn = dlms.get_db()
        try:
            question_id = conn.execute(
                "SELECT id FROM questions WHERE quiz_id=?", (quiz_id,)
            ).fetchone()[0]
        finally:
            conn.close()
        return quiz_id, question_id

    def _answer(self, quiz_id, question_id, correct, session):
        conn = dlms.get_db()
        try:
            cur = conn.cursor()
            dlms._record_learning_event(
                cur, event_type="study_answer", quiz_id=quiz_id,
                question_id=question_id, session_id=session, mode="Study",
                was_correct=correct,
            )
            cur.execute(
                "UPDATE learning_events SET occurred_at=? WHERE id=?",
                ("2026-09-10T12:00:00+00:00", cur.lastrowid),
            )
            conn.commit()
        finally:
            conn.close()

    def _exclude(self, *names):
        dlms.save_quiz_folder_state(
            dlms.get_quiz_folders(), dlms.get_hidden_quiz_folders(), list(names)
        )

    def _active(self):
        conn = dlms.get_db()
        try:
            cur = conn.cursor()
            return {
                "topics": dlms._learning_intelligence_topics(cur, now=NOW),
                "schedule": dlms._native_spaced_repetition_schedule(cur, now=NOW),
                "retention": dlms._review_schedule_payload(cur, now=NOW),
                "adaptive": dlms._adaptive_study_candidates(cur, now=NOW),
                "smart": dlms._smart_review_candidates(cur),
                "diagnostics": dlms._question_diagnostics_payload(cur),
                "profile": dlms._learning_profile_payload(cur),
                "today": dlms._daily_review_plan(cur, now=NOW),
            }
        finally:
            conn.close()

    def test_no_exclusions_preserve_all_active_outputs(self):
        quiz_id, question_id = self._publish("Current", ["Shared"])
        self._answer(quiz_id, question_id, False, "baseline")
        before = self._active()
        self._exclude()
        self.assertEqual(before, self._active())
        conn = dlms.get_db()
        try:
            self.assertIsNone(dlms._current_learning_scope(conn.cursor()))
        finally:
            conn.close()

    def test_source_scope_filters_topics_schedule_candidates_diagnostics_and_today(self):
        dlms.save_quiz_folders(["Uncategorized", "Archive"])
        current, current_q = self._publish("Current", ["Shared"])
        archived, archived_q = self._publish("Archived", ["Shared", "Archive Only"], folder="Archive")
        for index in range(6):
            self._answer(current, current_q, True, f"current-{index}")
            self._answer(archived, archived_q, False, f"archive-{index}")
        baseline = self._active()
        shared = next(topic for topic in baseline["topics"] if topic["name"] == "Shared")
        self.assertEqual(12, shared["evidence"])
        self.assertEqual(50.0, shared["accuracy"])

        self._exclude("archive")
        scoped = self._active()
        shared = next(topic for topic in scoped["topics"] if topic["name"] == "Shared")
        self.assertEqual(6, shared["evidence"])
        self.assertEqual(100.0, shared["accuracy"])
        self.assertEqual(100.0, shared["recent_accuracy"])
        self.assertGreater(shared["mastery"], next(topic for topic in baseline["topics"] if topic["name"] == "Shared")["mastery"])
        self.assertEqual("stable", shared["trend"])
        self.assertEqual(1, shared["question_count"])
        self.assertNotIn("Archive Only", [topic["name"] for topic in scoped["topics"]])
        self.assertEqual([current_q], [row["question_id"] for row in scoped["schedule"]["questions"]])
        self.assertEqual(1, scoped["schedule"]["summary"]["overdue"])
        self.assertEqual([current_q], [row["question_id"] for row in scoped["adaptive"]])
        self.assertEqual([], scoped["smart"][0])
        self.assertEqual(1, len(scoped["diagnostics"]["questions"]))
        self.assertEqual(6, scoped["profile"]["activity"]["study_answers"])
        self.assertEqual(1, scoped["today"]["summary"]["due_questions"])

        # Manual activity is saved while excluded and becomes eligible again.
        self._answer(archived, archived_q, True, "manual-while-excluded")
        self.assertEqual(6, next(t for t in self._active()["topics"] if t["name"] == "Shared")["evidence"])
        conn = dlms.get_db()
        try:
            self.assertEqual(13, conn.execute("SELECT COUNT(*) FROM learning_events WHERE event_type='study_answer'").fetchone()[0])
        finally:
            conn.close()
        self._exclude()
        self.assertEqual(13, next(t for t in self._active()["topics"] if t["name"] == "Shared")["evidence"])
        self.assertEqual(
            {current_q, archived_q},
            {item["question_id"] for item in self._active()["schedule"]["questions"]},
        )

    def test_generated_lineage_uses_source_and_ambiguous_legacy_is_omitted(self):
        dlms.save_quiz_folders(["Uncategorized", "Archive"])
        included, included_q = self._publish("Included", ["Shared"])
        excluded, excluded_q = self._publish("Excluded", ["Shared"], folder="Archive")
        conn = dlms.get_db()
        try:
            included_payload = dlms._question_payload_from_db(conn.cursor(), included_q)
            excluded_payload = dlms._question_payload_from_db(conn.cursor(), excluded_q)
        finally:
            conn.close()
        generated_id, _ = dlms._publish_quiz(
            "Mixed Quiz — Scope", [included_payload, excluded_payload, self._choice("Legacy", ["Shared"])],
            filename_prefix="mixed_quiz_scope", generation_kind="mixed_quiz",
        )
        registry = dlms.load_registry()
        next(item for item in registry if item["id"] == generated_id)["folder"] = "Archive"
        dlms.save_registry(registry)
        conn = dlms.get_db()
        try:
            generated = conn.execute(
                "SELECT id FROM questions WHERE quiz_id=? ORDER BY question_number", (generated_id,)
            ).fetchall()
        finally:
            conn.close()
        for index, row in enumerate(generated):
            self._answer(generated_id, row["id"], index == 0, f"generated-{index}")
        self._exclude("Archive")
        topic = next(t for t in self._active()["topics"] if t["name"] == "Shared")
        self.assertEqual(1, topic["evidence"])
        schedule = self._active()["schedule"]
        self.assertEqual([included_q], [row["question_id"] for row in schedule["questions"]])
        self.assertEqual(1, schedule["questions"][0]["responses"])
        self._exclude()
        self.assertEqual(3, next(t for t in self._active()["topics"] if t["name"] == "Shared")["evidence"])

    def test_native_schedule_buckets_and_needs_review_follow_source_scope(self):
        dlms.save_quiz_folders(["Uncategorized", "Archive"])
        current, current_q = self._publish("Current Due", ["Current Topic"])
        archived_due, archived_due_q = self._publish("Archived Due", ["Archive Topic"], folder="Archive")
        archived_soon, archived_soon_q = self._publish("Archived Soon", ["Archive Topic"], folder="Archive")
        self._publish("Archived Unscheduled", ["Archive Topic"], folder="Archive")
        self._answer(current, current_q, False, "current-due")
        self._answer(current, current_q, False, "current-due-2")
        self._answer(current, current_q, False, "current-due-3")
        self._answer(archived_due, archived_due_q, False, "archived-due")
        self._answer(archived_soon, archived_soon_q, True, "archived-soon")
        conn = dlms.get_db()
        try:
            conn.execute(
                "UPDATE learning_events SET occurred_at=? WHERE question_id=?",
                (NOW.isoformat(), archived_soon_q),
            )
            conn.commit()
        finally:
            conn.close()
        baseline = self._active()["schedule"]["summary"]
        self.assertEqual(4, baseline["eligible_questions"])
        self.assertEqual(1, baseline["due_next_7_days"])
        self.assertEqual(1, baseline["unscheduled"])

        self._exclude("Archive")
        scoped = self._active()
        self.assertEqual([current_q], [item["question_id"] for item in scoped["schedule"]["questions"]])
        self.assertEqual(1, scoped["schedule"]["summary"]["overdue"])
        self.assertEqual(0, scoped["schedule"]["summary"]["due_next_7_days"])
        self.assertEqual(0, scoped["schedule"]["summary"]["unscheduled"])
        self.assertEqual(["Current Topic"], [item["name"] for item in scoped["retention"]["topics"]])
        conn = dlms.get_db()
        try:
            smart = dlms._quiz_smart_view_service.build_quiz_smart_views(
                conn.cursor(), dlms.load_registry(),
                native_schedule=dlms._native_spaced_repetition_schedule, now=NOW,
            )
        finally:
            conn.close()
        self.assertEqual({current}, set(smart["matches"]["needs-review"]))
        self.assertNotIn(archived_due, smart["matches"]["needs-review"])

    def test_management_visibility_rename_delete_and_validation(self):
        dlms.save_quiz_folders(["Uncategorized", "Archive", "Empty"])
        quiz_id, _question_id = self._publish("Archived", ["Archive Only"], folder="Archive")
        client = dlms.app.test_client()
        page = client.get("/learning-scope")
        self.assertEqual(200, page.status_code)
        self.assertIn(b"Uncategorized", page.data)
        self.assertIn(b"Empty", page.data)
        token = re.search(rb'name="csrf_token" value="([^"]+)"', page.data).group(1).decode()
        response = client.post("/learning-scope", data={
            "csrf_token": token, "folder": "ARCHIVE", "included": "0",
        }, follow_redirects=True)
        self.assertEqual(200, response.status_code)
        self.assertIn(b"Excluded from Learning Scope", response.data)
        self.assertEqual(["Archive"], dlms.get_excluded_learning_folders())
        self.assertIn(b"Excluded from Learning Scope", client.get("/library?view=all").data)
        other_client = dlms.app.test_client()
        self.assertEqual(1, other_client.get("/api/learning-scope").get_json()["excluded_folders"])
        dlms.save_quiz_folder_state(dlms.get_quiz_folders(), ["Archive"], ["Archive"])
        conn = dlms.get_db()
        try:
            self.assertEqual([], dlms._learning_intelligence_topics(conn.cursor()))
        finally:
            conn.close()
        dlms._rename_quiz_folder_metadata("Archive", "Past Courses")
        self.assertEqual(["Past Courses"], dlms.get_excluded_learning_folders())
        registry = dlms.load_registry()
        next(item for item in registry if item["id"] == quiz_id)["folder"] = "Uncategorized"
        dlms.save_registry(registry)
        self.assertEqual(1, other_client.get("/api/learning-scope").get_json()["included_source_quizzes"])
        next(item for item in registry if item["id"] == quiz_id)["folder"] = "Past Courses"
        dlms.save_registry(registry)
        dlms._delete_quiz_folder_metadata("Past Courses")
        self.assertEqual([], dlms.get_excluded_learning_folders())
        self.assertEqual("Uncategorized", next(item for item in dlms.load_registry() if item["id"] == quiz_id)["folder"])

        path = self.root / "config" / "portal.json"
        data = json.loads(path.read_text())
        data["excluded_learning_folders"] = "Archive"
        path.write_text(json.dumps(data))
        self.assertEqual([], dlms.get_excluded_learning_folders())

    def test_rename_rollback_and_settings_reset_preserve_learning_data(self):
        dlms.save_quiz_folders(["Uncategorized", "Archive"])
        quiz_id, question_id = self._publish("Archived", ["Archive Only"], folder="Archive")
        self._answer(quiz_id, question_id, False, "before-reset")
        self._exclude("Archive")
        with mock.patch.object(dlms, "save_registry", side_effect=RuntimeError("disk fault")):
            with self.assertRaises(RuntimeError):
                dlms._rename_quiz_folder_metadata("Archive", "Renamed")
        self.assertEqual(["Archive"], dlms.get_excluded_learning_folders())
        self.assertIn("Archive", dlms.get_quiz_folders())
        self.assertEqual("Archive", next(item for item in dlms.load_registry() if item["id"] == quiz_id)["folder"])
        with mock.patch.object(dlms, "save_registry", side_effect=RuntimeError("disk fault")):
            with self.assertRaises(RuntimeError):
                dlms._delete_quiz_folder_metadata("Archive")
        self.assertEqual(["Archive"], dlms.get_excluded_learning_folders())
        self.assertIn("Archive", dlms.get_quiz_folders())
        self.assertEqual("Archive", next(item for item in dlms.load_registry() if item["id"] == quiz_id)["folder"])
        dlms._reset_app_settings_core()
        self.assertEqual([], dlms.get_excluded_learning_folders())
        conn = dlms.get_db()
        try:
            self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM learning_events WHERE event_type='study_answer'").fetchone()[0])
            self.assertEqual(1, len(dlms._learning_intelligence_topics(conn.cursor())))
        finally:
            conn.close()

    def test_uncategorized_and_moves_inherit_destination_scope(self):
        dlms.save_quiz_folders(["Uncategorized", "Archive"])
        quiz_id, _question_id = self._publish("Movable", ["Movement"], folder="Archive")
        self._exclude("Archive")
        self.assertEqual([], [t["name"] for t in self._active()["topics"]])
        registry = dlms.load_registry()
        next(item for item in registry if item["id"] == quiz_id)["folder"] = "Uncategorized"
        dlms.save_registry(registry)
        self.assertEqual(["Movement"], [t["name"] for t in self._active()["topics"]])
        self._exclude("Uncategorized")
        self.assertEqual([], [t["name"] for t in self._active()["topics"]])
        next(item for item in registry if item["id"] == quiz_id)["folder"] = "Archive"
        dlms.save_registry(registry)
        self.assertEqual(["Movement"], [t["name"] for t in self._active()["topics"]])

    def test_old_and_new_portal_documents_load_with_safe_defaults(self):
        path = self.root / "config" / "portal.json"
        old = {"quiz_folders": ["Uncategorized", "Archive"]}
        path.write_text(json.dumps(old), encoding="utf-8")
        self.assertEqual([], dlms.get_excluded_learning_folders())
        newer = {**old, "excluded_learning_folders": ["archive", "ARCHIVE", "Uncategorized"]}
        path.write_text(json.dumps(newer), encoding="utf-8")
        self.assertEqual(["archive", "Uncategorized"], dlms.get_excluded_learning_folders())
        path.write_text(json.dumps({**old, "excluded_learning_folders": ["Archive", 3]}), encoding="utf-8")
        self.assertEqual([], dlms.get_excluded_learning_folders())

    def test_full_backup_carries_portal_scope_setting(self):
        self._exclude("Uncategorized")
        backup_folder = self.root / "backups"
        backup_folder.mkdir()
        archive_path, _manifest = backup_service.create_dlms_backup(
            "scope-test", ensure_runtime_data_dirs=lambda: None,
            backup_folder=str(backup_folder), app_data_dir=str(self.root),
            db_path=str(self.root / "results.db"), app_version=dlms.APP_VERSION,
            backup_schema_version=dlms.DLMS_BACKUP_SCHEMA_VERSION,
            backup_manifest=dlms.DLMS_BACKUP_MANIFEST,
            backup_data_prefix=dlms.DLMS_BACKUP_DATA_PREFIX,
            file_inventory=lambda: [(str(self.root / "config" / "portal.json"), "config/portal.json")],
            summary=lambda: {},
        )
        with zipfile.ZipFile(archive_path) as archive:
            portal = json.loads(archive.read("DLMS_DATA/config/portal.json"))
        self.assertEqual(["Uncategorized"], portal["excluded_learning_folders"])
        restored_path = self.root / "restored-portal.json"
        restored_path.write_text(json.dumps(portal), encoding="utf-8")
        with mock.patch.object(dlms, "PORTAL_CONFIG", str(restored_path)):
            self.assertEqual(["Uncategorized"], dlms.get_excluded_learning_folders())

    def test_request_uses_one_scope_snapshot_for_nested_recommendations(self):
        dlms.save_quiz_folders(["Uncategorized", "Archive"])
        self._publish("Current", ["Shared"])
        self._exclude("Archive")
        original = dlms._learning_scope_service.build_learning_scope
        with mock.patch.object(dlms._learning_scope_service, "build_learning_scope", wraps=original) as build, \
             mock.patch.object(dlms, "load_registry", wraps=dlms.load_registry) as registry_reads:
            response = dlms.app.test_client().get("/api/daily-review-plan")
            self.assertEqual(200, response.status_code)
            self.assertEqual(1, build.call_count)
            self.assertEqual(1, registry_reads.call_count)

    def test_exclusion_does_not_change_history_or_analytics(self):
        dlms.save_quiz_folders(["Uncategorized", "Archive"])
        quiz_id, question_id = self._publish("Archived History", ["History Concept"], folder="Archive")
        conn = dlms.get_db()
        try:
            conn.execute("""
                INSERT INTO attempts (id, quiz_id, started_at, completed_at,
                                      score, total, percent, mode)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, ("scope-history-attempt", quiz_id, "2026-09-10T10:00:00",
                  "2026-09-10T10:05:00", 0, 1, 0, "Exam"))
            conn.commit()
        finally:
            conn.close()
        client = dlms.app.test_client()
        paths = ("/api/attempts", "/api/attempts/overview", "/api/attempts/analytics")
        before = {path: client.get(path).get_json() for path in paths}
        self.assertIn("Archived History", json.dumps(before["/api/attempts"]))
        self._exclude("Archive")
        self.assertEqual(before, {path: client.get(path).get_json() for path in paths})
        conn = dlms.get_db()
        try:
            self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM attempts WHERE quiz_id=?", (quiz_id,)).fetchone()[0])
            self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM questions WHERE id=?", (question_id,)).fetchone()[0])
        finally:
            conn.close()

    def test_study_pack_activity_recommendation_uses_source_scope(self):
        dlms.save_quiz_folders(["Uncategorized", "Archive"])
        quiz_id, question_id = self._publish("Pack Quiz", ["Pack Concept"], folder="Archive")
        registry = dlms.load_registry()
        next(item for item in registry if item["id"] == quiz_id)["source_pack_id"] = "pack-a"
        dlms.save_registry(registry)
        self._answer(quiz_id, question_id, True, "pack-activity")
        conn = dlms.get_db()
        try:
            def plan(scope):
                return dlms._learning_service._daily_review_plan(
                    conn.cursor(), registry=dlms.load_registry(),
                    installed_content_packs=[{"id": "pack-a", "name": "Pack A"}],
                    now=datetime(2026, 9, 17, tzinfo=timezone.utc),
                    review_schedule_payload=lambda _cur, now=None: {"questions": [], "topics": []},
                    learning_intelligence_payload=lambda _cur, now=None: {"topics": []},
                    adaptive_study_candidates=lambda _cur, now=None: [], scope=scope,
                )
            self.assertTrue(any(item["kind"] == "study_pack" for item in plan(None)["items"]))
            self._exclude("Archive")
            self.assertFalse(any(item["kind"] == "study_pack" for item in plan(dlms._current_learning_scope(conn.cursor()))["items"]))
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()

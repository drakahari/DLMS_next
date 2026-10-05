"""Disposable data checks for ordered Study facts, completion and reset boundaries."""
import json
import sqlite3
import unittest
import tempfile
from unittest import mock
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests._isolation import ensure_test_data_isolation

ensure_test_data_isolation()
from tests import test_generated_practice_lifecycle as lifecycle
from tests.csrf_test_utils import csrf_headers
import app as dlms
from dlms.services import study_sessions as study
from dlms.services import learning, restore


class StudySessionTests(unittest.TestCase):
    choice = staticmethod(lifecycle.GeneratedPracticeLifecycleTests.choice)
    matching = staticmethod(lifecycle.GeneratedPracticeLifecycleTests.matching)
    publish = lifecycle.GeneratedPracticeLifecycleTests.publish
    fingerprint = lifecycle.GeneratedPracticeLifecycleTests.fingerprint

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dlms-study-contract-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        paths = {"APP_DATA_DIR": root, "DB_PATH": root / "results.db", "DATA_FOLDER": root / "data", "QUIZ_FOLDER": root / "quizzes",
                 "CONFIG_FOLDER": root / "config", "QUIZ_REGISTRY": root / "config/quizzes.json", "PORTAL_CONFIG": root / "config/portal.json",
                 "QUIZ_ASSET_FOLDER": root / "quiz_assets", "LOGO_FOLDER": root / "static/logos", "BACKUP_FOLDER": root / "backups"}
        for name, path in paths.items():
            patcher = mock.patch.object(dlms, name, str(path))
            patcher.start(); self.addCleanup(patcher.stop)
            if not path.suffix:
                path.mkdir(parents=True, exist_ok=True)
        dlms._initialize_data_root_ownership(str(root)); dlms.ensure_db_initialized(); dlms.save_registry([])
        self.client = dlms.app.test_client()
        self.headers = csrf_headers(self.client)
        self.quiz_id, self.html = self.publish(kind=None)
        self.generation = self.client.get(f"/api/study/quiz/{self.quiz_id}").json["generation"]
        self.claim_data = dict(quizId=self.quiz_id, sessionId="session-one", owner="owner-one", generation=self.generation, fingerprint=self.fingerprint(self.quiz_id), variants={})
        response = self.client.post("/api/study/session", json=self.claim_data, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.json)
        self.session = response.json["session"]

    def payload(self, sequence, *, correct=True, selected=None, kind="response"):
        return dict(contract=2, quizId=self.quiz_id, sessionId="session-one", owner="owner-one", generation=self.generation,
                    assessmentRevision=self.session["assessment_revision"], eventId=f"event-{sequence}", sequence=sequence,
                    questionOrdinal=1, questionType="choice", wasCorrect=correct,
                    selected=selected if selected is not None else ["A" if correct else "C"], kind=kind)

    def save(self, payload):
        return self.client.post("/api/learning-events/study-response", json=payload, headers=self.headers)

    def finish(self, sequence):
        return self.client.post("/api/study/finish", json={**self.payload(sequence), "sequence": sequence}, headers=self.headers)

    def facts(self):
        return self.client.get(f"/api/study/quiz/{self.quiz_id}").json["session"]

    def evidence(self):
        conn = dlms.get_db()
        try:
            return learning._deduplicated_learning_answer_events(conn.cursor())
        finally:
            conn.close()

    def test_wrong_correct_order_and_completion_retry(self):
        self.assertEqual(self.save(self.payload(2)).status_code, 200)
        self.assertEqual(self.evidence(), [])
        self.assertEqual(self.finish(2).status_code, 409)
        wrong = self.payload(1, correct=False)
        self.assertEqual(self.save(wrong).status_code, 200)
        self.assertEqual(self.save(wrong).json["already_recorded"], True)
        self.assertEqual(self.facts()["answers"]["0"]["was_correct"], 1)
        self.assertFalse(self.facts()["observations"]["0"]["first"]["correct"])
        self.assertEqual(self.evidence()[0]["was_correct"], 0)
        finished = self.finish(2)
        self.assertEqual(finished.status_code, 200, finished.json)
        self.assertEqual(self.finish(2).json["session"]["completed_at"], finished.json["session"]["completed_at"])
        self.assertEqual(self.save(self.payload(3)).status_code, 409)
        self.assertEqual(self.save(wrong).status_code, 200)

    def test_conflicting_duplicate_and_takeover(self):
        self.assertEqual(self.save(self.payload(1)).status_code, 200)
        self.assertEqual(self.save(self.payload(1, correct=False)).status_code, 400)
        data = {**self.claim_data, "owner": "owner-two"}
        self.assertEqual(self.client.post("/api/study/session", json=data, headers=self.headers).status_code, 409)
        data["takeover"] = True
        self.assertEqual(self.client.post("/api/study/session", json=data, headers=self.headers).status_code, 200)
        self.assertEqual(self.save(self.payload(2)).status_code, 409)
        self.assertEqual(self.save({**self.payload(2), "owner": "owner-two"}).status_code, 200)
        self.assertEqual(self.finish(2).status_code, 409)
        completed = self.client.post("/api/study/finish", json={**self.payload(2), "owner": "owner-two"}, headers=self.headers)
        self.assertEqual(completed.status_code, 200)
        retry = self.client.post("/api/study/finish", json={**self.payload(2), "owner": "owner-two"}, headers=self.headers)
        self.assertEqual(retry.json["session"]["completed_at"], completed.json["session"]["completed_at"])

    def test_reset_retains_facts_does_not_replay(self):
        self.save(self.payload(1))
        self.finish(1)
        restore.reset_learning_intelligence_core(dlms.DB_PATH)
        self.assertEqual(self.evidence(), [])
        self.assertTrue(self.facts()["completed_at"])
        self.assertEqual(self.save(self.payload(1)).status_code, 409)
        self.assertEqual(self.evidence(), [])
        self.assertIn(b"Historical", self.client.get("/study-history").data)

    def test_changed_questions_reject_open_page_and_remove_estimate(self):
        self.save(self.payload(1))
        with dlms.get_db() as conn:
            conn.execute("UPDATE questions SET question_text = 'Changed question' WHERE quiz_id = ?", (self.quiz_id,))
        self.assertEqual(self.save(self.payload(2)).status_code, 409)
        self.assertEqual(self.finish(1).status_code, 409)
        self.assertEqual(self.evidence(), [])
        self.assertEqual(self.facts()["reviewed"], 1)

    def test_observable_action_before_correct_is_not_independent(self):
        action = self.payload(1, correct=None, kind="ai_open")
        action["selected"] = None
        self.assertEqual(self.save(action).status_code, 200)
        self.assertIsNone(self.facts())  # Opening an external tool is not Study progress.
        self.save(self.payload(2))
        observation = self.facts()["observations"]["0"]
        self.assertTrue(observation["first"]["correct"])
        self.assertTrue(observation["first"]["prior_feedback_or_action"])
        self.assertEqual(self.evidence()[0]["was_correct"], 1)
        self.assertFalse(self.evidence()[0]["independent_success"])

    def test_delete_requires_confirmation_and_csrf(self):
        self.save(self.payload(1))
        self.assertEqual(self.client.post("/api/delete_study_history", json={}).status_code, 400)
        self.assertEqual(self.client.post("/api/delete_study_history", json={}, headers=self.headers).status_code, 400)
        self.assertEqual(self.client.post("/api/delete_study_history", json=["DELETE STUDY HISTORY"], headers=self.headers).status_code, 400)
        # Exercise deletion core only on disposable DB; safeguard route separately mocked.
        restore.delete_study_history_core(dlms.DB_PATH)
        self.assertIsNone(self.facts())
        self.assertEqual(self.evidence(), [])

    def test_first_correct_and_elapsed_interval(self):
        self.save(self.payload(1))
        event = self.evidence()[0]
        self.assertEqual(event["was_correct"], 1)
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        event["occurred_at"] = start.isoformat()
        early = {**event, "occurred_at": (start + timedelta(hours=23)).isoformat()}
        due = {**event, "occurred_at": (start + timedelta(days=1)).isoformat()}
        schedule = learning._native_question_schedule_entry([event, early], now=start)
        self.assertEqual(schedule["correct_streak"], 1)
        self.assertEqual(schedule["next_review"], due["occurred_at"])
        self.assertEqual(learning._native_question_schedule_entry([event, early, due], now=start)["review_interval_days"], 3)

    def test_database_backup_retains_completion(self):
        self.save(self.payload(1)); self.finish(1)
        destination = Path(dlms.APP_DATA_DIR) / "disposable-copy.db"
        source = dlms.get_db()
        target = sqlite3.connect(destination)
        source.backup(target)
        source.close(); target.close()
        restore.delete_study_history_core(dlms.DB_PATH)
        with sqlite3.connect(destination) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM study_responses").fetchone()[0], 1)
            self.assertIsNotNone(conn.execute("SELECT completed_at FROM study_sessions").fetchone()[0])

    def test_portable_backup_staging_preserves_facts_and_invalidates_old_queues(self):
        self.save(self.payload(1, correct=False))
        self.save(self.payload(2))
        finished = self.finish(2).json["session"]["completed_at"]
        archive, _ = dlms._create_dlms_backup("study-contract-test")
        staged = Path(dlms.APP_DATA_DIR) / "disposable-restore"
        report = dlms._validate_dlms_backup(archive)
        dlms._extract_validated_backup(archive, staged, report)
        dlms._prepare_staged_restore_database(str(staged))
        with sqlite3.connect(staged / "results.db") as conn:
            self.assertEqual(conn.execute("SELECT completed_at FROM study_sessions").fetchone()[0], finished)
            self.assertEqual(conn.execute("SELECT was_correct FROM study_responses ORDER BY sequence").fetchall(), [(0,), (1,)])
            self.assertNotEqual(conn.execute("SELECT generation FROM study_state").fetchone()[0], self.generation)
        # A normal bootstrap/restart must preserve the live database's generation.
        dlms.ensure_db_initialized()
        self.assertEqual(self.client.get(f"/api/study/quiz/{self.quiz_id}").json["generation"], self.generation)
        self.assertEqual(self.facts()["completed_at"], finished)

    def replace_quiz(self, questions, *, kind=None, variants=None):
        self.quiz_id, self.html = self.publish(questions=questions, kind=kind)
        self.claim_data.update(quizId=self.quiz_id, sessionId="replacement", fingerprint=self.fingerprint(self.quiz_id), variants=variants or {})
        result = self.client.post("/api/study/session", json=self.claim_data, headers=self.headers)
        self.assertEqual(result.status_code, 200, result.json)
        self.session = result.json["session"]

    def test_partial_multi_and_matching_feedback_preserves_unknown_first(self):
        for question, partial, complete, variants in (
            (self.choice(multi=True), ["A"], ["A", "B"], {}),
            (self.matching(), {"0": 0}, {"0": 0, "1": 1}, {"0": {"sourcePairIndexes": [0, 1], "direction": "term_to_definition"}}),
        ):
            with self.subTest(question=question["type"]):
                self.replace_quiz([question], variants=variants)
                first = {**self.payload(1, correct=None, selected=partial), "eventId": f"partial-{self.quiz_id}", "sessionId": "replacement", "questionType": question["type"]}
                self.assertEqual(self.save(first).status_code, 200)
                self.assertIsNone(self.facts()["observations"]["0"]["first"])
                second = {**first, "eventId": f"complete-{self.quiz_id}", "sequence": 2, "selected": complete, "wasCorrect": True}
                self.assertEqual(self.save(second).status_code, 200)
                self.assertEqual(self.facts()["reviewed"], 1)
                self.assertEqual(self.evidence()[-1]["was_correct"], 1)
                self.assertFalse(self.evidence()[-1]["independent_success"])
                # A partial edit cannot leave the previous complete selection authoritative.
                self.assertEqual(self.save({**first, "eventId": f"edit-{self.quiz_id}", "sequence": 3}).status_code, 200)
                result = self.client.post("/api/study/finish", json={**first, "sequence": 3}, headers=self.headers)
                self.assertEqual(result.status_code, 400)
                # Keep the next disposable iteration's ID distinct.
                with dlms.get_db() as conn:
                    conn.execute("DELETE FROM study_sessions WHERE id = 'replacement'")

    def test_lineage_stays_distinct_and_changed_source_does_not_gain_evidence(self):
        with dlms.get_db() as conn:
            source_id = conn.execute("SELECT id FROM questions WHERE quiz_id = ?", (self.quiz_id,)).fetchone()[0]
            copied = dlms._question_payload_from_db(conn.cursor(), source_id)
        self.replace_quiz([copied], kind="adaptive_study")
        event = {**self.payload(1), "sessionId": "replacement"}
        self.assertEqual(self.save(event).status_code, 200)
        self.assertEqual(self.session["purpose"], "focused")
        self.assertEqual(len(self.evidence()), 1)
        with dlms.get_db() as conn:
            conn.execute("UPDATE questions SET question_text = 'Changed source assessment' WHERE id = ?", (source_id,))
        self.assertEqual(self.evidence(), [])
        self.assertEqual(self.facts()["reviewed"], 1)

    def test_delete_backup_failure_preserves_facts(self):
        self.save(self.payload(1))
        with mock.patch.object(dlms, "_create_dlms_backup", side_effect=OSError("test backup unavailable")):
            result = self.client.post("/api/delete_study_history", json={"confirmation": "DELETE STUDY HISTORY"}, headers=self.headers)
        self.assertGreaterEqual(result.status_code, 400)
        self.assertEqual(self.facts()["reviewed"], 1)

    def test_write_failure_rolls_back_both_fact_and_projection(self):
        with mock.patch.object(dlms, "_record_learning_event", side_effect=sqlite3.OperationalError("test disk full")):
            self.assertEqual(self.save(self.payload(1)).status_code, 500)
        self.assertIsNone(self.facts())
        self.assertEqual(self.save(self.payload(1)).status_code, 200)
        self.assertEqual(len(self.evidence()), 1)

    def test_schema_three_copy_migrates_without_inventing_sessions(self):
        path = Path(dlms.APP_DATA_DIR) / "old-copy.db"
        conn = dlms.get_db(); copied = sqlite3.connect(path); conn.backup(copied); conn.close()
        copied.executescript("DROP TABLE study_responses; DROP TABLE study_sessions; DROP TABLE study_state; DROP TABLE study_legacy_responses; UPDATE schema_meta SET version=3;")
        copied.close()
        result = dlms.bootstrap_database(str(path), require_owned_root=False)
        self.assertEqual(result["from_version"], 3)
        with sqlite3.connect(path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM study_sessions").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0], 1)

    def test_content_deletion_cascades_facts_without_touching_other_quizzes(self):
        self.save(self.payload(1))
        other, _ = self.publish(title="Unrelated content", kind=None)
        with dlms.get_db() as conn:
            conn.execute("DELETE FROM quizzes WHERE id = ?", (self.quiz_id,))
        self.assertIsNone(self.facts())
        with dlms.get_db() as conn:
            self.assertIsNotNone(conn.execute("SELECT id FROM quizzes WHERE id = ?", (other,)).fetchone())

    def test_legacy_reset_preserves_raw_facts_without_replaying_retry(self):
        legacy = {"quizId": self.quiz_id, "sessionId": "legacy-unknown", "eventId": "legacy-response", "questionOrdinal": 1, "questionType": "choice", "selected": ["C"], "wasCorrect": False}
        self.assertEqual(self.save(legacy).status_code, 200)
        restore.reset_learning_intelligence_core(dlms.DB_PATH)
        self.assertEqual(self.save(legacy).json["already_recorded"], True)
        self.assertEqual(self.evidence(), [])
        with dlms.get_db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM study_legacy_responses").fetchone()[0], 1)
        page = self.client.get("/study-history").data
        self.assertIn(b"Legacy saved responses", page)
        self.assertIn(b"incorrect response", page)

    def test_revision_ignores_lineage_assignment_but_not_answer_changes(self):
        with dlms.get_db() as conn:
            before = study.assessment_revision(conn.cursor(), self.quiz_id)
            conn.execute("UPDATE questions SET canonical_question_uid='new-lineage' WHERE quiz_id=?", (self.quiz_id,))
            self.assertEqual(study.assessment_revision(conn.cursor(), self.quiz_id), before)
            conn.execute("UPDATE choices SET text='Changed option' WHERE question_id IN (SELECT id FROM questions WHERE quiz_id=?)", (self.quiz_id,))
            self.assertNotEqual(study.assessment_revision(conn.cursor(), self.quiz_id), before)

    def test_raw_crlf_artifact_fingerprint_is_portable(self):
        import hashlib
        entry = next(e for e in dlms.load_registry() if e["id"] == self.quiz_id)
        _, name = dlms._quiz_artifact_names(entry)
        path = Path(dlms.DATA_FOLDER) / name
        raw = path.read_bytes().replace(b"\n", b"\r\n")
        path.write_bytes(raw)
        identity = "\0".join(("quiz-recovery-v1", "1", str(self.quiz_id), f"/data/{name}", str(entry.get("exam_minutes") or 90), raw.decode("utf-8")))
        request = {**self.claim_data, "sessionId": "crlf-session", "fingerprint": "sha256:" + hashlib.sha256(identity.encode()).hexdigest()}
        result = self.client.post("/api/study/session", json=request, headers=self.headers)
        self.assertEqual(result.status_code, 200, result.json)

    def test_incorrect_complete_answer_counts_as_reviewed(self):
        self.save(self.payload(1, correct=False))
        result = self.finish(1)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["session"]["reviewed"], 1)
        self.assertFalse(result.json["session"]["observations"]["0"]["first"]["correct"])

    def test_first_difficulty_reaches_real_recommendations_and_generated_lineage(self):
        source_quiz = self.quiz_id
        identical_quiz, _ = self.publish(title="Independent identical wording", kind=None)
        self.save(self.payload(1, correct=False)); self.save(self.payload(2))
        with dlms.get_db() as conn:
            candidates = dlms._adaptive_study_candidates(conn.cursor())
            source = next(c for c in candidates if c["quiz_id"] == source_quiz)
            identical = next(c for c in candidates if c["quiz_id"] == identical_quiz)
        self.assertEqual(source["score_components"]["recent_miss"], 35)
        self.assertEqual(source["recent_accuracy"], 0)
        self.assertEqual(identical["evidence"], 0)
        generated = self.client.post("/adaptive-study/generate", data={"question_count": "1"}, headers=self.headers)
        self.assertEqual(generated.status_code, 302)
        entry = next(e for e in dlms.load_registry() if generated.location.endswith(dlms._quiz_artifact_names(e)[0]))
        with dlms.get_db() as conn:
            source_uid = conn.execute("SELECT question_uid FROM questions WHERE quiz_id=?", (source_quiz,)).fetchone()[0]
            self.assertEqual(conn.execute("SELECT source_question_uid FROM questions WHERE quiz_id=?", (entry["id"],)).fetchone()[0], source_uid)
        self.quiz_id = entry["id"]
        data = {**self.claim_data, "quizId": self.quiz_id, "sessionId": "generated-review", "fingerprint": self.fingerprint(self.quiz_id)}
        self.session = self.client.post("/api/study/session", json=data, headers=self.headers).json["session"]
        for sequence, correct in ((1, False), (2, True)):
            result = self.save({**self.payload(sequence, correct=correct), "sessionId": "generated-review", "eventId": f"generated-{sequence}"})
            self.assertEqual(result.status_code, 200, result.json)
        with dlms.get_db() as conn:
            candidates = dlms._adaptive_study_candidates(conn.cursor())
            source = next(c for c in candidates if c["quiz_id"] == source_quiz)
        self.assertEqual(source["evidence"], 2)
        self.assertEqual(source["recent_accuracy"], 0)
        self.assertEqual(source["score_components"]["recent_miss"], 35)
        plan = self.client.get("/api/daily-review-plan").json
        self.assertIn("Missed within the last 14 days", json.dumps(plan))

    def test_elapsed_rule_through_saved_sessions_and_actual_schedule(self):
        start = datetime(2026, 3, 7, 17, tzinfo=timezone.utc)
        for number, seconds, streak, interval in ((1, 0, 1, 1), (2, 1, 1, 1), (3, 86399, 1, 1),
                                                   (4, 86400, 2, 3), (5, 345599, 2, 3), (6, 345600, 3, 7)):
            session_id = f"elapsed-{number}"
            response = self.client.post("/api/study/session", json={**self.claim_data, "sessionId": session_id}, headers=self.headers)
            self.assertEqual(response.status_code, 200)
            event = {**self.payload(1), "sessionId": session_id, "eventId": f"elapsed-event-{number}"}
            self.assertEqual(self.save(event).status_code, 200)
            self.assertTrue(self.save(event).json["already_recorded"])
            with dlms.get_db() as conn:
                conn.execute("UPDATE learning_events SET occurred_at=? WHERE attempt_id=?", ((start + timedelta(seconds=seconds)).isoformat(), event["eventId"]))
                schedule = dlms._native_spaced_repetition_schedule(conn.cursor(), now=start + timedelta(seconds=seconds))
            row = next(q for q in schedule["questions"] if q["quiz_id"] == self.quiz_id)
            self.assertEqual((row["correct_streak"], row["review_interval_days"]), (streak, interval))
            anchor = start + timedelta(seconds=0 if number <= 3 else 86400 if number <= 5 else 345600)
            self.assertEqual(row["next_review"], (anchor + timedelta(days=interval)).isoformat())

    def test_reset_then_restart_and_portable_restore_does_not_replay_history(self):
        self.save(self.payload(1, correct=False)); self.save(self.payload(2)); self.finish(2)
        restore.reset_learning_intelligence_core(dlms.DB_PATH)
        dlms.ensure_db_initialized()
        archive, _ = dlms._create_dlms_backup("post-reset-study")
        staged = Path(dlms.APP_DATA_DIR) / "post-reset-restore"
        dlms._extract_validated_backup(archive, staged, dlms._validate_dlms_backup(archive))
        dlms._prepare_staged_restore_database(str(staged))
        with mock.patch.object(dlms, "DB_PATH", str(staged / "results.db")):
            dlms.ensure_db_initialized()
            self.assertTrue(self.facts()["completed_at"])
            self.assertEqual(self.evidence(), [])
            with dlms.get_db() as conn:
                candidates = dlms._adaptive_study_candidates(conn.cursor())
                self.assertTrue(all(c["evidence"] == 0 and "recent_miss" not in c["score_components"] for c in candidates))
                self.assertTrue(all(q["responses"] == 0 and q["schedule_state"] == "unscheduled" for q in dlms._native_spaced_repetition_schedule(conn.cursor())["questions"]))

    def test_elapsed_rule_compares_instants_and_rejects_unknown_native_times(self):
        self.save(self.payload(1))
        event = self.evidence()[0]
        start = datetime(2026, 3, 8, 6, tzinfo=timezone.utc)
        first = {**event, "id": 10, "occurred_at": "2026-03-08T01:00:00-05:00"}
        early = {**event, "id": 11, "occurred_at": "2026-03-09T01:59:59-04:00"}
        due = {**event, "id": 12, "occurred_at": "2026-03-09T02:00:00-04:00"}
        row = learning._native_question_schedule_entry([due, early, first], now=start)
        self.assertEqual(row["correct_streak"], 2)
        self.assertEqual(row["next_review"], "2026-03-12T06:00:00+00:00")
        for unknown in ("2026-03-09", "2026-03-09T06:00:00", "2026-02-30T06:00:00Z"):
            row = learning._native_question_schedule_entry([first, {**event, "occurred_at": unknown}], now=start)
            self.assertIsNone(row["next_review"])
            self.assertIn("cannot be determined", row["schedule_reason"])

    def test_late_answer_save_does_not_move_acknowledged_navigation_back(self):
        self.replace_quiz([self.choice(), {**self.choice(), "number": 2}], kind=None)
        event = {**self.payload(1), "sessionId": "replacement"}
        response = self.client.post("/api/study/position", json={**event, "position": 1}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.save(event).status_code, 200)
        self.assertEqual(self.facts()["position"], 1)

    def test_regular_continuity_requires_response_and_resume_does_not_advance_it(self):
        def continuity():
            with dlms.get_db() as conn:
                return study.regular_continuity(conn.cursor(), dlms.load_registry(), data_folder=dlms.DATA_FOLDER,
                                                quiz_folder=dlms.QUIZ_FOLDER, artifact_names=dlms._quiz_artifact_names)
        self.assertIsNone(continuity())  # Claim/open alone has no learning progress.
        self.save(self.payload(1, correct=False))
        before = continuity()
        resumed = self.client.post("/api/study/session", json={**self.claim_data, "owner": "resume-owner", "takeover": True}, headers=self.headers)
        self.assertEqual(resumed.status_code, 200)
        self.assertEqual(continuity(), before)
        generated, _ = self.publish(title="Focused practice")
        claim = {**self.claim_data, "quizId": generated, "sessionId": "focused", "fingerprint": self.fingerprint(generated)}
        session = self.client.post("/api/study/session", json=claim, headers=self.headers).json["session"]
        result = self.save({**self.payload(1), "quizId": generated, "sessionId": "focused", "eventId": "focused-response", "assessmentRevision": session["assessment_revision"]})
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(continuity(), before)

    def test_legacy_served_notice_does_not_modify_artifact_or_invent_tracking(self):
        path = Path(dlms.QUIZ_FOLDER) / "legacy.html"
        source = '<html><body><h1>Older quiz</h1><!-- <script src="/static/script.js"></script> --></body></html>'
        path.write_text(source)
        response = self.client.get("/quizzes/legacy.html")
        self.assertIn(b'id="legacyStudyNotice"', response.data)
        self.assertIn(b'/admin/maintenance', response.data)
        self.assertEqual(path.read_text(), source)
        self.assertIsNone(self.facts())
        self.assertNotIn(b'id="legacyStudyNotice"', self.client.get("/quizzes/" + self.html).data)
        # Compatibility inspection must not break older non-UTF-8 pages.
        raw = b'<html><body><p>caf\xe9</p></body></html>'
        path.write_bytes(raw)
        served = self.client.get("/quizzes/legacy.html")
        self.assertEqual(served.status_code, 200)
        self.assertIn(b'<p>caf\xe9</p>', served.data)
        self.assertEqual(path.read_bytes(), raw)

    def test_old_portable_backup_preserves_legacy_and_exam_without_claims(self):
        legacy = {"quizId": self.quiz_id, "sessionId": "legacy-session", "eventId": "legacy-id", "questionOrdinal": 1,
                  "questionType": "choice", "selected": ["C"], "wasCorrect": False}
        self.assertEqual(self.save(legacy).status_code, 200)
        with dlms.get_db() as conn:
            conn.execute("INSERT INTO attempts(id,quiz_id,score,total,percent,mode) VALUES ('exam',?,1,1,100,'Exam')", (self.quiz_id,))
            original = tuple(conn.execute("SELECT quiz_id,question_id,attempt_id,session_id,mode,was_correct,response_json,occurred_at FROM learning_events WHERE attempt_id='legacy-id'").fetchone())
            conn.executescript("DROP TABLE study_responses; DROP TABLE study_sessions; DROP TABLE study_state; DROP TABLE study_legacy_responses; UPDATE schema_meta SET version=3;")
        archive, _ = dlms._create_dlms_backup("schema-three")
        staged = Path(dlms.APP_DATA_DIR) / "old-restore"
        dlms._extract_validated_backup(archive, staged, dlms._validate_dlms_backup(archive))
        dlms._prepare_staged_restore_database(str(staged))
        with sqlite3.connect(staged / "results.db") as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM study_sessions").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM study_responses").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT quiz_id,question_id,attempt_id,session_id,mode,was_correct,response_json,occurred_at FROM study_legacy_responses").fetchone(), original)
            self.assertEqual(conn.execute("SELECT percent FROM attempts WHERE id='exam'").fetchone()[0], 100)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0], 1)

    def test_explicit_delete_route_has_recoverable_backup_and_preserves_boundaries(self):
        self.save(self.payload(1)); self.finish(1)
        with dlms.get_db() as conn:
            conn.execute("INSERT INTO attempts(id,quiz_id,score,total,percent,mode) VALUES ('exam',?,1,1,100,'Exam')", (self.quiz_id,))
            conn.execute("INSERT INTO learning_events(event_type,quiz_id,attempt_id,mode,was_correct) VALUES ('exam_answer',?,'exam','Exam',1)", (self.quiz_id,))
        settings = Path(dlms.PORTAL_CONFIG)
        settings.write_text('{"theme":"dark","unrelated":"preserved"}')
        artifacts = {p: p.read_bytes() for folder in (dlms.QUIZ_FOLDER, dlms.DATA_FOLDER, dlms.CONFIG_FOLDER) for p in Path(folder).rglob('*') if p.is_file()}
        result = self.client.post("/api/delete_study_history", json={"confirmation": "DELETE STUDY HISTORY"}, headers=self.headers)
        self.assertEqual(result.status_code, 200, result.json)
        self.assertIsNone(self.facts())
        with dlms.get_db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT event_type FROM learning_events").fetchone()[0], 'exam_answer')
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0], 1)
        self.assertTrue(all(p.read_bytes() == content for p, content in artifacts.items()))
        archives = list(Path(dlms.BACKUP_FOLDER).glob('*.zip'))
        self.assertEqual(len(archives), 1)
        staged = Path(dlms.APP_DATA_DIR) / 'delete-recovery'
        dlms._extract_validated_backup(str(archives[0]), staged, dlms._validate_dlms_backup(str(archives[0])))
        dlms._prepare_staged_restore_database(str(staged))
        with sqlite3.connect(staged / 'results.db') as conn:
            self.assertIsNotNone(conn.execute("SELECT completed_at FROM study_sessions WHERE id='session-one'").fetchone()[0])
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM study_responses").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 1)

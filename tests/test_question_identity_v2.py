"""DLMS-092 durable question identity and lineage contract regressions."""

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms
from dlms.services.question_identity import canonical_learning_identity
from dlms.services.quiz_duplicates import build_quiz_duplicate_report
from dlms.services.quiz_composition import build_mixed_quiz_catalog
from tests.current_schema import seed_current_quiz


class QuestionIdentityV2Tests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dlms-092-v2-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        paths = {
            "APP_DATA_DIR": self.root,
            "DATA_FOLDER": self.root / "data",
            "QUIZ_FOLDER": self.root / "quizzes",
            "CONFIG_FOLDER": self.root / "config",
            "QUIZ_REGISTRY": self.root / "config" / "quizzes.json",
            "DB_PATH": self.root / "results.db",
            "QUIZ_ASSET_FOLDER": self.root / "quiz_assets",
            "LOGO_FOLDER": self.root / "static" / "logos",
        }
        for name, path in paths.items():
            patcher = mock.patch.object(dlms, name, str(path))
            patcher.start()
            self.addCleanup(patcher.stop)
            if name not in {"APP_DATA_DIR", "DB_PATH", "QUIZ_REGISTRY"}:
                path.mkdir(parents=True, exist_ok=True)
        self.assertTrue(dlms._initialize_data_root_ownership(str(self.root)))
        dlms.ensure_db_initialized()
        dlms.save_registry([])

    @staticmethod
    def _choice(text="A neutral identity question?"):
        return {
            "number": 1,
            "type": "choice",
            "question": text,
            "concepts": ["Identity"],
            "choices": [
                {"label": "A", "text": "Expected", "is_correct": True},
                {"label": "B", "text": "Alternative", "is_correct": False},
            ],
        }

    @staticmethod
    def _matching(right="First definition"):
        return {
            "number": 1,
            "type": "matching",
            "question": "Match each term.",
            "pairs": [
                {"left": "Alpha", "right": right},
                {"left": "Beta", "right": "Second definition"},
            ],
        }

    def _publish(self, title, questions, **kwargs):
        return dlms._publish_quiz(
            title,
            questions,
            filename_prefix=kwargs.pop("filename_prefix", "identity_source"),
            **kwargs,
        )[0]

    def _question_row(self, quiz_id):
        conn = dlms.get_db()
        try:
            return conn.execute(
                """
                SELECT q.*, z.generation_kind, z.source_file,
                       z.title AS quiz_title
                FROM questions q JOIN quizzes z ON z.id = q.quiz_id
                WHERE q.quiz_id = ? ORDER BY q.id LIMIT 1
                """,
                (quiz_id,),
            ).fetchone()
        finally:
            conn.close()

    def test_new_sources_are_durable_and_independent_despite_identical_text(self):
        first = self._publish("First Source", [self._choice()])
        second = self._publish(
            "Second Source", [self._choice("  A NEUTRAL identity   question? ")],
            filename_prefix="identity_second",
        )
        first_row = self._question_row(first)
        second_row = self._question_row(second)

        self.assertRegex(first_row["question_uid"], r"^[0-9a-f]{32}$")
        self.assertEqual(first_row["question_uid"], first_row["canonical_question_uid"])
        self.assertIsNone(first_row["source_question_uid"])
        self.assertEqual(0, first_row["is_generated_copy"])
        self.assertNotEqual(
            first_row["canonical_question_uid"], second_row["canonical_question_uid"]
        )

        conn = dlms.get_db()
        try:
            schedule = dlms._native_spaced_repetition_schedule(conn.cursor())
            report = build_quiz_duplicate_report(conn.cursor(), dlms.load_registry())
            composition = build_mixed_quiz_catalog(
                conn.cursor(), dlms.load_registry()
            )
        finally:
            conn.close()
        self.assertEqual(2, schedule["summary"]["eligible_questions"])
        self.assertEqual(1, report["exact_group_count"])
        self.assertEqual(1, len(composition))
        self.assertEqual(2, composition[0]["duplicate_count"])

    def test_generated_families_receive_explicit_lineage_and_attribute_events(self):
        source_quiz = self._publish("Source", [self._choice()])
        conn = dlms.get_db()
        try:
            source = conn.execute(
                "SELECT id, question_uid, canonical_question_uid FROM questions WHERE quiz_id = ?",
                (source_quiz,),
            ).fetchone()
            payload = dlms._question_payload_from_db(conn.cursor(), source["id"])
        finally:
            conn.close()

        generated = {}
        for kind in (
            "smart_review",
            "spaced_review",
            "concept_review",
            "adaptive_study",
            "mixed_quiz",
            "native_spaced_review",
        ):
            copied = dict(payload)
            copied["question"] = f"Edited generated copy for {kind}?"
            generated[kind] = self._publish(
                f"Generated {kind}",
                [copied],
                filename_prefix=f"identity_{kind}",
                generation_kind=kind,
            )

        conn = dlms.get_db()
        try:
            rows = conn.execute(
                """
                SELECT q.*, z.generation_kind, z.source_file,
                       z.title AS quiz_title
                FROM questions q JOIN quizzes z ON z.id = q.quiz_id
                WHERE z.generation_kind IS NOT NULL ORDER BY z.id
                """
            ).fetchall()
            self.assertEqual(6, len(rows))
            for row in rows:
                self.assertEqual(source["question_uid"], row["source_question_uid"])
                self.assertEqual(source["canonical_question_uid"], row["canonical_question_uid"])
                self.assertNotEqual(source["question_uid"], row["question_uid"])
                self.assertEqual(1, row["is_generated_copy"])
                self.assertEqual(
                    ("lineage", source["canonical_question_uid"]),
                    canonical_learning_identity(row),
                )

            event_row = rows[-1]
            conn.execute(
                "DELETE FROM question_concepts WHERE question_id = ?",
                (event_row["id"],),
            )
            dlms._record_learning_event(
                conn.cursor(),
                event_type="study_answer",
                quiz_id=event_row["quiz_id"],
                question_id=event_row["id"],
                session_id="lineage-session",
                mode="Study",
                was_correct=False,
            )
            conn.commit()
            schedule = dlms._native_spaced_repetition_schedule(
                conn.cursor(), now=datetime(2026, 9, 13, tzinfo=timezone.utc)
            )
            topics = dlms._learning_intelligence_topics(
                conn.cursor(), now=datetime(2026, 9, 13, tzinfo=timezone.utc)
            )
            adaptive = dlms._adaptive_study_candidates(
                conn.cursor(), now=datetime(2026, 9, 13, tzinfo=timezone.utc)
            )
            duplicate_report = build_quiz_duplicate_report(
                conn.cursor(), dlms.load_registry()
            )
            portable_catalog = dlms._portable_quiz_bundle_service.portable_quiz_export_catalog(
                conn.cursor(), dlms.load_registry()
            )
        finally:
            conn.close()
        self.assertEqual(1, schedule["summary"]["eligible_questions"])
        self.assertEqual(source["id"], schedule["questions"][0]["question_id"])
        self.assertEqual(1, schedule["questions"][0]["incorrect"])
        identity_topic = next(topic for topic in topics if topic["name"] == "Identity")
        self.assertEqual(1, identity_topic["incorrect"])
        self.assertEqual(1, identity_topic["question_count"])
        self.assertEqual(1, adaptive[0]["evidence"])
        self.assertEqual(6, duplicate_report["excluded_generated_count"])
        self.assertEqual(
            [source_quiz],
            [item["quiz_id"] for item in portable_catalog["quizzes"]],
        )

        runtime_files = list(Path(dlms.DATA_FOLDER).glob("*.json"))
        self.assertTrue(runtime_files)
        self.assertTrue(all(
            "_lineage" not in path.read_text(encoding="utf-8")
            for path in runtime_files
        ))

    def test_edits_and_deletions_do_not_rewrite_or_cascade_lineage(self):
        source_quiz = self._publish("Editable Source", [self._choice()])
        conn = dlms.get_db()
        source = conn.execute(
            "SELECT * FROM questions WHERE quiz_id = ?", (source_quiz,)
        ).fetchone()
        payload = dlms._question_payload_from_db(conn.cursor(), source["id"])
        conn.close()
        copy_quiz = self._publish(
            "Editable Copy", [payload],
            filename_prefix="identity_copy",
            generation_kind="smart_review",
        )
        surviving_copy_quiz = self._publish(
            "Sibling Copy", [payload],
            filename_prefix="identity_sibling_copy",
            generation_kind="concept_review",
        )

        conn = dlms.get_db()
        try:
            copied = conn.execute(
                "SELECT * FROM questions WHERE quiz_id = ?", (copy_quiz,)
            ).fetchone()
            conn.execute(
                "UPDATE questions SET question_text = 'Edited source wording' WHERE id = ?",
                (source["id"],),
            )
            conn.execute(
                "UPDATE questions SET question_text = 'Edited copy wording' WHERE id = ?",
                (copied["id"],),
            )
            conn.commit()
            edited_source = conn.execute(
                "SELECT * FROM questions WHERE id = ?", (source["id"],)
            ).fetchone()
            edited_copy = conn.execute(
                "SELECT * FROM questions WHERE id = ?", (copied["id"],)
            ).fetchone()
            self.assertEqual(source["canonical_question_uid"], edited_source["canonical_question_uid"])
            self.assertEqual(source["canonical_question_uid"], edited_copy["canonical_question_uid"])

            conn.execute("DELETE FROM questions WHERE id = ?", (copied["id"],))
            conn.commit()
            self.assertIsNotNone(conn.execute(
                "SELECT id FROM questions WHERE id = ?", (source["id"],)
            ).fetchone())

            sibling = conn.execute(
                "SELECT * FROM questions WHERE quiz_id = ?", (surviving_copy_quiz,)
            ).fetchone()
            dlms._record_learning_event(
                conn.cursor(), event_type="study_answer",
                quiz_id=surviving_copy_quiz, question_id=sibling["id"],
                session_id="surviving-copy", mode="Study", was_correct=True,
            )
            conn.commit()
            conn.execute("DELETE FROM questions WHERE id = ?", (source["id"],))
            conn.commit()
            surviving = conn.execute(
                "SELECT * FROM questions WHERE id = ?", (sibling["id"],)
            ).fetchone()
            self.assertIsNotNone(surviving)
            self.assertEqual(source["question_uid"], surviving["source_question_uid"])
            self.assertEqual(1, conn.execute(
                "SELECT COUNT(*) FROM learning_events WHERE question_id = ?",
                (sibling["id"],),
            ).fetchone()[0])
        finally:
            conn.close()

    def test_legacy_rows_remain_null_and_keep_text_fallback(self):
        source_quiz = seed_current_quiz(
            dlms.get_db, "Legacy Source", "legacy-source.html", [self._choice()]
        )
        copy_quiz = seed_current_quiz(
            dlms.get_db,
            "Smart Review — Legacy",
            "smart_review_legacy.html",
            [self._choice(" A NEUTRAL  IDENTITY QUESTION? ")],
        )
        conn = dlms.get_db()
        try:
            source = conn.execute(
                "SELECT * FROM questions WHERE quiz_id = ?", (source_quiz,)
            ).fetchone()
            copied = conn.execute(
                "SELECT * FROM questions WHERE quiz_id = ?", (copy_quiz,)
            ).fetchone()
            self.assertIsNone(source["question_uid"])
            self.assertIsNone(copied["canonical_question_uid"])
            dlms._record_learning_event(
                conn.cursor(), event_type="study_answer", quiz_id=copy_quiz,
                question_id=copied["id"], session_id="legacy-session",
                mode="Study", was_correct=False,
            )
            conn.commit()
            schedule = dlms._native_spaced_repetition_schedule(conn.cursor())
        finally:
            conn.close()
        self.assertEqual(1, schedule["summary"]["eligible_questions"])
        self.assertEqual(source["id"], schedule["questions"][0]["question_id"])
        self.assertEqual(1, schedule["questions"][0]["incorrect"])

    def test_matching_questions_with_generic_stems_keep_independent_lineage(self):
        first = self._publish("Matching One", [self._matching()])
        second = self._publish(
            "Matching Two", [self._matching("Different first definition")],
            filename_prefix="matching_two",
        )
        first_row = self._question_row(first)
        second_row = self._question_row(second)
        self.assertNotEqual(
            first_row["canonical_question_uid"], second_row["canonical_question_uid"]
        )
        conn = dlms.get_db()
        try:
            report = build_quiz_duplicate_report(conn.cursor(), dlms.load_registry())
        finally:
            conn.close()
        self.assertEqual(0, report["exact_group_count"])


if __name__ == "__main__":
    unittest.main()

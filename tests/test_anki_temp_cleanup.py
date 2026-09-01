import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app as dlms
from tests.csrf_test_utils import csrf_token


class AnkiTemporaryCleanupTests(unittest.TestCase):
    def _temporary_apkg(self, content=b"anki-package"):
        fd, path = tempfile.mkstemp(prefix="dlms-anki-cleanup-", suffix=".apkg")
        os.close(fd)
        Path(path).write_bytes(content)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        return path

    def test_file_exists_for_send_file_and_is_removed_on_response_close(self):
        path = self._temporary_apkg()
        with dlms.app.test_request_context("/anki/export/test"):
            response = dlms._send_temp_anki_package(path, "deck.apkg")
            self.assertTrue(os.path.exists(path))
            self.assertEqual(response.headers["Content-Disposition"], "attachment; filename=deck.apkg")
            response.close()
        self.assertFalse(os.path.exists(path))

    def test_send_file_failure_removes_generated_package(self):
        path = self._temporary_apkg()
        with dlms.app.test_request_context("/anki/export/test"):
            with mock.patch.object(dlms, "send_file", side_effect=RuntimeError("send failed")):
                with self.assertRaisesRegex(RuntimeError, "send failed"):
                    dlms._send_temp_anki_package(path, "deck.apkg")
        self.assertFalse(os.path.exists(path))

    def test_generation_failure_removes_partial_package(self):
        path = self._temporary_apkg(b"")
        fd = os.open(path, os.O_RDWR)

        def fail_after_partial_write(_package, output_path):
            Path(output_path).write_bytes(b"partial")
            raise RuntimeError("generation failed")

        with mock.patch.object(tempfile, "mkstemp", return_value=(fd, path)), \
             mock.patch.object(dlms.genanki.Package, "write_to_file", fail_after_partial_write):
            with self.assertRaisesRegex(RuntimeError, "generation failed"):
                dlms.export_quiz_to_apkg("Failure", [{"front": "Q", "back": "A"}])
        self.assertFalse(os.path.exists(path))

    def test_custom_and_quiz_routes_defer_cleanup_until_close(self):
        route_cases = [
            (
                "/anki/export/custom",
                {"deck_name": "Custom", "quiz_cards": ["quiz:1:1"]},
                mock.patch.object(dlms, "build_custom_anki_rows", return_value=[{"front": "Q", "back": "A"}]),
            ),
            (
                "/anki/export/quiz",
                {"quiz_id": "1"},
                mock.patch.object(dlms, "build_anki_rows_for_quiz", return_value=("Quiz", [{"front": "Q", "back": "A"}])),
            ),
        ]

        for route, form_data, row_patch in route_cases:
            with self.subTest(route=route):
                path = self._temporary_apkg()
                with row_patch, mock.patch.object(dlms, "export_quiz_to_apkg", return_value=path):
                    client = dlms.app.test_client()
                    form_data["csrf_token"] = csrf_token(client)
                    response = client.post(route, data=form_data, buffered=False)
                    self.assertEqual(response.status_code, 200)
                    self.assertTrue(os.path.exists(path))
                    response.close()
                self.assertFalse(os.path.exists(path))

    def test_all_apkg_routes_use_shared_cleanup_helper(self):
        source = Path(dlms.__file__).read_text(encoding="utf-8")
        self.assertEqual(source.count("apkg_path = export_quiz_to_apkg"), 6)
        self.assertEqual(source.count("return _send_temp_anki_package("), 6)

    def test_history_review_export_uses_registry_quiz_title_for_deck_and_file(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE quizzes (id INTEGER PRIMARY KEY, title TEXT);
            CREATE TABLE attempts (id TEXT PRIMARY KEY, quiz_id INTEGER);
            CREATE TABLE missed_questions (
                attempt_id TEXT, attempt_question_number INTEGER,
                question_text TEXT, choices_text TEXT, correct_text TEXT
            );
            INSERT INTO quizzes VALUES (7, 'Sample downloaded quiz');
            INSERT INTO attempts VALUES ('history-attempt', 7);
            INSERT INTO missed_questions VALUES (
                'history-attempt', 2, 'Which protocol?', 'A. HTTP\nB. DNS', 'B. DNS'
            );
        """)

        client = dlms.app.test_client()
        with mock.patch.object(dlms, "get_db", return_value=conn), \
             mock.patch.object(dlms, "_attempt_history_context", return_value=(
                 {7: {"title": "Network Fundamentals Final"}}, {}, {}
             )), \
             mock.patch.object(dlms, "export_quiz_to_apkg", return_value="/tmp/history.apkg") as export_mock, \
             mock.patch.object(dlms, "_send_temp_anki_package", side_effect=lambda path, name: {"path": path, "name": name}):
            response = client.post(
                "/export/anki",
                json={"attempt_id": "history-attempt"},
                headers={"X-CSRFToken": csrf_token(client)},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            export_mock.call_args.args[0],
            "Network Fundamentals Final - Missed Questions",
        )
        self.assertEqual(
            response.get_json()["name"],
            "Network_Fundamentals_Final_Missed_Questions.apkg",
        )
        review_script = Path(dlms.STATIC_ROOT, "review.html").read_text(encoding="utf-8")
        self.assertIn('res.headers.get("Content-Disposition")', review_script)
        self.assertIn("a.download = downloadName", review_script)
        self.assertNotIn('a.download = "missed_questions.apkg"', review_script)

    def test_anki_names_are_sanitized_with_safe_fallbacks(self):
        self.assertEqual(
            dlms.make_safe_anki_deck_name("  Course\x00Name::Review  "),
            "Course Name - Review",
        )
        self.assertEqual(dlms.make_safe_anki_deck_name("\x00\n", "DLMS Quiz"), "DLMS Quiz")
        self.assertEqual(
            dlms.make_safe_anki_download_name("Course / Review", "DLMS_Deck"),
            "Course_Review.apkg",
        )
        self.assertEqual(
            dlms.make_safe_anki_download_name("", "../"),
            "dlms_anki_deck.apkg",
        )

    def test_custom_deck_has_live_count_and_temporary_clear_control(self):
        sources = {"quiz_groups": [], "missed_cards": [], "law_groups": []}
        with mock.patch.object(dlms, "get_anki_custom_sources", return_value=sources):
            response = dlms.app.test_client().get("/anki/custom")
        html = response.get_data(as_text=True)

        self.assertIn('id="ankiSelectedCount" aria-live="polite">0 cards selected', html)
        self.assertIn('type="button" class="anki-clear-selection-button" id="ankiClearSelection" disabled', html)
        self.assertIn("Clear Selected Cards", html)
        self.assertIn('input[type="checkbox"][name$="_cards"]', html)
        self.assertIn("checkbox.checked = false", html)
        self.assertIn("ankiClearSelection.disabled = selectedCount === 0", html)


if __name__ == "__main__":
    unittest.main()

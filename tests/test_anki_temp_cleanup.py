import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app as dlms


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
                    response = dlms.app.test_client().post(route, data=form_data, buffered=False)
                    self.assertEqual(response.status_code, 200)
                    self.assertTrue(os.path.exists(path))
                    response.close()
                self.assertFalse(os.path.exists(path))

    def test_all_apkg_routes_use_shared_cleanup_helper(self):
        source = Path(dlms.__file__).read_text(encoding="utf-8")
        self.assertEqual(source.count("apkg_path = export_quiz_to_apkg"), 6)
        self.assertEqual(source.count("return _send_temp_anki_package("), 6)


if __name__ == "__main__":
    unittest.main()

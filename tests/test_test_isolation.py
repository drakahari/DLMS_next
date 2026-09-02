"""DLMS-081 aggregate-suite data isolation regressions."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests._isolation import TEST_DATA_ROOT, ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms


IMPORTED_APP_DATA_ROOT = Path(dlms.APP_DATA_DIR).resolve()
IMPORTED_MUTABLE_PATHS = {
    attribute: Path(getattr(dlms, attribute)).resolve()
    for attribute in (
        "DB_PATH",
        "UPLOAD_FOLDER",
        "DATA_FOLDER",
        "QUIZ_FOLDER",
        "CONFIG_FOLDER",
        "BACKGROUND_FOLDER",
        "CONTENT_PACK_FOLDER",
        "QUIZ_ASSET_FOLDER",
        "BACKUP_FOLDER",
        "LAW_FOLDER",
    )
}


class AggregateTestIsolationTests(unittest.TestCase):
    def test_application_mutable_paths_are_under_suite_temp_root(self):
        root = TEST_DATA_ROOT.resolve()
        self.assertEqual(root, IMPORTED_APP_DATA_ROOT)
        self.assertEqual(root, Path(os.environ["DLMS_TEST_DATA_ROOT"]).resolve())
        self.assertTrue(root.name.startswith("dlms-test-suite-"))

        for attribute, path in IMPORTED_MUTABLE_PATHS.items():
            with self.subTest(attribute=attribute, path=path):
                self.assertTrue(path == root or root in path.parents)

        # Some workflow fixtures intentionally rebind application globals for
        # their own isolated stores. They must remain temporary even when those
        # fixtures do not restore the singleton before this late-running test.
        current_root = Path(dlms.APP_DATA_DIR).resolve()
        temp_root = Path(tempfile.gettempdir()).resolve()
        self.assertTrue(temp_root in current_root.parents)
        self.assertTrue(current_root.name.startswith("dlms-"))

    def test_inherited_application_data_override_cannot_select_user_data(self):
        with tempfile.TemporaryDirectory(prefix="dlms-test-hostile-parent-") as temp:
            selected_by_caller = Path(temp) / "developer-data"
            selected_by_caller.mkdir()
            sentinel = selected_by_caller / "do-not-touch.txt"
            sentinel.write_text("preserve", encoding="utf-8")
            environment = os.environ.copy()
            environment["QUIZAPP_DATA_DIR"] = str(selected_by_caller)
            environment.pop("DLMS_TEST_DATA_ROOT", None)
            command = (
                "import tests; import app; "
                "print(app.APP_DATA_DIR); "
                "print(__import__('os').environ['DLMS_TEST_DATA_ROOT'])"
            )
            result = subprocess.run(
                [sys.executable, "-c", command],
                cwd=Path(__file__).resolve().parents[1],
                env=environment,
                text=True,
                capture_output=True,
                check=True,
            )

            selected, recorded = result.stdout.strip().splitlines()[-2:]
            self.assertEqual(Path(selected).resolve(), Path(recorded).resolve())
            self.assertNotEqual(Path(selected).resolve(), selected_by_caller.resolve())
            self.assertTrue(Path(selected).name.startswith("dlms-test-suite-"))
            self.assertEqual("preserve", sentinel.read_text(encoding="utf-8"))

    def test_every_test_app_import_establishes_isolation_first(self):
        tests_root = Path(__file__).resolve().parent
        for path in sorted(tests_root.glob("test_*.py")):
            source = path.read_text(encoding="utf-8")
            app_import = source.find("import app as dlms")
            if app_import < 0:
                continue
            isolation_call = source.find("ensure_test_data_isolation()")
            with self.subTest(path=path.name):
                self.assertGreaterEqual(isolation_call, 0)
                self.assertLess(isolation_call, app_import)


if __name__ == "__main__":
    unittest.main()

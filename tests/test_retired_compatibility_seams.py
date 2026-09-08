"""Structural coverage for retired app-level compatibility/test seams."""

import ast
import unittest
from pathlib import Path

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms


ROOT = Path(__file__).resolve().parents[1]


class RetiredCompatibilitySeamTests(unittest.TestCase):
    def test_registry_file_alias_has_no_active_python_reference(self):
        self.assertFalse(hasattr(dlms, "REGISTRY_FILE"))

        for path in self._active_python_paths():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            references = [
                node
                for node in ast.walk(tree)
                if (
                    isinstance(node, ast.Name)
                    and node.id == "REGISTRY_FILE"
                ) or (
                    isinstance(node, ast.Attribute)
                    and node.attr == "REGISTRY_FILE"
                )
            ]
            self.assertEqual([], references, str(path))

    def test_app_save_portal_config_seam_and_callers_are_absent(self):
        self.assertFalse(hasattr(dlms, "save_portal_config"))

        for path in self._active_python_paths():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            app_seam_calls = [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "save_portal_config"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in {"app", "dlms"}
            ]
            self.assertEqual([], app_seam_calls, str(path))

    @staticmethod
    def _active_python_paths():
        return [
            ROOT / "app.py",
            *(ROOT / "dlms").rglob("*.py"),
            *(ROOT / "tests").rglob("*.py"),
        ]


if __name__ == "__main__":
    unittest.main()

"""Regression coverage for Law Study's fresh and full-reset bootstrap state."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms
from tests.csrf_test_utils import csrf_token


BUILT_IN_LAW_COURSES = [
    "Torts",
    "Contracts",
    "Civil Procedure",
    "Criminal Law",
    "Property",
    "Constitutional Law",
    "Legal Writing",
]


class LawResetBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dlms-law-reset-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        config = self.root / "config"
        law = self.root / "law"
        backups = self.root / "backups"

        self.paths = {
            "APP_DATA_DIR": str(self.root),
            "UPLOAD_FOLDER": str(self.root / "uploads"),
            "DATA_FOLDER": str(self.root / "data"),
            "QUIZ_FOLDER": str(self.root / "quizzes"),
            "CONFIG_FOLDER": str(config),
            "REGISTRY_FILE": str(config / "quizzes.json"),
            "QUIZ_REGISTRY": str(config / "quizzes.json"),
            "PORTAL_CONFIG": str(config / "portal.json"),
            "DB_PATH": str(self.root / "results.db"),
            "LAW_FOLDER": str(law),
            "LAW_CASES_FOLDER": str(law / "cases"),
            "LAW_IMPORTS_FOLDER": str(law / "imports"),
            "LAW_EXPORTS_FOLDER": str(law / "exports"),
            "LAW_REGISTRY": str(config / "law.json"),
            "LOGO_FOLDER": str(self.root / "static" / "logos"),
            "LOGO_TEMP_FOLDER": str(self.root / "static" / "logos" / "_temp"),
            "BACKGROUND_FOLDER": str(self.root / "static" / "bg"),
            "CONTENT_PACK_FOLDER": str(self.root / "content_packs"),
            "QUIZ_ASSET_FOLDER": str(self.root / "quiz_assets"),
            "IMAGE_BUILDER_DRAFT_FOLDER": str(self.root / "image_builder_drafts"),
            "PDF_IMPORT_DRAFT_FOLDER": str(self.root / "pdf_import_drafts"),
            "PDF_QUESTION_BANK_FOLDER": str(self.root / "pdf_question_banks"),
            "PDF_TERMINOLOGY_BANK_FOLDER": str(self.root / "pdf_terminology_banks"),
            "CONTENT_PACK_STAGING_FOLDER": str(self.root / "content_pack_staging"),
            "BACKUP_FOLDER": str(backups),
            "BACKUP_RESTORE_STAGING_FOLDER": str(backups / "restore_staging"),
        }
        self.path_patcher = mock.patch.multiple(dlms, **self.paths)
        self.path_patcher.start()
        self.addCleanup(self.path_patcher.stop)
        dlms._initialize_data_root_ownership(str(self.root))
        dlms._ensure_runtime_data_dirs()

    def test_full_reset_clears_user_law_data_then_bootstraps_builtin_courses(self):
        registry = dlms.load_law_registry()
        self.assertEqual(BUILT_IN_LAW_COURSES, registry["folders"])
        self.assertEqual([], registry["cases"])

        registry["cases"] = [{
            "id": "user-case",
            "title": "User-created case",
            "file": "user-case.json",
            "course": "Torts",
        }]
        dlms.save_law_registry(registry)
        case_path = Path(dlms.LAW_CASES_FOLDER, "user-case.json")
        case_path.write_text(json.dumps({"id": "user-case"}), encoding="utf-8")

        client = dlms.app.test_client()
        response = client.post(
            "/api/reset_all_data",
            data={"csrf_token": csrf_token(client, "/settings")},
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual("ok", response.get_json()["status"])
        self.assertFalse(Path(dlms.LAW_REGISTRY).exists())
        self.assertFalse(case_path.exists())

        landing = client.get("/law")
        self.assertEqual(200, landing.status_code)
        self.assertIn(
            b"<strong>7</strong><small>study folders</small>", landing.data
        )
        rebuilt = dlms.load_law_registry()
        self.assertEqual([], rebuilt["cases"])
        self.assertEqual(BUILT_IN_LAW_COURSES, rebuilt["folders"])

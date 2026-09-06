"""Characterization coverage for the DLMS default AI prompt catalog."""

import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms
from dlms import prompts
from tests.csrf_test_utils import csrf_token


PROMPT_CONTRACTS = {
    "DEFAULT_AI_FEEDBACK_PROMPT": (
        402,
        "206b3d175d08d1d3a7459ad19053a4ce3721f4c2e07a4d2d45cc4581623bde00",
        ["{{questions}}"],
    ),
    "DEFAULT_LAW_AI_PROMPT": (
        2375,
        "163b8deaa245d1a920b6b1d470b10b6e1bf68ff80c53d38ccc9c2ac804ea57b1",
        ["{{case_name}}", "{{course}}", "{{study_sections}}"],
    ),
    "DEFAULT_MEDICAL_CONTENT_PACK_PROMPT": (
        9581,
        "fb3841bbfaca774c011d526c8a27f09769434bccd6ec3d32571d41ec87bfc756",
        ["{{topic}}", "{{content_request}}", "{{difficulty}}", "{{size_guidance}}"],
    ),
    "DEFAULT_STUDY_CONTENT_PACK_PROMPT": (
        13882,
        "ef7e2980a4d6543841420cbf93ae48baa8a24d8520484a53c7244c9de557cebe",
        [
            "{{domain}}",
            "{{topic}}",
            "{{content_request}}",
            "{{difficulty}}",
            "{{size_guidance}}",
            "{{image_guidance}}",
            "{{domain_slug}}",
        ],
    ),
    "DEFAULT_MEDICAL_STUDY_PACK_AI_ADDENDUM": (
        766,
        "37a50d15dde2c7c3c2d9299eaf429f38ba51ffa4c00c06b414c55f64e41a34ad",
        [],
    ),
}

SAVED_PROMPT_DEFAULTS = {
    "ai_prompt_template": "DEFAULT_AI_FEEDBACK_PROMPT",
    "law_ai_prompt_template": "DEFAULT_LAW_AI_PROMPT",
    "study_pack_ai_prompt_template": "DEFAULT_STUDY_CONTENT_PACK_PROMPT",
    "medical_study_pack_ai_addendum": "DEFAULT_MEDICAL_STUDY_PACK_AI_ADDENDUM",
}


class PromptCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dlms-prompt-catalog-")
        self.addCleanup(self.temporary.cleanup)
        self.portal_path = Path(self.temporary.name) / "config" / "portal.json"
        self.portal_path.parent.mkdir(parents=True)

    def test_prompt_text_whitespace_placeholders_and_app_exports_are_exact(self):
        for name, (expected_length, expected_digest, expected_placeholders) in PROMPT_CONTRACTS.items():
            with self.subTest(prompt=name):
                catalog_value = getattr(prompts, name)
                self.assertEqual(catalog_value, getattr(dlms, name))
                self.assertEqual(expected_length, len(catalog_value))
                self.assertEqual(
                    expected_digest,
                    hashlib.sha256(catalog_value.encode("utf-8")).hexdigest(),
                )
                self.assertEqual(
                    expected_placeholders,
                    re.findall(r"\{\{[a-z_]+\}\}", catalog_value),
                )

    def test_missing_saved_prompts_receive_exact_catalog_defaults(self):
        with mock.patch.object(dlms, "PORTAL_CONFIG", str(self.portal_path)):
            config = dlms.load_portal_config()

        persisted = json.loads(self.portal_path.read_text(encoding="utf-8"))
        for config_key, constant_name in SAVED_PROMPT_DEFAULTS.items():
            with self.subTest(config_key=config_key):
                expected = getattr(prompts, constant_name)
                self.assertEqual(expected, config[config_key])
                self.assertEqual(expected, persisted[config_key])

    def test_blank_saved_prompts_remain_blank_when_loaded(self):
        saved = {config_key: "" for config_key in SAVED_PROMPT_DEFAULTS}
        original = json.dumps(saved, indent=2)
        self.portal_path.write_text(original, encoding="utf-8")

        with mock.patch.object(dlms, "PORTAL_CONFIG", str(self.portal_path)):
            config = dlms.load_portal_config()

        for config_key in SAVED_PROMPT_DEFAULTS:
            self.assertEqual("", config[config_key])
        self.assertEqual(original, self.portal_path.read_text(encoding="utf-8"))

    def test_saved_prompt_overrides_are_preserved_exactly_when_loaded(self):
        saved = {
            config_key: f"  CUSTOM {config_key}\n{{{{questions}}}}  "
            for config_key in SAVED_PROMPT_DEFAULTS
        }
        original = json.dumps(saved, indent=2)
        self.portal_path.write_text(original, encoding="utf-8")

        with mock.patch.object(dlms, "PORTAL_CONFIG", str(self.portal_path)):
            config = dlms.load_portal_config()

        for config_key, expected in saved.items():
            self.assertEqual(expected, config[config_key])
        self.assertEqual(original, self.portal_path.read_text(encoding="utf-8"))

    def test_blank_settings_submission_preserves_existing_fallback_rules(self):
        client = dlms.app.test_client()
        with mock.patch.object(dlms, "PORTAL_CONFIG", str(self.portal_path)):
            token = csrf_token(client, "/settings/ai")
            response = client.post(
                "/settings/ai/save",
                data={
                    "csrf_token": token,
                    "ai_prompt_template": "   ",
                    "study_pack_ai_prompt_template": "   ",
                    "medical_study_pack_ai_addendum": "   ",
                    "law_ai_prompt_template": "   ",
                },
            )

        self.assertEqual(302, response.status_code)
        saved = json.loads(self.portal_path.read_text(encoding="utf-8"))
        self.assertEqual("", saved["ai_prompt_template"])
        self.assertEqual(
            prompts.DEFAULT_STUDY_CONTENT_PACK_PROMPT,
            saved["study_pack_ai_prompt_template"],
        )
        self.assertEqual(
            prompts.DEFAULT_MEDICAL_STUDY_PACK_AI_ADDENDUM,
            saved["medical_study_pack_ai_addendum"],
        )
        self.assertEqual(
            prompts.DEFAULT_LAW_AI_PROMPT,
            saved["law_ai_prompt_template"],
        )


if __name__ == "__main__":
    unittest.main()

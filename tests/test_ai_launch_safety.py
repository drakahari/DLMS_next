"""DLMS-064 regression tests for separated AI copy and launch behavior."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app as dlms
from tests.csrf_test_utils import csrf_token


class AIProviderLaunchSafetyTests(unittest.TestCase):
    def test_custom_provider_url_accepts_only_absolute_http_or_https(self):
        self.assertEqual(
            "https://example.test/provider?model=study",
            dlms._normalize_ai_provider_url("https://example.test/provider?model=study"),
        )
        self.assertEqual(
            "http://localhost:11434",
            dlms._normalize_ai_provider_url("http://localhost:11434"),
        )
        for candidate in (
            "javascript:alert(1)", "data:text/html,unsafe", "file:///tmp/provider",
            "//example.test/provider", "/relative/provider", "https:///missing-host",
        ):
            with self.subTest(candidate=candidate):
                self.assertEqual("", dlms._normalize_ai_provider_url(candidate))

    def test_invalid_legacy_custom_url_is_not_served_to_launch_clients(self):
        with tempfile.TemporaryDirectory(prefix="dlms-ai-url-config-") as directory:
            portal_config = Path(directory) / "portal.json"
            portal_config.write_text(json.dumps({
                "ai_provider": "local", "ai_custom_url": "javascript:alert(1)",
            }), encoding="utf-8")
            with mock.patch.object(dlms, "PORTAL_CONFIG", str(portal_config)):
                cfg = dlms.load_portal_config()
                response = dlms.app.test_client().get("/config/portal.json")

            self.assertEqual("", cfg["ai_custom_url"])
            self.assertEqual("", response.get_json()["ai_custom_url"])

    def test_ai_settings_reject_invalid_custom_url_without_overwriting_config(self):
        with tempfile.TemporaryDirectory(prefix="dlms-ai-url-settings-") as directory:
            portal_config = Path(directory) / "portal.json"
            original = {
                "title": "Keep existing settings",
                "ai_provider": "local",
                "ai_custom_url": "https://safe.example/provider",
            }
            portal_config.write_text(json.dumps(original), encoding="utf-8")
            with mock.patch.object(dlms, "PORTAL_CONFIG", str(portal_config)):
                client = dlms.app.test_client()
                response = client.post("/settings/ai/save", data={
                    "csrf_token": csrf_token(client, "/settings/ai"),
                    "ai_provider": "local",
                    "ai_custom_url": "javascript:alert(1)",
                }, follow_redirects=False)

            self.assertEqual(400, response.status_code)
            self.assertIn("absolute HTTP or HTTPS URL", response.get_data(as_text=True))
            self.assertEqual(original, json.loads(portal_config.read_text(encoding="utf-8")))

    def test_copy_and_launch_controls_are_explicitly_separated(self):
        app_source = Path(dlms.__file__).read_text(encoding="utf-8")
        review_source = Path(dlms.STATIC_ROOT, "review.html").read_text(encoding="utf-8")
        script_source = Path(dlms.STATIC_ROOT, "script.js").read_text(encoding="utf-8")

        self.assertNotIn("copyAndOpen(", app_source)
        self.assertNotIn("copyPromptAndOpenAi", app_source)
        self.assertNotIn("aiConfig.ai_auto_copy_prompt", review_source)
        self.assertIn("function openAIProvider(value)", review_source)
        individual_launch = review_source[
            review_source.index("window.openAIExplain"):
            review_source.index("window.explainSelectedWithAI")
        ]
        selected_launch = review_source[
            review_source.index("window.explainSelectedWithAI"):]
        self.assertNotIn("copyTextToClipboard", individual_launch)
        self.assertNotIn("copyTextToClipboard", selected_launch)
        self.assertIn("window.copyCurrentQuestionExplainPrompt", script_source)
        self.assertIn("window.reviewCurrentQuestionWithAI = async function(copyPromptOnly = false)", script_source)
        self.assertIn("if (copyPromptOnly)", script_source)
        study_launch = script_source[script_source.index("window.reviewCurrentQuestionWithAI") :]
        self.assertLess(study_launch.index("if (copyPromptOnly)"), study_launch.index("window.open("))
        self.assertIn("onclick=\"copyCurrentQuestionExplainPrompt()\"", app_source)
        self.assertIn("Open AI Provider</a>", app_source)
        self.assertIn('target="_blank" rel="noopener noreferrer"', app_source)


if __name__ == "__main__":
    unittest.main()

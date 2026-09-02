"""DLMS-038 AI Study Pack Builder prompt regression tests."""
import html
import os
import re
import tempfile
import unittest
from unittest import mock

_TEMP = tempfile.TemporaryDirectory(prefix="dlms-ai-builder-tests-")
os.environ["QUIZAPP_DATA_DIR"] = _TEMP.name
from tests._isolation import ensure_test_data_isolation
ensure_test_data_isolation()
import app as dlms
from tests.csrf_test_utils import csrf_token


class StudyPackAIBuilderTests(unittest.TestCase):
    @staticmethod
    def _prompt_from_response(response):
        page = response.get_data(as_text=True)
        match = re.search(
            r'<textarea id="studyPrompt"[^>]*>(.*?)</textarea>', page, re.DOTALL
        )
        if not match:
            raise AssertionError("Generated prompt textarea was not rendered")
        return html.unescape(match.group(1))

    def _post_builder(self, config=None, *, include_multiple_choice=False):
        client = dlms.app.test_client()
        token = csrf_token(client, "/study-packs/ai-builder")
        cfg = {
            "ai_provider": "chatgpt",
            "study_pack_ai_prompt_template": dlms.DEFAULT_STUDY_CONTENT_PACK_PROMPT,
            "medical_study_pack_ai_addendum": dlms.DEFAULT_MEDICAL_STUDY_PACK_AI_ADDENDUM,
        }
        if config:
            cfg.update(config)
        with mock.patch.object(dlms, "load_portal_config", return_value=cfg):
            data = {
                "csrf_token": token,
                "topic": "Network layers",
                "domain": "IT / Cybersecurity",
                "difficulty": "Intermediate",
                "size": "Standard",
                "image_count": "2–3",
                "image_style": "Mixed",
                "ai_provider": "chatgpt",
                "include_matching": "on",
                "include_images": "on",
            }
            if include_multiple_choice:
                data["include_multiple_choice"] = "on"
            return client.post("/study-packs/ai-builder", data=data)

    def test_generated_prompt_uses_real_newlines_without_literal_separators(self):
        response = self._post_builder()
        self.assertEqual(200, response.status_code)
        prompt = self._prompt_from_response(response)
        self.assertIn(
            "CONTENT REQUEST\n- Create one or more high-quality matching datasets",
            prompt,
        )
        self.assertIn("\n- Create image/diagram hotspot datasets", prompt)
        self.assertNotIn(r"\n- Create image/diagram hotspot datasets", prompt)

    def test_generated_prompt_contains_explicit_matching_quality_requirements(self):
        prompt = self._prompt_from_response(self._post_builder()).casefold()
        for requirement in (
            "unique terms",
            "unique record ids where ids are used",
            "one-to-one term/answer mappings",
            "meaningfully distinct answers",
            "no duplicate or near-duplicate pairs",
            "unambiguous when shuffled",
            "repair all collisions before delivery",
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, prompt)

    def test_default_prompt_requires_small_reusable_question_level_concepts(self):
        prompt = self._prompt_from_response(self._post_builder()).casefold()
        for requirement in (
            'question-level "concepts" field',
            "normally 1–3",
            "reuse identical spelling",
            "chmod",
            "octal-permissions",
            'do not use broad metadata-only values',
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, prompt)

    def test_builder_offers_single_select_mcqs_with_canonical_accuracy_requirements(self):
        page = self._post_builder(include_multiple_choice=True).get_data(as_text=True)
        prompt = self._prompt_from_response(self._post_builder(include_multiple_choice=True)).casefold()
        self.assertIn('name="include_multiple_choice"', page)
        self.assertIn("multiple-choice questions", page)
        for requirement in (
            '"type": "choice"',
            '"is_correct":true',
            "dlms assigns a–z labels",
            "do not invent factual answers",
            "omit it instead of guessing",
            "do not fabricate",
            "exactly one choice must be true",
            "concise explanation",
            "reliable source material",
            "vary the supplied correct-choice position",
            "do not force a perfectly equal distribution",
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, prompt)
        self.assertIn("source-supported single-select multiple-choice questions", prompt)

    def test_customized_prompt_template_is_used_without_being_overwritten(self):
        custom = "CUSTOM HEADER\n{{content_request}}\nCUSTOM FOOTER"
        prompt = self._prompt_from_response(self._post_builder({
            "study_pack_ai_prompt_template": custom,
        }))
        self.assertTrue(prompt.startswith("CUSTOM HEADER\n- "))
        self.assertTrue(prompt.endswith("CUSTOM FOOTER"))
        self.assertNotIn("STUDY QUALITY RULES", prompt)

    def test_generated_prompt_offers_guided_zip_return_step(self):
        page = self._post_builder().get_data(as_text=True)
        self.assertIn('aria-label="AI Study Pack workflow"', page)
        self.assertIn("Bring Back Study Pack ZIP", page)
        self.assertIn('action="/study-packs/ai-builder/import"', page)
        self.assertIn('name="pack_zip"', page)
        self.assertIn("Text-only AI responses are not installable", page)


if __name__ == "__main__":
    unittest.main()

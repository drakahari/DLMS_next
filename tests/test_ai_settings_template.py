"""Characterization coverage for the AI settings page template boundary."""

import json
import re
import unittest
from unittest import mock

from markupsafe import escape

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms


RESET_AI_PROMPT = """You are a technical tutor helping a student learn from mistakes.

For each question:
1. Explain why the correct answer is correct
2. Explain why the selected answer is incorrect
3. Give a short memory tip
4. Keep explanations concise but clear
5. Return your answer in clearly separated sections per question.

---

{{questions}}"""


class AISettingsTemplateTests(unittest.TestCase):
    def setUp(self):
        self.client = dlms.app.test_client()

    @staticmethod
    def _config(**overrides):
        config = {
            "ai_helper_enabled": False,
            "ai_provider": "chatgpt",
            "ai_custom_url": "",
            "ai_auto_copy_prompt": True,
            "ai_prompt_template": "",
            "study_pack_ai_prompt_template": dlms.DEFAULT_STUDY_CONTENT_PACK_PROMPT,
            "medical_study_pack_ai_addendum": dlms.DEFAULT_MEDICAL_STUDY_PACK_AI_ADDENDUM,
            "law_ai_prompt_template": dlms.DEFAULT_LAW_AI_PROMPT,
        }
        config.update(overrides)
        return config

    def _render(self, config, query=""):
        with mock.patch.object(dlms, "load_portal_config", return_value=config):
            response = self.client.get(f"/settings/ai{query}")
        self.assertEqual(200, response.status_code)
        return response.get_data(as_text=True)

    def test_prompt_text_placeholders_form_contract_and_selected_values_are_exact(self):
        config = self._config(
            ai_helper_enabled=True,
            ai_provider="gemini",
            ai_auto_copy_prompt=False,
            ai_prompt_template="Saved explanation {{questions}}",
            study_pack_ai_prompt_template="Saved {{domain}} / {{domain_slug}} / {{topic}} / {{content_request}} / {{difficulty}} / {{size_guidance}} / {{image_guidance}}",
            medical_study_pack_ai_addendum="Saved medical addendum",
            law_ai_prompt_template="Saved {{case_name}} / {{course}} / {{study_sections}}",
        )
        page = self._render(config)

        self.assertIn('action="/settings/ai/save" method="POST"', page)
        for field_name in (
            "ai_helper_enabled",
            "ai_auto_copy_prompt",
            "ai_provider",
            "ai_custom_url",
            "ai_prompt_template",
            "study_pack_ai_prompt_template",
            "medical_study_pack_ai_addendum",
            "law_ai_prompt_template",
        ):
            self.assertIn(f'name="{field_name}"', page)
        self.assertRegex(page, r'name="ai_helper_enabled"\s+checked')
        self.assertNotRegex(page, r'name="ai_auto_copy_prompt"\s+checked')
        self.assertIn('<option value="gemini" selected>Gemini</option>', page)
        for value in ("chatgpt", "claude", "local"):
            self.assertNotIn(f'<option value="{value}" selected>', page)
        self.assertIn('placeholder="Example: http://192.168.1.50:3000"', page)
        self.assertEqual(2, page.count('onclick="location.href=\'/settings\'"'))
        self.assertIn('<script src="/static/nav-normalize.js"></script>', page)

        textarea_values = {
            "aiPromptTemplate": config["ai_prompt_template"],
            "studyPackAIPromptTemplate": config["study_pack_ai_prompt_template"],
            "medicalStudyPackAddendum": config["medical_study_pack_ai_addendum"],
            "lawAIPromptTemplate": config["law_ai_prompt_template"],
        }
        for textarea_id, value in textarea_values.items():
            self.assertRegex(
                page,
                rf'(?s)id="{textarea_id}"[^>]*>{re.escape(value)}</textarea>',
            )

        for placeholder in (
            "{{questions}}",
            "{{domain}}",
            "{{domain_slug}}",
            "{{topic}}",
            "{{content_request}}",
            "{{difficulty}}",
            "{{size_guidance}}",
            "{{image_guidance}}",
            "{{case_name}}",
            "{{course}}",
            "{{study_sections}}",
        ):
            self.assertIn(f"<code>{placeholder}</code>", page)

        match = re.search(r"const DEFAULT_AI_PROMPT =\n`(.*?)`;", page, re.DOTALL)
        self.assertIsNotNone(match)
        self.assertEqual(
            RESET_AI_PROMPT,
            match.group(1).replace("${AI_QUESTIONS_PLACEHOLDER}", "{{questions}}"),
        )
        self.assertIn('const AI_QUESTIONS_PLACEHOLDER = "{" + "{questions}" + "}";', page)
        self.assertIn("${AI_QUESTIONS_PLACEHOLDER}", match.group(1))

    def test_saved_values_are_html_escaped_in_attributes_and_textareas(self):
        custom_url = 'https://example.test/?q="quoted"&tag=<tag>&apostrophe=\''
        prompt = 'Prompt <b>& "double" \'single\' {{questions}}\n</textarea><script>attack()</script>'
        page = self._render(
            self._config(
                ai_custom_url=custom_url,
                ai_prompt_template=prompt,
                study_pack_ai_prompt_template=prompt,
                medical_study_pack_ai_addendum=prompt,
                law_ai_prompt_template=prompt,
            )
        )

        self.assertIn(f'value="{escape(custom_url)}"', page)
        escaped_prompt = str(escape(prompt))
        for textarea_id in (
            "aiPromptTemplate",
            "studyPackAIPromptTemplate",
            "medicalStudyPackAddendum",
            "lawAIPromptTemplate",
        ):
            self.assertRegex(
                page,
                rf'(?s)id="{textarea_id}"[^>]*>{re.escape(escaped_prompt)}</textarea>',
            )
        self.assertNotIn(prompt, page)
        self.assertNotIn("</textarea><script>attack()</script>", page)

    def test_tojson_defaults_round_trip_and_neutralize_script_end_and_unicode_separators(self):
        special_defaults = {
            "study_pack_default_prompt": 'Study </script> <tag>& \'apostrophe\' "quote"\u2028line\u2029paragraph Ω',
            "medical_study_pack_default_addendum": 'Medical </script>\u2028\u2029',
            "law_default_prompt": 'Law </script>\u2029\u2028',
        }
        patches = (
            mock.patch.object(dlms, "DEFAULT_STUDY_CONTENT_PACK_PROMPT", special_defaults["study_pack_default_prompt"]),
            mock.patch.object(dlms, "DEFAULT_MEDICAL_STUDY_PACK_AI_ADDENDUM", special_defaults["medical_study_pack_default_addendum"]),
            mock.patch.object(dlms, "DEFAULT_LAW_AI_PROMPT", special_defaults["law_default_prompt"]),
            mock.patch.object(dlms, "load_portal_config", return_value=self._config()),
        )
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

        response = self.client.get("/settings/ai")
        self.assertEqual(200, response.status_code)
        page = response.get_data(as_text=True)
        assignments = {
            "study_pack_default_prompt": "DEFAULT_STUDY_PACK_AI_PROMPT",
            "medical_study_pack_default_addendum": "DEFAULT_MEDICAL_STUDY_PACK_ADDENDUM",
            "law_default_prompt": "DEFAULT_LAW_AI_PROMPT",
        }
        for context_name, javascript_name in assignments.items():
            match = re.search(
                rf"const {javascript_name} = (.*);",
                page,
            )
            self.assertIsNotNone(match)
            serialized = match.group(1)
            self.assertEqual(special_defaults[context_name], json.loads(serialized))
            self.assertNotIn("</script>", serialized.lower())
            self.assertIn(r"\u003c/script\u003e", serialized)
            self.assertNotIn("\u2028", serialized)
            self.assertNotIn("\u2029", serialized)
            if "\u2028" in special_defaults[context_name]:
                self.assertIn(r"\u2028", serialized)
            if "\u2029" in special_defaults[context_name]:
                self.assertIn(r"\u2029", serialized)

        self.assertIn(r"\u003e", page)
        self.assertIn(r"\u0026", page)
        self.assertIn(r"\u0027", page)

    def test_reset_buttons_restore_the_matching_defaults_and_focus_each_field(self):
        page = self._render(self._config())
        contracts = (
            ("resetAIPromptBtn", "aiPromptTemplate", "DEFAULT_AI_PROMPT"),
            ("resetStudyPackPromptBtn", "studyPackAIPromptTemplate", "DEFAULT_STUDY_PACK_AI_PROMPT"),
            ("resetMedicalStudyPackPromptBtn", "medicalStudyPackAddendum", "DEFAULT_MEDICAL_STUDY_PACK_ADDENDUM"),
            ("resetLawPromptBtn", "lawAIPromptTemplate", "DEFAULT_LAW_AI_PROMPT"),
        )
        for button, field, default in contracts:
            self.assertIn(f'const {button} = document.getElementById("{button}");', page)
            self.assertIn(f'const {field} = document.getElementById("{field}");', page)
            self.assertIn(
                f'''if ({button} && {field}) {{
    {button}.addEventListener("click", () => {{
        {field}.value = {default};
        {field}.focus();
    }});
}}''',
                page,
            )

    def test_saved_banner_depends_on_the_current_request_query(self):
        config = self._config()
        message = "✓ AI integration settings saved."
        self.assertNotIn(message, self._render(config))
        self.assertNotIn(message, self._render(config, "?saved=0"))
        self.assertNotIn(message, self._render(config, "?saved=true"))
        self.assertIn(message, self._render(config, "?saved=1"))


if __name__ == "__main__":
    unittest.main()

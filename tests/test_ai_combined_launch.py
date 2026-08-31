"""Focused regression coverage for combined AI prompt copy-and-launch actions."""
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def source_block(source, start, end):
    start_index = source.index(start)
    end_index = source.index(end, start_index)
    return source[start_index:end_index]


class AICombinedLaunchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.review_source = (ROOT / "static" / "review.html").read_text(encoding="utf-8")
        cls.study_source = (ROOT / "static" / "script.js").read_text(encoding="utf-8")
        cls.app_source = (ROOT / "app.py").read_text(encoding="utf-8")

    def test_history_single_combined_action_copies_synchronously_before_open(self):
        block = source_block(
            self.review_source,
            "window.openAIExplain = function",
            "window.explainSelectedWithAI = function",
        )
        self.assertIn("if (aiConfig.ai_auto_copy_prompt)", block)
        self.assertIn("copyTextToClipboardSynchronously(prompt)", block)
        self.assertIn('btn.innerText = "✅ Prompt Copied"', block)
        self.assertNotIn("navigator.clipboard.writeText", block)
        self.assertNotIn("await ", block)
        self.assertLess(
            block.index("copyTextToClipboardSynchronously(prompt)"),
            block.index('window.open(url, "_blank", "noopener,noreferrer")'),
        )

    def test_history_bulk_combined_action_uses_same_synchronous_sequence(self):
        block = source_block(
            self.review_source,
            "window.explainSelectedWithAI = function",
            "/* =====================================================\n   ANKI + UTIL FUNCTIONS",
        )
        self.assertIn("if (aiConfig.ai_auto_copy_prompt)", block)
        self.assertIn("copyTextToClipboardSynchronously(prompt)", block)
        self.assertNotIn("navigator.clipboard.writeText", block)
        self.assertNotIn("await ", block)
        self.assertLess(
            block.index("copyTextToClipboardSynchronously(prompt)"),
            block.index('window.open(url, "_blank", "noopener,noreferrer")'),
        )

    def test_history_explicit_copy_control_keeps_async_clipboard_helper(self):
        helper = source_block(
            self.review_source,
            "async function copyTextToClipboard(text)",
            "function copyTextToClipboardSynchronously(text)",
        )
        explicit_copy = source_block(
            self.review_source,
            "window.copyAIExplainPrompt = async function",
            "window.openAIExplain = function",
        )
        self.assertIn("await navigator.clipboard.writeText(text)", helper)
        self.assertIn("await copyTextToClipboard(prompt)", explicit_copy)
        self.assertIn("📋 Copy Explain Prompt", self.review_source)

    def test_combined_copy_helpers_use_textarea_selection_and_exec_command(self):
        history_helper = source_block(
            self.review_source,
            "function copyTextToClipboardSynchronously(text)",
            "/* =====================================================\n   LOAD REVIEW DATA",
        )
        study_helper = source_block(
            self.study_source,
            "function copyStudyAIPromptSynchronously(text)",
            "window.reviewCurrentQuestionWithAI = function",
        )
        for helper in (history_helper, study_helper):
            with self.subTest(helper=helper.splitlines()[0]):
                self.assertIn('document.createElement("textarea")', helper)
                self.assertIn("textarea.focus()", helper)
                self.assertIn("textarea.select()", helper)
                self.assertIn('document.execCommand("copy")', helper)

    def test_study_mode_preloads_config_and_combined_action_stays_synchronous(self):
        block = self.study_source[
            self.study_source.index("window.reviewCurrentQuestionWithAI = function"):
        ]
        self.assertIn("loadStudyAIConfig();", self.study_source)
        self.assertIn("const aiConfig = studyAIConfig", block)
        self.assertIn("copyStudyAIPromptSynchronously(finalPrompt)", block)
        self.assertNotIn("navigator.clipboard.writeText", block)
        self.assertNotIn("await ", block)
        self.assertNotIn('fetch("/config/portal.json"', block)
        self.assertLess(
            block.index("copyStudyAIPromptSynchronously(finalPrompt)"),
            block.index('window.open(url, "_blank", "noopener,noreferrer")'),
        )

    def test_study_pack_builder_combined_action_is_unchanged(self):
        self.assertIn(
            "function copyAndOpen(u){copyPrompt(false);window.open(u,'_blank','noopener,noreferrer')}",
            self.app_source,
        )
        self.assertIn("Copy Prompt &amp; Open AI", self.app_source)
        self.assertNotIn("window.open(prompt", self.review_source)
        self.assertNotIn("window.open(finalPrompt", self.study_source)


if __name__ == "__main__":
    unittest.main()

import json
import os
import re
import tempfile
import unittest
from unittest import mock

import app as dlms
from tests.csrf_test_utils import csrf_headers


class ThemeSystemTests(unittest.TestCase):
    @staticmethod
    def _style_css():
        path = os.path.join(os.path.dirname(dlms.__file__), "static", "style.css")
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    @staticmethod
    def _css_variables(css):
        return dict(re.findall(r"--([\w-]+):\s*([^;]+);", css))

    @staticmethod
    def _rgba(value):
        value = value.strip()
        if value.startswith("#"):
            raw = value[1:]
            if len(raw) == 3:
                raw = "".join(x * 2 for x in raw)
            return tuple(int(raw[i:i + 2], 16) / 255 for i in (0, 2, 4)) + (1.0,)
        match = re.fullmatch(r"rgba?\(([^)]+)\)", value)
        if not match:
            raise AssertionError(f"Unsupported test color: {value}")
        parts = [float(x.strip()) for x in match.group(1).split(",")]
        alpha = parts[3] if len(parts) == 4 else 1.0
        return tuple(x / 255 for x in parts[:3]) + (alpha,)

    @classmethod
    def _composite(cls, foreground, background):
        fg = cls._rgba(foreground)
        bg = cls._rgba(background)[:3] if isinstance(background, str) else background
        return tuple(fg[i] * fg[3] + bg[i] * (1 - fg[3]) for i in range(3))

    @staticmethod
    def _luminance(rgb):
        linear = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in rgb]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    @classmethod
    def _contrast(cls, foreground, background_rgb):
        fg_rgb = cls._rgba(foreground)[:3]
        first, second = cls._luminance(fg_rgb), cls._luminance(background_rgb)
        return (max(first, second) + 0.05) / (min(first, second) + 0.05)

    def test_portal_config_default_theme_is_dark(self):
        with tempfile.TemporaryDirectory() as td:
            portal = os.path.join(td, "config", "portal.json")
            with mock.patch.object(dlms, "PORTAL_CONFIG", portal):
                cfg = dlms.load_portal_config()
            self.assertEqual(cfg["theme"], "dark")

    def test_dynamic_css_contains_theme_variables(self):
        client = dlms.app.test_client()
        response = client.get("/dynamic.css")
        self.assertEqual(response.status_code, 200)
        css = response.get_data(as_text=True)
        self.assertIn("--theme-page-text", css)
        self.assertIn("--theme-accent", css)
        self.assertIn("--theme-accent-text", css)
        self.assertIn("--theme-color-scheme", css)

    def test_theme_api_rejects_unknown_theme(self):
        client = dlms.app.test_client()
        response = client.post("/api/theme", json={"theme": "neon-rainbow"}, headers=csrf_headers(client))
        self.assertEqual(response.status_code, 400)

    def test_theme_api_accepts_supported_theme(self):
        client = dlms.app.test_client()
        with tempfile.TemporaryDirectory() as td:
            portal = os.path.join(td, "portal.json")
            with mock.patch.object(dlms, "PORTAL_CONFIG", portal):
                with mock.patch.object(dlms, "load_portal_config", return_value={"title": "DLMS", "theme": "dark"}):
                    response = client.post("/api/theme", json={"theme": "purple-gold"}, headers=csrf_headers(client))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json()["theme"], "purple-gold")
                with open(portal, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                self.assertEqual(saved["theme"], "purple-gold")

    def test_theme_api_accepts_maroon_gold_theme(self):
        client = dlms.app.test_client()
        with tempfile.TemporaryDirectory() as td:
            portal = os.path.join(td, "portal.json")
            with mock.patch.object(dlms, "PORTAL_CONFIG", portal):
                with mock.patch.object(dlms, "load_portal_config", return_value={"title": "DLMS", "theme": "dark"}):
                    response = client.post("/api/theme", json={"theme": "maroon-gold"}, headers=csrf_headers(client))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json()["theme"], "maroon-gold")
                with open(portal, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                self.assertEqual(saved["theme"], "maroon-gold")

    def test_maroon_gold_dynamic_css_uses_umn_palette(self):
        client = dlms.app.test_client()
        with mock.patch.object(dlms, "load_portal_config", return_value={"title": "DLMS", "theme": "maroon-gold", "background_image": None}):
            response = client.get("/dynamic.css")
        self.assertEqual(response.status_code, 200)
        css = response.get_data(as_text=True).lower()
        self.assertIn("--theme-accent: #ffcc33", css)
        self.assertIn("--theme-accent-2: #ffb71e", css)
        self.assertIn("--theme-link: #ffde7a", css)
        self.assertIn("--theme-sidebar-1: rgba(91,0,19,.98)", css)
        self.assertIn("--theme-panel-1: rgba(31,32,36,.95)", css)
        self.assertIn("--theme-body-base: #0d0e10", css)

    def test_live_color_scheme_marks_only_light_palette_as_light(self):
        client = dlms.app.test_client()
        expected = {
            "light": "light",
            "dark": "dark",
            "purple-gold": "dark",
            "maroon-gold": "dark",
        }
        for theme, scheme in expected.items():
            with self.subTest(theme=theme):
                with mock.patch.object(dlms, "load_portal_config", return_value={
                    "title": "DLMS", "theme": theme, "background_image": None,
                }):
                    css = client.get("/dynamic.css").get_data(as_text=True)
                self.assertIn(f"--theme-color-scheme: {scheme}", css)

    def test_light_readability_colors_preserve_dark_component_colors(self):
        css = self._style_css()
        expected_rules = {
            ".history-table-review": "color: light-dark(#285d8f, #dcecff) !important",
            ".analytics-review-button": "color: light-dark(#285d8f, #a9d4ff) !important",
            ".analytics-history-link": "color: light-dark(#285d8f, #9fd0ff) !important",
            ".analytics-score-pill.good": "color: light-dark(#16784f, #7ee5ab) !important",
            ".analytics-score-pill.warn": "color: light-dark(#8a6300, #ffd37a) !important",
            ".analytics-score-pill.bad": "color: light-dark(#b93d52, #ff9eaa) !important",
            ".history-score-badge.good": "color: light-dark(#16784f, #86e8bb) !important",
            ".history-score-badge.warn": "color: light-dark(#8a6300, #edd681) !important",
            ".history-score-badge.bad": "color: light-dark(#b93d52, #ff9da3) !important",
            ".analytics-trend.good": "color:light-dark(#19764e, #7ee5ab) !important",
            ".analytics-trend.bad": "color:light-dark(#c43d52, #ff9eaa) !important",
            ".li-weak-score": "color: light-dark(#b5374d, #ff9ca7) !important",
            ".li-status-weak": "color:#ff9ba6",
        }
        for selector, declaration in expected_rules.items():
            with self.subTest(selector=selector):
                blocks = [
                    body for prelude, body in re.findall(r"([^{}]+)\{([^}]*)\}", css)
                    if selector in {item.strip() for item in prelude.split(",")}
                ]
                self.assertTrue(blocks, f"Missing CSS rule for {selector}")
                self.assertTrue(
                    any(declaration in block for block in blocks),
                    f"{selector} must select its accessible dark color through light-dark()",
                )

    def test_every_palette_accent_text_meets_normal_text_contrast(self):
        client = dlms.app.test_client()
        expected = {
            "dark": "#78bfff",
            "light": "#075f9f",
            "purple-gold": "#ffd85a",
            "maroon-gold": "#ffde7a",
        }
        for theme, expected_color in expected.items():
            with self.subTest(theme=theme):
                with mock.patch.object(dlms, "load_portal_config", return_value={
                    "title": "DLMS", "theme": theme, "background_image": None,
                }):
                    css = client.get("/dynamic.css").get_data(as_text=True).lower()
                variables = self._css_variables(css)
                self.assertEqual(variables.get("theme-accent-text"), expected_color)
                for surface_name in ("theme-panel-1", "theme-surface"):
                    surface = self._composite(
                        variables[surface_name], variables["theme-body-base"]
                    )
                    ratio = self._contrast(expected_color, surface)
                    self.assertGreaterEqual(
                        ratio, 4.5,
                        f"{theme} accent text is only {ratio:.2f}:1 on {surface_name}",
                    )

    def test_ai_builder_prompt_and_status_pill_use_semantic_theme_tokens(self):
        css = self._style_css()
        pill_blocks = re.findall(
            r"\.medical-ai-builder-page \.medical-ai-safety-pill\s*\{([^}]*)\}", css
        )
        self.assertTrue(pill_blocks)
        pill = pill_blocks[-1]
        self.assertIn("var(--theme-page-text", pill)
        self.assertIn("var(--theme-surface-2", pill)
        self.assertIn("var(--theme-border-soft", pill)
        self.assertNotIn(':root[style*="--theme-color-scheme: light"] .medical-ai-builder-page .medical-ai-safety-pill', css)

        prompt = re.search(r"\.medical-ai-prompt-box\s*\{([^}]*)\}", css).group(1)
        for token in ("--theme-input-bg", "--theme-input-text", "--theme-border-soft"):
            self.assertIn(token, prompt)
        self.assertIn("white-space: pre-wrap", prompt)
        self.assertIn("overflow-wrap: anywhere", prompt)

        panel = re.search(
            r"\.medical-ai-builder-page \.medical-ai-prompt-panel\s*\{([^}]*)\}", css
        ).group(1)
        self.assertIn("padding: var(--dlms-space-xl)", panel)
        pill_spacing = re.search(
            r"\.medical-ai-prompt-panel \.medical-ai-safety-pill\s*\{([^}]*)\}", css
        ).group(1)
        self.assertIn("margin-top: var(--dlms-space-xs)", pill_spacing)
        self.assertIn("margin-right: var(--dlms-space-xs)", pill_spacing)

    def test_ai_builder_status_pill_contrast_across_palettes(self):
        client = dlms.app.test_client()
        for theme in ("dark", "light", "purple-gold", "maroon-gold"):
            with self.subTest(theme=theme):
                with mock.patch.object(dlms, "load_portal_config", return_value={
                    "title": "DLMS", "theme": theme, "background_image": None,
                }):
                    css = client.get("/dynamic.css").get_data(as_text=True).lower()
                variables = self._css_variables(css)
                body = self._rgba(variables["theme-body-base"])[:3]
                panel = self._composite(variables["theme-panel-1"], body)
                pill_background = self._composite(variables["theme-surface-2"], panel)
                ratio = self._contrast(variables["theme-page-text"], pill_background)
                self.assertGreaterEqual(
                    ratio, 4.5, f"{theme} AI Builder pill contrast is only {ratio:.2f}:1",
                )

    def test_pack_validation_readability_rules_use_semantic_tokens(self):
        css = self._style_css()
        expected = {
            ".pack-validation-check > strong": "--theme-heading",
            ".pack-validation-check > span:last-child": "--theme-muted-text",
            ".pack-validation-summary-grid > div": "--theme-surface",
            ".pack-validation-summary-grid span": "--theme-muted-text",
            ".pack-validation-summary-grid strong": "--theme-heading",
        }
        for selector, token in expected.items():
            with self.subTest(selector=selector):
                blocks = [
                    body for prelude, body in re.findall(r"([^{}]+)\{([^}]*)\}", css)
                    if selector in {item.strip() for item in prelude.split(",")}
                ]
                self.assertTrue(blocks, f"Missing CSS rule for {selector}")
                self.assertTrue(any(token in block for block in blocks))

    def test_review_small_text_uses_accessible_accent_foreground_token(self):
        css = self._style_css()
        match = re.search(
            r"\.review-attempt-label,\s*\.review-question-kicker\s*\{([^}]*)\}",
            css,
        )
        self.assertIsNotNone(match)
        rule = match.group(1)
        self.assertIn("color: var(--theme-accent-text, #78bfff) !important", rule)
        self.assertNotIn("var(--theme-accent-3", rule)
        self.assertNotIn("var(--theme-accent,", rule)

    def test_anki_preview_uses_semantic_theme_colors(self):
        css = self._style_css()
        expected = {
            ".anki-count-pill": (
                "var(--theme-accent-text", "var(--theme-surface-2", "var(--theme-border-soft",
            ),
            ".anki-preview-card": (
                "var(--theme-page-text", "var(--theme-surface", "var(--theme-border-soft",
            ),
            ".anki-preview-number": (
                "var(--theme-accent-text", "var(--theme-surface-2", "var(--theme-border-soft",
            ),
            ".anki-card-side": ("var(--theme-page-text",),
            ".anki-card-side + .anki-card-side": ("var(--theme-border-soft",),
            ".anki-card-side > span": ("var(--theme-accent-text",),
            ".anki-card-side pre": ("var(--theme-page-text",),
            ".anki-card-back": ("var(--theme-surface-2",),
            ".anki-preview-more": ("var(--theme-muted-text", "var(--theme-surface"),
        }
        forbidden = {
            "#9bd4ff", "#7fbef4", "#6ebdff", "#e8f1fc", "#9fb2c8",
            "rgba(25, 99, 177, 0.14)", "rgba(3, 13, 29, 0.58)",
            "rgba(17, 54, 96, 0.22)", "rgba(13, 49, 82, 0.16)",
            "rgba(2, 11, 25, 0.46)",
        }
        for selector, tokens in expected.items():
            with self.subTest(selector=selector):
                blocks = [
                    body for prelude, body in re.findall(r"([^{}]+)\{([^}]*)\}", css)
                    if selector in {item.strip() for item in prelude.split(",")}
                ]
                self.assertTrue(blocks, f"Missing shared preview selector {selector}")
                semantic_block = next((body for body in blocks if all(x in body for x in tokens)), None)
                self.assertIsNotNone(semantic_block, f"{selector} must use {tokens}")
                self.assertFalse(any(color in semantic_block for color in forbidden))

    def test_anki_preview_text_contrast_across_palettes(self):
        client = dlms.app.test_client()
        for theme in ("dark", "light", "purple-gold", "maroon-gold"):
            with self.subTest(theme=theme):
                with mock.patch.object(dlms, "load_portal_config", return_value={
                    "title": "DLMS", "theme": theme, "background_image": None,
                }):
                    css = client.get("/dynamic.css").get_data(as_text=True).lower()
                variables = self._css_variables(css)
                body = self._rgba(variables["theme-body-base"])[:3]
                panel = self._composite(variables["theme-panel-1"], body)
                card = self._composite(variables["theme-surface"], panel)
                card_secondary = self._composite(variables["theme-surface-2"], card)
                panel_secondary = self._composite(variables["theme-surface-2"], panel)
                more = self._composite(variables["theme-surface"], panel)
                combinations = {
                    "card text": (variables["theme-page-text"], card),
                    "back text": (variables["theme-page-text"], card_secondary),
                    "card labels": (variables["theme-accent-text"], card),
                    "secondary labels": (variables["theme-accent-text"], card_secondary),
                    "count pill": (variables["theme-accent-text"], panel_secondary),
                    "preview note": (variables["theme-muted-text"], more),
                }
                for role, (foreground, background) in combinations.items():
                    ratio = self._contrast(foreground, background)
                    self.assertGreaterEqual(
                        ratio, 4.5, f"{theme} {role} is only {ratio:.2f}:1",
                    )

    def test_shared_anki_preview_classes_are_used_by_all_three_workflows(self):
        with open(dlms.__file__, "r", encoding="utf-8") as f:
            source = f.read()
        self.assertGreaterEqual(source.count('class="anki-preview-card"'), 3)
        self.assertGreaterEqual(source.count('class="anki-preview-number"'), 3)
        self.assertGreaterEqual(source.count('class="anki-card-side"'), 3)
        self.assertIn('@app.route("/anki")', source)
        self.assertIn('@app.route("/anki/custom"', source)
        self.assertIn('@app.route("/anki/law")', source)

    def test_custom_anki_theme_colors_are_class_based_not_inline(self):
        with open(dlms.__file__, "r", encoding="utf-8") as f:
            source = f.read()
        custom = source[source.index('@app.route("/anki/custom"'):source.index('@app.route("/anki/export/custom"')]
        for old_color in (
            "color:#eaf3ff", "background:rgba(3,13,30,.78)",
            "border:1px solid rgba(91,146,215,.42)",
            "border:1px solid rgba(90,147,215,.20)",
            "background:rgba(3,13,29,.42)",
            "border-top:1px solid rgba(90,147,215,.10)", "color:#8fa7c1",
        ):
            self.assertNotIn(old_color, custom)
        self.assertIn('class="anki-custom-deck-name"', custom)
        self.assertGreaterEqual(custom.count('class="anki-custom-selection-group"'), 3)
        self.assertGreaterEqual(custom.count('class="anki-custom-selection-summary"'), 3)
        self.assertGreaterEqual(custom.count('class="anki-custom-selection-row"'), 3)
        self.assertIn('class="anki-custom-selection-meta"', custom)

    def test_custom_anki_theme_classes_use_tokens_without_important(self):
        css = self._style_css()
        expected = {
            ".anki-custom-deck-name": ("--theme-input-text", "--theme-input-bg", "--theme-border-soft"),
            ".anki-custom-selection-group": ("--theme-page-text", "--theme-surface", "--theme-border-soft"),
            ".anki-custom-selection-summary": ("--theme-heading",),
            ".anki-custom-selection-row": ("--theme-page-text", "--theme-border-soft"),
            ".anki-custom-selection-meta": ("--theme-muted-text",),
        }
        for selector, tokens in expected.items():
            with self.subTest(selector=selector):
                match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
                self.assertIsNotNone(match)
                rule = match.group(1)
                self.assertTrue(all(token in rule for token in tokens))
                self.assertNotIn("!important", rule)
        self.assertNotIn("#customAnkiForm details", css)

    def test_custom_anki_semantic_text_contrast_across_palettes(self):
        client = dlms.app.test_client()
        for theme in ("dark", "light", "purple-gold", "maroon-gold"):
            with self.subTest(theme=theme):
                with mock.patch.object(dlms, "load_portal_config", return_value={
                    "title": "DLMS", "theme": theme, "background_image": None,
                }):
                    css = client.get("/dynamic.css").get_data(as_text=True).lower()
                variables = self._css_variables(css)
                body = self._rgba(variables["theme-body-base"])[:3]
                panel = self._composite(variables["theme-panel-1"], body)
                surface = self._composite(variables["theme-surface"], panel)
                combinations = {
                    "selection text": (variables["theme-page-text"], surface),
                    "selection heading": (variables["theme-heading"], surface),
                    "selection helper": (variables["theme-muted-text"], surface),
                    "input text": (
                        variables["theme-input-text"],
                        self._composite(variables["theme-input-bg"], panel),
                    ),
                }
                for role, (foreground, background) in combinations.items():
                    ratio = self._contrast(foreground, background)
                    self.assertGreaterEqual(
                        ratio, 4.5, f"{theme} {role} is only {ratio:.2f}:1",
                    )


if __name__ == "__main__":
    unittest.main()

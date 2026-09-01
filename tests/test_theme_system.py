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
    def _help_css():
        path = os.path.join(os.path.dirname(dlms.__file__), "static", "help-docs.css")
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    @staticmethod
    def _rule_blocks(css, selector):
        return [
            body for prelude, body in re.findall(r"([^{}]+)\{([^}]*)\}", css)
            if selector in {item.strip() for item in prelude.split(",")}
        ]

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

    def test_help_components_use_shared_semantic_theme_tokens(self):
        css = self._help_css()
        expected = {
            ".help-panel": (
                "--theme-panel-1", "--theme-panel-2", "--theme-border",
                "--theme-page-text",
            ),
            ".help-panel p": ("--theme-muted-text",),
            ".help-card": (
                "--theme-surface", "--theme-border-soft", "--theme-page-text",
            ),
            ".help-card p": ("--theme-muted-text",),
            ".help-steps > div": ("--theme-muted-text",),
            ".help-shot": ("--theme-surface-2", "--theme-border-soft"),
            ".help-shot figcaption": (
                "--theme-surface", "--theme-muted-text", "--theme-border-soft",
            ),
            ".help-toc": (
                "--theme-surface", "--theme-page-text", "--theme-border-soft",
            ),
            ".help-toc a": ("--theme-muted-text",),
            ".help-topic-nav a": (
                "--theme-surface", "--theme-link", "--theme-border-soft",
            ),
            ".help-index-card": (
                "--theme-panel-1", "--theme-panel-2", "--theme-page-text",
            ),
            ".help-lightbox-dialog": (
                "--theme-surface-2", "--theme-border", "--theme-shadow",
            ),
            ".help-lightbox-caption": (
                "--theme-surface", "--theme-muted-text", "--theme-border-soft",
            ),
        }
        for selector, tokens in expected.items():
            with self.subTest(selector=selector):
                blocks = self._rule_blocks(css, selector)
                self.assertTrue(blocks, f"Missing Help CSS rule for {selector}")
                self.assertTrue(
                    any(all(token in block for token in tokens) for block in blocks),
                    f"{selector} must resolve through semantic theme tokens {tokens}",
                )

    def test_help_step_markup_variants_share_theme_aware_styling(self):
        css = self._help_css()
        step = self._rule_blocks(css, ".help-steps > div")
        self.assertTrue(step)
        self.assertTrue(any("counter-increment: helpstep" in block for block in step))
        self.assertTrue(any("position: relative" in block for block in step))
        self.assertTrue(any("display: block" in block for block in step))
        self.assertTrue(any("min-width: 0" in block for block in step))
        self.assertTrue(any("padding-left: 42px" in block for block in step))
        self.assertTrue(any("overflow-wrap: break-word" in block for block in step))
        self.assertTrue(any("word-break: normal" in block for block in step))
        self.assertFalse(any("grid-template-columns" in block for block in step))
        self.assertTrue(any("--theme-muted-text" in block for block in step))

        marker = self._rule_blocks(css, ".help-steps > div::before")
        self.assertTrue(marker)
        self.assertTrue(any("position: absolute" in block for block in marker))
        self.assertTrue(any("--theme-accent" in block for block in marker))
        self.assertTrue(any("--theme-body-base" in block for block in marker))

    def test_help_navigation_and_focus_states_are_theme_aware(self):
        css = self._help_css()
        toc_state = self._rule_blocks(css, ".help-toc a.active")
        self.assertTrue(toc_state)
        self.assertTrue(any("--theme-heading" in block for block in toc_state))
        self.assertTrue(any("--theme-accent" in block for block in toc_state))
        self.assertTrue(any("--theme-surface-2" in block for block in toc_state))

        visited = self._rule_blocks(css, ".help-doc a:visited")
        self.assertTrue(any("--theme-link" in block for block in visited))

        focus = self._rule_blocks(css, ".help-doc a:focus-visible")
        self.assertTrue(focus)
        self.assertTrue(any("outline: 3px solid var(--theme-accent-text" in block for block in focus))
        self.assertTrue(any("outline-offset: 3px" in block for block in focus))

    def test_help_text_contrast_across_all_four_palettes(self):
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
                surface_2 = self._composite(variables["theme-surface-2"], panel)
                accent = self._rgba(variables["theme-accent"])[:3]
                combinations = {
                    "panel body": (variables["theme-muted-text"], panel),
                    "nested card body": (variables["theme-muted-text"], surface),
                    "panel heading": (variables["theme-heading"], panel),
                    "nested card text": (variables["theme-page-text"], surface),
                    "topic link": (variables["theme-link"], surface),
                    "path text": (variables["theme-accent-text"], surface_2),
                    "step marker": (variables["theme-body-base"], accent),
                }
                for role, (foreground, background) in combinations.items():
                    ratio = self._contrast(foreground, background)
                    self.assertGreaterEqual(
                        ratio, 4.5, f"{theme} Help {role} is only {ratio:.2f}:1",
                    )

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
            ".anki-custom-selection-toolbar": ("--theme-page-text", "--theme-surface", "--theme-border-soft"),
            ".anki-custom-selection-count": ("--theme-heading",),
            ".anki-clear-selection-button": ("--theme-page-text", "--theme-surface-2", "--theme-border-soft"),
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
                surface_2 = self._composite(variables["theme-surface-2"], panel)
                combinations = {
                    "selection text": (variables["theme-page-text"], surface),
                    "selection heading": (variables["theme-heading"], surface),
                    "selection helper": (variables["theme-muted-text"], surface),
                    "selection count": (variables["theme-heading"], surface),
                    "clear selection": (variables["theme-page-text"], surface_2),
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

    def test_anki_action_controls_and_print_note_use_semantic_theme_tokens(self):
        css = self._style_css()
        expected = {
            ".anki-source-icon": (
                "--theme-accent-text", "--theme-accent", "--theme-surface",
            ),
            ".anki-preview-button": (
                "--theme-accent-text", "--theme-accent", "--theme-surface",
            ),
            ".anki-export-button": (
                "--theme-accent-text", "--theme-accent", "--theme-surface",
            ),
            ".printable-flashcard-button": (
                "--theme-accent-text", "--theme-accent", "--theme-surface",
            ),
            ".anki-print-note": (
                "--theme-page-text", "--theme-accent", "--theme-surface",
            ),
        }
        forbidden = {"#86c9ff", "#176de0", "#1f9cff", "#6b46d9", "#8e62e8", "#d8cda8"}
        for selector, tokens in expected.items():
            with self.subTest(selector=selector):
                blocks = [
                    body for prelude, body in re.findall(r"([^{}]+)\{([^}]*)\}", css)
                    if selector in prelude
                ]
                semantic_block = next(
                    (body for body in blocks if all(token in body for token in tokens)), None
                )
                self.assertIsNotNone(semantic_block, f"{selector} must use semantic tokens")
                self.assertFalse(any(color in semantic_block for color in forbidden))

    def test_shared_keyboard_focus_indicator_uses_accessible_accent_text(self):
        css = self._style_css()
        rule = re.search(
            r":where\(a\[href\], button, input, select, textarea, summary, \[tabindex\]\):focus-visible\s*\{([^}]*)\}",
            css,
        )
        self.assertIsNotNone(rule)
        self.assertIn("outline: 3px solid var(--theme-accent-text", rule.group(1))
        self.assertIn("outline-offset: 3px", rule.group(1))

    def test_empty_legacy_light_theme_selector_is_removed(self):
        self.assertNotIn(
            ':root[style*="--theme-color-scheme: light"] { }', self._style_css()
        )

    def test_shared_focus_foreground_meets_contrast_across_palettes(self):
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
                ratio = self._contrast(variables["theme-accent-text"], panel)
                self.assertGreaterEqual(ratio, 4.5, f"{theme} focus ring is only {ratio:.2f}:1")

    def test_learning_controls_and_secondary_text_use_semantic_theme_tokens(self):
        css = self._style_css()
        expected = {
            ".learning-intelligence-filters button": (
                "--theme-page-text", "--theme-surface-2", "--theme-border-soft",
            ),
            ".learning-intelligence-table th": (
                "--theme-muted-text", "--theme-surface-2", "--theme-border-soft",
            ),
            ".learning-intelligence-table td": (
                "--theme-page-text", "--theme-border-soft",
            ),
            ".learning-diagnostics-collapse": (
                "--theme-page-text", "--theme-surface-2", "--theme-border-soft",
            ),
            ".learning-diagnostics-toolbar label": ("--theme-muted-text",),
            ".review-schedule-table th": (
                "--theme-muted-text", "--theme-surface-2", "--theme-border-soft",
            ),
            ".learning-intelligence-model-dialog": (
                "--theme-panel-1", "--theme-border-soft", "--theme-shadow",
            ),
        }
        for selector, tokens in expected.items():
            with self.subTest(selector=selector):
                blocks = [
                    body for prelude, body in re.findall(r"([^{}]+)\{([^}]*)\}", css)
                    if selector in prelude
                ]
                self.assertTrue(
                    any(all(token in body for token in tokens) for body in blocks),
                    f"{selector} must resolve through semantic theme tokens",
                )

    def test_muted_secondary_text_meets_contrast_across_palettes(self):
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
                ratio = self._contrast(variables["theme-muted-text"], surface)
                self.assertGreaterEqual(ratio, 4.5, f"{theme} muted text is only {ratio:.2f}:1")

    def test_pack_validation_review_uses_spaced_semantic_action_layout(self):
        css = self._style_css()
        summary = re.search(r"\.pack-review-summary\s*\{([^}]*)\}", css)
        actions = re.search(r"\.pack-review-actions\s*\{([^}]*)\}", css)
        confirmation = re.search(
            r"\.pack-review-actions \.content-pack-confirm-check\s*\{([^}]*)\}", css,
        )
        action_row = re.search(r"\.pack-review-button-row\s*\{([^}]*)\}", css)
        self.assertIsNotNone(summary)
        self.assertIn("padding: var(--dlms-space-xl)", summary.group(1))
        self.assertIsNotNone(actions)
        self.assertIn("display: grid", actions.group(1))
        self.assertIsNotNone(confirmation)
        self.assertIn("color: var(--theme-page-text)", confirmation.group(1))
        self.assertIsNotNone(action_row)
        self.assertIn("align-items: center", action_row.group(1))
        self.assertIn(
            ".pack-review-actions .content-pack-confirm-check input:disabled + span { color: var(--theme-muted-text); }",
            css,
        )
        self.assertNotIn(
            'html[data-theme="light"] .pack-review-actions .content-pack-confirm-check',
            css,
        )


if __name__ == "__main__":
    unittest.main()

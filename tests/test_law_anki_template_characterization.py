import ast
import unittest
from pathlib import Path
from unittest import mock

from tests._isolation import ensure_test_data_isolation

ensure_test_data_isolation()
import app as dlms
from dlms.routes import law as law_routes
from tests.csrf_test_utils import csrf_token


HOSTILE = '</textarea><script id="segment20Injected">bad()</script>&\u2028\u2029'


class LawAnkiTemplateCharacterizationTests(unittest.TestCase):
    def test_fixed_inventory_uses_external_templates_and_no_string_renderer_remains(self):
        expected = {
            "law_view_case_review": "law/case-detail.html",
            "anki_tools": "anki/index.html",
            "anki_custom_deck": "anki/custom.html",
            "anki_printable_flashcards": "anki/printable.html",
            "anki_law_tools": "anki/law.html",
        }
        app_source = Path(dlms.__file__).read_text(encoding="utf-8")
        law_source = Path(law_routes.__file__).read_text(encoding="utf-8")
        trees = {
            "law_view_case_review": ast.parse(law_source),
            **{
                function_name: ast.parse(app_source)
                for function_name in expected
                if function_name != "law_view_case_review"
            },
        }
        self.assertNotIn("render_template_string(", app_source)
        self.assertNotIn("render_template_string(", law_source)

        for function_name, template_name in expected.items():
            with self.subTest(function=function_name):
                owner = next(
                    node
                    for node in trees[function_name].body
                    if isinstance(node, ast.FunctionDef) and node.name == function_name
                )
                calls = [
                    node
                    for node in ast.walk(owner)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "render_template"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value == template_name
                ]
                self.assertEqual(1, len(calls))
                self.assertTrue((Path(dlms.TEMPLATE_ROOT) / template_name).is_file())

    def test_law_case_editor_preserves_forms_banners_content_and_escaping(self):
        rendered_case_id = "case'</script>&\"\u2028\u2029"
        escaped_case_id = "case&#39;&lt;/script&gt;&amp;&#34;\u2028\u2029"
        case_data = {
            "id": rendered_case_id,
            "title": HOSTILE,
            "course": 'Torts & <Procedure>',
            "created_at": '2026-09-07 <noon>',
            "source_import": 'packet <unsafe>.txt',
            "student_notes": HOSTILE,
            "sources_used": HOSTILE,
            "socratic_student_answers": {"q1": HOSTILE},
            "irac_student_response": {
                "issue": HOSTILE,
                "rule": HOSTILE,
                "analysis": HOSTILE,
                "conclusion": HOSTILE,
            },
            "sections": {
                "case_brief": HOSTILE,
                "irac_drill": HOSTILE,
                "rule_flashcards": HOSTILE,
                "socratic_review": "1. Hostile question",
                "socratic_answer_key": HOSTILE,
            },
        }
        with mock.patch.object(
            dlms, "load_law_registry", return_value={"folders": ["Torts & <Procedure>"]}
        ), mock.patch.object(
            dlms, "get_law_case_by_id", return_value={"file": "case-safe.json"}
        ), mock.patch.object(dlms.os.path, "exists", return_value=True), mock.patch.object(
            dlms.os.path, "isfile", return_value=True
        ), mock.patch.object(
            dlms, "_load_law_case_data", return_value=case_data
        ), mock.patch.object(
            dlms,
            "parse_socratic_questions",
            return_value=[{"id": "q1", "number": 1, "text": HOSTILE}],
        ):
            response = dlms.app.test_client().get(
                "/law/cases/case-safe?updated=1&notes_updated=1&"
                "socratic_answers_updated=1&irac_updated=1"
            )

        body = response.get_data(as_text=True)
        self.assertEqual(200, response.status_code)
        self.assertNotIn('id="segment20Injected"', body)
        self.assertIn("&lt;/textarea&gt;&lt;script", body)
        self.assertIn("\u2028\u2029", body)
        self.assertIn("Torts &amp; &lt;Procedure&gt;", body)
        for message in (
            "Case details updated.",
            "Student notes updated.",
            "Socratic answers updated.",
            "IRAC response updated.",
        ):
            self.assertIn(message, body)
        for suffix in (
            "update_details",
            "update_irac_response",
            "update_socratic_answers",
            "update_notes",
        ):
            self.assertIn(f'action="/law/cases/{escaped_case_id}/{suffix}"', body)
        for name in (
            "title", "course", "irac_issue", "irac_rule", "irac_analysis",
            "irac_conclusion", "answer_q1", "student_notes",
        ):
            self.assertIn(f'name="{name}"', body)
        self.assertIn(
            f"location.href='/law/cases/{escaped_case_id}/export.txt'",
            body,
        )
        self.assertIn('aria-label="Primary navigation"', body)
        self.assertIn('aria-label="Toggle navigation"', body)
        self.assertIn('fetch("/api/shutdown", { method: "POST" })', body)

    def test_anki_landing_preserves_sources_filters_previews_and_escaping(self):
        quizzes = [{"id": 7, "title": HOSTILE, "question_count": 21}]
        law_cases = [{"id": "law-1", "card_count": 4}]
        rows = [{"front": f"Front {index} {HOSTILE}", "back": HOSTILE} for index in range(21)]
        summary = {"total": 6, "currently_weak": 2, "recovered": 3, "repeated": 1, "once": 1}
        with mock.patch.object(dlms, "get_anki_quiz_choices", return_value=quizzes), mock.patch.object(
            dlms, "get_anki_law_case_choices", return_value=law_cases
        ), mock.patch.object(
            dlms, "build_anki_rows_for_quiz", return_value=(HOSTILE, rows)
        ), mock.patch.object(dlms, "get_anki_missed_summary", return_value=summary):
            response = dlms.app.test_client().get("/anki?source=quiz&quiz_id=7#ankiPreview")

        body = response.get_data(as_text=True)
        self.assertEqual(200, response.status_code)
        self.assertNotIn('id="segment20Injected"', body)
        self.assertIn("&lt;/textarea&gt;&lt;script", body)
        self.assertIn("\u2028\u2029", body)
        self.assertIn('method="GET" action="/anki"', body)
        self.assertIn('method="POST" action="/anki/export/quiz"', body)
        self.assertIn('name="source" value="quiz"', body)
        self.assertIn('<option value="7" selected>', body)
        self.assertIn('id="missedAnkiForm"', body)
        self.assertIn('name="min_misses" value="1"', body)
        self.assertIn('name="missed_status"', body)
        self.assertEqual(20, body.count('class="anki-preview-card"'))
        self.assertIn("Previewing the first 20 of 21 cards", body)
        self.assertIn('aria-labelledby="ankiMissedSummaryTitle"', body)
        self.assertIn('exportForm.action = "/anki/export/missed"', body)

    def test_anki_custom_get_post_contract_selection_javascript_and_escaping(self):
        sources = {
            "quiz_groups": [{
                "id": 7,
                "title": HOSTILE,
                "cards": [{"question_id": 11, "question_number": 1, "front": HOSTILE, "back": HOSTILE}],
            }],
            "missed_cards": [{
                "quiz_id": 7,
                "question_id": 11,
                "question_number": 1,
                "quiz_title": HOSTILE,
                "front": HOSTILE,
                "back": HOSTILE,
                "miss_count": 2,
                "recovery_status": "currently_weak",
            }],
            "law_groups": [{
                "id": "case-safe",
                "course": HOSTILE,
                "title": HOSTILE,
                "cards": [{"front": HOSTILE, "back": HOSTILE}],
            }],
        }
        client = dlms.app.test_client()
        with mock.patch.object(dlms, "get_anki_custom_sources", return_value=sources), mock.patch.object(
            dlms, "build_custom_anki_rows", return_value=[{"front": HOSTILE, "back": HOSTILE}]
        ):
            get_body = client.get("/anki/custom").get_data(as_text=True)
            response = client.post(
                "/anki/custom",
                data={
                    "csrf_token": csrf_token(client, "/anki/custom"),
                    "deck_name": HOSTILE,
                    "quiz_cards": ["quiz:7:11"],
                    "missed_cards": ["missed:7:11"],
                    "law_cards": ["law:case-safe:1"],
                },
            )

        body = response.get_data(as_text=True)
        self.assertEqual(200, response.status_code)
        for rendered in (get_body, body):
            self.assertNotIn('id="segment20Injected"', rendered)
            self.assertIn("&lt;/textarea&gt;&lt;script", rendered)
            self.assertIn("\u2028\u2029", rendered)
            self.assertIn('id="customAnkiForm"', rendered)
            self.assertIn('formaction="/anki/custom" formmethod="POST"', rendered)
            self.assertIn('formaction="/anki/export/custom" formmethod="POST"', rendered)
            self.assertIn('formaction="/anki/printable" formmethod="POST" formtarget="_blank"', rendered)
            self.assertIn('id="ankiSelectedCount" aria-live="polite"', rendered)
            self.assertIn('id="ankiQuizFilter"', rendered)
            self.assertIn('id="ankiLawFilter"', rendered)
            self.assertIn('JSON.parse(localStorage.getItem(ankiPerformanceOpenStateKey)', rendered)
        for token in ("quiz:7:11", "missed:7:11", "law:case-safe:1"):
            self.assertIn(f'value="{token}" checked', body)
        self.assertIn('value="&lt;/textarea&gt;&lt;script id=&#34;segment20Injected&#34;&gt;', body)
        self.assertIn('|| true)', body)

    def test_printable_preserves_status_duplex_layout_loops_and_escaping(self):
        rows = [
            {"front": f"Front {index} {HOSTILE}", "back": f"Back {index} {HOSTILE}"}
            for index in range(1, 5)
        ]
        client = dlms.app.test_client()
        with mock.patch.object(dlms, "build_custom_anki_rows", return_value=rows):
            response = client.post(
                "/anki/printable",
                data={
                    "csrf_token": csrf_token(client, "/anki/custom"),
                    "deck_name": HOSTILE,
                    "duplex_flip": "short",
                    "quiz_cards": ["quiz:7:11"],
                },
            )
        with mock.patch.object(dlms, "build_custom_anki_rows", return_value=[]):
            empty = client.post(
                "/anki/printable",
                data={"csrf_token": csrf_token(client, "/anki/custom")},
            )

        body = response.get_data(as_text=True)
        self.assertEqual(200, response.status_code)
        self.assertEqual("text/html; charset=utf-8", response.content_type)
        self.assertNotIn('id="segment20Injected"', body)
        self.assertIn("&lt;/textarea&gt;&lt;script", body)
        self.assertIn("\u2028\u2029", body)
        self.assertIn("short-edge flip", body)
        self.assertEqual(2, body.count('class="avery-sheet front-sheet"'))
        self.assertEqual(2, body.count('class="avery-sheet back-sheet"'))
        self.assertIn("Avery 5388", body)
        self.assertIn('onclick="window.print()"', body)
        self.assertEqual(400, empty.status_code)
        self.assertEqual(
            "Select at least one DLMS item before creating printable flashcards.",
            empty.get_data(as_text=True),
        )

    def test_anki_law_preserves_case_course_forms_preview_empty_state_and_escaping(self):
        cases = [{"id": "case-safe", "course": HOSTILE, "title": HOSTILE, "card_count": 2}]
        courses = [{"course": HOSTILE, "case_count": 1, "card_count": 2}]
        rows = [{"front": HOSTILE, "back": HOSTILE}]
        with mock.patch.object(dlms, "get_anki_law_case_choices", return_value=cases), mock.patch.object(
            dlms, "get_anki_law_courses", return_value=courses
        ), mock.patch.object(
            dlms,
            "load_law_flashcards_for_selection",
            return_value=({"case_count": 1}, rows),
        ):
            response = dlms.app.test_client().get(
                "/anki/law?preview=1&law_scope=cases&case_ids=case-safe"
            )
        with mock.patch.object(dlms, "get_anki_law_case_choices", return_value=[]), mock.patch.object(
            dlms, "get_anki_law_courses", return_value=[]
        ):
            empty_body = dlms.app.test_client().get("/anki/law").get_data(as_text=True)

        body = response.get_data(as_text=True)
        self.assertEqual(200, response.status_code)
        self.assertNotIn('id="segment20Injected"', body)
        self.assertIn("&lt;/textarea&gt;&lt;script", body)
        self.assertIn("\u2028\u2029", body)
        self.assertIn('method="GET" action="/anki/law"', body)
        self.assertIn('name="preview" value="1"', body)
        self.assertIn('<option value="case-safe" selected>', body)
        self.assertIn('name="law_scope"', body)
        self.assertIn('name="law_course"', body)
        self.assertIn('exportForm.action = "/anki/export/law"', body)
        self.assertIn('id="ankiPreview"', body)
        self.assertIn("Saved Case - Rule Flashcards", body)
        self.assertIn("No saved Law Study cases are currently available.", empty_body)
        self.assertIn('aria-label="Law Anki summary"', body)


if __name__ == "__main__":
    unittest.main()

import unittest
import ast
from pathlib import Path
from unittest import mock

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms
from tests.csrf_test_utils import csrf_token


class AdvancedAuthoringTemplateCharacterizationTests(unittest.TestCase):
    def test_inventory_items_use_external_templates_under_template_root(self):
        expected = {
            "admin_hotspot_editor": "admin/image-editor.html",
            "study_pack_ai_builder": "study_packs/ai-builder.html",
            "image_quiz_builder": "study_packs/image-builder.html",
            "pdf_import_page": "pdf_import/index.html",
            "_render_pdf_glossary_review": "pdf_import/review-glossary.html",
            "pdf_import_review": "pdf_import/review-question-bank.html",
            "pdf_question_bank_page": "pdf_import/question-bank.html",
            "pdf_terminology_bank_page": "pdf_import/terminology-bank.html",
        }
        source = Path(dlms.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        for function_name, template_name in expected.items():
            with self.subTest(function=function_name):
                owner = next(
                    node
                    for node in ast.walk(tree)
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

        self.assertNotIn("HOTSPOT_EDITOR_TEMPLATE", source)
        self.assertNotIn("IMAGE_QUIZ_BUILDER_TEMPLATE", source)

    def test_pdf_landing_preserves_upload_contract_catalog_states_and_escaping(self):
        marker = '</strong><script id="pdf-catalog-injection">bad()</script>&'
        question_banks = [{
            "id": "question_bank",
            "title": marker,
            "source_name": '<source "questions.pdf">',
            "active_count": 7,
            "used_count": 3,
            "generated_count": 2,
        }]
        term_banks = [{
            "id": "term_bank",
            "title": marker,
            "source_name": '<source "terms.pdf">',
            "active_count": 5,
            "used_count": 1,
            "generated_count": 4,
        }]
        with mock.patch.object(
            dlms, "_list_pdf_question_banks", return_value=question_banks
        ), mock.patch.object(
            dlms, "_list_pdf_terminology_banks", return_value=term_banks
        ):
            response = dlms.app.test_client().get("/pdf-import")

        body = response.get_data(as_text=True)
        self.assertEqual(200, response.status_code)
        self.assertNotIn('id="pdf-catalog-injection"', body)
        self.assertIn("&lt;source &#34;questions.pdf&#34;&gt;", body)
        self.assertIn('action="/pdf-import/analyze" method="POST"', body)
        self.assertIn('enctype="multipart/form-data"', body)
        self.assertIn('name="pdf_file"', body)
        self.assertIn('name="pdf_content_type"', body)
        self.assertIn('name="rights_ok" required', body)
        self.assertIn('action="/pdf-import/bank/question_bank/delete"', body)
        self.assertIn('action="/pdf-import/terms/term_bank/delete"', body)
        self.assertIn('aria-pressed="false"', body)

    def test_pdf_review_branches_preserve_editable_fields_status_and_escaping(self):
        marker = '</textarea><script id="pdf-review-injection">bad()</script>&'
        base = {
            "source_name": '<unsafe "source.pdf">',
            "page_count": 2,
            "detection": {"recovery_mode": True},
            "recovery_mode": True,
            "quiz_title": marker,
            "exam_minutes": 45,
            "summary": {"detected": 1, "complete": 0, "review": 1, "incomplete": 0},
        }
        question_draft = {
            **base,
            "id": "question_review",
            "document_type": "question_bank",
            "questions": [{
                "number": 9,
                "question": marker,
                "correct": "B",
                "declared_answer_text": marker,
                "explanation": marker,
                "choice_feedback": {"A": marker},
                "choices": [
                    {"label": "A", "text": marker},
                    {"label": "B", "text": "Safe answer"},
                ],
                "pages": [1, 2],
                "status": "review",
                "issues": [marker],
            }],
        }
        glossary_draft = {
            **base,
            "id": "term_review",
            "document_type": "glossary",
            "terms": [{
                "number": 4,
                "term": marker,
                "definition": marker,
                "pages": [2],
                "status": "review",
                "issues": [marker],
            }],
        }
        client = dlms.app.test_client()
        for draft, action, form_id, payload_name, live_id in (
            (question_draft, "/pdf-import/save/question_review", "pdfReviewForm", "review_payload", "pdfSelectionCount"),
            (glossary_draft, "/pdf-import/save/term_review", "pdfTermReviewForm", "term_review_payload", "pdfTermSelectionCount"),
        ):
            with self.subTest(document_type=draft["document_type"]), mock.patch.object(
                dlms, "_load_pdf_import_draft", return_value=draft
            ):
                response = client.get(f'/pdf-import/review/{draft["id"]}')
                body = response.get_data(as_text=True)
                self.assertEqual(200, response.status_code)
                self.assertNotIn('id="pdf-review-injection"', body)
                self.assertIn("&lt;/textarea&gt;", body)
                self.assertIn(f'action="{action}"', body)
                self.assertIn(f'id="{form_id}"', body)
                self.assertIn(f'name="{payload_name}"', body)
                self.assertIn(f'id="{live_id}" aria-live="polite"', body)
                self.assertIn("Automatic parsing confidence was low", body)
                self.assertIn("JSON.stringify(payload)", body)

    def test_pdf_bank_pages_preserve_counts_usage_forms_and_escaping(self):
        marker = '</h1><script id="pdf-bank-injection">bad()</script>&'
        question_bank = {
            "id": "question_bank",
            "title": marker,
            "source_name": '<questions "source.pdf">',
            "default_exam_minutes": 75,
            "generated_quizzes": [{"quiz_id": 1}],
            "used_question_numbers": [2],
            "questions": [
                {"number": 1, "original_number": 1, "question": marker, "active": True, "pages": [1]},
                {"number": 2, "original_number": 2, "question": "Excluded", "active": False, "pages": [2]},
            ],
        }
        term_bank = {
            "id": "term_bank",
            "title": marker,
            "source_name": '<terms "source.pdf">',
            "default_exam_minutes": 60,
            "generated_quizzes": [{"quiz_id": 2}],
            "used_term_numbers": [1],
            "terms": [
                {"number": 1, "term": marker, "definition": marker, "active": True, "pages": [1]},
                {"number": 2, "term": "Excluded", "definition": "Preserved", "active": False, "pages": [2]},
            ],
        }
        client = dlms.app.test_client()
        with mock.patch.object(dlms, "_load_pdf_question_bank", return_value=question_bank):
            question_response = client.get("/pdf-import/bank/question_bank")
        with mock.patch.object(dlms, "_load_pdf_terminology_bank", return_value=term_bank):
            term_response = client.get("/pdf-import/terms/term_bank")

        for response, action, count_name in (
            (question_response, "/pdf-import/bank/question_bank/generate", "question_count"),
            (term_response, "/pdf-import/terms/term_bank/generate", "term_count"),
        ):
            with self.subTest(action=action):
                body = response.get_data(as_text=True)
                self.assertEqual(200, response.status_code)
                self.assertNotIn('id="pdf-bank-injection"', body)
                self.assertIn("&lt;/h1&gt;", body)
                self.assertIn(f'action="{action}"', body)
                self.assertIn(f'name="{count_name}"', body)
                self.assertIn("1 active · 1 excluded but preserved", body)
                self.assertIn("EXCLUDED", body)
                self.assertIn("Yes", body)

    def test_ai_builder_tojson_blocks_script_breakout_and_preserves_prompt_text(self):
        marker = '"</script><script id="ai-url-injection">bad()</script>&\'a\u2028b\u2029c'
        topic = '</textarea><script id="ai-prompt-injection">bad()</script>&'
        config = {
            "ai_provider": "local",
            "ai_custom_url": f"https://example.invalid/{marker}",
            "study_pack_ai_prompt_template": dlms.DEFAULT_STUDY_CONTENT_PACK_PROMPT,
            "medical_study_pack_ai_addendum": dlms.DEFAULT_MEDICAL_STUDY_PACK_AI_ADDENDUM,
        }
        client = dlms.app.test_client()
        token = csrf_token(client, "/study-packs/ai-builder")
        with mock.patch.object(dlms, "load_portal_config", return_value=config):
            response = client.post("/study-packs/ai-builder", data={
                "csrf_token": token,
                "topic": topic,
                "domain": "Medical",
                "difficulty": "Foundational",
                "size": "Compact",
                "image_count": "1",
                "image_style": "Diagram / schematic",
                "ai_provider": "local",
                "from_section": "medical",
                "include_matching": "on",
                "include_images": "on",
            })

        body = response.get_data(as_text=True)
        self.assertEqual(200, response.status_code)
        self.assertNotIn('id="ai-url-injection"', body)
        self.assertNotIn('id="ai-prompt-injection"', body)
        self.assertIn("&lt;/textarea&gt;", body)
        self.assertIn("\\u003c/script\\u003e", body)
        self.assertIn("\\u003cscript id=\\\"ai-url-injection\\\"\\u003e", body)
        self.assertIn("\\u0026", body)
        self.assertIn("\\u0027", body)
        self.assertIn("\\u2028", body)
        self.assertIn("\\u2029", body)
        self.assertIn('action="/study-packs/ai-builder/import"', body)
        self.assertIn('name="pack_zip"', body)
        self.assertIn('href="/medical"', body)
        self.assertIn("MEDICAL-SPECIFIC SAFETY AND SOURCE REQUIREMENTS", body)

    def test_image_builder_tojson_and_form_contract_survive_hostile_filename(self):
        marker = '</script><script id="draft-injection">bad()</script>&\'\u2028\u2029.png'
        draft = {
            "id": "12345678",
            "images": [{
                "id": "image_1",
                "filename": "safe.png",
                "original_name": marker,
                "url": "/image-builder/drafts/12345678/safe.png",
            }],
        }
        with dlms.app.test_request_context("/study-packs/image-builder"):
            body = dlms.render_template(
                "study_packs/image-builder.html",
                draft=draft,
                medical_pack_installed=True,
            )

        self.assertNotIn('id="draft-injection"', body)
        self.assertIn("const DRAFT=", body)
        self.assertIn("\\u003c/script\\u003e", body)
        self.assertIn("\\u0026", body)
        self.assertIn("\\u0027", body)
        self.assertIn("\\u2028", body)
        self.assertIn("\\u2029", body)
        self.assertIn('action="/study-packs/image-builder/save"', body)
        self.assertIn('name="draft_id"', body)
        self.assertIn('name="builder_payload"', body)
        self.assertIn('name="rights_ok" required', body)
        self.assertIn("JSON.stringify(p)", body)

    def test_shared_image_editor_tojson_mutation_and_accessibility_contracts(self):
        marker = '</script><script id="editor-injection">bad()</script>&\'\u2028\u2029'
        catalog = [{
            "pack_id": "pack",
            "pack_name": marker,
            "dataset_id": "dataset",
            "dataset_kind": "hotspot",
            "title": marker,
            "images": 1,
            "hotspots": 1,
        }]
        dataset = {
            "title": marker,
            "images": [{
                "id": marker,
                "file": "images/diagram.png",
                "alt_text": marker,
                "hotspots": [{"id": marker, "label": marker, "shape": {"type": "circle", "x": .5, "y": .5, "radius": .1}}],
                "edits": [{"type": "text", "x": .2, "y": .2, "text": marker, "size": 18, "tone": "light"}],
            }],
        }
        with mock.patch.object(dlms, "_hotspot_editor_catalog", return_value=catalog), mock.patch.object(
            dlms, "load_content_pack_image_dataset", return_value=dataset
        ):
            response = dlms.app.test_client().get(
                "/admin/image-editor?pack=pack&dataset=dataset&kind=hotspot"
            )

        body = response.get_data(as_text=True)
        self.assertEqual(200, response.status_code)
        self.assertNotIn('id="editor-injection"', body)
        self.assertIn("const EDITOR_DATA=", body)
        self.assertIn("\\u003c/script\\u003e", body)
        self.assertIn("\\u0026", body)
        self.assertIn("\\u0027", body)
        self.assertIn("\\u2028", body)
        self.assertIn("\\u2029", body)
        self.assertIn("/admin/image-editor/hotspot/save", body)
        self.assertIn("/admin/image-editor/edits/save", body)
        self.assertIn("JSON.stringify({pack_id:EDITOR_DATA.pack_id", body)
        self.assertIn('aria-label="Toggle navigation"', body)
        self.assertIn('id="editorStatus"', body)
        self.assertIn('/static/nav-normalize.js', body)


if __name__ == "__main__":
    unittest.main()

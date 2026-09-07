"""Characterization coverage for the IT Study read-only views."""

import unittest
from pathlib import Path
from unittest import mock

from markupsafe import escape

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms


class ITTemplateTests(unittest.TestCase):
    def setUp(self):
        self.client = dlms.app.test_client()

    @staticmethod
    def _pack(**overrides):
        pack = {
            "id": "it_sample",
            "name": "IT Sample",
            "version": "2.1",
            "description": "Sample IT content.",
        }
        pack.update(overrides)
        return pack

    @staticmethod
    def _matching(**overrides):
        dataset = {
            "pack_id": "it_sample",
            "pack_name": "IT Sample",
            "id": "concepts",
            "title": "IT Concepts",
            "description": "Foundational concepts.",
            "type": "matching",
            "term_count": 12,
            "category": "IT / Cybersecurity",
        }
        dataset.update(overrides)
        return dataset

    @staticmethod
    def _image(**overrides):
        dataset = {
            "pack_id": "it_sample",
            "pack_name": "IT Sample",
            "id": "diagrams",
            "title": "Network Diagrams",
            "description": "Identify network components.",
            "image_count": 2,
            "hotspot_count": 7,
            "category": "Diagrams & Images",
        }
        dataset.update(overrides)
        return dataset

    @staticmethod
    def _quiz(**overrides):
        dataset = {
            "pack_id": "it_sample",
            "pack_name": "IT Sample",
            "id": "questions",
            "title": "IT Questions",
            "description": "Mixed practice.",
            "question_count": 9,
            "image_count": 0,
            "category": "Question Set",
        }
        dataset.update(overrides)
        return dataset

    def _get(self, path, pack, matching=None, images=None, quizzes=None, discovered=None):
        with mock.patch.object(
            dlms,
            "_it_pack_page_data",
            return_value=(pack, matching or [], images or [], quizzes or []),
        ), mock.patch.object(
            dlms, "discover_content_packs", return_value=discovered or {}
        ):
            response = self.client.get(path)
        self.assertEqual(200, response.status_code)
        return response.get_data(as_text=True)

    def test_no_pack_state_is_shared_by_all_routes_with_home_navigation(self):
        with mock.patch.object(
            dlms, "_it_pack_page_data", return_value=(None, [], [], [])
        ), mock.patch.object(dlms, "discover_content_packs", return_value={}):
            pages = {
                path: self.client.get(path).get_data(as_text=True)
                for path in ("/it", "/it/matching", "/it/images")
            }

        self.assertEqual(1, len(set(pages.values())))
        page = pages["/it"]
        self.assertIn("<h1>DLMS IT Study</h1>", page)
        self.assertIn("<span>Installed Packs</span><strong>0</strong>", page)
        self.assertIn("<span>Study Banks</span><strong>0</strong>", page)
        self.assertIn("<span>Image Sets</span><strong>0</strong>", page)
        self.assertIn(
            'href="/study-packs/ai-builder?domain=IT%20/%20Cybersecurity&amp;from=it"',
            page,
        )
        self.assertIn('href="/content-packs"', page)
        self.assertIn(
            'class="dashboard-nav-item active" href="/it" aria-current="page"',
            page,
        )
        self.assertIn('aria-label="Toggle navigation"', page)
        self.assertIn('aria-controls="dashboardSidebar"', page)
        self.assertIn('aria-expanded="false"', page)

    def test_home_populated_counts_question_status_links_and_escaping(self):
        pack = self._pack(
            name='IT </script><img id="itHomeInjected"> & Study \u2028\u2029',
            version='2<3 & "quoted"',
        )
        matching = [self._matching(term_count=12), self._matching(id="second", term_count=3)]
        images = [self._image(image_count=2, hotspot_count=5)]
        quizzes = [self._quiz(question_count=9), self._quiz(id="second-quiz", question_count=4)]
        discovered = {
            "one": {"content_domain": "IT / Cybersecurity"},
            "two": {"content_domain": "IT"},
            "medical": {"content_domain": "Medical"},
        }
        page = self._get("/it", pack, matching, images, quizzes, discovered)

        self.assertIn(str(escape(pack["name"])), page)
        self.assertIn(str(escape(pack["version"])), page)
        self.assertNotIn('<img id="itHomeInjected">', page)
        self.assertIn("<span>Installed Packs</span><strong>2</strong>", page)
        self.assertIn("<span>Study Banks</span><strong>2</strong><small>15 concepts</small>", page)
        self.assertIn("<span>Visual Sets</span><strong>1</strong><small>5 targets across 2 images</small>", page)
        self.assertIn("<h2>2 Question Sets</h2>", page)
        self.assertIn("13 mixed questions are available", page)
        self.assertIn('href="/study-packs">Open Study Packs</a>', page)
        self.assertIn('href="/it/matching"', page)
        self.assertIn('href="/it/images"', page)
        self.assertIn(
            'href="/study-packs/ai-builder?domain=IT%20/%20Cybersecurity&amp;from=it"',
            page,
        )

    def test_home_hides_question_set_panel_without_quiz_datasets(self):
        page = self._get("/it", self._pack(), [], [], [], {})

        self.assertNotIn("MIXED PRACTICE", page)
        self.assertNotIn("mixed questions are available", page)
        self.assertIn("CUSTOM CONTENT", page)

    def test_matching_populated_forms_metadata_inline_controls_and_escaping(self):
        dataset = self._matching(
            pack_id='pack<id>&"',
            pack_name='Pack </script><img id="itMatchPackInjected">',
            id='terms<id>&"',
            title='Terms </script><svg id="itMatchInjected"> \u2028\u2029',
            description='Description <b id="itMatchDescriptionInjected"> & safe',
            category='Category <tag> & "quoted"',
            term_count=12,
        )
        short = self._matching(
            id="short", title="Short Bank", description="", category="", term_count=4
        )
        page = self._get("/it/matching", self._pack(), [dataset, short])

        for value in (
            dataset["pack_id"], dataset["pack_name"], dataset["id"],
            dataset["title"], dataset["description"], dataset["category"],
        ):
            self.assertIn(str(escape(value)), page)
        for injected_id in (
            "itMatchPackInjected", "itMatchInjected", "itMatchDescriptionInjected"
        ):
            self.assertNotIn(f'id="{injected_id}"', page)
        self.assertIn("<span>Study Banks</span><strong>2</strong>", page)
        self.assertIn("<span>Total Concepts</span><strong>16</strong>", page)
        self.assertEqual(2, page.count('method="POST" action="/study-packs/generate"'))
        self.assertIn('form="it-match-form-1" type="hidden" name="pack_id"', page)
        self.assertIn(f'name="pack_id" value="{escape(dataset["pack_id"])}"', page)
        self.assertIn(f'name="dataset_id" value="{escape(dataset["id"])}"', page)
        self.assertIn('name="round_size" min="2" max="12" value="10"', page)
        self.assertIn('name="round_size" min="2" max="4" value="4"', page)
        self.assertIn('select form="it-match-form-1" name="direction"', page)
        self.assertIn('<option value="random">Random</option>', page)
        self.assertIn('form="it-match-form-1" class="medical-primary-button', page)
        self.assertIn('id="it-match-1" class="study-dataset-detail-row it-detail-row" hidden', page)
        self.assertIn("document.querySelectorAll('.it-detail-row').forEach(r=>r.hidden=false)", page)
        self.assertIn("document.querySelectorAll('.it-detail-row').forEach(r=>r.hidden=true)", page)
        self.assertIn(
            'class="dashboard-nav-subitem active" href="/it/matching" aria-current="page"',
            page,
        )
        self.assertIn('href="/it">← Back to IT Study</a>', page)

    def test_matching_pack_without_usable_datasets_preserves_empty_state(self):
        page = self._get("/it/matching", self._pack())

        self.assertIn("No IT matching datasets installed", page)
        self.assertIn("Create or install an IT / Cybersecurity Study Pack", page)
        self.assertIn("<span>Study Banks</span><strong>0</strong>", page)
        self.assertIn("<span>Total Concepts</span><strong>0</strong>", page)
        self.assertNotIn('action="/study-packs/generate"', page)

    def test_images_populated_forms_metadata_counts_and_escaping(self):
        dataset = self._image(
            pack_id='pack<id>&"',
            pack_name='Pack </script><img id="itImagePackInjected">',
            id='images<id>&"',
            title='Images </script><svg id="itImageInjected"> \u2028\u2029',
            description='Description <b id="itImageDescriptionInjected"> & safe',
            category='Category <tag> & "quoted"',
            image_count=2,
            hotspot_count=7,
        )
        page = self._get("/it/images", self._pack(), [], [dataset])

        for value in (
            dataset["pack_id"], dataset["pack_name"], dataset["id"],
            dataset["title"], dataset["description"], dataset["category"],
        ):
            self.assertIn(str(escape(value)), page)
        for injected_id in (
            "itImagePackInjected", "itImageInjected", "itImageDescriptionInjected"
        ):
            self.assertNotIn(f'id="{injected_id}"', page)
        self.assertIn("<span>Image Sets</span><strong>1</strong>", page)
        self.assertIn("<span>Targets</span><strong>7</strong><small>across 2 images</small>", page)
        self.assertIn('method="POST" action="/study-packs/image/generate"', page)
        self.assertIn(f'name="pack_id" value="{escape(dataset["pack_id"])}"', page)
        self.assertIn(f'name="dataset_id" value="{escape(dataset["id"])}"', page)
        self.assertIn('id="it-image-1" class="study-dataset-detail-row" hidden', page)
        self.assertIn(
            'class="dashboard-nav-subitem active" href="/it/images" aria-current="page"',
            page,
        )

    def test_images_pack_without_usable_datasets_and_scripts_preserve_boundaries(self):
        empty = self._get("/it/images", self._pack())
        self.assertIn("No IT image datasets installed", empty)
        self.assertIn("with image datasets to populate this page", empty)
        self.assertIn("<span>Image Sets</span><strong>0</strong>", empty)
        self.assertIn("<span>Targets</span><strong>0</strong><small>across 0 images</small>", empty)
        self.assertNotIn('action="/study-packs/image/generate"', empty)

        hostile = 'Rendered </script><img id="itScriptInjected"> \u2028\u2029'
        pages = (
            self._get("/it", self._pack(name=hostile)),
            self._get("/it/matching", self._pack(), [self._matching(title=hostile)]),
            self._get("/it/images", self._pack(), [], [self._image(title=hostile)]),
        )
        for page in pages:
            with self.subTest(title=page.split("<title>", 1)[1].split("</title>", 1)[0]):
                self.assertEqual(2, page.count("</script>"))
                inline_script = page.split("<script>", 1)[1].split("</script>", 1)[0]
                self.assertNotIn(hostile, inline_script)
                self.assertNotIn("{{", inline_script)
                self.assertIn("menuButton", inline_script)
                self.assertIn('<script src="/static/nav-normalize.js"></script>', page)

    def test_routes_render_external_templates_with_unchanged_context(self):
        pack = self._pack()
        matching = [self._matching()]
        images = [self._image()]
        quizzes = [self._quiz()]
        discovered = {
            "it_sample": {"content_domain": "IT / Cybersecurity"},
            "medical": {"content_domain": "Medical"},
        }

        with mock.patch.object(
            dlms,
            "_it_pack_page_data",
            return_value=(pack, matching, images, quizzes),
        ), mock.patch.object(
            dlms, "discover_content_packs", return_value=discovered
        ), mock.patch.object(
            dlms, "render_template", return_value="rendered"
        ) as renderer:
            self.assertEqual("rendered", dlms.it_study_home())
            renderer.assert_called_once_with(
                "it/index.html",
                pack=pack,
                datasets=matching,
                image_datasets=images,
                quiz_datasets=quizzes,
                total_terms=12,
                total_images=2,
                total_hotspots=7,
                total_questions=9,
                pack_count=1,
                it_section="home",
            )

        with mock.patch.object(
            dlms,
            "_it_pack_page_data",
            return_value=(pack, matching, images, quizzes),
        ), mock.patch.object(
            dlms, "render_template", return_value="rendered"
        ) as renderer:
            self.assertEqual("rendered", dlms.it_matching())
            renderer.assert_called_once_with(
                "it/matching.html",
                pack=pack,
                datasets=matching,
                total_terms=12,
                it_section="matching",
            )

            renderer.reset_mock()
            self.assertEqual("rendered", dlms.it_images())
            renderer.assert_called_once_with(
                "it/images.html",
                pack=pack,
                image_datasets=images,
                total_images=2,
                total_hotspots=7,
                it_section="images",
            )

        with mock.patch.object(
            dlms, "render_template", return_value="rendered"
        ) as renderer:
            self.assertEqual("rendered", dlms._it_empty_page())
            renderer.assert_called_once_with(
                "it/empty.html",
                pack={"name": "IT Study", "version": "No packs installed"},
                it_section="home",
            )

        template_root = Path(dlms.TEMPLATE_ROOT)
        for relative_path in (
            "it/_sidebar.html",
            "it/empty.html",
            "it/index.html",
            "it/matching.html",
            "it/images.html",
        ):
            with self.subTest(template=relative_path):
                self.assertTrue((template_root / relative_path).is_file())


if __name__ == "__main__":
    unittest.main()

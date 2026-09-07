"""Characterization coverage for the Medical Study read-only views."""

import unittest
from pathlib import Path
from unittest import mock

from markupsafe import escape

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms


class MedicalTemplateTests(unittest.TestCase):
    def setUp(self):
        self.client = dlms.app.test_client()

    @staticmethod
    def _pack(**overrides):
        pack = {
            "id": "medical_sample",
            "name": "Medical Sample",
            "version": "2.1",
            "description": "Sample medical content.",
        }
        pack.update(overrides)
        return pack

    @staticmethod
    def _matching(**overrides):
        dataset = {
            "pack_id": "medical_sample",
            "pack_name": "Medical Sample",
            "id": "terminology",
            "title": "Medical Terminology",
            "description": "Foundational terms.",
            "type": "matching",
            "term_count": 12,
            "category": "Terminology",
        }
        dataset.update(overrides)
        return dataset

    @staticmethod
    def _image(**overrides):
        dataset = {
            "pack_id": "medical_sample",
            "pack_name": "Medical Sample",
            "id": "anatomy",
            "title": "Anatomy Images",
            "description": "Identify structures.",
            "image_count": 2,
            "hotspot_count": 7,
            "category": "Anatomy",
        }
        dataset.update(overrides)
        return dataset

    def _get(self, path, pack, matching=None, images=None):
        with mock.patch.object(
            dlms,
            "_medical_pack_page_data",
            return_value=(pack, matching or [], images or []),
        ):
            response = self.client.get(path)
        self.assertEqual(200, response.status_code)
        return response.get_data(as_text=True)

    def test_routes_use_external_templates_and_preserve_exact_context(self):
        pack = self._pack(image_framework={"status": "ready"})
        matching = [self._matching(term_count=12)]
        images = [self._image(image_count=2, hotspot_count=7)]
        cases = (
            (
                "/medical",
                "medical/index.html",
                {
                    "pack": pack,
                    "datasets": matching,
                    "image_datasets": images,
                    "total_terms": 12,
                    "total_images": 2,
                    "total_hotspots": 7,
                    "medical_section": "home",
                },
            ),
            (
                "/medical/matching",
                "medical/matching.html",
                {
                    "pack": pack,
                    "datasets": matching,
                    "total_terms": 12,
                    "medical_section": "matching",
                },
            ),
            (
                "/medical/anatomy",
                "medical/anatomy.html",
                {
                    "pack": pack,
                    "image_datasets": images,
                    "total_images": 2,
                    "total_hotspots": 7,
                    "image_framework": pack["image_framework"],
                    "medical_section": "anatomy",
                },
            ),
        )

        for path, template, context in cases:
            with self.subTest(path=path), mock.patch.object(
                dlms,
                "_medical_pack_page_data",
                return_value=(pack, matching, images),
            ), mock.patch.object(
                dlms, "render_template", wraps=dlms.render_template
            ) as render_template:
                response = self.client.get(path)

            self.assertEqual(200, response.status_code)
            render_template.assert_called_once_with(template, **context)
            self.assertTrue((Path(dlms.TEMPLATE_ROOT) / template).is_file())

        with mock.patch.object(
            dlms, "_medical_pack_page_data", return_value=(None, [], [])
        ), mock.patch.object(
            dlms, "discover_content_packs", return_value={}
        ), mock.patch.object(
            dlms, "render_template", wraps=dlms.render_template
        ) as render_template:
            response = self.client.get("/medical")

        self.assertEqual(200, response.status_code)
        render_template.assert_called_once_with(
            "medical/empty.html",
            pack={"name": "Medical Study", "version": "No packs installed"},
            pack_folder=dlms.CONTENT_PACK_FOLDER,
            medical_section="home",
        )
        self.assertTrue(
            (Path(dlms.TEMPLATE_ROOT) / "medical" / "empty.html").is_file()
        )
        self.assertTrue(
            (Path(dlms.TEMPLATE_ROOT) / "medical" / "_sidebar.html").is_file()
        )

    def test_no_pack_state_is_shared_by_all_three_routes_and_escapes_path(self):
        pack_folder = '/packs/<img id="pathInjected"> & medical'
        with mock.patch.object(
            dlms, "_medical_pack_page_data", return_value=(None, [], [])
        ), mock.patch.object(
            dlms, "discover_content_packs", return_value={}
        ), mock.patch.object(dlms, "CONTENT_PACK_FOLDER", pack_folder):
            pages = {
                path: self.client.get(path).get_data(as_text=True)
                for path in ("/medical", "/medical/matching", "/medical/anatomy")
            }

        self.assertEqual(1, len(set(pages.values())))
        page = pages["/medical"]
        self.assertIn("No Medical Study Packs Installed", page)
        self.assertIn("Medical Study Ready", page)
        self.assertIn("<span>Installed Packs</span>", page)
        self.assertIn("<span>Study Banks</span>", page)
        self.assertIn("<span>Image Sets</span>", page)
        self.assertIn(str(escape(pack_folder)), page)
        self.assertNotIn('<img id="pathInjected">', page)
        self.assertIn(
            'href="/study-packs/ai-builder?domain=Medical&amp;from=medical"', page
        )
        self.assertIn('href="/content-packs"', page)
        self.assertIn(
            'class="dashboard-nav-item active" href="/medical" aria-current="page"',
            page,
        )
        self.assertIn('aria-label="Toggle navigation"', page)
        self.assertIn('aria-controls="dashboardSidebar"', page)
        self.assertIn('aria-expanded="false"', page)

    def test_home_populated_state_preserves_counts_links_navigation_and_escaping(self):
        pack = self._pack(
            name='Medical </script><img id="homeInjected"> & Study \u2028\u2029',
            version='2<3 & "quoted"',
        )
        matching = [self._matching(term_count=12), self._matching(id="second", term_count=3)]
        images = [self._image(image_count=1, hotspot_count=4)]
        page = self._get("/medical", pack, matching, images)

        self.assertIn(str(escape(pack["name"])), page)
        self.assertIn(str(escape(pack["version"])), page)
        self.assertNotIn('<img id="homeInjected">', page)
        self.assertIn("<span>Study Banks</span><strong>2</strong><small>15 terminology terms</small>", page)
        self.assertIn("<span>Image Sets</span><strong>1</strong><small>4 visual structures</small>", page)
        self.assertIn("<span>2 study banks</span>", page)
        self.assertIn("<span>15 terms</span>", page)
        self.assertIn("<span>1 image sets</span>", page)
        self.assertIn("<span>1 images</span>", page)
        self.assertIn("<span>4 structures</span>", page)
        self.assertIn('href="/medical/matching"', page)
        self.assertIn('href="/medical/anatomy"', page)
        self.assertIn(
            'href="/study-packs/ai-builder?domain=Medical&amp;from=medical"', page
        )
        self.assertIn(
            'class="dashboard-nav-item active" href="/medical" aria-current="page"',
            page,
        )

    def test_matching_populated_state_preserves_forms_details_and_accessibility(self):
        dataset = self._matching(
            pack_id='pack<id>&"',
            pack_name='Pack </script><img id="matchingPackInjected">',
            id='terms<id>&"',
            title='Terms </script><svg id="matchingInjected"> \u2028\u2029',
            description='Description <b id="descriptionInjected"> & safe',
            category='Category <tag> & "quoted"',
            term_count=12,
        )
        short = self._matching(
            id="short",
            title="Short Bank",
            description="",
            category="",
            term_count=4,
        )
        page = self._get("/medical/matching", self._pack(), [dataset, short], [])

        for value in (
            dataset["pack_id"], dataset["pack_name"], dataset["id"],
            dataset["title"], dataset["description"], dataset["category"],
        ):
            self.assertIn(str(escape(value)), page)
        self.assertNotIn('<svg id="matchingInjected">', page)
        self.assertNotIn('<img id="matchingPackInjected">', page)
        self.assertNotIn('<b id="descriptionInjected">', page)
        self.assertIn("<span>Study Banks</span><strong>2</strong>", page)
        self.assertIn("<span>Total Terms</span><strong>16</strong>", page)
        self.assertEqual(2, page.count('method="POST" action="/medical/generate"'))
        self.assertIn(f'name="pack_id" value="{escape(dataset["pack_id"])}"', page)
        self.assertIn(f'name="dataset_id" value="{escape(dataset["id"])}"', page)
        self.assertIn('name="round_size" min="2" max="12" value="10"', page)
        self.assertIn('name="round_size" min="2" max="4" value="4"', page)
        self.assertIn('select name="direction"', page)
        self.assertIn('<option value="random" selected>Random</option>', page)
        self.assertIn('<option value="term_to_definition">Term → Definition</option>', page)
        self.assertIn('<option value="definition_to_term">Definition → Term</option>', page)
        self.assertIn('data-medical-detail="matching-detail-1"', page)
        self.assertIn('id="matching-detail-1"', page)
        self.assertIn('aria-expanded="false"', page)
        self.assertIn('data-medical-expand="matching"', page)
        self.assertIn('data-medical-collapse="matching"', page)
        self.assertIn(
            'class="dashboard-nav-subitem active" href="/medical/matching"', page
        )
        self.assertIn('href="/medical">← Back to Medical Study</a>', page)

    def test_matching_pack_without_usable_datasets_preserves_empty_state(self):
        page = self._get("/medical/matching", self._pack(), [], [])

        self.assertIn("No usable terminology datasets", page)
        self.assertIn("No valid Medical terminology datasets are currently installed.", page)
        self.assertIn("<span>Study Banks</span><strong>0</strong>", page)
        self.assertIn("<span>Total Terms</span><strong>0</strong>", page)
        self.assertNotIn('action="/medical/generate"', page)

    def test_anatomy_populated_state_preserves_framework_forms_counts_and_escaping(self):
        pack = self._pack(image_framework={
            "name": 'Framework </script><img id="frameworkInjected">',
            "description": 'Framework <b id="frameworkDescriptionInjected"> & safe',
            "schema_version": '2<schema>&"',
            "status": 'review <status> & pending',
        })
        dataset = self._image(
            pack_id='pack<id>&"',
            pack_name='Pack </script><img id="anatomyPackInjected">',
            id='images<id>&"',
            title='Images </script><svg id="anatomyInjected"> \u2028\u2029',
            description='Description <b id="anatomyDescriptionInjected"> & safe',
            category='Category <tag> & "quoted"',
            image_count=1,
            hotspot_count=5,
        )
        page = self._get("/medical/anatomy", pack, [], [dataset])

        for value in (
            pack["image_framework"]["name"],
            pack["image_framework"]["description"],
            pack["image_framework"]["schema_version"],
            dataset["pack_id"], dataset["pack_name"], dataset["id"],
            dataset["title"], dataset["description"], dataset["category"],
        ):
            self.assertIn(str(escape(value)), page)
        self.assertIn("Review &lt;status&gt; &amp; pending", page)
        for injected_id in (
            "frameworkInjected", "frameworkDescriptionInjected", "anatomyPackInjected",
            "anatomyInjected", "anatomyDescriptionInjected",
        ):
            self.assertNotIn(f'id="{injected_id}"', page)
        self.assertIn("<span>Image Sets</span><strong>1</strong>", page)
        self.assertIn("<span>Structures</span><strong>5</strong><small>across 1 image</small>", page)
        self.assertIn('method="POST" action="/medical/anatomy/generate"', page)
        self.assertIn(f'name="pack_id" value="{escape(dataset["pack_id"])}"', page)
        self.assertIn(f'name="dataset_id" value="{escape(dataset["id"])}"', page)
        self.assertIn('data-medical-detail="anatomy-detail-1"', page)
        self.assertIn('id="anatomy-detail-1"', page)
        self.assertIn('aria-expanded="false"', page)
        self.assertIn('data-medical-expand="anatomy"', page)
        self.assertIn('data-medical-collapse="anatomy"', page)
        self.assertIn(
            'class="dashboard-nav-subitem active" href="/medical/anatomy"', page
        )

    def test_anatomy_pack_without_usable_images_preserves_empty_state(self):
        page = self._get("/medical/anatomy", self._pack(), [], [])

        self.assertIn("No usable image datasets", page)
        self.assertIn("No valid Medical image datasets are currently installed.", page)
        self.assertIn("<span>Image Sets</span><strong>0</strong>", page)
        self.assertIn("<span>Structures</span><strong>0</strong><small>across 0 images</small>", page)
        self.assertNotIn("IMAGE CONTENT FRAMEWORK", page)
        self.assertNotIn('action="/medical/anatomy/generate"', page)

    def test_inline_scripts_remain_static_and_contain_no_rendered_values(self):
        hostile = 'Rendered </script><img id="scriptInjected"> \u2028\u2029'
        pages = (
            self._get("/medical", self._pack(name=hostile), [], []),
            self._get(
                "/medical/matching",
                self._pack(),
                [self._matching(title=hostile)],
                [],
            ),
            self._get(
                "/medical/anatomy",
                self._pack(),
                [],
                [self._image(title=hostile)],
            ),
        )

        for page in pages:
            with self.subTest(title=page.split("<title>", 1)[1].split("</title>", 1)[0]):
                self.assertEqual(2, page.count("</script>"))
                inline_script = page.split("<script>", 1)[1].split("</script>", 1)[0]
                self.assertNotIn(hostile, inline_script)
                self.assertNotIn("{{", inline_script)
                self.assertIn("menuButton", inline_script)
                self.assertIn('<script src="/static/nav-normalize.js"></script>', page)


if __name__ == "__main__":
    unittest.main()

"""Characterization coverage for the read-only Study Packs catalog."""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from markupsafe import escape

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms
from dlms.routes import study_packs as study_pack_routes
from dlms.services import content_packs as content_pack_service


class StudyPackDomainGroupTests(unittest.TestCase):
    def test_canonical_it_aliases_and_extends_are_classified_as_it(self):
        for value in (
            "IT",
            "IT / Cybersecurity",
            "it_cybersecurity",
            "cybersecurity",
            "information_technology",
        ):
            with self.subTest(value=value):
                self.assertEqual(
                    "it",
                    content_pack_service._study_pack_catalog_domain_group(
                        "pack", {"content_domain": value}
                    ),
                )
        self.assertEqual(
            "it",
            content_pack_service._study_pack_catalog_domain_group(
                "pack", {"extends": "IT / Cybersecurity"}
            ),
        )

    def test_medical_current_legacy_and_extends_forms_are_classified_as_medical(self):
        for pack_id, manifest in (
            ("pack", {"content_domain": "Medical"}),
            ("pack", {"extends": "medical"}),
            ("medical", {}),
        ):
            with self.subTest(pack_id=pack_id, manifest=manifest):
                self.assertEqual(
                    "medical",
                    content_pack_service._study_pack_catalog_domain_group(
                        pack_id, manifest
                    ),
                )

    def test_other_product_domains_custom_and_missing_values_share_other_group(self):
        for value in ("General", "Science", "History", "Language", "Other", "Astronomy", ""):
            with self.subTest(value=value):
                manifest = {"content_domain": value} if value else {}
                self.assertEqual(
                    "other",
                    content_pack_service._study_pack_catalog_domain_group(
                        "pack", manifest
                    ),
                )

    def test_law_and_legal_use_internal_exclusion_group(self):
        for field in ("content_domain", "extends"):
            for value in ("Law", "Legal"):
                with self.subTest(field=field, value=value):
                    self.assertEqual(
                        "law",
                        content_pack_service._study_pack_catalog_domain_group(
                            "pack", {field: value}
                        ),
                    )
        self.assertEqual(
            "law",
            content_pack_service._study_pack_catalog_domain_group(
                "pack", {"content_domain": "General", "extends": "Legal"}
            ),
        )

    def test_catalog_uses_injected_classifier_for_every_rendered_pack(self):
        manifests = {
            "it": {"name": "IT", "extends": "information_technology"},
            "medical": {"name": "Medical", "extends": "Medical"},
            "custom": {"name": "Custom", "content_domain": "Astronomy"},
            "law": {"name": "Law", "content_domain": "Legal"},
        }
        for manifest in manifests.values():
            manifest["datasets"] = [{"id": "terms"}]
        dependencies = SimpleNamespace(
            discover_content_packs=lambda: manifests,
            study_pack_catalog_domain_group=(
                content_pack_service._study_pack_catalog_domain_group
            ),
            load_content_pack_dataset=lambda pack_id, dataset_id: {
                "title": f"{pack_id} terms", "terms": []
            },
            load_content_pack_image_dataset=lambda *args: {},
            load_content_pack_quiz_dataset=lambda *args: {},
        )

        catalog = study_pack_routes._study_pack_catalog(dependencies)

        self.assertEqual(
            {"custom": "other", "it": "it", "law": "law", "medical": "medical"},
            {pack["id"]: pack["domain_group"] for pack in catalog},
        )


class StudyPacksCatalogTemplateTests(unittest.TestCase):
    def setUp(self):
        self.client = dlms.app.test_client()

    @staticmethod
    def _pack(**overrides):
        pack = {
            "id": "network_pack",
            "name": "Network Study",
            "version": "2.0",
            "description": "Networking fundamentals.",
            "domain": "IT / Cybersecurity",
            "domain_group": "it",
            "datasets": [],
            "image_datasets": [],
            "quiz_datasets": [],
        }
        pack.update(overrides)
        return pack

    def _get(self, packs, query=""):
        with mock.patch.object(study_pack_routes, "_study_pack_catalog", return_value=packs):
            response = self.client.get(f"/study-packs{query}")
        self.assertEqual(200, response.status_code)
        return response.get_data(as_text=True)

    def test_empty_catalog_preserves_navigation_launches_and_accessibility(self):
        page = self._get([])

        self.assertIn("<title>Study Packs - DLMS</title>", page)
        self.assertIn("<h1>Study Packs</h1>", page)
        self.assertIn("No usable study packs yet", page)
        self.assertIn('class="dashboard-nav-item active" href="/study-packs"', page)
        self.assertIn('href="/study-packs/ai-builder"', page)
        self.assertIn('href="/study-packs/image-builder"', page)
        self.assertIn('href="/admin/image-editor"', page)
        self.assertIn('aria-label="Toggle navigation"', page)
        self.assertIn('aria-controls="dashboardSidebar"', page)
        self.assertIn('aria-expanded="false"', page)
        self.assertNotIn("study-pack-installed-notice", page)
        self.assertNotIn("study-pack-toolbar", page)

    def test_other_mode_filters_dedicated_domains_and_changes_copy_and_links(self):
        packs = [
            self._pack(id="science", name="Science", domain="Science", domain_group="other"),
            self._pack(id="general", name="General", domain="General", domain_group="other"),
            self._pack(id="medical", name="Medical", domain="Medical", domain_group="medical"),
            self._pack(id="it", name="IT", domain="IT / Cybersecurity", domain_group="it"),
            self._pack(id="law", name="Law", domain="Legal", domain_group="law"),
        ]
        page = self._get(packs, "?domain_group=other")

        self.assertIn("<title>Other Studies - DLMS</title>", page)
        self.assertIn("<h1>Other Studies</h1>", page)
        self.assertIn("CROSS-DOMAIN STUDY", page)
        self.assertIn("2 study packs", page)
        self.assertIn(">Science</h2>", page)
        self.assertIn(">General</h2>", page)
        self.assertNotIn(">Medical</h2>", page)
        self.assertNotIn(">IT</h2>", page)
        self.assertNotIn(">Law</h2>", page)
        self.assertIn(
            'href="/study-packs/ai-builder?domain=Other&amp;from=other"', page
        )

        empty = self._get(
            [self._pack(id="medical", domain="Medical", domain_group="medical")],
            "?domain_group=other",
        )
        self.assertIn("No Other Studies packs installed yet", empty)
        self.assertIn("outside IT, Law, and Medical", empty)

    def test_populated_catalog_metadata_counts_forms_and_conditional_content(self):
        pack = self._pack(
            datasets=[{
                "id": "terms",
                "title": "Network Terms",
                "description": "Term details.",
                "term_count": 12,
                "category": "Networking",
            }],
            image_datasets=[{
                "id": "diagram",
                "title": "Network Diagram",
                "description": "Diagram details.",
                "image_count": 1,
                "hotspot_count": 3,
                "category": "Topology",
            }],
            quiz_datasets=[{
                "id": "mixed",
                "title": "Mixed Questions",
                "description": "Question details.",
                "question_count": 7,
                "image_count": 2,
                "hotspot_count": 1,
                "category": "Review",
            }],
        )
        page = self._get([pack])

        self.assertIn("1 study pack", page)
        self.assertIn("3 datasets", page)
        self.assertIn("1 matching", page)
        self.assertIn("1 image", page)
        self.assertIn("1 mixed", page)
        self.assertIn("IT / CYBERSECURITY · 2.0", page)
        self.assertIn("Networking fundamentals.", page)
        self.assertIn("7 questions", page)
        self.assertIn("2 images · 1 hotspots", page)
        self.assertIn("12 items", page)
        self.assertIn("1 image</span><small>3 targets", page)
        self.assertIn('method="POST" action="/study-packs/quiz/generate"', page)
        self.assertIn('method="POST" action="/study-packs/generate"', page)
        self.assertIn('method="POST" action="/study-packs/image/generate"', page)
        self.assertEqual(3, page.count('name="pack_id" value="network_pack"'))
        for dataset_id in ("mixed", "terms", "diagram"):
            self.assertIn(f'name="dataset_id" value="{dataset_id}"', page)
        self.assertIn('name="round_size" min="2" max="12" value="10"', page)
        self.assertIn('name="direction"', page)
        self.assertIn('<option value="random">Random</option>', page)
        for controlled_id in (
            "dataset-network_pack-mixed-1",
            "dataset-network_pack-matching-1",
            "dataset-network_pack-image-1",
        ):
            self.assertIn(
                f'aria-expanded="false" aria-controls="{controlled_id}"', page
            )
            self.assertIn(f'id="{controlled_id}" hidden', page)
        self.assertIn('id="expandAllPacks"', page)
        self.assertIn('id="collapseAllPacks"', page)
        self.assertIn('href="/content-packs">Manage Packs</a>', page)

    def test_normal_catalog_renders_fixed_domain_groups_counts_and_default_filter(self):
        packs = [
            self._pack(id="it-one", domain_group="it"),
            self._pack(id="it-two", domain="information_technology", domain_group="it"),
            self._pack(id="medical", domain="Medical", domain_group="medical"),
            self._pack(id="science", domain="Science", domain_group="other"),
            self._pack(id="legal", domain="Legal", domain_group="law"),
        ]
        page = self._get(packs)

        self.assertIn('role="group" aria-label="Filter installed content by domain"', page)
        self.assertIn('data-domain-filter="all" aria-pressed="true">All <span>5</span>', page)
        self.assertIn('data-domain-filter="it" aria-pressed="false">IT <span>2</span>', page)
        self.assertIn('data-domain-filter="medical" aria-pressed="false">Medical <span>1</span>', page)
        self.assertIn('data-domain-filter="other" aria-pressed="false">Other <span>1</span>', page)
        for group in ("it", "medical", "other", "law"):
            self.assertIn(f'data-domain-group="{group}"', page)
        self.assertNotIn('data-domain-filter="law"', page)
        self.assertIn(
            'id="studyPackResultCount" role="status" aria-live="polite" '
            'aria-atomic="true">5 study packs</strong>',
            page,
        )

    def test_zero_count_domain_filters_are_omitted_and_other_mode_has_no_strip(self):
        only_it = self._get([self._pack(domain_group="it")])
        self.assertIn('data-domain-filter="all"', only_it)
        self.assertIn('data-domain-filter="it"', only_it)
        self.assertNotIn('data-domain-filter="medical"', only_it)
        self.assertNotIn('data-domain-filter="other"', only_it)

        other_page = self._get(
            [self._pack(id="science", domain="Science", domain_group="other")],
            "?domain_group=other",
        )
        self.assertNotIn("study-pack-domain-filters", other_page)
        self.assertNotIn("data-domain-filter", other_page)

    def test_installed_banner_flash_and_requested_pack_state(self):
        packs = [self._pack(id="first"), self._pack(id="installed_pack")]
        with self.client.session_transaction() as session:
            session["_flashes"] = [
                ("success", 'Installed <b id="flashInjected"> safely & ready')
            ]
        page = self._get(packs, "?installed=installed_pack")

        self.assertIn('class="flash success"', page)
        self.assertIn(
            str(escape('Installed <b id="flashInjected"> safely & ready')), page
        )
        self.assertNotIn('<b id="flashInjected">', page)
        self.assertIn(
            '<section class="dashboard-panel study-pack-installed-notice" '
            'aria-label="Newly installed Study Pack">',
            page,
        )
        self.assertIn("<strong>installed_pack</strong>", page)
        self.assertIn('href="#installed-study-pack"', page)
        self.assertIn(
            'id="installed-study-pack" class="dashboard-panel study-pack-section '
            'study-pack-collapsible is-newly-installed"',
            page,
        )

    def test_pack_and_dataset_values_are_html_escaped_at_every_boundary(self):
        hostile = 'value </script><img id="catalogInjected"> & < > "   '
        hostile_id = "pack'\"<id>&"
        dataset_id = "data'\"<id>&"
        pack = self._pack(
            id=hostile_id,
            name=hostile,
            version=hostile,
            description=hostile,
            domain=hostile,
            datasets=[{
                "id": dataset_id,
                "title": hostile,
                "description": hostile,
                "term_count": 2,
                "category": hostile,
            }],
        )
        page = self._get([pack])

        for value in (hostile, hostile_id, dataset_id):
            self.assertIn(str(escape(value)), page)
        self.assertNotIn('<img id="catalogInjected">', page)
        self.assertIn(f'data-pack-id="{escape(hostile_id)}"', page)
        self.assertIn(f'name="pack_id" value="{escape(hostile_id)}"', page)
        self.assertIn(f'name="dataset_id" value="{escape(dataset_id)}"', page)
        self.assertIn(
            f'aria-controls="dataset-{escape(hostile_id)}-matching-1" '
            'onclick="toggleDatasetDetails(this)"',
            page,
        )

    def test_inline_javascript_state_and_serialization_boundaries_are_preserved(self):
        hostile = 'Rendered </script><img id="scriptInjected">   '
        page = self._get([self._pack(name=hostile)])

        self.assertEqual(2, page.count("</script>"))
        inline_script = page.split("<script>", 1)[1].split("</script>", 1)[0]
        self.assertNotIn(hostile, inline_script)
        self.assertNotIn("{{", inline_script)
        self.assertIn("dlms.studyPacks.openState.v1", inline_script)
        self.assertIn("JSON.parse(localStorage.getItem(stateKey)||'{}')", inline_script)
        self.assertIn("localStorage.setItem(stateKey,JSON.stringify(state))", inline_script)
        self.assertIn("installedPack.scrollIntoView", inline_script)
        self.assertIn("expandAllPacks", inline_script)
        self.assertIn("collapseAllPacks", inline_script)
        self.assertIn("function filterPackCatalog(group)", inline_script)
        self.assertIn("pack.hidden=group!=='all'&&pack.dataset.domainGroup!==group", inline_script)
        self.assertIn("visiblePackDetails().forEach(el=>el.open=true)", inline_script)
        self.assertIn("visiblePackDetails().forEach(el=>el.open=false)", inline_script)
        self.assertEqual(1, inline_script.count("localStorage.setItem("))
        self.assertIn("function toggleDatasetDetails(toggle)", inline_script)
        self.assertIn("toggle.setAttribute('aria-expanded',String(open))", inline_script)
        self.assertIn('<script src="/static/nav-normalize.js"></script>', page)

    def test_route_uses_external_template_with_unchanged_context(self):
        packs = [
            self._pack(id="science", domain="Science", domain_group="other"),
            self._pack(id="medical", domain="Medical", domain_group="medical"),
        ]
        with mock.patch.object(
            study_pack_routes, "_study_pack_catalog", return_value=packs
        ), mock.patch.object(
            study_pack_routes, "render_template", return_value="rendered"
        ) as renderer:
            response = self.client.get(
                "/study-packs?domain_group=other&installed=science"
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual("rendered", response.get_data(as_text=True))
        renderer.assert_called_once_with(
            "study_packs/catalog.html",
            packs=[packs[0]],
            medical_pack_installed=True,
            other_mode=True,
            installed_pack_id="science",
            total_pack_count=1,
            domain_filter_counts={"other": 1},
        )
        self.assertTrue(
            (Path(dlms.TEMPLATE_ROOT) / "study_packs" / "catalog.html").is_file()
        )


if __name__ == "__main__":
    unittest.main()

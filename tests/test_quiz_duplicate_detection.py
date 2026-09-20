"""DLMS-132 advisory duplicate-question detection regressions."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms
from dlms.services.quiz_duplicates import build_quiz_duplicate_report
from tests.current_schema import seed_current_quiz


class QuizDuplicateDetectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dlms-132-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        paths = {
            "APP_DATA_DIR": self.root,
            "DATA_FOLDER": self.root / "data",
            "QUIZ_FOLDER": self.root / "quizzes",
            "CONFIG_FOLDER": self.root / "config",
            "QUIZ_REGISTRY": self.root / "config" / "quizzes.json",
            "DB_PATH": self.root / "results.db",
            "QUIZ_ASSET_FOLDER": self.root / "quiz_assets",
            "LOGO_FOLDER": self.root / "static" / "logos",
        }
        for name, path in paths.items():
            patcher = mock.patch.object(dlms, name, str(path))
            patcher.start()
            self.addCleanup(patcher.stop)
            if name not in {"QUIZ_REGISTRY", "DB_PATH", "APP_DATA_DIR"}:
                path.mkdir(parents=True, exist_ok=True)
        self.assertTrue(dlms._initialize_data_root_ownership(str(self.root)))
        dlms.ensure_db_initialized()
        dlms.save_registry([])

    @staticmethod
    def _choice(text, *, number=1, choices=None):
        return {
            "number": number,
            "question": text,
            "choices": choices or [
                {"label": "A", "text": "Secure Shell", "is_correct": True},
                {"label": "B", "text": "File Transfer", "is_correct": False},
                {"label": "C", "text": "Name Service", "is_correct": False},
            ],
        }

    @staticmethod
    def _matching(text, *, number=1, pairs=None, direction="term_to_definition"):
        return {
            "number": number,
            "type": "matching",
            "question": text,
            "direction": direction,
            "round_size": 2,
            "pairs": pairs or [
                {"left": "Alpha", "right": "First definition"},
                {"left": "Beta", "right": "Second definition"},
            ],
        }

    def _seed(self, title, source_file, questions, *, folder="Uncategorized"):
        quiz_id = seed_current_quiz(dlms.get_db, title, source_file, questions)
        registry = dlms.load_registry()
        registry.append({
            "id": quiz_id,
            "title": title,
            "html": source_file,
            "folder": folder,
            "exam_minutes": 90,
        })
        dlms.save_registry(registry)
        return quiz_id

    def _report(self):
        connection = dlms.get_db()
        try:
            return build_quiz_duplicate_report(
                connection.cursor(), dlms.load_registry()
            )
        finally:
            connection.close()

    def test_exact_duplicates_across_quizzes_use_case_whitespace_and_response_structure(self):
        self._seed(
            "First Bank", "first.html",
            [self._choice("Which protocol provides secure remote access?")],
            folder="Networking",
        )
        self._seed(
            "Second Bank", "second.html",
            [self._choice("  WHICH protocol provides   secure remote access?  ")],
            folder="Security",
        )

        report = self._report()

        self.assertEqual(2, report["scanned_question_count"])
        self.assertEqual(2, report["scanned_quiz_count"])
        self.assertEqual(1, report["exact_group_count"])
        self.assertEqual(0, report["near_group_count"])
        locations = report["exact_groups"][0]["questions"]
        self.assertEqual(["First Bank", "Second Bank"], [item["quiz_title"] for item in locations])
        self.assertEqual(["Networking", "Security"], [item["folder"] for item in locations])

    def test_duplicate_questions_within_one_quiz_are_reported_separately(self):
        self._seed(
            "Repeated Bank",
            "repeated.html",
            [
                self._choice("Which protocol provides secure remote access?", number=1),
                self._choice("Which protocol provides secure remote access?", number=2),
            ],
        )

        group = self._report()["exact_groups"][0]

        self.assertEqual([1, 2], [item["question_number"] for item in group["questions"]])
        self.assertEqual(1, len({item["quiz_id"] for item in group["questions"]}))

    def test_different_types_or_answer_structures_are_not_exact_duplicates(self):
        stem = "Which items belong together in this neutral exercise?"
        self._seed("Choice Bank", "choice.html", [self._choice(stem)])
        self._seed("Matching Bank", "matching.html", [self._matching(stem)])
        self._seed(
            "Different Answers",
            "different.html",
            [self._choice(stem, choices=[
                {"label": "A", "text": "Different answer", "is_correct": True},
                {"label": "B", "text": "Another answer", "is_correct": False},
            ])],
        )

        report = self._report()

        self.assertEqual(0, report["exact_group_count"])
        self.assertEqual(0, report["near_group_count"])

    def test_generated_quiz_copies_are_excluded_as_independent_duplicates(self):
        stem = "Which protocol provides secure remote access?"
        self._seed("Source Bank", "source.html", [self._choice(stem)])
        self._seed("Smart Review — Source Bank", "smart_review_123.html", [self._choice(stem)])
        self._seed("Adaptive Copy", "adaptive_study_456.html", [self._choice(stem)])

        report = self._report()

        self.assertEqual(1, report["scanned_question_count"])
        self.assertEqual(2, report["excluded_generated_count"])
        self.assertEqual([], report["exact_groups"])
        self.assertEqual([], report["near_groups"])

    def test_conservative_near_duplicate_requires_same_complete_response_structure(self):
        self._seed(
            "Original Wording", "original.html",
            [self._choice("Which command displays the active network configuration?")],
        )
        self._seed(
            "Minor Rewrite", "rewrite.html",
            [self._choice("Which command displays active network configuration?")],
        )

        report = self._report()

        self.assertEqual(0, report["exact_group_count"])
        self.assertEqual(1, report["near_group_count"])
        pair = report["near_groups"][0]
        self.assertEqual("Original Wording", pair["left"]["questions"][0]["quiz_title"])
        self.assertEqual("Minor Rewrite", pair["right"]["questions"][0]["quiz_title"])
        self.assertEqual(
            "Very similar wording with the same answer structure", pair["reason"]
        )
        html = dlms.app.test_client().get('/library/duplicates').get_data(as_text=True)
        self.assertIn('id="nearDuplicateHeading"', html)
        self.assertNotIn('id="exactDuplicateHeading"', html)
        self.assertIn('details class="dashboard-panel duplicate-question-group" open', html)

    def test_near_duplicate_resists_shared_terms_negation_and_answer_differences(self):
        self._seed(
            "Web Bank", "web.html",
            [self._choice("Which protocol protects web traffic during transit?")],
        )
        self._seed(
            "Mail Bank", "mail.html",
            [self._choice("Which protocol protects email traffic during transit?")],
        )
        self._seed(
            "Negated Bank", "negated.html",
            [self._choice("Which protocol does not protect web traffic during transit?")],
        )
        self._seed(
            "Changed Responses",
            "changed.html",
            [self._choice(
                "Which protocol protects web traffic during network transit?",
                choices=[
                    {"label": "A", "text": "Transport Security", "is_correct": True},
                    {"label": "B", "text": "Remote Shell", "is_correct": False},
                ],
            )],
        )

        self.assertEqual([], self._report()["near_groups"])

    def test_matching_questions_compare_pairs_and_direction_without_cross_type_matches(self):
        pairs_reordered = [
            {"left": " beta ", "right": "SECOND DEFINITION"},
            {"left": "ALPHA", "right": "first   definition"},
        ]
        stem = "Match each neutral term with its definition."
        self._seed("Matching One", "matching-one.html", [self._matching(stem)])
        self._seed(
            "Matching Two", "matching-two.html",
            [self._matching("  MATCH each neutral term with its definition. ", pairs=pairs_reordered)],
        )
        self._seed(
            "Reverse Direction", "matching-reverse.html",
            [self._matching(stem, direction="definition_to_term")],
        )

        report = self._report()

        self.assertEqual(1, report["exact_group_count"])
        self.assertEqual(
            {"Matching One", "Matching Two"},
            {item["quiz_title"] for item in report["exact_groups"][0]["questions"]},
        )
        self.assertEqual(0, report["near_group_count"])

    def test_empty_report_and_repeated_scans_are_stable_and_read_only(self):
        self._seed(
            "Unique Bank", "unique.html",
            [self._choice("Which unique item has no similar neighbor in this library?")],
        )
        connection = dlms.get_db()
        before = tuple(connection.execute(
            "SELECT id, quiz_id, question_text FROM questions ORDER BY id"
        ).fetchall())
        connection.close()

        first = self._report()
        second = self._report()

        self.assertEqual(first, second)
        self.assertEqual([], first["exact_groups"])
        self.assertEqual([], first["near_groups"])
        connection = dlms.get_db()
        after = tuple(connection.execute(
            "SELECT id, quiz_id, question_text FROM questions ORDER BY id"
        ).fetchall())
        connection.close()
        self.assertEqual(before, after)

        dlms.save_registry([])
        empty = self._report()
        self.assertEqual(0, empty["scanned_question_count"])
        self.assertEqual([], empty["exact_groups"])
        self.assertEqual([], empty["near_groups"])

    def test_quiz_library_links_to_advisory_report_with_manual_edit_actions(self):
        stem = "Which protocol provides secure remote access?"
        first_quiz = self._seed(
            "First UI Bank", "ui-first.html", [self._choice(stem)], folder="IT"
        )
        second_quiz = self._seed(
            "Second UI Bank", "ui-second.html", [self._choice(stem)], folder="Review"
        )
        client = dlms.app.test_client()

        library_html = client.get("/library").get_data(as_text=True)
        response = client.get("/library/duplicates")
        html = response.get_data(as_text=True)

        self.assertEqual(200, response.status_code)
        self.assertIn('href="/library/duplicates">Find Duplicates</a>', library_html)
        self.assertIn("Duplicate Question Review", html)
        self.assertIn("Exact duplicates", html)
        self.assertIn("First UI Bank", html)
        self.assertIn("Second UI Bank", html)
        self.assertIn(f'href="/edit_quiz/{first_quiz}"', html)
        self.assertIn(f'href="/edit_quiz/{second_quiz}"', html)
        self.assertIn("nothing is merged, deleted, or rewritten", html)
        self.assertNotIn("Merge", html)

    def test_filtered_page_keeps_summary_and_source_content_unchanged(self):
        first = self._seed('Repeated Bank', 'first.html', [self._choice('Same source question')], folder='Uncategorized')
        self._seed('Other Bank', 'second.html', [self._choice('Same source question')], folder='Custom')
        connection = dlms.get_db()
        before = list(connection.iterdump())
        connection.close()
        client = dlms.app.test_client()
        html = client.get('/library/duplicates', query_string={'quiz': first, 'folder': 'Custom', 'search': 'same'}).get_data(as_text=True)
        self.assertIn('details class="dashboard-panel duplicate-question-group" open', html)
        self.assertIn('Expand all on page', html)
        self.assertIn('Collapse all on page', html)
        self.assertIn('Showing 1–1 of 1 matching group', html)
        empty = client.get('/library/duplicates?search=nonexistent').get_data(as_text=True)
        self.assertIn('No matching groups', empty)
        self.assertNotIn('details class="dashboard-panel duplicate-question-group"', empty)
        connection = dlms.get_db()
        try:
            self.assertEqual(before, list(connection.iterdump()))
        finally:
            connection.close()

    def test_large_report_is_paginated_before_rendering(self):
        self._seed('First', 'first.html', [self._choice('Repeated question')])
        self._seed('Second', 'second.html', [self._choice('Repeated question')])
        report = self._report()
        report['exact_groups'] *= 221
        report['exact_group_count'] = 221
        with mock.patch.object(dlms._quiz_duplicate_service, 'build_quiz_duplicate_report', return_value=report):
            html = dlms.app.test_client().get('/library/duplicates').get_data(as_text=True)
            self.assertEqual(20, html.count('details class="dashboard-panel duplicate-question-group"'))
            self.assertNotIn('duplicate-question-group" open', html)
            self.assertIn('Showing 1–20 of 221 matching groups', html)
            self.assertIn('Next page', html)
            self.assertEqual(221, len(report['exact_groups']))

    def test_result_type_route_preserves_scan_and_filters_before_pagination(self):
        first = self._seed('Source Bank', 'first.html', [self._choice('Repeated question')], folder='CISM')
        self._seed('Second Bank', 'second.html', [self._choice('Repeated question')])
        self._seed('Original', 'original.html', [self._choice('Which command displays the active network configuration?')], folder='CISM')
        self._seed('Rewrite', 'rewrite.html', [self._choice('Which command displays active network configuration?')])
        report = self._report()
        self.assertEqual((1, 1), (report['exact_group_count'], report['near_group_count']))
        report['exact_groups'] *= 221
        report['near_groups'] *= 38
        report['exact_group_count'], report['near_group_count'] = 221, 38
        connection = dlms.get_db()
        before = list(connection.iterdump())
        connection.close()
        client = dlms.app.test_client()
        with mock.patch.object(dlms._quiz_duplicate_service, 'build_quiz_duplicate_report', return_value=report):
            possible = client.get('/library/duplicates?result_type=possible&page=13').get_data(as_text=True)
            self.assertIn('Showing 21–38 of 38 possible matches', possible)
            self.assertIn('id="nearDuplicateHeading"', possible)
            self.assertNotIn('id="exactDuplicateHeading"', possible)
            self.assertIn('value="possible" selected', possible)
            self.assertIn('result_type=possible&amp;', possible)
            self.assertNotIn('name="page"', possible)  # Applying filters starts at page one.
            for total in (221, 38):
                self.assertIn(f'<strong>{total}</strong>', possible)
            exact = client.get('/library/duplicates', query_string=dict(result_type='exact', quiz=first, folder='CISM', search='Repeated', page=2)).get_data(as_text=True)
            self.assertIn('Showing 21–40 of 221 exact duplicate groups', exact)
            self.assertIn('id="exactDuplicateHeading"', exact)
            self.assertNotIn('id="nearDuplicateHeading"', exact)
            empty = client.get('/library/duplicates', query_string=dict(result_type='possible', quiz=first)).get_data(as_text=True)
            self.assertIn('No matching groups', empty)
            reset = client.get('/library/duplicates').get_data(as_text=True)
            self.assertIn('value="all" selected', reset)
            self.assertIn('Showing 1–20 of 259 matching groups', reset)
        connection = dlms.get_db()
        try:
            self.assertEqual(before, list(connection.iterdump()))
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()

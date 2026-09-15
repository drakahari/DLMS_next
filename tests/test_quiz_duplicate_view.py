"""Presentation filtering/pagination must not change duplicate detection data."""

import copy
import unittest

from dlms.services.quiz_duplicate_view import duplicate_report_view


class DuplicateReportViewTests(unittest.TestCase):
    def _report(self, count=1):
        def record(quiz, text, folder):
            return dict(quiz_id=quiz, quiz_title='Same title', question_text=text, folder=folder)
        exact = [dict(question_type='choice', questions=[
            record(1, f'Question {index} secure access', 'Uncategorized'),
            record(2, f'Question {index} secure access', 'Custom'),
        ]) for index in range(count)]
        near = [dict(left=dict(questions=[record(3, 'Possible candidate', 'Other')]),
                     right=dict(questions=[record(4, 'Another candidate', 'Other')]))]
        return dict(exact_groups=exact, near_groups=near, exact_group_count=count,
                    near_group_count=1, scanned_question_count=count * 2 + 2,
                    scanned_quiz_count=4, excluded_generated_count=0)

    def test_filters_use_group_membership_and_combine_with_search(self):
        report = self._report()
        before = copy.deepcopy(report)
        for args, exact, near in [({}, 1, 1), ({'quiz': '2'}, 1, 0),
                                  ({'folder': 'Other'}, 0, 1),
                                  ({'quiz': '2', 'folder': 'Custom', 'search': 'SECURE'}, 1, 0),
                                  ({'search': 'same title'}, 1, 1),
                                  ({'quiz': '2', 'search': 'possible'}, 0, 0)]:
            with self.subTest(args=args):
                view = duplicate_report_view(report, args)
                self.assertEqual(exact, len(view['report']['exact_groups']))
                self.assertEqual(near, len(view['report']['near_groups']))
                self.assertEqual(1, view['report']['exact_group_count'])
                self.assertEqual(4, len(view['duplicate_view']['quizzes']))
        self.assertEqual(before, report)

    def test_large_results_render_twenty_groups_in_canonical_order(self):
        report = self._report(221)
        report['near_groups'] *= 38
        report['near_group_count'] = 38
        before = copy.deepcopy(report)
        first = duplicate_report_view(report, {})
        self.assertEqual(259, first['duplicate_view']['matched_count'])
        self.assertFalse(first['duplicate_view']['expanded'])
        self.assertEqual(report['exact_groups'][:20], first['report']['exact_groups'])
        last = duplicate_report_view(report, {'page': '9999'})
        self.assertEqual(13, last['duplicate_view']['page'])
        self.assertEqual(19, len(last['report']['near_groups']))
        self.assertFalse(last['report']['exact_groups'])
        for page in ('invalid', '-1'):
            self.assertEqual(1, duplicate_report_view(report, {'page': page})['duplicate_view']['page'])
        self.assertEqual(before, report)

    def test_small_results_expand_and_links_preserve_filters(self):
        view = duplicate_report_view(self._report(25), {'quiz': '1', 'folder': 'Uncategorized', 'search': 'secure'})
        self.assertIn('quiz=1&folder=Uncategorized&search=secure&page=2', view['duplicate_view']['next_url'])
        self.assertTrue(duplicate_report_view(self._report(), {})['duplicate_view']['expanded'])

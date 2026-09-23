import inspect
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from tests.browser._bidi import FirefoxBidi
from tests.browser import test_critical_workflows as browser_workflows


class BrowserHarnessStructureTests(unittest.TestCase):
    def test_server_data_and_bidi_session_are_workflow_scoped(self):
        self.assertEqual(
            "function",
            browser_workflows.browser_server._fixture_function_marker.scope,
        )
        self.assertEqual(
            "function",
            browser_workflows.browser_stack._fixture_function_marker.scope,
        )

    def test_browser_and_server_fixtures_keep_failure_safe_cleanup(self):
        browser_source = inspect.getsource(browser_workflows.browser_stack)
        self.assertIn("finally:", browser_source)
        self.assertIn("browser.close()", browser_source)
        self.assertIn("_terminate_process_tree(browser_process)", browser_source)
        self.assertIn("shutil.rmtree(session_root, ignore_errors=True)", browser_source)

        server_source = inspect.getsource(browser_workflows.browser_server)
        self.assertIn("finally:", server_source)
        self.assertIn("_terminate_process_tree(server_process)", server_source)
        self.assertIn("shutil.rmtree(work_root, ignore_errors=True)", server_source)

    def test_cross_tab_close_waits_for_pagehide_checkpoint(self):
        helper_source = inspect.getsource(
            browser_workflows._close_context_after_pagehide
        )
        self.assertIn("addEventListener('pagehide'", helper_source)
        self.assertIn("localStorage.setItem", helper_source)
        self.assertIn("browser.wait_for", helper_source)

        workflow_source = inspect.getsource(
            browser_workflows.test_quiz_recovery_rejects_bad_state_and_enforces_single_writer
        )
        self.assertIn("_close_context_after_pagehide", workflow_source)

    def test_restore_workflow_observes_prior_async_boundaries(self):
        workflow_source = inspect.getsource(
            browser_workflows.test_restore_confirmation_and_success_replace_live_quiz_state
        )
        self.assertIn("studyLearningEventSaves.size === 0", workflow_source)
        self.assertGreaterEqual(workflow_source.count("wait_for_page_ready"), 3)

    def test_clicks_use_live_element_origin_instead_of_stale_coordinates(self):
        click_source = inspect.getsource(FirefoxBidi.click)
        self.assertIn("wait_for_page_ready", click_source)
        self.assertIn('"type": "element"', click_source)
        self.assertIn('"sharedId": shared_id', click_source)
        self.assertNotIn("getBoundingClientRect", click_source)


class BrowserReadinessTests(unittest.TestCase):
    def test_cold_listener_and_session_share_startup_budget(self):
        clock = [0.0]
        client = mock.Mock()

        def connect(*args, **kwargs):
            if clock[0] < 13:
                raise ConnectionRefusedError('listener not ready')
            return client

        def start_session(*, timeout):
            self.assertGreater(timeout, 9)
            self.assertLess(timeout, 18)
            clock[0] += 9

        client.start_session.side_effect = start_session
        with mock.patch.object(browser_workflows.time, 'monotonic', side_effect=lambda: clock[0]), mock.patch.object(
            browser_workflows.time, 'sleep', side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds)
        ), mock.patch.object(FirefoxBidi, 'connect', side_effect=connect):
            result = browser_workflows._connect_firefox(1234, mock.Mock(poll=lambda: None), Path('unused.log'))
        self.assertIs(result, client)
        client.close.assert_not_called()

    def test_startup_failure_closes_connected_client_and_reports_log(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / 'firefox.log'
            log.write_text('session initialization failed')
            client = mock.Mock()
            client.start_session.side_effect = TimeoutError('session timeout')
            with mock.patch.object(browser_workflows.time, 'monotonic', side_effect=[0, 0, 0, 0, 31]), mock.patch.object(
                browser_workflows.time, 'sleep'
            ), mock.patch.object(FirefoxBidi, 'connect', return_value=client):
                with self.assertRaisesRegex(RuntimeError, 'session initialization failed'):
                    browser_workflows._connect_firefox(1234, mock.Mock(poll=lambda: None), log)
            client.close.assert_called_once()

    def test_bank_document_can_become_ready_after_default_six_seconds(self):
        clock = [0.0]
        browser = FirefoxBidi(mock.Mock())
        expressions = []

        def evaluate(expression):
            expressions.append(expression)
            return clock[0] >= 8

        with mock.patch.object(browser, 'evaluate', side_effect=evaluate), mock.patch.object(
            browser_workflows.time, 'monotonic', side_effect=lambda: clock[0]
        ), mock.patch.object(browser_workflows.time, 'sleep', side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds)):
            browser_workflows._wait_for_reviewed_pdf_bank(SimpleNamespace(browser=browser))
        self.assertGreaterEqual(clock[0], 8)
        self.assertLess(clock[0], 9)
        self.assertTrue(all("document.readyState === 'complete'" in e and '.pdf-bank-question-table' in e for e in expressions))

    def test_bank_timeout_still_fails_with_file_present_and_keeps_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bank_dir = root / 'data-root/pdf_question_banks'
            bank_dir.mkdir(parents=True)
            (bank_dir / 'saved-bank.json').write_text('{}')
            (root / 'server.log').write_text('POST /pdf-import/save/draft 302')
            browser = mock.Mock()
            browser.wait_for_page_ready.side_effect = TimeoutError('not ready')
            browser.evaluate.return_value = {'url': '/pdf-import/review/draft', 'invalid': ['quiz_title']}
            stack = SimpleNamespace(browser=browser, data_root=root / 'data-root')
            with self.assertRaises(TimeoutError) as caught:
                browser_workflows._wait_for_reviewed_pdf_bank(stack)
            message = str(caught.exception)
            for evidence in ('saved-bank.json', 'POST /pdf-import/save/draft 302', 'quiz_title', '/pdf-import/review/draft'):
                self.assertIn(evidence, message)
            browser.click.assert_not_called()


if __name__ == "__main__":
    unittest.main()

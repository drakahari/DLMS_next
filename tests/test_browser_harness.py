import inspect
import unittest

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


if __name__ == "__main__":
    unittest.main()

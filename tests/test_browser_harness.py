import inspect
import unittest

from tests.browser import test_critical_workflows as browser_workflows


class BrowserHarnessStructureTests(unittest.TestCase):
    def test_server_is_module_scoped_but_bidi_session_is_workflow_scoped(self):
        self.assertEqual(
            "module",
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


if __name__ == "__main__":
    unittest.main()

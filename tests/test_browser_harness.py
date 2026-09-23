import inspect
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from tests.browser._bidi import FirefoxBidi
from tests.browser import test_critical_workflows as browser_workflows


class BrowserHarnessStructureTests(unittest.TestCase):
    def test_local_launch_stays_headless_even_with_desktop_display(self):
        for env in ({}, {"DISPLAY": ":0"}, {"DLMS_FIREFOX_MODE": "headless"}):
            with self.subTest(env=env):
                self.assertEqual(
                    browser_workflows._firefox_command("firefox", Path("profile"), 1234, env),
                    ["firefox", "--headless", "--no-remote", "--profile", "profile",
                     "--remote-debugging-port", "1234", "about:blank"],
                )

    def test_virtual_display_launch_omits_only_headless_argument(self):
        env = {"DLMS_FIREFOX_MODE": "xvfb", "DISPLAY": ":99", "XAUTHORITY": "/tmp/auth",
               "WAYLAND_DISPLAY": "wayland-1", "WAYLAND_SOCKET": "4",
               "GDK_BACKEND": "wayland,x11", "MOZ_ENABLE_WAYLAND": "1"}
        with mock.patch.object(browser_workflows, "_require_private_xvfb") as require:
            command = browser_workflows._firefox_command("firefox", Path("profile"), 1234, env)
        require.assert_called_once_with(env)
        self.assertEqual(env["DISPLAY"], ":99")
        self.assertEqual(env["GDK_BACKEND"], "x11")
        self.assertEqual(env["MOZ_ENABLE_WAYLAND"], "0")
        self.assertNotIn("WAYLAND_DISPLAY", env)
        self.assertNotIn("WAYLAND_SOCKET", env)
        local = browser_workflows._firefox_command("firefox", Path("profile"), 1234, {})
        local.remove("--headless")
        self.assertEqual(command, local)

    def test_default_launch_removes_physical_display_access(self):
        env = {"DISPLAY": ":0", "XAUTHORITY": "/tmp/desktop-auth", "WAYLAND_DISPLAY": "wayland-1",
               "WAYLAND_SOCKET": "4", "GDK_BACKEND": "wayland,x11", "MOZ_ENABLE_WAYLAND": "1"}
        command = browser_workflows._firefox_command("firefox", Path("profile"), 1234, env)
        self.assertIn("--headless", command)
        for name in ("DISPLAY", "XAUTHORITY", "WAYLAND_DISPLAY", "WAYLAND_SOCKET"):
            self.assertNotIn(name, env)
        self.assertEqual(env["GDK_BACKEND"], "x11")
        self.assertEqual(env["MOZ_ENABLE_WAYLAND"], "0")

    def test_xvfb_requires_matching_live_virtual_server_not_desktop_or_stale_marker(self):
        env = {"DISPLAY": ":99", "XAUTHORITY": "/tmp/auth"}
        for comm, command, valid in (
            ("Xvfb\n", "Xvfb\0:99\0-screen\0", True),
            ("Xorg\n", "Xorg\0:99\0", False),
            ("Xwayland\n", "Xwayland\0:99\0", False),
            ("Xvfb\n", "Xvfb\0:100\0", False),
        ):
            with self.subTest(comm=comm, command=command), mock.patch.object(Path, "is_file", return_value=True), mock.patch.object(
                Path, "read_text", side_effect=["12345", comm, command]
            ):
                if valid:
                    browser_workflows._require_private_xvfb(env)
                else:
                    with self.assertRaises(ValueError):
                        browser_workflows._require_private_xvfb(env)
        with mock.patch.object(Path, "is_file", return_value=True), mock.patch.object(Path, "read_text", side_effect=FileNotFoundError):
            with self.assertRaises(ValueError):
                browser_workflows._require_private_xvfb(env)

    def test_all_five_browser_launch_sites_use_the_guarded_command_and_child_env(self):
        import ast
        module = ast.parse(inspect.getsource(browser_workflows))
        launches = [node for node in ast.walk(module) if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute) and node.func.attr == "Popen"
                    and node.args and isinstance(node.args[0], ast.Call)
                    and isinstance(node.args[0].func, ast.Name) and node.args[0].func.id == "_firefox_command"]
        self.assertEqual(len(launches), 5)
        for launch in launches:
            child_env = next(keyword.value for keyword in launch.keywords if keyword.arg == "env")
            self.assertEqual(ast.dump(launch.args[0].args[-1]), ast.dump(child_env))

    def test_manual_and_demo_capture_launcher_is_unconditionally_headless(self):
        import ast
        root = Path(__file__).resolve().parents[1]
        module = ast.parse((root / "tools/capture_user_manual_screenshots.py").read_text())
        launch = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == "_start_firefox")
        processes = [node for node in ast.walk(launch) if isinstance(node, ast.Call)
                     and isinstance(node.func, ast.Attribute) and node.func.attr == "Popen"]
        self.assertEqual(len(processes), 1)
        self.assertIsInstance(processes[0].args[0], ast.List)
        self.assertIn("--headless", [node.value for node in processes[0].args[0].elts if isinstance(node, ast.Constant)])

    def test_invalid_or_conflicting_display_modes_fail_before_launch(self):
        for env in (
            {"DLMS_FIREFOX_MODE": "typo"},
            {"DLMS_FIREFOX_MODE": "xvfb"},
            {"DLMS_FIREFOX_MODE": "xvfb", "DISPLAY": ":99", "MOZ_HEADLESS": "1"},
            {"DLMS_FIREFOX_MODE": "xvfb", "DISPLAY": ":99", "MOZ_HEADLESS": "0"},
        ):
            with self.subTest(env=env), self.assertRaises(ValueError):
                browser_workflows._firefox_command("firefox", Path("profile"), 1234, env)

    def test_browser_fixture_cleans_process_and_profile_after_startup_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            server = SimpleNamespace(
                work_root=Path(directory), firefox="firefox", env={}, process_options={},
            )
            process = mock.Mock()
            with mock.patch.object(browser_workflows.subprocess, "Popen", return_value=process), mock.patch.object(
                browser_workflows, "_connect_firefox", side_effect=RuntimeError("startup failed")
            ), mock.patch.object(browser_workflows, "_free_loopback_port", return_value=1234), mock.patch.object(
                browser_workflows, "_terminate_process_tree"
            ) as terminate:
                fixture = browser_workflows.browser_stack.__wrapped__(server)
                with self.assertRaisesRegex(RuntimeError, "startup failed"):
                    next(fixture)
                terminate.assert_called_once_with(process)
            self.assertEqual(list(Path(directory).iterdir()), [])

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
    def test_review_submit_loads_and_decodes_each_lazy_preview_before_click(self):
        browser = mock.Mock()
        browser.evaluate.side_effect = [True, 2, True, True, True, True]
        stack = SimpleNamespace(browser=browser)
        with mock.patch.object(browser_workflows, '_wait_for_reviewed_pdf_bank') as bank_ready:
            browser_workflows._submit_reviewed_pdf_bank(stack)
        calls = browser.method_calls
        self.assertEqual([call[0] for call in calls], [
            'evaluate', 'evaluate', 'evaluate', 'wait_for', 'evaluate',
            'evaluate', 'wait_for', 'evaluate', 'click',
        ])
        for index, position in enumerate((3, 6)):
            condition = calls[position].args[0]
            self.assertIn(f'[{index}].complete', condition)
            self.assertIn('naturalWidth > 0', condition)
            self.assertIn('.decode()', calls[position + 1].args[0])
        browser.click.assert_called_once_with('#pdfReviewForm button[type=submit]:not([formaction])')
        bank_ready.assert_called_once_with(stack)

    def test_review_submit_does_not_click_when_preview_readiness_fails(self):
        browser = mock.Mock()
        browser.evaluate.side_effect = [True, 1, True, {'disabled': False, 'events': []}]
        browser.wait_for.side_effect = TimeoutError('image not loaded')
        with self.assertRaisesRegex(RuntimeError, 'image not loaded') as caught:
            browser_workflows._submit_reviewed_pdf_bank(SimpleNamespace(browser=browser))
        browser.click.assert_not_called()
        self.assertIn("'events': []", str(caught.exception))

    def test_review_submit_keeps_trace_and_bank_failure_without_retry(self):
        browser = mock.Mock()
        browser.evaluate.side_effect = [True, 0, {'events': [{'type': 'click', 'defaultPrevented': True}]}]
        with mock.patch.object(browser_workflows, '_wait_for_reviewed_pdf_bank', side_effect=TimeoutError('no bank; server log')):
            with self.assertRaisesRegex(RuntimeError, 'no bank; server log') as caught:
                browser_workflows._submit_reviewed_pdf_bank(SimpleNamespace(browser=browser))
        browser.click.assert_called_once()
        self.assertIn("'defaultPrevented': True", str(caught.exception))

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
                with self.assertRaisesRegex(RuntimeError, 'session initialization failed') as caught:
                    browser_workflows._connect_firefox(1234, mock.Mock(poll=lambda: None), log)
            client.close.assert_called_once()
            self.assertIn('during session initialization', str(caught.exception))
            self.assertIn('budget=30.0s', str(caught.exception))
            self.assertIn('command=', str(caught.exception))

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

"""Bounded macOS application/browser adapters; no external app is opened."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from desktop import macos_browser


@unittest.skipUnless(sys.platform == 'darwin', 'macOS platform adapter')
class MacBrowserTests(unittest.TestCase):
    def test_handoff_uses_system_open_and_real_home_without_scoped_environment(self):
        scoped = {'HOME': '/synthetic/scoped', 'PATH': '/synthetic/bin',
                  'DLMS_SECRET': 'synthetic', 'QUIZAPP_DATA_DIR': '/private/synthetic',
                  'QT_PLUGIN_PATH': '/synthetic/plugins', 'XDG_CONFIG_HOME': '/synthetic/config',
                  'PYTHONPATH': '/synthetic/modules', 'DYLD_LIBRARY_PATH': '/synthetic/libraries',
                  'TMPDIR': '/synthetic/tmp', 'LANG': 'en_US.UTF-8'}
        with patch.dict(os.environ, scoped, clear=True), patch.object(macos_browser, 'real_home', return_value=Path('/synthetic/account')):
            with patch.object(macos_browser.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
                self.assertTrue(macos_browser.dispatch('https://example.invalid/allowed?q=synthetic'))
        args, kwargs = run.call_args
        self.assertEqual(args[0], ['/usr/bin/open', '--', 'https://example.invalid/allowed?q=synthetic'])
        self.assertEqual(kwargs['env'], {'HOME': '/synthetic/account', 'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'LANG': 'en_US.UTF-8'})
        self.assertIs(kwargs['stdin'], subprocess.DEVNULL)
        self.assertIs(kwargs['stdout'], subprocess.DEVNULL)
        self.assertTrue(kwargs['close_fds'])
        self.assertEqual(kwargs['timeout'], 10)

    def test_unsupported_destinations_are_refused_before_launch(self):
        invalid = ('file:///synthetic/private.txt', 'javascript:alert(1)', 'https:///missing-host',
                   'https://user:password@example.invalid/', 'https://example.invalid/\nunsafe',
                   'https://example.invalid/\x7funsafe')
        with patch.object(macos_browser.subprocess, 'run') as run:
            for value in invalid:
                with self.subTest(value=value), self.assertRaises(ValueError):
                    macos_browser.dispatch(value)
        run.assert_not_called()

    def test_launch_refusal_is_reported_as_false(self):
        with patch.object(macos_browser.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1)):
            self.assertFalse(macos_browser.dispatch('https://example.invalid/'))

    def test_launch_timeout_uses_shared_visible_error_contract(self):
        timeout = subprocess.TimeoutExpired(['/usr/bin/open'], 10)
        with patch.object(macos_browser.subprocess, 'run', side_effect=timeout):
            # shell.handoff_external owns visible OSError/ValueError feedback.
            with self.assertRaises(OSError):
                macos_browser.dispatch('https://example.invalid/')


try:
    from PySide6.QtCore import QEvent, QTimer, Qt
    from PySide6.QtGui import QAction, QKeySequence
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QMainWindow, QMessageBox
    from desktop.macos_application import MacApplication
except ImportError:
    MacApplication = None


@unittest.skipUnless(sys.platform == 'darwin' and MacApplication is not None, 'native Qt application adapter requires project environment')
class MacApplicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.platform_scope = patch.dict(os.environ, {'QT_QPA_PLATFORM': 'offscreen'})
        cls.platform_scope.start()
        cls.application = MacApplication.instance() or MacApplication(['dlms-native-adapter-unit'])

    @classmethod
    def tearDownClass(cls):
        cls.application.desktop_window = None
        cls.platform_scope.stop()

    def setUp(self):
        class SyntheticWindow(QMainWindow):
            def __init__(self):
                super().__init__()
                self._closing = False
                self.allow_close = False
                self.close_requests = 0

            def closeEvent(self, event):
                self.close_requests += 1
                if self.allow_close:
                    self._closing = True
                    event.accept()
                else:
                    event.ignore()

        self.window = SyntheticWindow()
        self.application.bind_window(self.window)
        self.window.show()

    def tearDown(self):
        self.application.desktop_window = None
        self.window.allow_close = True
        self.window.close()
        self.window.deleteLater()

    def test_native_quit_runs_close_refusal_and_keeps_window_alive(self):
        event = QEvent(QEvent.Type.Quit)
        self.assertTrue(self.application.event(event))
        self.assertEqual(self.window.close_requests, 1)
        self.assertTrue(self.window.isVisible())
        self.assertFalse(self.window._closing)

    def test_native_quit_runs_accepted_close(self):
        self.window.allow_close = True
        self.application.event(QEvent(QEvent.Type.Quit))
        self.assertEqual(self.window.close_requests, 1)
        self.assertFalse(self.window.isVisible())
        self.assertTrue(self.window._closing)

    def test_cmd_q_action_has_native_role_and_keeps_close_refusal(self):
        actions = [action for action in self.window.findChildren(QAction)
                   if action.menuRole() == QAction.MenuRole.QuitRole]
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].shortcut(), QKeySequence(QKeySequence.StandardKey.Quit))
        actions[0].trigger()
        self.assertEqual(self.window.close_requests, 1)
        self.assertTrue(self.window.isVisible())

    def test_activation_reopens_hidden_existing_window(self):
        self.window.hide()
        self.application.event(QEvent(QEvent.Type.ApplicationActivate))
        self.assertTrue(self.window.isVisible())
        self.assertEqual(self.window.close_requests, 0)

    def test_server_close_body_safe_defaults_and_all_choices_on_macos(self):
        from desktop.shell import DesktopWindow
        # Native macOS QMessageBox suppresses its title; qualify the visible
        # body/defaults and actual decisions without assuming a Linux titlebar.
        for action, accepted in (('enter', False), ('escape', False),
                                 ('keep', False), ('close', True)):
            with self.subTest(action=action):
                errors = []

                def interact():
                    dialog = self.application.activeModalWidget()
                    try:
                        self.assertIsInstance(dialog, QMessageBox)
                        self.assertIn('DLMS Desktop cannot verify its save state.', dialog.text())
                        self.assertIn('does not delete results already saved on the server', dialog.text())
                        self.assertIn('inspect Server History', dialog.text())
                        buttons = {button.text(): button for button in dialog.buttons()}
                        self.assertEqual(set(buttons), {'Keep open', 'Close DLMS Desktop'})
                        self.assertIs(dialog.defaultButton(), buttons['Keep open'])
                        self.assertIs(dialog.escapeButton(), buttons['Keep open'])
                        if action in ('enter', 'escape'):
                            QTest.keyClick(dialog, Qt.Key.Key_Return if action == 'enter' else Qt.Key.Key_Escape)
                        else:
                            buttons['Keep open' if action == 'keep' else 'Close DLMS Desktop'].click()
                    except BaseException as exc:
                        errors.append(exc)
                        if isinstance(dialog, QMessageBox):
                            dialog.reject()

                QTimer.singleShot(0, interact)
                self.assertEqual(DesktopWindow._confirm_server_close(self.window), accepted)
                if errors:
                    raise errors[0]


if __name__ == '__main__':
    unittest.main()

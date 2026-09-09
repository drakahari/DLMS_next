"""DLMS-079 browser-presence lifecycle and Settings regressions."""

import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

_TEMP = tempfile.TemporaryDirectory(prefix="dlms-browser-presence-tests-")
os.environ["QUIZAPP_DATA_DIR"] = _TEMP.name

from tests._isolation import ensure_test_data_isolation

ensure_test_data_isolation()
import app as dlms
from dlms.browser_presence import BrowserPresenceManager
from tests.csrf_test_utils import csrf_headers, csrf_token


class FakeClock:
    def __init__(self):
        self.value = 1000.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds
        return self.value


class BrowserPresenceManagerTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.shutdown = mock.Mock()
        self.manager = BrowserPresenceManager(
            self.shutdown,
            clock=self.clock,
            heartbeat_seconds=30,
            token_ttl_seconds=90,
            grace_seconds=300,
            poll_seconds=2,
            suspend_gap_seconds=120,
        )

    def _advance_with_polls(self, seconds, step=30):
        remaining = seconds
        result = False
        while remaining:
            increment = min(step, remaining)
            self.clock.advance(increment)
            result = self.manager.poll_once()
            remaining -= increment
        return result

    def test_disabled_feature_never_requests_automatic_shutdown(self):
        self.clock.advance(1000)
        self.assertFalse(self.manager.poll_once())
        self.shutdown.assert_not_called()
        self.assertFalse(self.manager.heartbeat("page_disabled_123456"))

    def test_one_live_tab_stays_running_and_stale_token_eventually_expires(self):
        self.manager.set_enabled(True)
        self.assertTrue(self.manager.heartbeat("page_one_live_123456"))
        self.clock.advance(89)
        self.assertFalse(self.manager.poll_once())
        self.assertEqual(1, self.manager.snapshot()["active_clients"])

        self.clock.advance(1)
        self.assertFalse(self.manager.poll_once())
        self.assertEqual(0, self.manager.snapshot()["active_clients"])
        self.assertFalse(self._advance_with_polls(299))
        self.assertTrue(self._advance_with_polls(1))
        self.shutdown.assert_called_once_with()

    def test_multiple_tabs_and_closing_only_the_final_tab_starts_grace(self):
        self.manager.set_enabled(True)
        self.manager.heartbeat("page_first_tab_123456")
        self.manager.heartbeat("page_second_tab_12345")
        self.manager.close("page_first_tab_123456")
        self.assertEqual(
            {
                "enabled": True,
                "active_clients": 1,
                "grace_started": False,
                "critical_operations": 0,
                "shutdown_requested": False,
            },
            self.manager.snapshot(),
        )
        self.manager.close("page_second_tab_12345")
        self.assertTrue(self.manager.snapshot()["grace_started"])
        self.clock.advance(300)
        self.assertTrue(self.manager.poll_once())

    def test_heartbeat_returning_during_grace_cancels_pending_shutdown(self):
        self.manager.set_enabled(True)
        self.manager.heartbeat("page_returning_123456")
        self.manager.close("page_returning_123456")
        self.clock.advance(299)
        self.manager.heartbeat("page_reloaded_123456")
        self.clock.advance(299)
        self.assertFalse(self.manager.poll_once())
        self.shutdown.assert_not_called()

    def test_navigation_replacement_token_keeps_presence_alive(self):
        self.manager.set_enabled(True)
        self.manager.heartbeat("page_before_nav_123456")
        self.manager.close("page_before_nav_123456")
        self.clock.advance(1)
        self.manager.heartbeat("page_after_nav_1234567")
        self.clock.advance(89)
        self.assertFalse(self.manager.poll_once())
        self.assertEqual(1, self.manager.snapshot()["active_clients"])

    def test_critical_operation_defers_due_shutdown_then_rechecks(self):
        self.manager.set_enabled(True)
        self.clock.advance(300)
        self.manager.begin_critical_operation()
        self.assertFalse(self.manager.poll_once())
        self.shutdown.assert_not_called()
        self.manager.end_critical_operation()
        self.assertTrue(self.manager.poll_once())
        self.shutdown.assert_called_once_with()

    def test_final_shutdown_check_is_cancelled_by_returning_presence(self):
        final_shutdown = mock.Mock()
        self.manager.set_enabled(True)
        self.clock.advance(300)
        self.assertTrue(self.manager.poll_once())
        self.manager.heartbeat("page_last_second_123456")
        self.assertFalse(self.manager.complete_automatic_shutdown(final_shutdown))
        final_shutdown.assert_not_called()

    def test_suspend_gap_does_not_consume_presence_or_grace_time(self):
        self.manager.set_enabled(True)
        self.manager.poll_once()
        self.assertFalse(self._advance_with_polls(290))
        self.clock.advance(600)
        self.assertFalse(self.manager.poll_once())
        self.assertFalse(self._advance_with_polls(9))
        self.assertTrue(self._advance_with_polls(1))

    def test_presence_tokens_are_runtime_only_and_not_shared_by_new_manager(self):
        self.manager.set_enabled(True)
        self.manager.heartbeat("page_process_one_12345")
        replacement = BrowserPresenceManager(mock.Mock(), clock=self.clock)
        replacement.set_enabled(True)
        self.assertEqual(0, replacement.snapshot()["active_clients"])

    def test_presence_token_validation_is_bounded(self):
        self.manager.set_enabled(True)
        for invalid in ("short", "path/token_123456", "space token 123456", "x" * 129):
            with self.subTest(token=invalid):
                with self.assertRaises(ValueError):
                    self.manager.heartbeat(invalid)


class BrowserPresenceIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(_TEMP.name)
        self.root.mkdir(parents=True, exist_ok=True)
        self.portal_path = self.root / "portal-lifecycle.json"
        self.portal_path.unlink(missing_ok=True)
        self.client = dlms.app.test_client()

    def test_setting_defaults_disabled_and_persists_enabled(self):
        manager = mock.Mock()
        with mock.patch.object(dlms, "PORTAL_CONFIG", str(self.portal_path)), mock.patch.object(
            dlms, "browser_presence_manager", manager
        ):
            page = self.client.get("/settings/lifecycle").get_data(as_text=True)
            self.assertIn("Application Lifecycle", page)
            self.assertIn("approximately 5 minutes", page)
            self.assertNotIn(
                'name="automatic_browser_shutdown_enabled" checked', page
            )

            response = self.client.post(
                "/settings/lifecycle/save",
                data={
                    "csrf_token": csrf_token(self.client, "/settings/lifecycle"),
                    "automatic_browser_shutdown_enabled": "on",
                },
                follow_redirects=False,
            )
            self.assertEqual(302, response.status_code)
            self.assertEqual("/settings/lifecycle?saved=1", response.headers["Location"])
            saved = json.loads(self.portal_path.read_text(encoding="utf-8"))
            self.assertIs(True, saved["automatic_browser_shutdown_enabled"])
            manager.set_enabled.assert_called_with(True)

    def test_unchecked_setting_persists_disabled(self):
        self.portal_path.write_text(
            json.dumps({"automatic_browser_shutdown_enabled": True}),
            encoding="utf-8",
        )
        manager = mock.Mock()
        with mock.patch.object(dlms, "PORTAL_CONFIG", str(self.portal_path)), mock.patch.object(
            dlms, "browser_presence_manager", manager
        ):
            response = self.client.post(
                "/settings/lifecycle/save",
                data={"csrf_token": csrf_token(self.client, "/settings/lifecycle")},
            )
            self.assertEqual(302, response.status_code)
            saved = json.loads(self.portal_path.read_text(encoding="utf-8"))
            self.assertIs(False, saved["automatic_browser_shutdown_enabled"])
            manager.set_enabled.assert_called_with(False)

    def test_heartbeat_requires_csrf_and_same_origin_and_accepts_valid_token(self):
        self.assertEqual(400, self.client.post("/api/browser-presence", json={
            "token": "page_valid_token_123456", "event": "present"
        }).status_code)
        headers = csrf_headers(self.client)
        hostile = dict(headers, Origin="https://attacker.example")
        self.assertEqual(403, self.client.post(
            "/api/browser-presence",
            json={"token": "page_valid_token_123456", "event": "present"},
            headers=hostile,
        ).status_code)

        manager = mock.Mock()
        manager.heartbeat.return_value = True
        with mock.patch.object(dlms, "browser_presence_manager", manager):
            response = self.client.post(
                "/api/browser-presence",
                json={"token": "page_valid_token_123456", "event": "present"},
                headers=csrf_headers(self.client),
            )
        self.assertEqual(200, response.status_code)
        self.assertEqual({"ok": True, "accepted": True}, response.get_json())
        manager.heartbeat.assert_called_once_with("page_valid_token_123456")

    def test_state_changing_requests_are_guarded_but_heartbeat_is_not(self):
        manager = mock.Mock()
        manager.heartbeat.return_value = True
        with mock.patch.object(dlms, "browser_presence_manager", manager):
            heartbeat = self.client.post(
                "/api/browser-presence",
                json={"token": "page_guard_test_123456", "event": "present"},
                headers=csrf_headers(self.client),
            )
            theme = self.client.post(
                "/api/theme",
                json={"theme": "dark"},
                headers=csrf_headers(self.client),
            )
        self.assertEqual(200, heartbeat.status_code)
        self.assertEqual(200, theme.status_code)
        manager.begin_critical_operation.assert_called_once_with()
        manager.end_critical_operation.assert_called_once_with()

    def test_manual_shutdown_still_schedules_immediately(self):
        manager = mock.Mock()
        with mock.patch.object(dlms, "browser_presence_manager", manager), mock.patch.object(
            threading, "Timer"
        ) as timer:
            response = self.client.post(
                "/api/shutdown", headers=csrf_headers(self.client)
            )
        self.assertEqual(200, response.status_code)
        self.assertEqual({"status": "ok"}, response.get_json())
        timer.assert_called_once()
        manager.begin_critical_operation.assert_called_once_with()
        manager.end_critical_operation.assert_called_once_with()

    def test_shared_client_reports_presence_without_activity_tracking(self):
        source = Path(dlms.STATIC_ROOT, "nav-normalize.js").read_text(encoding="utf-8")
        self.assertIn("/api/browser-presence", source)
        self.assertIn("30000", source)
        self.assertIn("pagehide", source)
        self.assertIn("pageshow", source)
        presence_source = source.split(
            "const sidebar = document.querySelector('.dashboard-sidebar');", 1
        )[0]
        for activity_event in ("mousemove", "mousedown", "keydown", "scroll"):
            self.assertNotIn(activity_event, presence_source)

    def test_shared_presence_client_is_loaded_by_every_complete_html_page(self):
        expected_script = '<script src="/static/nav-normalize.js"></script>'
        pages = [
            path
            for root in (Path(dlms.TEMPLATE_ROOT), Path(dlms.STATIC_ROOT))
            for path in root.rglob("*.html")
            if not path.name.startswith("_")
        ]
        missing = [
            str(path.relative_to(Path(dlms.RESOURCE_ROOT)))
            for path in pages
            if expected_script not in path.read_text(encoding="utf-8")
        ]
        self.assertEqual([], missing)


if __name__ == "__main__":
    unittest.main()

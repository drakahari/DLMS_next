"""Application-local Qt acceptance for managed Settings placement."""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog, QMessageBox

from desktop.maintenance import SCOPES
from tests.gate1.qt_checks import QtChecks


def capture(q: QtChecks, name: str) -> str:
    target = q.paths["root"] / name
    q.delay(.5)
    if not q.window.grab().save(str(target)):
        raise AssertionError(f"Qt window capture failed: {target}")
    return str(target)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    q = QtChecks(args.profile, automated=True)
    report = {"profile": args.profile}
    original_picker, original_question = QFileDialog.getOpenFileName, QMessageBox.question
    original_warning = QMessageBox.warning
    try:
        assert not q.window.menuBar().actions(), "duplicate operation menu remains"
        q.go("/settings/backup")
        q.delay(.6)
        assert q.window._settings_ready("backup")
        assert q.window.settings_panel.isVisible()
        assert q.window.settings_buttons["backup"].isVisible()
        assert q.window.settings_buttons["create_backup"].isVisible()
        assert q.window.settings_buttons["refresh_storage"].isVisible()
        assert all(not button.isVisible() for key, button in q.window.settings_buttons.items()
                   if key not in {"backup", "create_backup", "refresh_storage"})
        assert not q.window.view.isVisible(), "the web page must not compete with native Settings"
        q.delay(.8)
        assert "DLMS data size:" in q.window.settings_panel.storage_label.text()
        def summary(headers):
            conn = http.client.HTTPConnection("127.0.0.1", q.window.port, timeout=5)
            conn.request("GET", "/_desktop/settings/summary", headers=headers)
            response = conn.getresponse()
            code, body = response.status, response.read()
            conn.close()
            return code, body
        base_headers = {"X-DLMS-Desktop-Token": q.window.nonce}
        assert summary(base_headers)[0] == 403
        assert summary({**base_headers, "X-DLMS-Desktop-Nonce": q.window.nonce,
                        "Origin": "http://remote.example"})[0] == 403
        code, body = summary({**base_headers, "X-DLMS-Desktop-Nonce": q.window.nonce})
        assert code == 200 and b'"recent_backups"' in body and b'"storage"' in body
        report["summary_auth_and_content"] = True
        report["backup_wide"] = capture(q, "settings-backup-wide.png")
        q.window.resize(690, 760)
        report["backup_narrow"] = capture(q, "settings-backup-narrow.png")
        q.window.resize(1280, 850)
        assert q.window.settings_buttons["backup"].accessibleName().endswith(args.profile)
        assert q.window.settings_buttons["backup"].focusPolicy().value != 0
        assert q.js("document.documentElement.getAttribute('data-dlms-desktop-settings')") == "backup"
        assert q.js("!document.querySelector('form[action=\"/settings/backup/restore/stage\"]')")
        q.window._settings_marker_checked(q.window.view.page(), bytes(q.window.view.url().toEncoded()),
                                          "backup", q.window._settings_generation, '{"kind":null}')
        assert not q.window.settings_panel.isVisible() and q.window.settings_fallback.isVisible()
        q.window._settings_page_loaded(True)
        q.delay(.2)
        assert q.window._settings_ready("backup")
        report["wrong_document_marker_read_only"] = True

        db = q.paths["backend"] / "results.db"
        db_before = hashlib.sha256(db.read_bytes()).hexdigest()
        synthetic = q.paths["root"] / "cancelled-backup.zip"
        synthetic.write_bytes(b"synthetic cancellation fixture\n")
        invalid = q.paths["root"] / "missing-backup.zip"
        questions, warnings = [], []
        QFileDialog.getOpenFileName = lambda *a, **kw: (str(invalid), "DLMS backups (*.zip)")
        QMessageBox.question = lambda *a, **kw: questions.append(a) or QMessageBox.StandardButton.Yes
        QMessageBox.warning = lambda *a, **kw: warnings.append(a) or QMessageBox.StandardButton.Ok
        q.window.settings_buttons["backup"].click()
        assert not questions and warnings and not q.window.import_in_progress
        assert hashlib.sha256(db.read_bytes()).hexdigest() == db_before
        assert q.window.settings_buttons["backup"].hasFocus()
        report["invalid_source_before_confirmation"] = True

        QFileDialog.getOpenFileName = lambda *a, **kw: (str(synthetic), "DLMS backups (*.zip)")
        QMessageBox.question = lambda *a, **kw: QMessageBox.StandardButton.No
        q.window.settings_buttons["backup"].click()
        assert not q.window.import_in_progress and q.window.backend.poll() is None
        assert hashlib.sha256(db.read_bytes()).hexdigest() == db_before
        assert q.window.settings_panel.isVisible()
        assert q.window.settings_buttons["backup"].hasFocus(), "cancel must restore focus"
        report["cancel_no_mutation"] = True
        QFileDialog.getOpenFileName = lambda *a, **kw: ("", "DLMS backups (*.zip)")
        QTest.keyClick(q.window.settings_buttons["backup"], Qt.Key.Key_Return)
        assert q.window.settings_buttons["backup"].hasFocus() and not q.window.import_in_progress
        QTest.keyClick(q.window.settings_buttons["backup"], Qt.Key.Key_Space)
        assert q.window.settings_buttons["backup"].hasFocus() and not q.window.import_in_progress
        report["focused_return_and_space_cancel"] = True

        # A regular source may be replaced after the early picker check. The
        # use-time check must still refuse a symlink before touching the data.
        changing = q.paths["root"] / "changing-backup.zip"
        changing.write_bytes(b"synthetic pre-confirmation bytes\n")
        QFileDialog.getOpenFileName = lambda *a, **kw: (str(changing), "DLMS backups (*.zip)")
        def replace_after_confirmation(*_a, **_kw):
            changing.unlink()
            changing.symlink_to(synthetic)
            return QMessageBox.StandardButton.Yes
        QMessageBox.question = replace_after_confirmation
        warnings.clear()
        q.window.settings_buttons["backup"].click()
        assert changing.is_symlink() and warnings and not q.window.import_in_progress
        assert hashlib.sha256(db.read_bytes()).hexdigest() == db_before
        assert q.window.settings_buttons["backup"].hasFocus()
        report["replaced_source_refused_at_use_time"] = True

        regular_change = q.paths["root"] / "changed-regular-backup.zip"
        regular_change.write_bytes(b"before confirmation\n")
        QFileDialog.getOpenFileName = lambda *a, **kw: (str(regular_change), "DLMS backups (*.zip)")
        def change_bytes_after_confirmation(*_a, **_kw):
            regular_change.write_bytes(b"after confirmation\n")
            return QMessageBox.StandardButton.Yes
        QMessageBox.question = change_bytes_after_confirmation
        warnings.clear()
        q.window.settings_buttons["backup"].click()
        assert warnings and "changed" in warnings[-1][1].lower()
        assert not q.window.import_in_progress
        assert hashlib.sha256(db.read_bytes()).hexdigest() == db_before
        assert q.window.settings_buttons["backup"].hasFocus()
        report["changed_regular_source_refused_at_use_time"] = True

        def navigate_during_picker(*_a, **_kw):
            q.go("/library")
            return str(synthetic), "DLMS backups (*.zip)"

        QFileDialog.getOpenFileName = navigate_during_picker
        QMessageBox.question = lambda *a, **kw: QMessageBox.StandardButton.Yes
        q.window.settings_buttons["backup"].click()
        assert not q.window.import_in_progress and not q.window.settings_panel.isVisible()
        assert hashlib.sha256(db.read_bytes()).hexdigest() == db_before
        report["picker_navigation_revokes_action"] = True
        q.go("/settings/backup")

        calls = []
        q.window._choose_backup = lambda **kw: calls.append(("backup",))
        q.window.begin_maintenance = lambda scope, **kw: calls.append(("maintenance", scope))
        q.window.begin_removal = lambda **kw: calls.append(("remove",))
        q.window.settings_buttons["backup"].click()
        assert calls == [("backup",)]
        calls.clear()
        q.go("/settings/reset-remove")
        assert q.window._settings_ready("reset-remove") and q.window.settings_panel.isVisible()
        assert not q.window.settings_buttons["backup"].isVisible()
        assert q.js("[...document.querySelectorAll('#clearDBBtn,.resetAction,#removeAllDlmsDataBtn,#removeDlmsConfirmation')].every(x=>x.disabled)")
        report["reset_wide"] = capture(q, "settings-reset-wide.png")
        q.window.resize(690, 760)
        report["reset_narrow"] = capture(q, "settings-reset-narrow.png")
        assert q.window.settings_panel.height() >= 500
        q.window.resize(1280, 850)
        for scope in SCOPES:
            q.window.settings_buttons[scope].click()
        q.window.settings_buttons["remove"].click()
        assert calls == [("maintenance", scope) for scope in SCOPES] + [("remove",)]
        report["exact_handler_map"] = calls.copy()
        calls.clear()

        page = q.window.view.page()
        old_url = bytes(q.window.view.url().toEncoded())
        old_generation = q.window._settings_generation
        q.go("/library")
        assert not q.window.settings_panel.isVisible()
        q.window._settings_marker_checked(page, old_url, "reset-remove", old_generation, '{"kind":"reset-remove","theme":"dark"}')
        q.window._activate_settings_action("remove")
        assert not calls and not q.window.settings_panel.isVisible()
        report["navigation_and_stale_callback_blocked"] = True

        q.go("/settings/backup?storage=1")
        assert q.window._settings_ready("backup")
        q.window.import_in_progress = True
        q.window._activate_settings_action("backup")
        assert not calls
        q.window.import_in_progress = False
        report["busy_refused"] = True

        # A same-origin script can navigate to Settings but cannot invoke Qt.
        q.go("/library")
        q.js("(()=>{let a=document.createElement('a');a.href='/settings/reset-remove';document.body.append(a);a.click();return true})()")
        q.wait("location.pathname === '/settings/reset-remove' && document.readyState === 'complete'")
        q.delay(.3)
        assert not calls and q.window._settings_ready("reset-remove")
        report["scripted_navigation_no_action"] = True

        # A failed main-frame load offers only nonmutating profile/log guidance.
        q.window.interceptor.blocked_internal_paths.add("/settings/reset-remove")
        q.window.view.setUrl(QUrl(f"http://127.0.0.1:{q.window.port}/settings/reset-remove"))
        q.delay(1)
        assert not q.window.settings_panel.isVisible()
        assert q.window.settings_fallback.isVisible()
        assert args.profile in q.window.settings_fallback.text()
        report["failed_page_read_only"] = True
        report["failure_screenshot"] = capture(q, "settings-load-failure.png")
        report["pass"] = True
    finally:
        QFileDialog.getOpenFileName, QMessageBox.question = original_picker, original_question
        QMessageBox.warning = original_warning
        (q.paths["root"] / "settings-boundary.json").write_text(json.dumps(report, indent=2) + "\n")
        q.close()
    print(json.dumps(report, indent=2))
    return 0 if report.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())

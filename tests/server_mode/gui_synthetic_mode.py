"""Application-local Qt acceptance against a copied-source synthetic server.

No desktop-wide input, owner server, or external network is used. The server
binds a task-owned loopback port and stores data only in this test run root.
"""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import threading
import time

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QInputDialog, QMessageBox, QToolBar

from desktop.isolation import AREA, PROJECT
from desktop.settings_surface import THEME_REGISTRY
from desktop.server_mode import configured_server, read_config, write_config
from tests.gate1.qt_checks import QtChecks


def count(path: Path, table: str) -> int:
    if not path.exists():
        return 0
    with sqlite3.connect(path) as connection:
        return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


class SecondOrigin(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"<html><body>SECOND SYNTHETIC SERVER</body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--server-source", type=Path,
                        help="Explicit task-local released-source snapshot, never an original checkout")
    args = parser.parse_args()
    server_source = args.server_source.resolve() if args.server_source else PROJECT
    if args.server_source and not server_source.is_relative_to(PROJECT / '.gate1'):
        raise ValueError('Released Server tests require a project-local reference snapshot')
    run = AREA / "server-mode-acceptance" / args.profile
    run.mkdir(mode=0o700, parents=True, exist_ok=False)
    for part in ("server-data", "home", "cache", "tmp"):
        (run / part).mkdir(mode=0o700)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.2", 0))
        port = probe.getsockname()[1]
    env = os.environ.copy()
    env.update(DLMS_NO_BROWSER="1", QUIZAPP_DATA_DIR=str(run / "server-data"),
               DLMS_BROWSER_TEST_PORT=str(port), DLMS_BROWSER_TEST_BIND_HOST="127.0.0.2",
               HOME=str(run / "home"), XDG_CACHE_HOME=str(run / "cache"), TMPDIR=str(run / "tmp"))
    log = (run / "server.log").open("w")
    process = subprocess.Popen([sys.executable, str(server_source / "tests/browser/_server.py")],
                               cwd=PROJECT, env=env, stdout=log, stderr=subprocess.STDOUT,
                               start_new_session=True)
    q = None
    second_server = None
    second_thread = None
    report = {"profile": args.profile, "server_origin": f"http://127.0.0.2:{port}"}
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"Synthetic server exited: {process.returncode}")
            if (run / "server-data/browser_fixture.json").exists():
                try:
                    with socket.create_connection(("127.0.0.2", port), timeout=.2):
                        break
                except OSError:
                    pass
            time.sleep(.15)
        else:
            raise TimeoutError("Synthetic server did not listen")
        fixture = json.loads((run / "server-data/browser_fixture.json").read_text())
        q = QtChecks(args.profile, automated=True)
        local_db = q.paths["backend"] / "results.db"
        before = {table: count(local_db, table) for table in ("attempts", "study_responses")}
        assert q.window.mode == "local" and q.window.backend.poll() is None
        assert q.window.mode_identity.text().startswith("Local")
        assert not q.window.findChildren(QToolBar)
        assert q.window.local_mode_action.isChecked()
        assert args.profile in q.window.windowTitle()
        q.window.mode_identity.setFocus()
        menu_opened = []
        def close_keyboard_menu():
            menu_opened.append(q.window.mode_menu.isVisible())
            q.window.mode_menu.close()
        QTimer.singleShot(150, close_keyboard_menu)
        QTest.keyClick(q.window.mode_identity, Qt.Key.Key_Space)
        assert menu_opened == [True], "Space must open the Qt-owned mode menu"
        assert q.window.configure_server_action.isEnabled()
        assert not q.window.mode_menu.isVisible()
        report["compact_keyboard_menu"] = True
        first_storage = q.paths["web_storage"]
        original_get_text, original_warning = QInputDialog.getText, QMessageBox.warning
        try:
            def configure_with(choice):
                answers = iter(((report["server_origin"] + "/", True), ("Synthetic Server", True)))
                prompts = []
                QInputDialog.getText = lambda *_a, **_kw: next(answers)
                QMessageBox.warning = lambda _parent, title, message, *_a, **_kw: (
                    prompts.append((title, message)) or choice)
                def activate_configuration():
                    assert q.window.mode_menu.isVisible()
                    q.window.mode_menu.setActiveAction(q.window.configure_server_action)
                    QTest.keyClick(q.window.mode_menu, Qt.Key.Key_Return)
                QTimer.singleShot(100, activate_configuration)
                QTest.keyClick(q.window.mode_identity, Qt.Key.Key_Space)
                return prompts
            refused = configure_with(QMessageBox.StandardButton.No)
            assert refused and "HTTP does not encrypt" in refused[0][1]
            assert q.window.mode_config["server"] is None
            assert read_config(args.profile)["server"] is None
            accepted = configure_with(QMessageBox.StandardButton.Yes)
            assert accepted and q.window.mode_config["server"]["origin"] == report["server_origin"]
            assert read_config(args.profile)["server"] == q.window.mode_config["server"]
        finally:
            QInputDialog.getText, QMessageBox.warning = original_get_text, original_warning
        report["private_http_exact_origin_opt_in"] = True
        for theme in THEME_REGISTRY:
            q.window._style_mode_control(theme)
            assert q.window.mode_identity.styleSheet() and q.window.mode_menu.styleSheet()
        report["mode_control_theme_count"] = len(THEME_REGISTRY)
        q.js("localStorage.setItem('dlms.reviewMarkPending.synthetic-switch-check', '{}'); true")
        q.window.server_mode_action.trigger()
        assert q.window.local_mode_action.isChecked() and q.window.backend.poll() is None
        assert q.window.mode == "local"
        q.js("localStorage.removeItem('dlms.reviewMarkPending.synthetic-switch-check'); true")
        q.js("localStorage.setItem('dlms.quiz-progress.v1:synthetic-switch-check', JSON.stringify({pendingAttempt:{attemptId:'synthetic'}})); true")
        assert not q.window.switch_to_server() and q.window.mode == "local"
        q.js("localStorage.removeItem('dlms.quiz-progress.v1:synthetic-switch-check'); true")
        durable = q.paths["root"] / "durable-actions"
        durable.mkdir(mode=0o700, exist_ok=True)
        sentinel = durable / "synthetic-accepted.json"
        sentinel.write_text('{"synthetic":"pending accepted work"}')
        try:
            assert not q.window.switch_to_server() and q.window.mode == "local"
        finally:
            sentinel.unlink()
        q.window.import_in_progress = True
        assert not q.window.switch_to_server() and q.window.mode == "local"
        q.window.import_in_progress = False
        q.window._backup_creating = True
        assert not q.window.switch_to_server() and q.window.mode == "local"
        q.window._backup_creating = False
        q.window.maintenance_worker = object()
        assert not q.window.switch_to_server() and q.window.mode == "local"
        q.window.maintenance_worker = None
        q.window.download_results.append({"path": "synthetic", "state": "in_progress"})
        assert not q.window.switch_to_server() and q.window.mode == "local"
        q.window.download_results.pop()
        report["simulated_pending_action_import_backup_maintenance_download_refused"] = True
        feedback_ticket = q.window._begin_feedback("create_backup")
        q.window._feedback(feedback_ticket, "Earlier Local backup saved", "success")
        q.window.server_mode_action.trigger()
        assert q.window.mode == "server" and q.window.backend is None
        q.wait("location.pathname === '/' && document.readyState === 'complete'", 30)
        assert q.window.mode_identity.text().startswith("Server:")
        assert q.window.server_mode_action.isChecked()
        assert report["server_origin"] in q.window.mode_identity.toolTip()
        assert report["server_origin"] in q.window.mode_identity.accessibleName()
        assert report["server_origin"] in q.window.windowTitle()
        assert not q.window.configure_server_action.isEnabled()
        assert not q.window._feedback(feedback_ticket, "Late Local success", "success")
        assert not q.window.operation_feedback.message
        assert q.window.statusBar().accessibleDescription() == q.window.statusBar().currentMessage()
        report["server_identity_and_local_privilege_separation"] = True
        q.window.resize(610, 750)
        saved_server = q.window.mode_config["server"]
        q.window.mode_config = dict(q.window.mode_config,
                                    server=dict(saved_server, label="Long synthetic server name " * 8))
        q.window._update_mode_toolbar()
        assert q.window.mode_identity.text().endswith("…")
        assert saved_server["origin"] in q.window.mode_identity.toolTip()
        q.window.mode_config = dict(q.window.mode_config, server=saved_server)
        q.window.resize(1280, 850)
        q.window._update_mode_toolbar()
        report["narrow_long_name_elided_full_origin_accessible"] = True
        assert q.window.server_paths["storage"] != first_storage
        assert q.window.profile.persistentStoragePath() == str(q.window.server_paths["storage"])
        assert not hasattr(q.window.server_interceptor, "token")
        assert q.js("location.origin") == report["server_origin"]
        q.window.view.setUrl(QUrl(report["server_origin"] + "/library"))
        q.wait("location.pathname === '/library' && document.readyState === 'complete'", 20)
        q.wait("document.body.innerText.includes('Browser Critical Workflow')", 12)
        assert q.window.grab().save(str(run / "server-mode-offscreen.png"))
        report["separate_server_view"] = True
        # Subframes, wrong-origin navigation and local backend requests cannot
        # be promoted into an authenticated Local page.
        assert not q.window.view.page().acceptNavigationRequest(QUrl("http://127.0.0.1:9001/settings/backup"),
            q.window.view.page().NavigationType.NavigationTypeLinkClicked, True)
        assert q.window.blocked_urls
        q.js(f"document.body.insertAdjacentHTML('beforeend', '<iframe src=\"http://127.0.0.1:{q.window.port}/_desktop/ready\"></iframe>'); true")
        q.delay(.25)
        assert any("127.0.0.1" in value for value in (q.window.server_interceptor.blocked + q.window.blocked_urls))
        report["wrong_origin_blocked"] = True
        q.window.view.setUrl(QUrl(f"{report['server_origin']}/quizzes/{fixture['critical_html']}"))
        q.wait("typeof quizRecoveryReady !== 'undefined' && quizRecoveryReady === true", 25)
        q.js("document.querySelector('.study-mode-btn').click(); true")
        q.wait("durableStudySession !== null && document.querySelector('#choices .choice') !== null", 20)
        q.js("document.querySelector('#choices .choice[data-index=\"0\"]').click(); true")
        q.wait("studyLearningEventSaves.size === 0", 20)
        assert count(run / "server-data/results.db", "study_responses") >= 1
        assert count(local_db, "study_responses") == before["study_responses"]
        report["server_study_only"] = True
        prior_automated = os.environ.pop("DLMS_DESKTOP_AUTOMATED", None)
        original_question = QMessageBox.question
        try:
            QMessageBox.question = lambda *_a, **_kw: QMessageBox.StandardButton.No
            assert not q.window.switch_to_local() and q.window.mode == "server"
            assert q.window.local_lock is None
            assert not (q.paths["root"] / "instance-owner.json").exists()
        finally:
            QMessageBox.question = original_question
            if prior_automated is not None:
                os.environ["DLMS_DESKTOP_AUTOMATED"] = prior_automated
        report["remote_unsaved_warning_can_refuse_switch"] = True
        q.window.view.setUrl(QUrl(f"{report['server_origin']}/quizzes/{fixture['companion_html']}"))
        q.wait("typeof quizRecoveryReady !== 'undefined' && quizRecoveryReady === true && !document.querySelector('.exam-mode-btn').disabled", 25)
        q.js("document.querySelector('.exam-mode-btn').click(); true")
        q.wait("examMode === true && document.querySelector('#choices .choice') !== null", 20)
        q.js("document.querySelector('#choices .choice[data-index=\"0\"]').click(); window.confirm=()=>true; document.querySelector('#submitBtn').click(); true")
        q.wait("document.querySelector('#result')?.textContent.includes('saved successfully')", 25)
        assert count(run / "server-data/results.db", "attempts") >= 2  # fixture includes one historical attempt
        assert count(local_db, "attempts") == before["attempts"]
        report["server_exam_only"] = True
        q.window.view.setUrl(QUrl(report["server_origin"] + "/history"))
        q.wait("location.pathname === '/history' && document.readyState === 'complete'", 20)
        assert q.js("document.body.innerText.includes('Browser Critical Workflow')")
        report["server_history"] = True
        q.window.local_mode_action.trigger()
        assert not q.window.operation_feedback.message
        report["local_feedback_invalidated_across_mode_roundtrip"] = True
        q.wait("location.origin.startsWith('http://127.0.0.1:') && document.readyState === 'complete'", 30)
        assert q.window.mode == "local" and q.window.backend.poll() is None
        assert count(local_db, "attempts") == before["attempts"]
        assert count(local_db, "study_responses") == before["study_responses"]
        report["return_same_local_dataset"] = True
        assert q.window.switch_to_server()
        q.wait("location.pathname === '/' && document.readyState === 'complete'", 25)
        report["remember_server_on_restart"] = True
        q.js("document.cookie='serverProbe=originOne; Path=/'; localStorage.setItem('serverProbe','originOne'); true")
        assert q.js("document.cookie.includes('serverProbe=originOne')")
        first_server_id = q.window.mode_config["server"]["id"]
        first_server_storage = q.window.server_paths["storage"]
        assert q.window.switch_to_local()
        q.wait("location.origin.startsWith('http://127.0.0.1:') && document.readyState === 'complete'", 25)
        second_server = ThreadingHTTPServer(("127.0.0.2", 0), SecondOrigin)
        second_thread = threading.Thread(target=second_server.serve_forever, daemon=True)
        second_thread.start()
        second_origin = f"http://127.0.0.2:{second_server.server_port}"
        changed = dict(q.window.mode_config,
                       server=configured_server(q.window.mode_config, second_origin,
                                                "Other synthetic Server", private_http_opt_in=True))
        write_config(args.profile, changed)
        q.window.mode_config = changed
        q.window._update_mode_toolbar()
        assert q.window.switch_to_server()
        q.wait("document.body.innerText.includes('SECOND SYNTHETIC SERVER')", 20)
        assert q.window.mode_config["server"]["id"] != first_server_id
        assert q.window.server_paths["storage"] != first_server_storage
        assert not q.js("document.cookie.includes('serverProbe=originOne')")
        second_state = json.loads(q.js("JSON.stringify({origin:location.origin, value:localStorage.getItem('serverProbe')})"))
        assert second_state == {"origin": second_origin, "value": None}, second_state
        report["endpoint_change_cookie_and_local_storage_isolated"] = True
        (run / "result.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))
        return 0
    finally:
        if q is not None:
            q.close()
        if second_server is not None:
            second_server.shutdown()
            second_server.server_close()
            second_thread.join(timeout=5)
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        log.close()


if __name__ == "__main__":
    raise SystemExit(main())

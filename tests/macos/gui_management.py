"""Bounded source/instrumented Mac management checks using task-owned data only.

Seed the source profile with gui_candidate import first. Run backup, restore,
restore (separate-process reopen), reset, reset (reconciliation/reopen), server.
Chooser replacements are app-owned Qt widgets, not native-sheet acceptance.
The tiny Server exercises host policy/storage/outage, not DLMS Server features.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import faulthandler
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import stat
from socketserver import TCPServer
import sys
import threading
import time
import traceback
import zipfile

from tests.macos.gui_candidate import fixtures_at, owned_picker, digest, TITLE

_DIAGNOSTICS = None


class Diagnostics:
    """Bounded task-local observations; never inspect or control another app."""
    def __init__(self, q, report, output):
        from PySide6.QtCore import QTimer
        self.q, self.report = q, report
        self.started = time.monotonic()
        self.last_heartbeat = self.started
        self.failed = None
        self.last = None
        self.seen_modals = set()
        self.stream = output.with_suffix('.progress.jsonl').open('x')
        self.timer = QTimer(q.window)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        faulthandler.dump_traceback_later(200, repeat=False, file=sys.stderr)
        self.step('phase-start')

    def state(self):
        from PySide6.QtWidgets import QMessageBox
        from shiboken6 import isValid
        window = self.q.window
        view = window.view
        modal = self.q.app.activeModalWidget()
        result = {'page': view.url().toString() if view is not None and isValid(view) else None,
                  'status': window.statusBar().currentMessage(),
                  'failed_reason': window.failed_reason,
                  'backend_pid': window.backend.pid if window.backend is not None else None,
                  'backend_returncode': window.backend.poll() if window.backend is not None else None,
                  'import_worker_pid': window.import_worker.pid if window.import_worker is not None else None,
                  'import_worker_returncode': window.import_worker.poll() if window.import_worker is not None else None}
        for name in ('import_in_progress', 'maintenance_transition', '_closing', '_close_complete',
                     '_settings_transition_refused', '_settings_kind', '_browser_dialog_depth',
                     '_retirement_wait_active', '_browser_operation_depth', '_settings_action_busy'):
            result[name] = getattr(window, name, None)
        if modal is not None and isValid(modal):
            result['modal'] = {'type': type(modal).__name__, 'title': modal.windowTitle()}
            if isinstance(modal, QMessageBox):
                result['modal'].update(text=modal.text(), details=modal.detailedText())
        return result

    def record(self, kind, value):
        item = {'kind': kind, 'seconds': round(time.monotonic() - self.started, 3), **value}
        self.stream.write(json.dumps(item, default=str) + '\n')
        self.stream.flush()
        print('MANAGEMENT', json.dumps(item, default=str), flush=True)
        if len(self.report.setdefault('diagnostics', [])) < 128:
            self.report['diagnostics'].append(item)

    def step(self, name):
        self.record('step', {'name': name, 'state': self.state()})
        self.check()

    def tick(self):
        from PySide6.QtWidgets import QDialog, QMessageBox
        try:
            state = self.state()
            if state != self.last:
                self.record('state', {'state': state})
                self.last = state
            if time.monotonic() - self.last_heartbeat >= 5:
                self.record('heartbeat', {'state': state})
                self.last_heartbeat = time.monotonic()
            modal = self.q.app.activeModalWidget()
            # The sole expected confirmation is explicitly handled by restore.
            # Unexpected task-owned warning/error dialogs must fail this check,
            # not wait indefinitely or be treated as successful confirmation.
            if isinstance(modal, QMessageBox) and id(modal) not in self.seen_modals:
                self.seen_modals.add(id(modal))
                self.failed = 'Unexpected management message: ' + modal.text()
                self.record('unexpected-modal-rejected', {'state': state})
                modal.reject()
            if time.monotonic() - self.started > 230 and self.failed is None:
                self.failed = 'Management phase exceeded its 230-second watchdog'
                self.record('watchdog', {'state': state})
                faulthandler.dump_traceback(file=sys.stderr)
                if isinstance(modal, QDialog):
                    modal.reject()
        except Exception as exc:
            self.failed = 'Management diagnostic failed: ' + repr(exc)
            print(self.failed, flush=True)

    def check(self):
        if self.failed:
            raise RuntimeError(self.failed)

    def close(self):
        self.timer.stop()
        faulthandler.cancel_dump_traceback_later()
        self.stream.close()


def step(name):
    if _DIAGNOSTICS is not None:
        _DIAGNOSTICS.step(name)


def lifecycle_delay(seconds):
    """Pump the task application's events without another harness QEventLoop.

    Avoid wrapping browser retirement/recreation in QtChecks.delay's extra
    nested exec while the lifecycle enters its own event loop. QTest.qWait
    pumps bounded events directly; the production window's retirement and
    shutdown loops remain unchanged.
"""
    from PySide6.QtTest import QTest
    QTest.qWait(max(1, round(seconds * 1000)))
    if _DIAGNOSTICS is not None:
        _DIAGNOSTICS.check()


def wait_until(q, condition, seconds=45):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if _DIAGNOSTICS is not None:
            _DIAGNOSTICS.check()
        if q.window.failed_reason:
            raise RuntimeError(q.window.failed_reason)
        if condition():
            return
        q.delay(.1)
    raise TimeoutError('Management workflow did not reach its expected state')


@contextmanager
def save_picker(q, destination):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QFileDialog
    previous = QFileDialog.getSaveFileName
    calls = []

    def choose(parent, title, start, filters, **kwargs):
        assert parent is q.window
        dialog = QFileDialog(parent, title, str(destination.parent) if destination else start, filters)
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        dialog.setOption(QFileDialog.Option.DontConfirmOverwrite, True)
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        calls.append({'title': title, 'destination': str(destination) if destination else None})
        timeout = QTimer(dialog)
        timeout.setSingleShot(True)
        timeout.timeout.connect(dialog.reject)
        timeout.start(4000)
        if destination:
            assert not destination.exists()
            dialog.selectFile(str(destination))
            QTimer.singleShot(120, dialog.accept)
        else:
            QTimer.singleShot(120, dialog.reject)
        try:
            accepted = dialog.exec()
            if accepted != QFileDialog.DialogCode.Accepted:
                return '', ''
            paths = dialog.selectedFiles()
            assert len(paths) == 1 and Path(paths[0]) == destination, paths
            return paths[0], dialog.selectedNameFilter()
        finally:
            timeout.stop()
            dialog.deleteLater()

    QFileDialog.getSaveFileName = choose
    try:
        yield calls
    finally:
        QFileDialog.getSaveFileName = previous


def facts(q):
    from tests.settings.gui_native_roundtrip import facts as database_facts
    return database_facts(q.paths['backend'])


def write_new(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)


def management_output_folder(args, *, create=False):
    """One fixed visible Downloads namespace; never adopt an unrelated folder."""
    from desktop.macos_paths import real_home
    root = real_home() / 'Downloads/DLMS-Mac-candidate-outputs-20261017'
    downloads = root.parent.stat()
    if downloads.st_uid != os.getuid() or downloads.st_mode & 0o022:
        raise ValueError('Normal Downloads is not owned and protected from other users')
    root_identity = {'kind': 'dlms-macos-synthetic-outputs', 'version': 1, 'uid': os.getuid()}

    def validate(directory, identity, marker_name, allow_create):
        for part in (*reversed(directory.parents), directory):
            if part.is_symlink() or (part.exists() and not part.is_dir()):
                raise ValueError('Synthetic output folder contains a symlink or non-directory')
        if not directory.exists():
            if not allow_create:
                raise ValueError('Expected task-owned Downloads output folder is missing')
            directory.mkdir(mode=0o700)  # No parents, replacement or adoption.
            marker = directory / marker_name
            fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'w') as stream:
                json.dump(identity, stream)
                stream.flush()
                os.fsync(stream.fileno())
        elif allow_create:
            raise FileExistsError('Preserve existing synthetic output folder: ' + str(directory))
        info = directory.stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('Synthetic output folder is not privately owned')
        marker = directory / marker_name
        found = marker.lstat()
        if (not stat.S_ISREG(found.st_mode) or found.st_nlink != 1 or found.st_uid != os.getuid()
                or found.st_mode & 0o077 or found.st_size > 1024):
            raise ValueError('Synthetic output folder marker is unsafe')
        value = json.loads(marker.read_text())
        if not isinstance(value, dict) or type(value.get('version')) is not int or value != identity:
            raise ValueError('Synthetic output folder marker differs')

    # An existing marked parent is reusable across disjoint fresh task runs.
    validate(root, root_identity, '.dlms-macos-outputs.json', create and not root.exists())
    folder = root / ('management-' + args.profile)
    identity = {'kind': 'dlms-macos-management-outputs', 'version': 1,
                'profile': args.profile, 'data_root': str(args.data_root)}
    validate(folder, identity, '.dlms-macos-management.json', create)
    return folder


def archive_identity(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
        raise ValueError('Synthetic backup is no longer a singly linked owned regular file')
    return {name: getattr(info, name) for name in ('st_dev', 'st_ino', 'st_size',
            'st_mtime_ns', 'st_ctime_ns', 'st_mode', 'st_uid', 'st_nlink', 'st_flags')}


def archive_observation(path, label, report):
    value = {'step': label, 'path': str(path), 'identity': archive_identity(path)}
    report.setdefault('archive_observations', []).append(value)
    if _DIAGNOSTICS is not None:
        _DIAGNOSTICS.record('archive-identity', value)
    return value['identity']


def settle_visible_archive(q, path, expected_sha, published_ns, report):
    """Wait before consent, without retrying or weakening an issued grant."""
    if type(published_ns) is not int or not 0 < published_ns <= time.monotonic_ns():
        raise ValueError('Fresh synthetic backup publication clock is missing or invalid')
    deadline = time.monotonic() + 15
    unchanged_since = time.monotonic()
    previous = None
    while time.monotonic() < deadline:
        before = archive_identity(path)
        actual = digest(path)
        after = archive_identity(path)
        if actual != expected_sha:
            raise ValueError('Visible synthetic backup contents changed; no selection attempted')
        if before != after or after != previous:
            unchanged_since = time.monotonic()
            previous = after
        elif time.monotonic() - unchanged_since >= 2:
            archive_observation(path, 'stable-before-selection', report)
            report['archive_preselection_stable_seconds'] = 2
            report['archive_preselection_age_seconds'] = round((time.monotonic_ns() - published_ns) / 1e9, 3)
            report['archive_settling_condition'] = '2s stable source identity/hash before consent; later environmental metadata changes remain a refusal'
            return
        q.delay(.2)
    raise TimeoutError('Visible synthetic backup metadata did not settle; no selection attempted')


def new_selection_receipts(q, previous):
    folder = q.paths['root'] / 'imports'
    receipts = []
    for path in sorted(folder.glob('*.json')):
        if path.name not in previous:
            value = json.loads(path.read_text())
            receipts.append({key: value.get(key) for key in
                             ('token', 'state', 'profile', 'epoch', 'sha256', 'source_name')})
    return receipts


def backup(q, args, report):
    source = q.paths['root'] / 'macos-source-import.json'
    assert source.is_file(), 'Seed gui_candidate import first'
    before = facts(q)
    assert before['rows']['quizzes'] and before['rows']['study_responses']
    folder = management_output_folder(args, create=True)
    archive = folder / 'Populated Mac synthetic backup é.zip'
    q.go('/settings/backup')
    wait_until(q, lambda: q.window._settings_ready('backup'))
    with save_picker(q, None) as canceled:
        q.window.settings_buttons['create_backup'].click()
    assert len(canceled) == 1 and not q.window._backup_creating
    assert 'canceled' in q.window.statusBar().currentMessage().lower()
    with save_picker(q, archive) as selected:
        q.window.settings_buttons['create_backup'].click()
        wait_until(q, lambda: archive.is_file() and not q.window._backup_creating
                   and q.window.backup_output_future is None, 70)
    assert len(selected) == 1
    published_ns = time.monotonic_ns()
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None and 'DLMS_BACKUP_MANIFEST.json' in bundle.namelist()
    assert before == facts(q)
    q.go('/library')
    export = folder / 'Mac synthetic library reference é.txt'
    initial = len(q.window.download_results)
    with save_picker(q, export) as exported:
        q.click_css('a[href="/export/all_quizzes.txt"]')
        wait_until(q, lambda: len(q.window.download_results) > initial
                   and q.window.download_results[-1]['state'] not in {'in_progress'}, 40)
    record = q.window.download_results[-1]
    assert record['state'] == 'completed', record
    assert Path(record['published_path']) == export and TITLE in export.read_text()
    assert export.read_bytes() == Path(record['path']).read_bytes()
    assert len(exported) == 1 and before == facts(q)
    receipt = {'profile': args.profile, 'archive': str(archive), 'sha256': digest(archive),
               'archive_published_monotonic_ns': published_ns,
               'output_folder': str(folder),
               'facts': before, 'export': str(export), 'export_sha256': digest(export)}
    write_new(args.data_root / 'management-backup.json', receipt)
    report.update(archive=str(archive), sha256=receipt['sha256'], export=str(export),
                  export_sha256=receipt['export_sha256'], cancel_then_save=True,
                  source_rows_assets_unchanged=True, populated_backup=True)


def restore(q, args, report):
    from PySide6.QtWidgets import QMessageBox
    step('restore-read-receipt')
    expected = json.loads((args.data_root / 'management-backup.json').read_text())
    archive = Path(expected['archive'])
    folder = management_output_folder(args)
    assert expected['profile'] == args.profile and expected.get('output_folder') == str(folder)
    assert archive == folder / 'Populated Mac synthetic backup é.zip'
    assert not archive.is_symlink()
    assert digest(archive) == expected['sha256']
    receipt = args.data_root / 'management-restore.json'
    if receipt.exists():
        step('restore-reopen-read-facts')
        prior = json.loads(receipt.read_text())
        assert prior['restored_profile'] == q.window.profile_name
        assert facts(q) == expected['facts']
        report['separate_process_reopen_exact_rows_assets'] = True
        return
    step('restore-verify-empty-target')
    assert not facts(q)['rows']['quizzes'], 'Restore requires a new empty derived synthetic profile'
    step('restore-open-settings')
    q.go('/settings/backup')
    wait_until(q, lambda: q.window._settings_ready('backup'))
    step('restore-cancel-picker')
    with owned_picker(q, None) as canceled:
        q.window.settings_buttons['backup'].click()
    assert len(canceled) == 1 and not q.window.import_in_progress
    step('restore-settle-visible-archive')
    settle_visible_archive(q, archive, expected['sha256'], expected.get('archive_published_monotonic_ns'), report)
    previous_receipts = {path.name for path in (q.paths['root'] / 'imports').glob('*.json')}
    old_question = QMessageBox.question

    def confirm(parent, title, message, *unused, **kwargs):
        assert parent is q.window and title == 'Import validated backup into this disposable profile?'
        assert expected['sha256'] in message and q.window.profile_name in message
        archive_observation(archive, 'confirmation', report)
        receipts = new_selection_receipts(q, previous_receipts)
        report['confirmation_receipts'] = receipts
        assert len(receipts) == 1 and receipts[0]['state'] == 'ready', receipts
        assert receipts[0]['sha256'] == expected['sha256']
        step('restore-confirm-ready-receipt')
        return QMessageBox.StandardButton.Yes

    QMessageBox.question = confirm
    try:
        step('restore-select-archive')
        archive_observation(archive, 'selector-start', report)
        with owned_picker(q, archive) as selected:
            q.window.settings_buttons['backup'].click()
        assert len(selected) == 1
        archive_observation(archive, 'selector-end', report)

        def completed_and_reopened():
            receipts = new_selection_receipts(q, previous_receipts)
            report['selection_receipts'] = receipts
            if any(value['state'] in {'refused', 'canceled', 'failed'} for value in receipts):
                raise RuntimeError('Restore selection refused: ' + json.dumps(receipts))
            idle = (not q.window.import_in_progress and q.window.backup_selection_future is None
                    and q.window.import_worker is None)
            if not idle:
                return False
            if len(receipts) != 1 or receipts[0]['state'] != 'completed':
                raise RuntimeError('Restore did not complete a private selection receipt: ' +
                                   q.window.statusBar().currentMessage() + '; ' + json.dumps(receipts))
            assert receipts[0]['sha256'] == expected['sha256']
            assert receipts[0]['profile'] == q.window.profile_name
            return (q.window.view is not None and q.window.backend is not None
                    and q.window.backend.poll() is None)

        step('restore-await-worker-and-new-view')
        wait_until(q, completed_and_reopened, 90)
        archive_observation(archive, 'completed-receipt', report)
        step('restore-await-home-document')
        q.wait("location.pathname==='/' && document.readyState==='complete'", 30)
    finally:
        QMessageBox.question = old_question
    step('restore-compare-exact-facts')
    assert facts(q) == expected['facts']
    step('restore-write-receipt')
    write_new(receipt, {'source_profile': args.profile, 'restored_profile': q.window.profile_name,
                        'archive_sha256': expected['sha256']})
    report.update(restored_profile=q.window.profile_name, exact_rows_ids_assets=True,
                  cancel_then_restore=True, separate_process_reopen_required=True)


def reset(q, args, report):
    from desktop.maintenance import read_marker
    receipt = args.data_root / 'management-reset.json'
    if receipt.exists():
        expected = json.loads(receipt.read_text())
        assert facts(q) == expected['after']
        assert read_marker(q.window.profile_name) is None
        report['separate_process_reset_reconciliation_exact_rows_assets'] = True
        return
    assert (args.data_root / 'management-restore.json').is_file(), 'Restore into derived profile first'
    before = facts(q)
    assert before['rows']['study_responses'], 'Populated Study history is required'
    q.go('/settings/reset-remove')
    wait_until(q, lambda: q.window._settings_ready('reset-remove'))
    assert q.window.begin_maintenance('study', confirmed=True)
    wait_until(q, lambda: (read_marker(q.window.profile_name) or {}).get('phase')
               in {'browser_check_pending', 'browser_done'}, 100)
    after = facts(q)
    assert not after['rows']['study_sessions'] and not after['rows']['study_responses']
    for table in ('quizzes', 'questions', 'choices', 'matching_pairs', 'attempts', 'attempt_answers'):
        assert after['rows'][table] == before['rows'][table], table
    assert after['assets'] == before['assets']
    marker = read_marker(q.window.profile_name)
    assert marker.get('retained_safety_sha256'), marker
    safety = (args.data_root / 'recovery' / q.window.profile_name /
              marker['operation_id'] / marker['safety_backup'])
    assert safety.is_file() and digest(safety) == marker['retained_safety_sha256']
    from desktop.isolation import profile_paths
    from tests.settings.gui_native_roundtrip import facts as database_facts
    original = json.loads((args.data_root / 'management-backup.json').read_text())
    assert database_facts(profile_paths(args.profile, create=False)['backend']) == original['facts']
    write_new(receipt, {'profile': q.window.profile_name, 'before': before, 'after': after,
                        'safety_sha256': marker['retained_safety_sha256']})
    report.update(scope='study', only_derived_synthetic_profile_changed=True,
                  unrelated_rows_ids_assets_preserved=True,
                  retained_safety_sha256=marker['retained_safety_sha256'],
                  separate_process_reconciliation_required=True)


def server(q, args, report):
    from PySide6.QtCore import QUrl
    from desktop.server_mode import configured_server, write_config
    faulthandler.dump_traceback_later(15, repeat=False, file=sys.stderr)
    step('server-read-local-facts')
    before = facts(q)
    requests = []

    class NumericLoopbackServer(ThreadingHTTPServer):
        def server_bind(self):
            # HTTPServer.server_bind calls getfqdn even for numeric loopback.
            # This test needs no DNS and uses its already acquired exact port.
            TCPServer.server_bind(self)
            self.server_name = '127.0.0.1'
            self.server_port = self.server_address[1]

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append({'path': self.path, 'local_credentials': any(
                key.lower().startswith('x-dlms-desktop') for key in self.headers)})
            body = b'<!doctype html><html><body><h1>MAC TASK-OWNED SERVER</h1><p>Distinct synthetic remote dataset</p></body></html>'
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    service = None
    thread = None

    def start(port=0):
        step('server-create-listener-' + str(port))
        instance = NumericLoopbackServer(('127.0.0.1', port), Handler)
        instance.daemon_threads = True
        worker = threading.Thread(target=instance.serve_forever, daemon=True)
        worker.start()
        step('server-listener-started-' + str(instance.server_port))
        return instance, worker

    def stop(instance, worker):
        instance.shutdown()
        instance.server_close()
        worker.join(timeout=3)
        assert not worker.is_alive()

    try:
        service, thread = start()
        port = service.server_port
        origin = f'http://127.0.0.1:{port}'
        report['server_origin'] = origin
        step('server-configure-exact-origin')
        config = dict(q.window.mode_config, server=configured_server(
            q.window.mode_config, origin, 'Mac task-owned synthetic Server', private_http_opt_in=True))
        write_config(args.profile, config)
        q.window.mode_config = config
        step('server-create-local-storage-sentinel')
        q.js("localStorage.setItem('macOnlyLocal','synthetic-local');true")
        step('server-create-pending-switch-sentinel')
        q.js("localStorage.setItem('dlms.reviewMarkPending.mac-switch-check','{}');true")
        step('server-pending-switch-refusal')
        assert not q.window.switch_to_server() and q.window.mode == 'local'
        q.js("localStorage.removeItem('dlms.reviewMarkPending.mac-switch-check');true")
        step('server-switch-after-pending-cleared')
        assert q.window.switch_to_server()
        step('server-await-visible-document')
        q.wait("document.body.innerText.includes('MAC TASK-OWNED SERVER')", 25)
        assert q.window.mode == 'server' and q.window.backend is None
        assert q.window.server_paths['storage'] != q.paths['web_storage']
        step('server-read-typed-storage-state')
        remote_state = json.loads(q.js("JSON.stringify({origin:location.origin,local:localStorage.getItem('macOnlyLocal')})"))
        report['remote_storage_probe'] = remote_state
        assert remote_state == {'origin': origin, 'local': None}, remote_state
        assert not hasattr(q.window.server_interceptor, 'token')
        assert q.window.settings_panel is None or not q.window.settings_panel.isVisible()
        q.js("localStorage.setItem('macOnlyServer','synthetic-server');true")
        step('server-stop-task-listener')
        stop(service, thread)
        service = thread = None
        q.window.view.setUrl(QUrl(origin + '/outage'))
        step('server-await-outage-refusal')
        wait_until(q, lambda: q.window.server_unreachable, 30)
        assert q.window.mode == 'server' and q.window.backend is None
        assert facts(q) == before
        step('server-restart-exact-task-port')
        service, thread = start(port)
        q.window._retry_server()
        step('server-await-restarted-document')
        q.wait("document.body.innerText.includes('MAC TASK-OWNED SERVER')", 25)
        remote_reopened = json.loads(q.js("JSON.stringify({origin:location.origin,server:localStorage.getItem('macOnlyServer')})"))
        report['remote_restarted_storage_probe'] = remote_reopened
        assert remote_reopened == {'origin': origin, 'server': 'synthetic-server'}, remote_reopened
        step('server-explicit-return-to-local')
        assert q.window.switch_to_local()
        q.wait("location.pathname==='/' && document.readyState==='complete'", 30)
        local_state = json.loads(q.js("JSON.stringify({local:localStorage.getItem('macOnlyLocal'),server:localStorage.getItem('macOnlyServer')})"))
        report['local_restored_storage_probe'] = local_state
        assert local_state == {'local': 'synthetic-local', 'server': None}, local_state
        step('server-compare-preserved-local-facts')
        assert facts(q) == before
        assert requests and not any(item['local_credentials'] for item in requests)
        report.update(server_origin=origin, task_owned_minimal_html_server=True,
                      pending_switch_refused=True, local_server_storage_isolated=True,
                      no_remote_native_settings_or_local_tokens=True,
                      outage_keeps_server_without_local_fallback=True,
                      restart_retains_remote_storage=True, local_rows_assets_unchanged=True,
                      full_dlms_server_workflows_qualified=False)
    finally:
        faulthandler.cancel_dump_traceback_later()
        if service is not None:
            if _DIAGNOSTICS is not None:
                _DIAGNOSTICS.record('step', {'name': 'server-close-task-listener', 'state': _DIAGNOSTICS.state()})
            stop(service, thread)


def main(argv=None):
    global _DIAGNOSTICS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--profile', required=True)
    parser.add_argument('--fixtures', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--phase', choices=('backup', 'restore', 'reset', 'server'), required=True)
    args = parser.parse_args(argv)
    repo = Path(__file__).resolve().parents[2]
    from desktop.macos_paths import real_home
    scope = real_home() / '.cache/dlms-desktop-macos-candidate/qualification-data'
    if sys.platform != 'darwin' or getattr(sys, 'frozen', False):
        parser.error('Source/instrumented macOS only')
    if not re.fullmatch(r'macqual[a-z0-9_-]{1,24}', args.profile):
        parser.error('Dedicated macqual source profile required')
    if (not args.data_root.is_absolute() or '..' in args.data_root.parts
            or not args.data_root.is_relative_to(scope) or args.data_root == scope):
        parser.error('Use a marked task root below ' + str(scope))
    if (not args.output.is_absolute() or '..' in args.output.parts
            or not args.output.is_relative_to(repo / '.gate1/macos') or args.output.exists()
            or any(p.is_symlink() for p in (args.output, *args.output.parents))
            or not args.output.parent.is_dir()):
        parser.error('Use a fresh absolute JSON output below .gate1/macos')
    import package_macos
    package_macos.ACTIVE = True
    from desktop.macos_paths import prepare_root
    root = prepare_root(args.data_root, create=False)
    os.environ.update(DLMS_MACOS_DATA_ROOT=str(root), DLMS_DESKTOP_DATA_ROOT=str(root),
                      DLMS_DESKTOP_ROOT_KIND='macos-candidate')
    args.fixtures = fixtures_at(args.fixtures)
    restored = 'macqualrestore' + hashlib.sha256(args.profile.encode()).hexdigest()[:10]
    chosen = restored if args.phase in {'restore', 'reset'} else args.profile
    from desktop.isolation import profile_paths
    q = None
    started = time.monotonic()
    report = {'phase': args.phase, 'source_profile': args.profile, 'profile': chosen,
              'data_root': str(root), 'kind': 'source/instrumented Qt', 'status': 'running',
              'normal_package_qualified': False, 'physical_focus_qualified': False,
              'native_sheet_qualified': False, 'production_data_accessed': False}
    try:
        source_paths = profile_paths(args.profile, create=False)
        assert (source_paths['root'] / 'macos-source-import.json').is_file(), 'Seed source import first'
        target = profile_paths(chosen, create=False)
        if args.phase == 'restore' and not (root / 'management-restore.json').exists():
            assert not target['root'].exists(), 'Existing target profile is preserved; choose another task root'
        from tests.gate1.qt_checks import QtChecks
        q = QtChecks(chosen, automated=True, normal_identity=True)
        q.delay = lifecycle_delay
        report['harness_event_pump'] = 'bounded QTest.qWait; no added harness QEventLoop during lifecycle'
        _DIAGNOSTICS = Diagnostics(q, report, args.output)
        report['qt_platform'] = q.app.platformName()
        assert report['qt_platform'] == 'cocoa', 'Native cocoa session required'
        {'backup': backup, 'restore': restore, 'reset': reset, 'server': server}[args.phase](q, args, report)
        step('phase-workflows-complete')
        report['status'] = 'pass'
    except (Exception, KeyboardInterrupt) as exc:
        report.update(status='fail', error=f'{type(exc).__name__}: {exc}')
        if _DIAGNOSTICS is not None:
            report['failure_state'] = _DIAGNOSTICS.state()
        traceback.print_exc()
    finally:
        if q is not None:
            try:
                if _DIAGNOSTICS is not None:
                    _DIAGNOSTICS.record('step', {'name': 'ordered-close-begin', 'state': _DIAGNOSTICS.state()})
                q.close()
                assert q.window._close_complete, 'Ordered close incomplete'
                assert q.window.backend is None or q.window.backend.poll() is not None
                report['ordered_close_complete'] = True
            except Exception as exc:
                report.update(status='fail', close_error=f'{type(exc).__name__}: {exc}')
        if _DIAGNOSTICS is not None:
            _DIAGNOSTICS.close()
            _DIAGNOSTICS = None
        report['elapsed_seconds'] = round(time.monotonic() - started, 2)
        write_new(args.output, report)
        print(json.dumps(report, indent=2), flush=True)
    return 0 if report['status'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())

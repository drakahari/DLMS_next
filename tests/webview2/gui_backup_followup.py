"""Instrumented-only native backup checks; never normal-package acceptance.

Actual COM Show/Close cancellation is tested without synthesized input. Successful
selection is injected at the chooser result boundary and is labelled separately.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import zipfile


def until(q, predicate, timeout=90):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate(): return
        q.delay(.08)
    raise TimeoutError('Synthetic backup check did not reach its expected terminal state')


def cancel_dialog_class(base, observation, stage=lambda value: None):
    class CancelDialog(base):
        def show(self, owner):
            from tests.webview2.native_dialog_events import CancelEvents
            with CancelEvents(self, stage) as sink:
                observation['actual_native_show_called'] = True
                stage('native-show-enter')
                result = super().show(owner)
                stage('native-show-return')
                assert result == '', result
                assert sink.fired and not sink.errors, sink.errors
                observation['native_cancel_returned_empty'] = True
                observation['callback_errors'] = sink.errors
            observation['native_event_sink_unadvised'] = True
            return result
    return CancelDialog


def seed_quiz_study_theme(q, stage, theme, facts):
    from desktop.isolation import PROJECT
    content = (PROJECT / 'fixtures' / 'gate1-neutral-quiz.txt').read_text(encoding='utf-8')
    q.js("""(()=>{const f=new FormData(); f.append('file',new File([CONTENT],'Synthetic quiz 日本語.txt',{type:'text/plain'}));
      f.append('quiz_title','Native backup synthetic quiz');
      const token=decodeURIComponent(document.cookie.split('; ').find(v=>v.startsWith('dlms_csrf_token='))?.split('=')[1]||'');
      f.append('csrf_token',token);fetch('/process',{method:'POST',body:f,headers:{'X-CSRFToken':token}})
        .then(r=>window.__backupImportStatus=r.status);return true;})()""".replace('CONTENT', json.dumps(content)))
    q.wait('window.__backupImportStatus===200', 40)
    q.go('/library'); q.wait("document.body.innerText.includes('Native backup synthetic quiz')")
    link = q.js("document.querySelector('a[href^=\"/quizzes/\"]').getAttribute('href')")
    q.go(link); q.wait('quizRecoveryReady===true')
    q.js("document.querySelector('.study-mode-btn').click();true")
    q.wait("Boolean(document.querySelector('button.choice'))")
    q.js("document.querySelector('button.choice').click();true")
    until(q, lambda: len(facts(q.paths['backend'])['rows']['study_responses']) == 1)
    q.js("fetch('/api/theme',{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':decodeURIComponent(document.cookie.split('; ').find(x=>x.startsWith('dlms_csrf_token='))?.split('=')[1]||'')},body:JSON.stringify({theme:'dark'})}).then(r=>r.json()).then(r=>window.__backupTheme=r.theme);true")
    q.wait("window.__backupTheme==='dark'")
    stage('quiz-study-theme-created')
    return {'facts': facts(q.paths['backend']), 'theme': theme()}


def main():
    import package_windows_webview2
    package_windows_webview2.ACTIVE = True
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--operation', choices=('backup', 'restore', 'reopen', 'fresh', 'fresh-reopen', 'restore-fresh'), default='backup')
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--oracle', type=Path)
    args = parser.parse_args()
    args.output.mkdir(mode=0o700, exist_ok=False)
    def stage(value):
        with (args.output / 'stages.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'stage': value, 'monotonic': time.monotonic()}) + '\n')
        print(value, flush=True)
    stage('start')
    # Test-only bound on this exact interpreter (also covers venv redirectors).
    # Its kill-on-close Job owns only these synthetic backend/browser children.
    def timed_out():
        stage('owned-check-watchdog-timeout')
        os._exit(124)
    watchdog = threading.Timer(150, timed_out)
    watchdog.daemon = True
    watchdog.start()
    documents, downloads = args.output / 'Synthetic Documents', args.output / 'Synthetic Downloads 日本語'
    documents.mkdir(mode=0o700); downloads.mkdir(mode=0o700)
    from desktop import windows_backup_chooser as native
    from desktop.webview2_shell import DesktopWindow
    from desktop.webview2_file_selection import _known_private_roots
    import desktop.shell
    roots = _known_private_roots()
    original_window = desktop.shell.DesktopWindow
    desktop.shell.DesktopWindow = lambda *a, **kw: DesktopWindow(*a, documents_folder=documents,
        backup_chooser_folders=(documents, downloads), selection_private_roots=roots, **kw)
    from tests.gate1.qt_checks import QtChecks
    from tests.settings.gui_native_roundtrip import facts
    from PySide6.QtWidgets import QMessageBox, QApplication
    if args.operation == 'fresh':
        from desktop.isolation import profile_paths
        if profile_paths(args.profile, create=False)['root'].exists():
            raise ValueError('The fresh-reset drill requires a new synthetic profile')
    q = QtChecks(args.profile, automated=True)
    stage('browser-ready')
    report = {'instrumented_frozen': bool(getattr(__import__('sys'), 'frozen', False)),
              'normal_package': False, 'operation': args.operation, 'profile': args.profile,
              'native_interactive_save_acceptance': False}
    original_choose, open_picker, question, warning = native.choose, native.choose_open, QMessageBox.question, QMessageBox.warning
    def theme():
        portal = q.paths['backend'] / 'config' / 'portal.json'
        return json.loads(portal.read_text(encoding='utf-8')).get('theme') if portal.exists() else None
    try:
        if args.operation == 'backup':
            before = seed_quiz_study_theme(q, stage, theme, facts)
            q.go('/settings/backup'); until(q, lambda: q.window._settings_ready('backup'), 30)
            native_observation = {}
            native.choose = lambda owner, filename, folders: original_choose(owner, filename, folders,
                factory=cancel_dialog_class(native.NativeSaveDialog, native_observation, stage))
            started = time.monotonic()
            q.window.settings_buttons['create_backup'].click()
            stage('native-cancel-action-return')
            assert not q.window._backup_creating and not q.window.download_results
            assert 'Backup save canceled' in q.window.statusBar().currentMessage()
            assert q.window.settings_buttons['create_backup'].isEnabled()
            report['actual_native_cancel'] = native_observation | {'seconds': round(time.monotonic()-started, 3),
                'dialog_depth_after': q.window._browser_dialog_depth, 'button_enabled': True}
            archive = downloads / 'Backup chosen 日本語.zip'
            native.choose = lambda *a, **kw: (str(archive), '')
            q.window.settings_buttons['create_backup'].click()
            until(q, lambda: not q.window._backup_creating and q.window._settings_ready('backup'))
            assert archive.is_file(), q.window.statusBar().currentMessage()
            assert 'Backup saved:' in q.window.statusBar().currentMessage()
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            with zipfile.ZipFile(archive) as bundle: assert bundle.testzip() is None
            assert {'facts': facts(q.paths['backend']), 'theme': theme()} == before
            q.window.settings_buttons['create_backup'].click()
            assert 'refused:' in q.window.statusBar().currentMessage()
            assert hashlib.sha256(archive.read_bytes()).hexdigest() == digest
            with (args.output / 'oracle.json').open('x', encoding='utf-8') as stream:
                stream.write(json.dumps(before, ensure_ascii=False, indent=2)+'\n')
            report.update(selection_boundary_injected=True, real_backend_backup_publication=True,
                          ordinary_synthetic_downloads=True, existing_file_refused_unchanged=True,
                          archive=str(archive), sha256=digest, source_rows_assets_theme_unchanged=True)
        elif args.operation == 'fresh':
            from desktop import maintenance
            before = seed_quiz_study_theme(q, stage, theme, facts)
            identity = dict(q.window.manifest)
            q.go('/')
            # A rejected current-context callback must not retire the page or
            # begin a worker; the next call uses the unchanged owning context.
            old_view = q.window.view
            assert not q.window.begin_maintenance('fresh', confirmed=True, still_authorized=lambda: False)
            assert q.window.view is old_view and q.window.maintenance_worker is None
            prior_backup = q.paths['backend'] / 'backups' / 'Existing synthetic backup.zip'
            with zipfile.ZipFile(prior_backup, 'x') as bundle:
                bundle.writestr('synthetic-retained-marker.txt', 'Preserve this prior backup')
            prior_digest = hashlib.sha256(prior_backup.read_bytes()).hexdigest()
            assert q.window.begin_maintenance('fresh', confirmed=True,
                still_authorized=lambda: q.window.mode == 'local' and q.window.manifest == identity)
            worker = q.window.maintenance_worker
            assert worker is not None
            warnings = []
            QMessageBox.warning = lambda *values, **kwargs: warnings.append(values[1])
            assert not q.window.begin_maintenance('settings', confirmed=True)
            assert q.window.maintenance_worker is worker
            until(q, lambda: bool(q.window.failed_reason) or q.window._close_complete, 120)
            assert not q.window.failed_reason, q.window.failed_reason
            marker = maintenance.read_marker(args.profile)
            assert marker['scope'] == 'fresh' and marker['phase'] == 'browser_check_pending'
            assert marker['whole_chromium_quarantine'] and marker['retained_safety_sha256']
            current = facts(q.paths['backend'])
            assert not current['rows']['quizzes'] and not current['rows']['study_responses'] and not current['rows']['attempts']
            assert hashlib.sha256(prior_backup.read_bytes()).hexdigest() == prior_digest
            recovery = maintenance._recovery_dir(args.profile, marker['operation_id'])
            assert (recovery / 'backend').is_dir() and (recovery / 'web_storage').is_dir()
            assert hashlib.sha256((recovery / marker['safety_backup']).read_bytes()).hexdigest() == marker['retained_safety_sha256']
            with (args.output / 'oracle.json').open('x', encoding='utf-8') as stream:
                stream.write(json.dumps({'identity': identity, 'operation_id': marker['operation_id'],
                    'prior_backup': prior_backup.name, 'prior_backup_sha256': prior_digest, 'before': before}, indent=2) + '\n')
            report.update(actual_packaged_maintenance_worker=report['instrumented_frozen'],
                actual_worker_pid=worker.pid, confirmation_boundary_injected=True, rejected_stale_context=True,
                repeated_activation_refused=True, refusal_warning_recorded=bool(warnings), fresh_reset_committed=True,
                browser_quarantined=True, prior_backup_preserved=True, retained_verified_preimage=True,
                pending_separate_process_browser_verification=True)
        elif args.operation == 'fresh-reopen':
            from desktop import maintenance
            expected = json.loads(args.oracle.read_text(encoding='utf-8'))
            assert maintenance.read_marker(args.profile) is None
            current = facts(q.paths['backend'])
            assert not current['rows']['quizzes'] and not current['rows']['study_responses'] and not current['rows']['attempts']
            assert theme() == 'purple-gold'
            assert q.window.manifest['uuid'] == expected['identity']['uuid']
            assert q.window.manifest['epoch'] != expected['identity']['epoch']
            prior_backup = q.paths['backend'] / 'backups' / expected['prior_backup']
            assert hashlib.sha256(prior_backup.read_bytes()).hexdigest() == expected['prior_backup_sha256']
            receipt = maintenance._completed_receipt(args.profile, expected['operation_id'])
            assert receipt['phase'] == 'browser_done' and receipt['whole_chromium_quarantine']
            assert q.js("location.pathname==='/'")
            report.update(separate_process_reopen=True, empty_quiz_study_exam_preserved=True,
                source_default_theme=True, same_profile_new_epoch=True, browser_transition_verified=True,
                prior_backup_preserved=True)
        else:
            expected = json.loads(args.oracle.read_text(encoding='utf-8'))
            if args.operation in {'restore', 'restore-fresh'}:
                assert not facts(q.paths['backend'])['rows']['quizzes']
                archive = args.archive.resolve(strict=True)
                digest = hashlib.sha256(archive.read_bytes()).hexdigest()
                q.go('/settings/backup'); until(q, lambda: q.window._settings_ready('backup'), 30)
                native.choose_open = lambda *a, **kw: (str(archive), 'DLMS backups (*.zip)')
                QMessageBox.question = lambda *a, **kw: QMessageBox.StandardButton.Yes
                q.window.settings_buttons['backup'].click()
                until(q, lambda: not q.window.import_in_progress and q.window.backup_selection_future is None
                      and q.window.import_worker is None, 120)
                q.wait("location.pathname==='/' && document.readyState==='complete'", 40)
                assert hashlib.sha256(archive.read_bytes()).hexdigest() == digest
                report['restore_selection_and_confirmation_boundary_injected'] = True
            assert {'facts': facts(q.paths['backend']), 'theme': theme()} == expected
            q.go('/library'); q.wait("document.body.innerText.includes('Native backup synthetic quiz')")
            report['restored_rows_assets_study_theme_match'] = True
            if args.operation == 'restore-fresh':
                # Exercise the normal native Settings callback, not confirmed=True.
                # Successful restore moved both old roots; the new host must have
                # safely recreated/pinned both before any reset capture.
                from desktop import maintenance
                from desktop.windows_browser_quarantine import root_ids
                from PySide6.QtCore import QTimer
                from PySide6.QtTest import QTest
                from PySide6.QtCore import Qt
                new_roots = root_ids(q.paths)
                identity = dict(q.window.manifest)
                prior_backup = q.paths['backend'] / 'backups' / 'Existing restore-fresh synthetic backup.zip'
                with zipfile.ZipFile(prior_backup, 'x') as bundle:
                    bundle.writestr('retained.txt', 'Keep this synthetic backup')
                prior_digest = hashlib.sha256(prior_backup.read_bytes()).hexdigest()
                q.go('/settings/reset-remove')
                until(q, lambda: q.window.settings_buttons['fresh'].isEnabled(), 30)
                QMessageBox.question = question
                confirmations, errors = [], []
                timer = QTimer()
                def confirm_owned_dialog():
                    dialog = QApplication.activeModalWidget()
                    if not isinstance(dialog, QMessageBox):
                        return
                    timer.stop()
                    try:
                        assert dialog.windowTitle() == 'Confirm Desktop maintenance'
                        assert args.profile in dialog.text()
                        assert dialog.defaultButton() is dialog.button(QMessageBox.StandardButton.No)
                        confirmations.append({'title': dialog.windowTitle(), 'default_no': True})
                        QTest.mouseClick(dialog.button(QMessageBox.StandardButton.Yes), Qt.MouseButton.LeftButton)
                    except BaseException as exc:
                        errors.append(repr(exc))
                        dialog.reject()
                timer.timeout.connect(confirm_owned_dialog)
                timer.start(25)
                q.window.settings_panel.reset_page[0].ensureWidgetVisible(q.window.settings_buttons['fresh'], 12, 12)
                q.delay(.15)
                q.window.settings_buttons['fresh'].setFocus()
                QTest.mouseClick(q.window.settings_buttons['fresh'], Qt.MouseButton.LeftButton)
                timer.stop()
                assert not errors and len(confirmations) == 1, (errors, confirmations)
                assert not q.window.failed_reason, q.window.failed_reason
                until(q, lambda: bool(q.window.failed_reason) or q.window._close_complete, 120)
                assert not q.window.failed_reason, q.window.failed_reason
                marker = maintenance.read_marker(args.profile)
                assert marker['scope'] == 'fresh' and marker['phase'] == 'browser_check_pending'
                assert marker['whole_chromium_quarantine'] and marker['retained_safety_sha256']
                current = facts(q.paths['backend'])
                assert not current['rows']['quizzes'] and not current['rows']['study_responses'] and not current['rows']['attempts']
                assert hashlib.sha256(prior_backup.read_bytes()).hexdigest() == prior_digest
                recovery = maintenance._recovery_dir(args.profile, marker['operation_id'])
                assert (recovery / 'backend').is_dir() and (recovery / 'web_storage').is_dir()
                assert hashlib.sha256((recovery / marker['safety_backup']).read_bytes()).hexdigest() == marker['retained_safety_sha256']
                (args.output / 'oracle.json').write_text(json.dumps({
                    'operation_id': marker['operation_id'], 'identity': identity,
                    'prior_backup': prior_backup.name, 'prior_backup_sha256': prior_digest,
                    'before': expected}, indent=2) + '\n', encoding='utf-8')
                report.update(actual_packaged_maintenance_worker=report['instrumented_frozen'],
                    restore_then_native_settings_fresh=True, real_native_confirmation=confirmations,
                    fresh_confirmation_boundary_injected=False, app_scoped_test_input=True,
                    physical_acceptance=False, restored_root_ids=new_roots,
                    fresh_reset_committed=True, browser_quarantined=True,
                    retained_verified_preimage=True, prior_backup_preserved=True,
                    pending_separate_process_browser_verification=True)
        report['passed'] = True
    finally:
        watchdog.cancel()
        native.choose, native.choose_open, QMessageBox.question, QMessageBox.warning = original_choose, open_picker, question, warning
        desktop.shell.DesktopWindow = original_window
        q.close(); q.delay(.4)
        report['close_complete'] = q.window._close_complete
        with (args.output / 'result.json').open('x', encoding='utf-8') as stream:
            stream.write(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(report, ensure_ascii=True, indent=2), flush=True)
    assert report.get('passed') and report['close_complete']
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

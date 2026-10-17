"""Application-local Qt native chooser checks; no host input injection."""
import argparse
import json
from pathlib import Path
import time
import threading

from PySide6.QtWidgets import QFileDialog, QMessageBox
from tests.gate1.qt_checks import QtChecks
from tests.settings.gui_native_roundtrip import facts


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--profile', required=True)
    p.add_argument('--folder', type=Path, required=True)
    p.add_argument('--phase', choices=('export', 'import', 'reopen'), required=True)
    a = p.parse_args()
    folder = a.folder.resolve(); folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    archive = folder / 'daily-backup.zip'
    evidence = folder / 'portable-facts.json'
    q = QtChecks(a.profile, automated=True)
    q.window.documents_folder = folder
    old_save, old_open, old_question, old_warning = QFileDialog.getSaveFileName, QFileDialog.getOpenFileName, QMessageBox.question, QMessageBox.warning
    warnings=[]
    QMessageBox.warning=lambda *args, **kw: warnings.append(str(args[2]))
    result={'phase':a.phase, 'profile':a.profile}
    def feedback(action, severity=None):
        label=q.window.settings_panel.action_status[action]
        assert label.text()==q.window.statusBar().currentMessage(), (label.text(),q.window.statusBar().currentMessage())
        assert label.isVisible() and label.text()
        if severity:assert label.property('severity')==severity
        return label.text()
    def wait_idle():
        end=time.monotonic()+90
        while time.monotonic()<end and (q.window.import_in_progress or q.window._backup_creating):q.delay(.1)
        assert not q.window.import_in_progress and not q.window._backup_creating
    def go_backup():
        q.go('/settings/backup')
        # Web loadFinished precedes the shell's asynchronous document-bound
        # Settings verification. Never click a still-disabled native control.
        end=time.monotonic()+15
        while time.monotonic()<end and not q.window._settings_ready('backup'):
            q.delay(.05)
        assert q.window._settings_ready('backup'), 'Native Settings not verified'
        assert q.window.settings_buttons['backup'].isEnabled()
    try:
        if a.phase=='export':
            before=facts(q.paths['backend'])
            assert before['rows']['study_responses'] and before['rows']['attempts']
            go_backup()
            QFileDialog.getSaveFileName=lambda *args, **kw: ('','')
            q.window.settings_buttons['create_backup'].click()
            assert not q.window._backup_creating and not archive.exists()
            assert q.window.settings_buttons['create_backup'].hasFocus()
            feedback('create_backup')
            result['save_cancel_focus']=True
            collision=folder/'existing.zip';collision.write_bytes(b'unrelated existing content')
            QFileDialog.getSaveFileName=lambda *args, **kw: (str(collision),'')
            q.window.settings_buttons['create_backup'].click()
            assert collision.read_bytes()==b'unrelated existing content'
            assert 'refused' in q.window.settings_panel.action_status['create_backup'].text()
            feedback('create_backup','error')
            QFileDialog.getSaveFileName=lambda *args, **kw: (str(archive),'')
            from desktop import backup_output
            original_publish = backup_output.publish
            entered, release = threading.Event(), threading.Event()
            calls = []
            def paused_publish(*args, **kw):
                calls.append(args[1]['operation']); entered.set()
                if not release.wait(15): raise TimeoutError('test publication barrier')
                return original_publish(*args, **kw)
            backup_output.publish = paused_publish
            try:
                q.window.settings_buttons['create_backup'].click()
                end=time.monotonic()+20
                while not entered.is_set() and time.monotonic()<end:q.delay(.1)
                assert entered.is_set()
                try:q.window._local_switch_preflight()
                except RuntimeError:pass
                else:raise AssertionError('switch allowed during publication')
                previous=q.window.view.url()
                q.window._navigate_settings('/library')
                assert q.window.view.url()==previous
                q.window.settings_buttons['create_backup'].click()
                assert len(calls)==1
                from PySide6.QtGui import QCloseEvent
                event=QCloseEvent();q.window.closeEvent(event)
                assert not event.isAccepted() and not q.window._closing
                result['publication_busy_guards']=True
            finally:
                release.set();backup_output.publish=original_publish
            wait_idle()
            assert archive.is_file(),q.window.statusBar().currentMessage()
            assert 'Backup saved:' in q.window.statusBar().currentMessage()
            end=time.monotonic()+10
            while not q.window._settings_ready('backup') and time.monotonic()<end:q.delay(.1)
            assert q.window._settings_ready('backup'), 'Native Settings did not recover after download navigation'
            assert q.window.open_backup_folder.isVisible()
            feedback('create_backup','success')
            assert facts(q.paths['backend'])==before
            evidence.write_text(json.dumps(before,sort_keys=True,indent=2)+'\n')
            result.update(saved=True,unchanged_source=True,status=q.window.statusBar().currentMessage())
            from hashlib import sha256
            saved_hash=sha256(archive.read_bytes()).hexdigest()
            stale_ticket=q.window._backup_feedback_ticket
            q.window.settings_buttons['create_backup'].click()
            refusal=feedback('create_backup','error')
            assert 'refused' in refusal and sha256(archive.read_bytes()).hexdigest()==saved_hash
            assert not q.window._feedback(stale_ticket,'Late obsolete success','success')
            assert feedback('create_backup','error')==refusal
            assert q.window.settings_buttons['create_backup'].hasFocus()
            result.update(collision_after_success_consistent=True,late_success_ignored=True,collision_zip_unchanged=True)
            failed_output=folder/'simulated-failed-publication.zip'
            QFileDialog.getSaveFileName=lambda *args, **kw: (str(failed_output),'')
            def fail_publish(*args,**kw):raise OSError('simulated destination write failure')
            backup_output.publish=fail_publish
            try:
                q.window.settings_buttons['create_backup'].click();wait_idle()
                end=time.monotonic()+10
                while not q.window._settings_ready('backup') and time.monotonic()<end:q.delay(.1)
                assert 'not confirmed' in feedback('create_backup','error')
                assert not failed_output.exists() and sha256(archive.read_bytes()).hexdigest()==saved_hash
                assert facts(q.paths['backend'])==before
                retained=q.window.download_results[-1]
                assert retained['state']=='publication_failed' and Path(retained['path']).is_file()
                result['simulated_publication_failure_visible_and_private_copy_retained']=True
            finally:backup_output.publish=original_publish
            for theme in ('light','dark','ethereal'):
                q.window.settings_panel.set_theme(theme);q.window._style_mode_control(theme)
                for width in (1280,640):
                    q.window.resize(width,850);q.delay(.2)
                    q.window.grab().save(str(folder/f'native-{theme}-{width}.png'))
        elif a.phase=='import':
            before=facts(q.paths['backend'])
            go_backup()
            QFileDialog.getOpenFileName=lambda *args, **kw: ('','')
            q.window.settings_buttons['backup'].click()
            assert not q.window.import_in_progress and facts(q.paths['backend'])==before
            assert q.window.settings_buttons['backup'].hasFocus()
            feedback('backup')
            bad=folder/'bad.zip';bad.write_bytes(b'not a ZIP')
            QFileDialog.getOpenFileName=lambda *args, **kw: (str(bad),'')
            q.window.settings_buttons['backup'].click();wait_idle()
            assert 'not staged or confirmed' in q.window.statusBar().currentMessage()
            feedback('backup','error')
            assert facts(q.paths['backend'])==before
            QFileDialog.getOpenFileName=lambda *args, **kw: (str(archive),'')
            QMessageBox.question=lambda *args, **kw: QMessageBox.StandardButton.No
            q.window.settings_buttons['backup'].click();wait_idle()
            assert 'canceled' in feedback('backup') and facts(q.paths['backend'])==before
            assert q.window.settings_buttons['backup'].hasFocus()
            changed=folder/'changed-during-confirm.zip';changed.write_bytes(archive.read_bytes())
            QFileDialog.getOpenFileName=lambda *args, **kw: (str(changed),'')
            def change_at_confirmation(*args,**kw):
                changed.write_bytes(b'x'*changed.stat().st_size)
                return QMessageBox.StandardButton.Yes
            QMessageBox.question=change_at_confirmation
            q.window.settings_buttons['backup'].click();wait_idle()
            assert 'source changed' in feedback('backup','error')
            assert facts(q.paths['backend'])==before and q.window.settings_buttons['backup'].hasFocus()
            result['confirmation_cancel_and_changed_source_unchanged']=True
            QFileDialog.getOpenFileName=lambda *args, **kw: (str(archive),'')
            QMessageBox.question=lambda *args, **kw: QMessageBox.StandardButton.Yes
            q.window.settings_buttons['backup'].click();wait_idle()
            q.wait("location.pathname === '/' && document.readyState === 'complete'",30)
            assert facts(q.paths['backend'])==json.loads(evidence.read_text())
            go_backup()
            feedback('backup','success')
            result.update(imported=True,cancel_and_malformed_unchanged=True,exact_data_equal=True,status=q.window.statusBar().currentMessage())
        else:
            assert facts(q.paths['backend'])==json.loads(evidence.read_text())
            result['exact_data_equal_after_restart']=True
        result['passed']=True
    finally:
        QFileDialog.getSaveFileName, QFileDialog.getOpenFileName, QMessageBox.question, QMessageBox.warning=old_save,old_open,old_question,old_warning
        (folder/f'{a.profile}-{a.phase}.json').write_text(json.dumps(result,indent=2)+'\n')
        q.close()
    print(json.dumps(result,indent=2))
    return 0

if __name__=='__main__':raise SystemExit(main())

"""Diagnose Wayland activation separately from own native-dialog focus return."""
import argparse,json
from PySide6.QtCore import QTimer,Qt
from PySide6.QtWidgets import QFileDialog
from tests.gate1.qt_checks import QtChecks


def main():
    p=argparse.ArgumentParser();p.add_argument('--profile',required=True);a=p.parse_args()
    q=QtChecks(a.profile,automated=True);report={'platform':q.app.platformName(),'physical_input':False}
    try:
        q.go('/settings/backup')
        import time
        deadline=time.monotonic()+15
        while not q.window._settings_ready('backup') and time.monotonic()<deadline:q.delay(.05)
        assert q.window._settings_ready('backup')
        button=q.window.settings_buttons['backup'];button.setFocus();q.delay(.2)
        def capture():
            fw=q.app.focusWidget();aw=q.app.activeWindow();win=q.app.focusWindow()
            return dict(window_active=q.window.isActiveWindow(),button_has_focus=button.hasFocus(),
                focus_widget=type(fw).__name__ if fw else None,active_window=type(aw).__name__ if aw else None,
                focus_window=win.objectName() if win else None,remembered_widget=type(q.window.focusWidget()).__name__ if q.window.focusWidget() else None,button_visible=button.isVisible(),button_enabled=button.isEnabled())
        report['before']=capture()
        # Construct our own native-capable chooser, retain its exact QObject so
        # rejecting it is bounded even if platform dialog is not a QWidget.
        original=QFileDialog.getOpenFileName
        dialog_info=[]
        def native_owned(parent,title,start,filters):
            dlg=QFileDialog(parent,title,start,filters)
            dlg.setFileMode(QFileDialog.FileMode.ExistingFile)
            dialog_info.append({'dont_use_native':dlg.testOption(QFileDialog.Option.DontUseNativeDialog)})
            QTimer.singleShot(400,dlg.reject)
            result=dlg.exec();dialog_info[-1]['result']=result;dlg.deleteLater();return ('','')
        QFileDialog.getOpenFileName=native_owned
        try:button.click()
        finally:QFileDialog.getOpenFileName=original
        q.delay(.3);report['after']=capture();report['dialogs']=dialog_info
        assert not q.window.import_in_progress and not (q.paths['root']/'dataset-transition.json').exists()
        if report['before']['window_active'] and report['after']['window_active']:
            assert report['after']['button_has_focus'],'Cancellation lost focus while the test window stayed active'
            report['active_window_cancel_focus_passed']=True
        else:
            report['active_window_cancel_focus_passed']=None
            report['limitation']='The test window was inactive before or after the chooser. Record both activation states and remembered widget; active-window/physical-input acceptance is pending.'
        report['focus_widget_preserved']=q.app.focusWidget() is button
        if report['before']['window_active'] and report['after']['window_active']:assert report['focus_widget_preserved']
        report['diagnostic_completed']=True
        report['focus_acceptance']='passed-active-window' if report['before']['window_active'] and report['after']['window_active'] else 'blocked-inactive-compositor-window'
    finally:
        (q.paths['root']/'file-focus.json').write_text(json.dumps(report,indent=2)+'\n');q.close();print(json.dumps(report,indent=2),flush=True)
if __name__=='__main__':main()

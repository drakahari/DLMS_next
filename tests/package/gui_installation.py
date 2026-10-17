"""App-local management/About keyboard, busy and rendering evidence."""
import argparse
import json
from pathlib import Path
import threading
from PySide6.QtCore import Qt,QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QFileDialog,QMessageBox,QDialog
from tests.gate1.qt_checks import QtChecks
from package_fedora.manage_gui import ManagementWindow


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--profile',required=True);a=p.parse_args()
    a.output=a.output.resolve();a.output.mkdir(mode=0o700,parents=True,exist_ok=False)
    q=QtChecks(a.profile,automated=True);old=QFileDialog.getOpenFileName
    gate=threading.Event()
    try:
        q.go('/settings/backup')
        mgr=ManagementWindow(a.output/'synthetic-home');mgr.show();q.delay(.1)
        QFileDialog.getOpenFileName=lambda *args,**kw:('','')
        for kind in ('install','transition-pilot','update'):
            button=mgr.buttons[kind];button.setFocus();QTest.keyClick(button,Qt.Key.Key_Space);q.delay(.03)
            assert 'cancelled' in mgr.status.text() and button.hasFocus()
        mgr._start(lambda:(gate.wait(5),{'outcome':'synthetic-no-mutation'})[1],mgr.completed);q.delay(.1)
        assert mgr.job is not None and not mgr.buttons['install'].isEnabled()
        assert not mgr.close() and mgr.isVisible();gate.set()
        while mgr.job is not None:q.delay(.03)
        assert 'Committed' in mgr.status.text();mgr.close()
        text=q.window._about_text();assert 'Active mode: Local' in text and a.profile in text
        captures=[]
        for theme in ('light','dark','ethereal'):
            q.window._style_mode_control(theme)
            for width in (1100,540):
                q.window.resize(width,800);q.window.activateWindow();q.window.mode_identity.setFocus();q.delay(.05)
                def check():
                    dialog=next(w for w in q.app.topLevelWidgets() if isinstance(w,QDialog) and w.windowTitle()=='About DLMS Desktop')
                    assert dialog.isVisible() and dialog.width()<=600
                    assert dialog.focusWidget() is not None
                    dialog.grab().save(str(a.output/f'about-{theme}-{width}.png'))
                    QTest.keyClick(dialog.focusWidget(),Qt.Key.Key_Escape)
                    captures.append({'theme':theme,'window_width':width,'dialog_width':dialog.width()})
                QTimer.singleShot(120,check);q.window._show_about();q.delay(.05)
                if not q.window.mode_identity.hasFocus():
                    print('ABOUT FOCUS DEBUG',{'enabled':q.window.mode_identity.isEnabled(),'visible':q.window.mode_identity.isVisible(),'active':q.window.isActiveWindow(),'focus':str(q.app.focusWidget()),'active_window':str(q.app.activeWindow()),'closing':q.window._closing},flush=True)
                assert q.window.mode_identity.hasFocus()
        assert len(captures)==6
        q.window.mode='server';q.window.mode_config['server']={'label':'Synthetic deployment','origin':'http://127.0.0.1:54321'}
        remote=q.window._about_text();assert 'Its deployed version is not established' in remote and 'http://127.0.0.1:54321' in remote
        q.window.mode='local';q.window.mode_config['server']=None
        result={'passed':True,'captures':captures,'native_scale':q.window.devicePixelRatioF(),'chooser_cancel_focus':True,
                'busy_close_refused':True,'about_close_focus':True,'server_version_not_inferred':True,'physical_input':False}
        (a.output/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
    finally:
        gate.set();QFileDialog.getOpenFileName=old;q.close()

if __name__=='__main__':main()

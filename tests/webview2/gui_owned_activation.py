"""Measure Qt activation only while this isolated application's root is foreground."""
import argparse
import ctypes
from ctypes import wintypes
import json
import sys


def main():
    p=argparse.ArgumentParser();p.add_argument('--profile',required=True);a=p.parse_args()
    import package_windows_webview2
    package_windows_webview2.ACTIVE=True
    from desktop.webview2_shell import DesktopWindow
    import desktop.shell
    desktop.shell.DesktopWindow=DesktopWindow
    from tests.gate1.qt_checks import QtChecks
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    import PySide6
    q=QtChecks(a.profile,automated=True)
    report={'source_instrumented':True,'physical_tab_acceptance':False,'normal_package':False,
            'python_version':sys.version,'python_executable':sys.executable,'pyside_version':PySide6.__version__}
    user=ctypes.windll.user32
    user.GetForegroundWindow.restype=wintypes.HWND
    user.GetAncestor.argtypes=[wintypes.HWND,wintypes.UINT];user.GetAncestor.restype=wintypes.HWND
    def state():
        focus=QApplication.focusWidget();active=QApplication.activeWindow();foreground=user.GetForegroundWindow()
        return {'foreground_root_owned':int(user.GetAncestor(foreground,2) or 0)==int(q.window.winId()),
                'owner_active':q.window.isActiveWindow(),'qt_active':active is q.window,
                'qt_focus_class':focus.metaObject().className() if focus else None,'qt_focus_name':focus.objectName() if focus else None,
                'dom':q.js("({tag:document.activeElement?.tagName,id:document.activeElement?.id,focused:document.hasFocus()})")}
    try:
        q.js("document.body.innerHTML='<input id=first><input id=last>';document.getElementById('last').focus();true")
        report['before']=state()
        if report['before']['foreground_root_owned']:
            q.window.activateWindow();q.window.mode_identity.setFocus(Qt.FocusReason.TabFocusReason);q.delay(.15)
            report['after_owned_qt_activation']=state()
            q.window.view.setFocus(Qt.FocusReason.TabFocusReason);q.delay(.15)
            report['after_tab_entry']=state()
            report['measurement_performed']=True
        else:report['skipped_foreign_foreground']=True
    finally:
        q.close();q.delay(.2);report['close_complete']=q.window._close_complete
        (q.paths['root']/'wv-owned-activation.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2),flush=True)
    assert report['close_complete']


if __name__=='__main__':main()

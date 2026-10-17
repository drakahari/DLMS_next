"""Read-only focus measurement in isolated embedded source host33; no OS input."""
import argparse
import ctypes
from ctypes import wintypes
import json
import time


def main():
    p=argparse.ArgumentParser();p.add_argument('--profile',required=True);p.add_argument('--baseline33',action='store_true');a=p.parse_args()
    import package_windows_webview2
    package_windows_webview2.ACTIVE=True
    from desktop import webview2_browser as browser
    from desktop.isolation import PROJECT
    if a.baseline33:
        browser.host_executable=lambda:PROJECT/'.gate1/windows-native/webview2-host-candidate-33/payload/DLMS-WebView2-Host.exe'
    from desktop.webview2_shell import DesktopWindow
    import desktop.shell
    desktop.shell.DesktopWindow=DesktopWindow
    from tests.gate1.qt_checks import QtChecks
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    q=QtChecks(a.profile,automated=True)
    import sys,PySide6
    report={'source_instrumented':True,'normal_package':False,'physical_keyboard_acceptance':False,'measurements':[],
            'baseline33':a.baseline33,'python_version':sys.version,'python_executable':sys.executable,'pyside_version':PySide6.__version__}
    boundaries=[];report['boundaries']=boundaries
    original_boundary=q.window.view._leave_browser_focus
    def trace_boundary(direction):
        view=q.window.view;nodes=[];candidate=view.nextInFocusChain() if direction=='next' else view.previousInFocusChain();seen={view}
        while candidate not in seen and len(nodes)<100:
            seen.add(candidate)
            nodes.append({'class':candidate.metaObject().className(),'name':candidate.objectName(),'visible':candidate.isVisible(),
                          'enabled':candidate.isEnabled(),'tab_stop':bool(candidate.focusPolicy() & Qt.FocusPolicy.TabFocus),
                          'browser_child':view.isAncestorOf(candidate),'same_window':candidate.window() is view.window()})
            candidate=candidate.nextInFocusChain() if direction=='next' else candidate.previousInFocusChain()
        boundaries.append({'direction':direction,'generation':view._active_generation,'nav_id':view._active_navigation,
                           'chain':nodes,'before':focus()})
        original_boundary(direction)
        boundaries[-1]['after_handler']=focus()
    q.window.view._leave_browser_focus=trace_boundary
    def call(op,**kw):
        values=[];errors=[];q.window.view.command(op,callback=values.append,on_error=errors.append,**kw)
        deadline=time.monotonic()+10
        while not values and not errors and time.monotonic()<deadline:q.delay(.04)
        if errors:raise RuntimeError(errors)
        if not values:raise TimeoutError(op)
        return values[-1]
    def focus():
        widget=QApplication.focusWidget()
        class GUIInfo(ctypes.Structure):
            _fields_=[('cbSize',wintypes.DWORD),('flags',wintypes.DWORD),
                      *[(name,wintypes.HWND) for name in ('active','focus','capture','menu_owner','move_size','caret')],
                      ('caret_rect',wintypes.RECT)]
        state=GUIInfo();state.cbSize=ctypes.sizeof(state)
        user=ctypes.windll.user32
        thread=user.GetWindowThreadProcessId(wintypes.HWND(int(q.window.view.native_window.winId())),None)
        ok=user.GetGUIThreadInfo(thread,ctypes.byref(state))
        title=ctypes.create_unicode_buffer(256)
        if ok and state.focus:user.GetClassNameW(wintypes.HWND(state.focus),title,256)
        qt_state=GUIInfo();qt_state.cbSize=ctypes.sizeof(qt_state)
        qt_hwnd=int(q.window.winId());qt_thread=user.GetWindowThreadProcessId(wintypes.HWND(qt_hwnd),None)
        qt_ok=user.GetGUIThreadInfo(qt_thread,ctypes.byref(qt_state))
        user.GetForegroundWindow.restype=wintypes.HWND
        user.GetAncestor.argtypes=[wintypes.HWND,wintypes.UINT];user.GetAncestor.restype=wintypes.HWND
        foreground=user.GetForegroundWindow();root=user.GetAncestor(foreground,2) if foreground else 0
        active=QApplication.activeWindow()
        return {'qt_widget':widget.metaObject().className() if widget else None,
                'qt_object_name':widget.objectName() if widget else None,
                'owner_active':q.window.isActiveWindow(),'qt_active_window':active.metaObject().className() if active else None,
                'dom':q.js("({id:document.activeElement?.id,tag:document.activeElement?.tagName})"),
                'native':{'get_gui_thread_info':bool(ok),'focus_hwnd':int(state.focus or 0),'focus_class':title.value,
                          'qt_thread_info':bool(qt_ok),'qt_thread_focus_hwnd':int(qt_state.focus or 0),
                          'foreground_root_is_owned_qt':int(root or 0)==qt_hwnd}}
    try:
        # This deliberately small synthetic document isolates the embedded
        # renderer boundary from ordinary page tab order and application logic.
        q.js("document.body.innerHTML='<input id=first><input id=last>';true")
        for start,backward in [('last',False),('first',True)]:
            q.js(f"document.getElementById('{start}').focus();true")
            q.window.view.setFocus();q.delay(.1)
            before=focus();reply=call('tab',backward=backward);q.delay(.2)
            after=focus()
            q.window.view.setFocus(Qt.FocusReason.BacktabFocusReason if backward else Qt.FocusReason.TabFocusReason)
            q.delay(.15)
            report['measurements'].append({'start':start,'backward':backward,'before':before,'reply':reply,'after':after,'reentry':focus()})
        report['measurement_complete']=True
        sent=[];original_command=q.window.view.command
        def observed_command(op,*args,**kw):
            if op=='position':sent.append(op)
            return original_command(op,*args,**kw)
        q.window.view.command=observed_command
        position=q.window.pos();q.window.move(position.x()+12,position.y()+8);q.delay(.15)
        report['ancestor_move_position_notifications']=len(sent)
        assert sent
    finally:
        q.close();q.delay(.3);report['close_complete']=q.window._close_complete
        (q.paths['root']/'wv-tab-boundary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2),flush=True)
    assert report.get('measurement_complete') and report['close_complete']
    if not a.baseline33:
        assert all(m['after']['qt_widget'] and m['after']['qt_widget'] != 'View' for m in report['measurements']), 'Native Tab boundary did not reach a Qt control'
        assert [m['reentry']['dom']['id'] for m in report['measurements']] == ['first','last'], 'Native Tab entry reason did not select the DOM boundary'


if __name__=='__main__':main()

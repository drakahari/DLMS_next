"""Instrumented native common-dialog navigation, without OS input synthesis.

The actual production control-event interface is called while Show is active;
GetFolder proves Shell navigation. This is not a physical button-click test.
"""
import argparse
import ctypes as c
from ctypes import wintypes as w
import json
from pathlib import Path
import threading


def dialog_navigation(dialog, folders, owner, output, initial=None):
    from desktop.windows_backup_chooser import GUID, _method, _checked, _release
    class Interface(c.Structure):
        _fields_ = [('table', c.POINTER(c.c_void_p))]
    rows, errors, callbacks = [], [], []
    state = [0]
    refs = [1]
    unknown = bytes(GUID.parse('00000000-0000-0000-c000-000000000046'))
    events = bytes(GUID.parse('973510db-7d7f-452b-8975-74a85828d354'))
    def query(this, iid, result):
        if c.string_at(iid,16) not in (unknown,events): result[0]=None; return -2147467262
        result[0]=c.addressof(interface); refs[0]+=1; return 0
    def add(this): refs[0]+=1; return refs[0]
    def release(this): refs[0]-=1; return refs[0]
    def noop(*args): return 0
    def response(this, dialog, item, output): output[0]=0; return 0
    def changed(this, pointer):
        try:
            if state[0] == 3:
                dialog.call(23,(c.c_long,),c.c_long(-2147023673))
        except BaseException as exc:
            errors.append(repr(exc))
            try:dialog.call(23,(c.c_long,),c.c_long(-2147023673))
            except BaseException as close_error:errors.append(repr(close_error))
        return 0
    specs=[(c.c_long,(c.c_void_p,c.POINTER(c.c_void_p)),query),
           (w.ULONG,(),add),(w.ULONG,(),release),
           (c.c_long,(c.c_void_p,),changed),
           (c.c_long,(c.c_void_p,c.c_void_p),noop),
           (c.c_long,(c.c_void_p,),changed),
           (c.c_long,(c.c_void_p,),noop),
           (c.c_long,(c.c_void_p,c.c_void_p,c.POINTER(c.c_int)),response),
           (c.c_long,(c.c_void_p,),changed),
           (c.c_long,(c.c_void_p,c.c_void_p,c.POINTER(c.c_int)),response)]
    for result,args,fn in specs: callbacks.append(c.WINFUNCTYPE(result,c.c_void_p,*args)(fn))
    table=(c.c_void_p*len(callbacks))(*(c.cast(fn,c.c_void_p).value for fn in callbacks))
    interface=Interface(table); cookie=w.DWORD()
    dialog.call(7,(c.c_void_p,c.POINTER(w.DWORD)),c.byref(interface),c.byref(cookie))
    user=c.WinDLL('user32',use_last_error=True)
    timer_type=c.WINFUNCTYPE(None,w.HWND,w.UINT,c.c_size_t,w.DWORD)
    user.SetTimer.argtypes,user.SetTimer.restype=(w.HWND,c.c_size_t,w.UINT,timer_type),c.c_size_t
    user.KillTimer.argtypes,user.KillTimer.restype=(w.HWND,c.c_size_t),w.BOOL
    def visible_controls():
        window=c.c_void_p();hwnd=w.HWND()
        try:
            _checked(_method(dialog.dialog,0,c.POINTER(GUID),c.POINTER(c.c_void_p))(
                dialog.dialog,c.byref(GUID.parse('00000114-0000-0000-c000-000000000046')),c.byref(window)))
            _checked(_method(window,3,c.POINTER(w.HWND))(window,c.byref(hwnd)))
        finally:_release(window)
        user.GetWindowRect.argtypes=(w.HWND,c.POINTER(w.RECT));user.GetWindowRect.restype=w.BOOL
        user.GetWindowTextW.argtypes=(w.HWND,w.LPWSTR,c.c_int);user.GetWindowTextW.restype=c.c_int
        user.IsWindowVisible.argtypes=(w.HWND,);user.IsWindowVisible.restype=w.BOOL
        rect=w.RECT();assert user.GetWindowRect(hwnd,c.byref(rect))
        found=[]
        enum_type=c.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM)
        def child(handle,param):
            try:
                text=c.create_unicode_buffer(512);user.GetWindowTextW(handle,text,len(text))
                if text.value.replace('&','') in ('Downloads','Documents'):
                    bounds=w.RECT();assert user.GetWindowRect(handle,c.byref(bounds))
                    inside=(rect.left <= bounds.left < bounds.right <= rect.right
                            and rect.top <= bounds.top < bounds.bottom <= rect.bottom)
                    visible=bool(user.IsWindowVisible(handle))
                    found.append({'label':text.value,'visible':visible,'inside_dialog':inside,
                                  'bounds':[bounds.left,bounds.top,bounds.right,bounds.bottom]})
                return True
            except BaseException as exc:
                errors.append(repr(exc));return False
        enum=enum_type(child)
        user.EnumChildWindows.argtypes=(w.HWND,enum_type,w.LPARAM);user.EnumChildWindows.restype=w.BOOL
        user.EnumChildWindows(hwnd,enum,0)
        for label in ('Downloads','Documents'):
            assert any(row['label'].replace('&','')==label and row['visible'] and row['inside_dialog'] for row in found),found
        from PySide6.QtGui import QGuiApplication
        image=QGuiApplication.primaryScreen().grabWindow(int(hwnd.value))
        assert not image.isNull()
        assert image.save(str(output/(('open' if dialog.opening else 'save')+'-native-dialog.png')))
        return found
    def tick(*args):
        try:
            phase=state[0]
            if phase >= 3:return
            try: current=Path(dialog.current_folder())
            except OSError:return  # Initial filter event precedes folder setup.
            expected=(initial or folders[0]) if phase==0 else folders[1] if phase==1 else folders[0]
            assert current==expected,(phase,current,expected)
            row={'phase':phase,'actual_folder':str(current)}
            if phase==0:row['native_child_controls']=visible_controls()
            for label,control_id in [('Downloads',dialog.places.DOWNLOADS),('Documents',dialog.places.DOCUMENTS)]:
                flags=w.DWORD()
                dialog.places._custom(13,(w.DWORD,c.POINTER(w.DWORD)),control_id,c.byref(flags))
                assert flags.value & 3 == 3
                row[label+'_visible_enabled']=True
            rows.append(row)
            with (output/'navigation-stages.jsonl').open('a',encoding='utf-8') as stream:
                stream.write(json.dumps(row,ensure_ascii=False)+'\n')
            state[0]+=1
            identifier=dialog.places.DOWNLOADS if phase==0 else dialog.places.DOCUMENTS
            if phase==2:
                # Force one native folder event, which closes from its callback.
                dialog.set_folder(folders[1])
            else:
                _checked(_method(c.byref(dialog.places.controls),4,c.c_void_p,w.DWORD)(
                    c.byref(dialog.places.controls),dialog.places.custom,identifier))
        except BaseException as exc:
            errors.append(repr(exc));state[0]=3
            try:dialog.call(23,(c.c_long,),c.c_long(-2147023673))
            except BaseException as close_error:errors.append(repr(close_error))
    timer_callback=timer_type(tick)
    timer=user.SetTimer(None,0,350,timer_callback)
    assert timer
    try:
        selected=dialog.show(int(owner.winId()))
        assert selected == '' and state[0] == 3 and not errors, (selected,state,errors)
        assert not dialog.places.errors
        return {'actual_Show':True,'control_event_interface_driven':True,
                'physical_input':False,'cancel_no_result':True,'navigation':rows}
    finally:
        user.KillTimer(None,timer)
        dialog.call(8,(w.DWORD,),cookie)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--profile',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output=args.output.resolve()
    args.output.mkdir(mode=0o700,exist_ok=False)
    from desktop.windows_processes import own_launcher
    own_launcher()
    from PySide6.QtWidgets import QApplication,QMainWindow
    from desktop.windows_backup_chooser import NativeSaveDialog,NativeOpenDialog
    import os,sys
    watchdog=threading.Timer(45,lambda:os._exit(124));watchdog.daemon=True;watchdog.start()
    app=QApplication([]);owner=QMainWindow();owner.resize(800,600);owner.show();app.processEvents()
    folders=(args.output/'Redirected Documents 日本語',args.output/'Real Downloads 日本語')
    for folder in folders: folder.mkdir(mode=0o700)
    report={'instrumented_frozen':bool(getattr(sys,'frozen',False)),'normal_package':False,
            'owner_folder_contents_accessed':False,'checks':{}}
    try:
        for name,kind,filename,title,pattern in [
            ('backup-save',NativeSaveDialog,'synthetic backup.zip','Save Local DLMS backup','*.zip'),
            ('backup-restore',NativeOpenDialog,'','Select a Local DLMS backup','*.zip'),
            ('export-save',NativeSaveDialog,'synthetic quiz.txt','Save quiz export as','*.txt')]:
            with kind() as dialog:
                initial=folders[1] if name=='export-save' else folders[0]
                dialog.configure(filename,folders,title=title,pattern=pattern,initial=initial)
                report['checks'][name]=dialog_navigation(dialog,folders,owner,args.output,initial)
        report['passed']=True
        with (args.output/'result.json').open('x',encoding='utf-8') as stream:
            json.dump(report,stream,ensure_ascii=False,indent=2)
    finally:
        owner.close();app.processEvents();watchdog.cancel()


if __name__=='__main__':main()

"""Qt-local folder dispatch to a task-owned detached helper; no desktop input.

The file URL handler is replaced inside this QApplication. It exercises the
native method, QDesktopServices dispatch and cleanup without opening host apps.
The receiver execs a real helper with close_fds=False to test the FD boundary.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def wait_for(path, process=None):
    deadline=time.monotonic()+10
    while not path.exists():
        if process is not None and process.poll() is not None:raise RuntimeError('Helper exited before checkpoint')
        if time.monotonic()>deadline:raise TimeoutError(str(path))
        time.sleep(.03)


def worker(args):
    from tests.gate1.qt_checks import QtChecks
    from desktop.package_entry import _installation_read_lock
    from PySide6.QtCore import QObject,Slot,QUrl
    from PySide6.QtGui import QDesktopServices
    q=QtChecks(args.profile,automated=True)
    helper=None
    class Handler(QObject):
        @Slot(QUrl)
        def open(self,url):
            nonlocal helper
            assert url.isLocalFile() and url.toLocalFile()==str(args.output)
            helper=subprocess.Popen([sys.executable,str(args.output/'helper.py'),str(args.output)],
                close_fds=False,start_new_session=True,stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    handler=Handler()
    QDesktopServices.setUrlHandler('file',handler,'open')
    _installation_read_lock(args.output/'installation')
    fd=os.open(args.output/'private-sentinel',os.O_RDONLY);os.set_inheritable(fd,True)
    try:
        q.go('/settings/backup')
        q.window.last_backup_output=args.output/'backup.zip'
        q.window._open_backup_folder()
        wait_for(args.output/'helper.json',helper)
        record=json.loads((args.output/'helper.json').read_text())
        assert not record['private_descriptors']
        assert record['process_group']!=os.getpgrp()
        q.close()
        assert helper.poll() is None,'External helper was wrongly cleaned as a Desktop process'
        (args.output/'qt-result.json').write_text(json.dumps({'passed':True,'helper_alive_after_window_close':True,
            'dispatch':'actual QDesktopServices with app-local synthetic file URL handler',
            'system_file_manager':False,'helper':record,'driver_pid':os.getpid()},indent=2)+'\n')
    finally:
        QDesktopServices.unsetUrlHandler('file')
        os.close(fd)
        if q.window.backend is not None:q.close()


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=Path);p.add_argument('--worker',action='store_true');p.add_argument('--profile',required=True);a=p.parse_args()
    a.output=a.output.resolve()
    if a.worker:worker(a);return
    a.output.mkdir(mode=0o700,parents=True,exist_ok=False)
    opt=a.output/'installation';opt.mkdir(mode=0o700)
    (opt/'manual-replacement.lock').write_bytes(b'');(opt/'manual-replacement.lock').chmod(0o600)
    (a.output/'private-sentinel').write_text('synthetic private evidence')
    (a.output/'helper.py').write_text('''import os,json,sys,time
from pathlib import Path
root=Path(sys.argv[1]);found=[]
for fd in os.listdir('/proc/self/fd'):
 try:
  target=os.readlink('/proc/self/fd/'+fd)
  if target in (str(root/'installation/manual-replacement.lock'),str(root/'private-sentinel')):found.append(target)
 except FileNotFoundError:pass
(root/'helper.json').write_text(json.dumps({'pid':os.getpid(),'process_group':os.getpgrp(),'private_descriptors':found,'nonce_present':'DLMS_DESKTOP_NONCE' in os.environ}))
while not (root/'helper-stop').exists():time.sleep(.02)
(root/'helper-finished').write_text('closed normally')
''')
    with (a.output/'qt.log').open('w') as log:
        process=subprocess.Popen([sys.executable,'-m','tests.package.gui_external_descriptors','--worker','--output',str(a.output),'--profile',a.profile],stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        try:
            assert process.wait(timeout=65)==0,(a.output/'qt.log').read_text()[-4000:]
            record=json.loads((a.output/'qt-result.json').read_text())
            os.kill(record['helper']['pid'],0)
            import fcntl
            with (opt/'manual-replacement.lock').open('rb') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            record['exclusive_lock_after_driver_exit']=True
            (a.output/'result.json').write_text(json.dumps(record,indent=2)+'\n')
        finally:
            (a.output/'helper-stop').touch()
            if (a.output/'helper.json').exists():wait_for(a.output/'helper-finished')
    print(json.dumps(record,indent=2))

if __name__=='__main__':main()

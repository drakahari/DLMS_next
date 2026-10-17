"""Exec/lock regressions in separate processes and synthetic installation homes."""
import errno
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest
from desktop import package_entry
from package_fedora import manual_replace as m
from tests.package.test_manual_replace import v2, staged


def test_private_descriptors_closed_to_external_exec(tmp_path):
    script = '''import os,subprocess,sys
from desktop.package_entry import _seal_private_descriptors
fd=os.open(sys.argv[1],os.O_RDONLY); os.set_inheritable(fd,True)
_seal_private_descriptors()
assert not os.get_inheritable(fd)
result=subprocess.run([sys.executable,'-c',"import os,sys; print(any(os.path.realpath('/proc/self/fd/'+x)==sys.argv[1] for x in os.listdir('/proc/self/fd')))",sys.argv[1]],close_fds=False,capture_output=True,text=True)
assert result.stdout.strip()=='False',result
assert os.read(fd,100)==b'private evidence'
'''
    leaf=tmp_path/'private';leaf.write_bytes(b'private evidence')
    result=subprocess.run([sys.executable,'-c',script,str(leaf)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr


def test_failed_guard_exec_restores_lock_flags(tmp_path,monkeypatch):
    import fcntl
    leaf=tmp_path/'lock';fd=os.open(leaf,os.O_RDWR|os.O_CREAT,0o600)
    fcntl.flock(fd,fcntl.LOCK_SH)
    monkeypatch.setattr(package_entry,'_INSTALL_LOCKS',{str(tmp_path):fd})
    def fail(*args):
        assert os.get_inheritable(fd)
        raise OSError(errno.ENOENT,'synthetic missing executable')
    monkeypatch.setattr(os,'execv',fail)
    try:
        with pytest.raises(OSError):package_entry._exec_active('missing',['missing'])
        assert not os.get_inheritable(fd)
        with pytest.raises(BlockingIOError):
            with leaf.open('rb') as other:fcntl.flock(other,fcntl.LOCK_EX|fcntl.LOCK_NB)
    finally:os.close(fd)


def test_sealing_failure_refuses_and_preserves_open_descriptors(monkeypatch):
    monkeypatch.setattr(os,'listdir',lambda path:(_ for _ in ()).throw(PermissionError('synthetic proc refusal')))
    with pytest.raises(ValueError,match='Cannot secure private descriptors'):package_entry._seal_private_descriptors()


def test_external_helper_survives_app_exit_without_blocking_replacement(tmp_path):
    home,p,sentinel=v2(tmp_path);stage=staged(home,p,tmp_path,'descriptor-fixed')
    # Fixture guard execs active in the same PID. Active deliberately uses an
    # external launch primitive with close_fds=False to expose any leakage.
    helper=tmp_path/'helper.py';ready=tmp_path/'helper-ready.json';stop=tmp_path/'helper-stop'
    private=tmp_path/'private';private.write_text('private synthetic evidence')
    helper.write_text('''import json,os,sys,time
from pathlib import Path
root=Path(sys.argv[1]); evidence=Path(sys.argv[2]); stop=Path(sys.argv[3]); private=Path(sys.argv[4])
found=[]
for name in os.listdir('/proc/self/fd'):
 try:
  target=os.readlink('/proc/self/fd/'+name)
  if target in (str(root/'manual-replacement.lock'),str(private)):found.append(target)
 except FileNotFoundError:pass
evidence.write_text(json.dumps({'pid':os.getpid(),'leaked':found}))
while not stop.exists():time.sleep(.02)
''')
    app=tmp_path/'app.py'
    app.write_text('''import os,subprocess,sys,time
from pathlib import Path
from desktop.package_entry import _seal_private_descriptors,_installation_read_lock,_exec_active
_seal_private_descriptors()
root,helper,ready,stop,private=map(Path,sys.argv[1:6])
if len(sys.argv)==6:
 _installation_read_lock(root)
 _exec_active(sys.executable,[sys.executable,__file__,*sys.argv[1:],'--active'])
_installation_read_lock(root)
fd=os.open(private,os.O_RDONLY);os.set_inheritable(fd,True)
_seal_private_descriptors()
proc=subprocess.Popen([sys.executable,str(helper),str(root),str(ready),str(stop),str(private)],close_fds=False,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
deadline=time.monotonic()+5
while not ready.exists():
 assert proc.poll() is None and time.monotonic()<deadline
 time.sleep(.01)
print('active',flush=True);input()
''')
    env=dict(os.environ,PYTHONPATH=str(Path.cwd()))
    proc=subprocess.Popen([sys.executable,str(app),str(p['opt']),str(helper),str(ready),str(stop),str(private)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env)
    try:
        assert proc.stdout.readline().strip()=='active',proc.stderr.read() if proc.poll() is not None else 'no active checkpoint'
        evidence=json.loads(ready.read_text());assert not evidence['leaked']
        with pytest.raises(ValueError,match='lock is held'):m.transition(home,stage_operation=stage['operation_id'])
        proc.stdin.write('\n');proc.stdin.flush();assert proc.wait(timeout=5)==0
        os.kill(evidence['pid'],0)  # read-only existence probe, no signal
        assert m.transition(home,stage_operation=stage['operation_id'])['active_release']=='descriptor-fixed'
        os.kill(evidence['pid'],0)
        assert sentinel.read_text()=='original synthetic quiz and Study history\n'
    finally:
        stop.touch()  # exact task helper's normal exit, no broad kill
        if proc.poll() is None:proc.stdin.write('\n');proc.stdin.flush();proc.wait(timeout=5)


def test_partial_handoff_failure_restores_all_tracked_locks(tmp_path,monkeypatch):
    first=os.open(tmp_path/'a',os.O_RDWR|os.O_CREAT,0o600)
    second=os.open(tmp_path/'b',os.O_RDWR|os.O_CREAT,0o600)
    monkeypatch.setattr(package_entry,'_INSTALL_LOCKS',{'a':first,'b':second})
    original=os.set_inheritable
    def fail_second(fd,value):
        if fd==second and value:raise OSError(errno.EIO,'synthetic handoff failure')
        original(fd,value)
    monkeypatch.setattr(os,'set_inheritable',fail_second)
    try:
        with pytest.raises(OSError):package_entry._exec_active('not reached',['not reached'])
        assert not os.get_inheritable(first) and not os.get_inheritable(second)
    finally:os.close(first);os.close(second)


def test_failed_seal_never_dispatches_external_url(monkeypatch,tmp_path):
    from desktop import shell
    from PySide6.QtCore import QUrl
    called=[]
    monkeypatch.setattr(package_entry,'_seal_private_descriptors',lambda:(_ for _ in ()).throw(ValueError('synthetic descriptor refusal')))
    monkeypatch.setattr(shell.QDesktopServices,'openUrl',lambda url:called.append(url) or True)
    with pytest.raises(ValueError,match='synthetic descriptor refusal'):shell.dispatch_external(QUrl.fromLocalFile(str(tmp_path)))
    assert not called

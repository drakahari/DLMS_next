"""Bounded stderr capture for an owner-observed normal Windows09 run.

Never closes/kills the application. After the recording bound, keeps draining
the pipe until the owner closes normally. Uses existing opt-in window metadata
probes; adds no instrumentation/bridge or graphics selection flags.
Raw chunks are unchanged; index times are receipt times.
Raw stderr can contain application messages, URLs and paths: synthetic data only.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT=Path(__file__).resolve().parents[2]

EXE_SHA256='3a08b6a8a098e5885c9a5becad0e356f7d70a0ab32280dd11c1ce359570ac5e6'


class BoundedLog:
    def __init__(self,raw,index,*,seconds=900,limit=8*1024*1024,records=65536,clock=time.monotonic):
        self.raw=raw;self.index=index;self.seconds=seconds;self.limit=limit;self.records=records
        self.clock=clock;self.start=clock();self.bytes=0;self.chunks=0;self.reason=None;self.errors=[]
    def failure(self,stage,error):
        # No exception text/content in the bounded error receipt.
        if len(self.errors)<8:self.errors.append({'stage':stage,'type':type(error).__name__})
        try:self.stop('collector-error')
        except (Exception,KeyboardInterrupt):pass
    def stop(self,reason):
        if self.reason is not None:return
        self.reason=reason
        self.index.write(json.dumps({'event':'capture-stop','reason':reason,'raw_bytes':self.bytes,'chunks':self.chunks,
            'observed_utc':datetime.now(timezone.utc).isoformat(),'elapsed_ms':round((self.clock()-self.start)*1000)})+'\n')
        self.raw.flush();self.index.flush()
    def feed(self,data):
        if self.reason is not None:return
        if self.clock()-self.start>=self.seconds:self.stop('duration');return
        if self.chunks>=self.records:self.stop('record-limit');return
        remaining=self.limit-self.bytes
        piece=data[:remaining]
        if piece:
            offset=self.bytes
            written=self.raw.write(piece)
            self.bytes+=written
            if written!=len(piece):raise OSError('Incomplete raw capture write')
            self.chunks+=1
            self.index.write(json.dumps({'event':'chunk','received_utc':datetime.now(timezone.utc).isoformat(),
                'elapsed_ms':round((self.clock()-self.start)*1000),'offset':offset,'bytes':len(piece)})+'\n')
        if len(data)>=remaining:self.stop('byte-limit')


def drain_capture(source,capture,started=lambda:None,finished=lambda:None):
    """Logging failures/interrupts never abandon a live application's pipe.

    The owner closes the application. Bounds disable recording, not draining.
    A duration footer is delayed until the next chunk/EOF on a quiet pipe.
    """
    try:started()
    except (Exception,KeyboardInterrupt) as exc:capture.failure('startup-metadata',exc)
    while True:
        try:
            block=source.read1(65536)
        except KeyboardInterrupt as exc:
            capture.failure('interrupt',exc)
            continue
        except Exception as exc:
            # An unreadable source cannot be drained. Report this separately
            # instead of retrying forever or claiming a normal capture.
            capture.failure('pipe-read',exc)
            raise
        if not block:break
        try:capture.feed(block)
        except (Exception,KeyboardInterrupt) as exc:capture.failure('log',exc)
    try:capture.stop('application-exit')
    except (Exception,KeyboardInterrupt) as exc:capture.failure('footer',exc)
    try:finished()
    except (Exception,KeyboardInterrupt) as exc:capture.failure('result-metadata',exc)


def private_json(path,*,limit=4096):
    from desktop.windows_files import assert_path,owned,open_read
    assert_path(path,leaf=True);owned(path,private=True)
    with os.fdopen(open_read(path),'rb') as stream:
        value=stream.read(limit+1)
    if len(value)>limit:raise ValueError('Oversized synthetic profile metadata')
    return json.loads(value)


def capture_file(path,binary):
    from desktop.windows_files import pinned_parents,owned
    with pinned_parents(path):
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_BINARY,0o600)
        try:
            owned(path,private=True);os.set_inheritable(fd,False)
            return os.fdopen(fd,'wb' if binary else 'w',**({} if binary else {'encoding':'utf-8'}))
        except BaseException:os.close(fd);raise


def main():
    if os.name!='nt':raise RuntimeError('Normal native Windows capture only')
    from tests.windows.normal_processes import identity
    p=argparse.ArgumentParser();p.add_argument('--exe',type=Path,required=True)
    p.add_argument('--data',type=Path,required=True);p.add_argument('--profile',required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--check-only',action='store_true');a=p.parse_args()
    exe=a.exe.absolute();data=a.data.absolute();out=a.output.absolute()
    from desktop.windows_files import assert_path,owned
    from desktop.isolation import NAME
    for path in (exe,data,out):assert_path(path)
    if (not NAME.fullmatch(a.profile) or not all(path.is_relative_to(ROOT/'.gate1/windows-native') for path in (exe,data,out))
            or out.parent!=ROOT/'.gate1/windows-native' or out.exists()
            or data.is_relative_to(exe.parent) or exe.parent.is_relative_to(data)
            or exe.name!='DLMS-Desktop.exe' or hashlib.sha256(exe.read_bytes()).hexdigest()!=EXE_SHA256):
        raise ValueError('Exact Windows09 executable, scoped data and fresh output required')
    marker=private_json(data/'.dlms-desktop-windows-candidate.json')
    if marker!={'kind':'dlms-desktop-windows-candidate','version':1}:raise ValueError('Candidate marker mismatch')
    for directory in (data,data/'profiles',data/'profiles'/a.profile,data/'shell',data/'shell'/a.profile):
        assert_path(directory);owned(directory,private=True)
        if not directory.is_dir():raise ValueError('Existing synthetic profile required')
    manifest=private_json(data/'profiles'/a.profile/'desktop-profile.json')
    if manifest.get('name')!=a.profile:raise ValueError('Existing profile identity mismatch')
    mode=data/'shell'/a.profile/'mode.json'
    assert_path(mode,leaf=True)
    if mode.exists():
        from desktop.server_mode import _validate_config
        if _validate_config(a.profile,private_json(mode))['mode']!='local':
            raise ValueError('This graphics capture requires Local; no Server endpoint will be contacted')
    # Absent mode.json is the application's defined Local default.
    if a.check_only:
        print('Read-only preflight passed: exact Windows09 hash, existing private synthetic profile, Local mode, fresh output. No launch or writes.')
        return
    out.mkdir(mode=0o700);owned(out,private=True)
    env={k:v for k,v in os.environ.items() if not k.startswith(('DLMS_','QUIZAPP_','QTWEBENGINE_','PYTHON'))}
    env.update(QT_LOGGING_RULES='qt.webenginecontext.debug=true;qt.webengine.compositor.debug=true',
        QT_FORCE_STDERR_LOGGING='1',QT_MESSAGE_PATTERN='[%{time yyyy-MM-ddTHH:mm:ss.zzz} %{pid} %{category}] %{message}')
    command=[str(exe),'--data-root',str(data),'--profile',a.profile,'--capture-window-events']
    from desktop.profile_state import atomic_json
    record={'prepared_utc':datetime.now(timezone.utc).isoformat(),
        'local_prepared':datetime.now().astimezone().isoformat(),
        'exe_sha256':EXE_SHA256,'data':str(data),'profile':a.profile,'seconds':900,'raw_limit':8*1024*1024,
        'chunk_limit':65536,'settings_changed':False,'recorder':'Windows Snipping Tool (owner operated)',
        'physical_acceptance':False,'logging_may_affect_timing':True}
    with capture_file(out/'graphics.raw.log',True) as raw,capture_file(out/'graphics-index.jsonl',False) as index:
        capture=BoundedLog(raw,index)
        proc=subprocess.Popen(command,cwd=exe.parent,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        def started():
            record['started_utc']=datetime.now(timezone.utc).isoformat()
            record['launcher']=identity(proc.pid)
            atomic_json(out/'launcher.json',record)
            print('Normal Windows09 launched. Use Windows Snipping Tool. Close DLMS normally to finish; capture bounds never close it.',flush=True)
        def finished():
            # EOF need not imply process exit; continue waiting without sending
            # a signal, including when Ctrl+C interrupts this wait.
            while True:
                try:code=proc.wait();break
                except KeyboardInterrupt as exc:capture.failure('wait-interrupt',exc)
            atomic_json(out/'result.json',record|{'exit_code':code,'stop_reason':capture.reason,
                'raw_bytes':capture.bytes,'chunks':capture.chunks,'errors':capture.errors,
                'application_closed_by_harness':False})
        drain_capture(proc.stdout,capture,started,finished)
        proc.stdout.close()  # Only after EOF and the owner's normal close.
        if capture.errors:
            try:atomic_json(out/'capture-errors.json',{'errors':capture.errors})
            except (Exception,KeyboardInterrupt):pass  # Disk may still be unavailable.
            print('Capture had collector errors; do not count it as a clean capture.',flush=True)

if __name__=='__main__':main()

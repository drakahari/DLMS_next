"""Real process identities, copied executable bytes and AppImage-only gating."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import pytest
from desktop import ownership, build_info
from desktop.appimage_runtime import NAMESPACE, same_image_executable

@pytest.fixture
def image_owner(tmp_path,monkeypatch):
    real_python=sys.executable
    copied=tmp_path/'different mount/python';copied.parent.mkdir();shutil.copyfile(real_python,copied)
    payload=tmp_path/'payload';assets=payload/'desktop_assets';assets.mkdir(parents=True)
    sha=hashlib.sha256(copied.read_bytes()).hexdigest()
    meta=assets/'appimage-info.json';meta.write_text(json.dumps({'format':1,'namespace':NAMESPACE,'release':'image-test','executable_sha256':sha}))
    monkeypatch.setattr(sys,'_MEIPASS',str(payload),raising=False)
    monkeypatch.setattr(sys,'executable',str(copied))
    monkeypatch.setattr(build_info,'information',lambda:{'release':'image-test'})
    monkeypatch.setattr(ownership,'FROZEN',True)
    root=tmp_path/'root';profile=root/'profiles/appimage01';profile.mkdir(parents=True)
    monkeypatch.setattr(ownership,'AREA',root);monkeypatch.setenv('DLMS_DESKTOP_ROOT_KIND','disposable')
    procs=[]
    def start(args=None):
        args=args or ['--profile','appimage01','--data-root',str(root)]
        p=subprocess.Popen([real_python,'-c','import time;time.sleep(30)',*args],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);procs.append(p)
        descriptor=profile/'instance-owner.json';descriptor.write_text(json.dumps({'pid':p.pid,'start_ticks':ownership.process_start_ticks(p.pid),'name':'appimage01','secret':'b'*64}))
        return p,descriptor
    yield start,meta,root,copied
    for p in procs:p.terminate();p.wait(timeout=5)


def test_same_bytes_different_mount_pass(image_owner):
    start,_,_,_=image_owner;p,descriptor=start()
    assert Path(f'/proc/{p.pid}/exe').resolve()!=Path(sys.executable).resolve()
    assert same_image_executable(p.pid)
    assert ownership.verified_instance(descriptor,'appimage01')=='b'*64


@pytest.mark.parametrize('fault',['untagged','sha','release','code','secret','birth','uid'])
def test_image_identity_mismatch_refuses(image_owner,monkeypatch,fault):
    start,meta,_,copied=image_owner;p,d=start()
    if fault=='untagged':meta.unlink()
    elif fault=='code':copied.write_bytes(b'foreign binary')
    elif fault in {'sha','release'}:
        x=json.loads(meta.read_text());x['executable_sha256' if fault=='sha' else 'release']='wrong';meta.write_text(json.dumps(x))
    elif fault=='uid':monkeypatch.setattr(os,'getuid',lambda:99999999)
    else:
        x=json.loads(d.read_text());x['secret' if fault=='secret' else 'start_ticks']='invalid';d.write_text(json.dumps(x))
    assert ownership.verified_instance(d,'appimage01') is None


@pytest.mark.parametrize('args', [
    ['--desktop-worker','backend','--profile','appimage01','--data-root','{root}'],
    ['--profile','other','--data-root','{root}'],
    ['--profile','appimage01','--data-root','wrong'],
    ['--profile','appimage01','--data-root','{root}','--data-root','{root}'],
    ['--profile','appimage01','--installed-pilot-root','{root}'],
])
def test_byte_match_does_not_override_role_profile_or_root(image_owner,args):
    start,_,root,_=image_owner;p,d=start([str(root) if s=='{root}' else s for s in args])
    assert same_image_executable(p.pid)
    assert ownership.verified_instance(d,'appimage01') is None

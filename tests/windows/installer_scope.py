"""Qualify only compile-time TestScope installers; never real-user integration."""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
WORK=ROOT/'.gate1/windows-native'

def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def tree(root):
    return {p.relative_to(root).as_posix():digest(p) for p in root.rglob('*') if p.is_file()}

def variant(path):
    path=path.resolve(strict=True)
    if not path.is_relative_to(WORK):raise ValueError('Task-local installer only')
    records=json.loads((path.parent/'artifacts.json').read_text())
    item=next(x for x in records if x['file']==path.name)
    if not item['isolated_variant'] or digest(path)!=item['sha256']:
        raise ValueError('Only an unchanged compile-time isolated variant may run')
    return path

def invoke(exe,app,log,*,uninstall=False):
    command=[str(exe),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/LOG='+str(log)]
    if not uninstall:command.append('/DIR='+str(app))
    return subprocess.run(command,timeout=120).returncode

def junction(path,target):
    path.parent.mkdir(parents=True,exist_ok=True)
    subprocess.run(['cmd.exe','/c','mklink','/J',str(path),str(target)],capture_output=True,check=True)

def main():
    p=argparse.ArgumentParser();p.add_argument('--candidate',required=True);p.add_argument('--initial',type=Path,required=True)
    p.add_argument('--update',type=Path,required=True);p.add_argument('--initial-release',required=True)
    p.add_argument('--update-release',required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();first,second=variant(args.initial),variant(args.update)
    out=args.output.absolute()
    if not out.is_relative_to(WORK) or out.exists():raise ValueError('Use a fresh task-local scope')
    out.mkdir(mode=0o700);records=[]
    outside=out/'outside sentinel';outside.mkdir();(outside/'unchanged.txt').write_bytes(b'not an application payload')
    expected=tree(outside)
    # No existing nested reparse point may redirect extraction/uninstaller writes.
    for number,relative in enumerate(('versions/'+args.initial_release+'/_internal','uninstall')):
        app=out/f'unsafe-{number}';link=app/relative;junction(link,outside)
        try:
            code=invoke(first,app,out/f'junction-{number}.log')
            assert code!=0 and tree(outside)==expected,(code,relative)
            assert not list(app.rglob('DLMS-Desktop.exe'))
            records.append({'case':relative,'refused':True,'exit':code})
        finally:link.rmdir()
    app=out/'publicly writable fixture';app.mkdir(mode=0o700)
    subprocess.run(['icacls.exe',str(app),'/grant','*S-1-1-0:(OI)(CI)M'],capture_output=True,check=True)
    try:
        code=invoke(first,app,out/'public-write.log')
        assert code!=0 and not (app/'versions').exists(),code
        records.append({'case':'public write ACL','refused':True,'exit':code})
    finally:
        subprocess.run(['icacls.exe',str(app),'/remove:g','*S-1-1-0'],capture_output=True,check=True)
    # An app-owned mutex must cause refusal without terminating the owner.
    from desktop.windows_processes import api,k,close
    from ctypes import wintypes as w
    mutex=api(k,'CreateMutexW',w.HANDLE,w.LPVOID,w.BOOL,w.LPCWSTR)(None,False,'Local\\DLMSDesktop.WindowsCandidate.Running')
    assert mutex
    try:
        app=out/'in-use'
        code=invoke(first,app,out/'in-use.log')
        assert code!=0 and not (app/'versions').exists(),code
        records.append({'case':'in-use mutex','refused':True,'exit':code})
    finally:close(mutex)
    app=out/'Installed candidate 日本語 with spaces'
    assert invoke(first,app,out/'install.log')==0
    inventory=json.loads((WORK/args.candidate/'payload-inventory.json').read_text())
    expected_payload={x['path']:x['sha256'] for x in inventory}
    original=app/'versions'/args.initial_release
    assert tree(original)==expected_payload
    subprocess.run([sys.executable,'-m','tests.windows.normal_candidate','--exe',str(original/'DLMS-Desktop.exe'),
                    '--output',str(out/'external persistent data'),'--ocr'],cwd=ROOT,check=True,timeout=120)
    data=out/'external persistent data'/'Synthetic data 日本語 with spaces'
    data_before=tree(data)
    assert data_before
    assert invoke(second,app,out/'update.log')==0
    assert tree(original)==expected_payload and tree(app/'versions'/args.update_release)==expected_payload
    assert tree(data)==data_before
    # Substitution after installation also refuses uninstall before any file deletion.
    actual=original/'_internal';moved=original/'_internal.retained'
    actual.rename(moved);junction(actual,outside)
    uninstaller=app/'uninstall/unins000.exe'
    try:
        code=invoke(uninstaller,app,out/'unsafe-uninstall.log',uninstall=True)
        assert code!=0 and tree(outside)==expected and (original/'DLMS-Desktop.exe').is_file()
        assert tree(data)==data_before
        records.append({'case':'post-install substitution','refused':True,'exit':code})
    finally:actual.rmdir();moved.rename(actual)
    assert invoke(uninstaller,app,out/'uninstall.log',uninstall=True)==0
    assert tree(data)==data_before and tree(outside)==expected
    assert not list(app.rglob('DLMS-Desktop.exe'))
    # Inno's normal uninstaller helper removes its running image asynchronously.
    deadline=time.monotonic()+15
    while any(x.is_file() for x in app.rglob('*')) and time.monotonic()<deadline:time.sleep(.1)
    assert not [x for x in app.rglob('*') if x.is_file()], 'Unexpected installed files remain'
    result={'isolated_variant_only':True,'real_user_integration_tested':False,'normal_installed_payload_tested':True,
            'same_payload_update':True,'prior_version_retained':True,'external_data_preserved':True,
            'uninstalled':True,'guards':records,'remaining_empty_directories':[str(x) for x in app.rglob('*') if x.is_dir()]}
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print('Isolated installer/update/uninstall, path refusal and external-data preservation passed')

if __name__=='__main__':main()

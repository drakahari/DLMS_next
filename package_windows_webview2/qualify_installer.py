"""Qualify only compile-time TestScope installers; never real-user integration."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'.gate1/windows-native'
RESERVED_FIXTURES=('CON','PRN','AUX','NUL.txt','COM1','COM\u00b9.txt','LPT9','LPT\u00b2.txt','LPT\u00b3','CON .txt')

def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def tree(root):
    return {p.relative_to(root).as_posix():digest(p) for p in root.rglob('*') if p.is_file()}

def release_identity(value):
    if not re.fullmatch(r'[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*', value):
        raise ValueError('Unsafe isolated release identity')
    return value


def candidate_inventory(candidate):
    release_identity(candidate)
    from desktop.windows_files import assert_path
    assert_path(WORK/candidate)
    directory=(WORK/candidate).resolve(strict=True)
    if directory.parent!=WORK.resolve():raise ValueError('Candidate must be a direct task-local build')
    path=directory/'payload-inventory.json'
    rows=json.loads(path.read_text())
    return path,{row['path']:row['sha256'] for row in rows}


def fresh_scope(path):
    path = path.resolve()
    if path.parent != WORK.resolve() or path.exists():
        raise ValueError('Use a fresh direct task-local scope')
    return path


def variant(path, release, inventory=None):
    path=path.resolve(strict=True)
    if not path.is_relative_to(WORK):raise ValueError('Task-local installer only')
    records=json.loads((path.parent/'artifacts.json').read_text())
    item=next(x for x in records if x['file']==path.name)
    if (not item['isolated_variant'] or digest(path)!=item['sha256']
            or item.get('application') != 'DLMSDesktopWebView2Candidate'
            or item.get('release') != release
            or inventory is not None and item.get('payload_inventory_sha256')!=digest(inventory)):
        raise ValueError('Only an unchanged compile-time isolated variant may run')
    return path

def invoke(exe,app,log,*,uninstall=False):
    command=[str(exe),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/LOG='+str(log)]
    if not uninstall:command.extend(['/DIR='+str(app), '/DLMSPROFILE=normal01'])
    return subprocess.run(command,timeout=120).returncode

def junction(path,target):
    path.parent.mkdir(parents=True,exist_ok=True)
    subprocess.run(['cmd.exe','/c','mklink','/J',str(path),str(target)],capture_output=True,check=True)


def reserved_fixture(root,name):
    """Create only fixed reserved-name negative fixtures below the fresh scope."""
    if name not in RESERVED_FIXTURES or not root.resolve().is_relative_to(WORK.resolve()):
        raise ValueError('Refuse reserved-name fixture outside the isolated task scope')
    parent=root/'reserved DOS fixtures'
    from desktop.windows_files import assert_path
    assert_path(parent)
    parent.mkdir(mode=0o700,exist_ok=True)
    target=parent/name
    # Extended syntax is intentional only here: ordinary extraction must refuse
    # these literal directory names before writing any application payload.
    native=Path('\\\\?\\'+str(target))
    native.mkdir(mode=0o700)
    return target,native

def main():
    p=argparse.ArgumentParser();p.add_argument('--candidate',required=True);p.add_argument('--initial',type=Path,required=True)
    p.add_argument('--initial-candidate',help='Distinct original payload for real cross-version qualification')
    p.add_argument('--update',type=Path,required=True);p.add_argument('--initial-release',required=True)
    p.add_argument('--update-release',required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    for value in (args.candidate,args.initial_release,args.update_release):release_identity(value)
    old_candidate=args.initial_candidate or args.candidate
    old_inventory,expected_old=candidate_inventory(old_candidate)
    new_inventory,expected_new=candidate_inventory(args.candidate)
    if args.initial_release==args.update_release:raise ValueError('Distinct release identities required')
    first=variant(args.initial,args.initial_release,old_inventory)
    second=variant(args.update,args.update_release,new_inventory)
    out=fresh_scope(args.output)
    out.mkdir(mode=0o700);records=[]
    outside=out/'outside sentinel';outside.mkdir();(outside/'unchanged.txt').write_bytes(b'not an application payload')
    expected=tree(outside)
    for number,name in enumerate(RESERVED_FIXTURES):
        app,native=reserved_fixture(out,name)
        code=invoke(first,app,out/f'reserved-{number}.log')
        assert code!=0 and not list(native.iterdir()),(code,name)
        assert tree(outside)==expected
        records.append({'case':'reserved DOS component','component':name,'refused':True,'exit':code})
    # No existing nested reparse point may redirect extraction/uninstaller writes.
    for number,relative in enumerate(('versions/'+args.initial_release+'/_internal','uninstall')):
        app=out/f'unsafe-{number}';link=app/relative;junction(link,outside)
        try:
            code=invoke(first,app,out/f'junction-{number}.log')
            assert code!=0 and tree(outside)==expected,(code,relative)
            assert not list(app.rglob('DLMS-Desktop-WebView2.exe'))
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
    mutex=api(k,'CreateMutexW',w.HANDLE,w.LPVOID,w.BOOL,w.LPCWSTR)(None,False,'Local\\DLMSDesktop.WebView2Candidate.Running')
    assert mutex
    try:
        app=out/'in-use'
        code=invoke(first,app,out/'in-use.log')
        assert code!=0 and not (app/'versions').exists(),code
        records.append({'case':'in-use mutex','refused':True,'exit':code})
    finally:close(mutex)
    app=out/'Installed candidate 日本語 with spaces'
    assert invoke(first,app,out/'install.log')==0
    original=app/'versions'/args.initial_release
    updated=app/'versions'/args.update_release
    assert tree(original)==expected_old
    subprocess.run([sys.executable,'-m','tests.webview2.normal_candidate','--exe',str(original/'DLMS-Desktop-WebView2.exe'),
                    '--inventory',str(old_inventory),
                    '--output',str(out/'external persistent data'),'--ocr'],cwd=ROOT,check=True,timeout=120)
    external=out/'external persistent data'
    data=external/'Synthetic data 日本語 with spaces'
    data_before=tree(external)
    assert data_before
    (out/'external-before-update.json').write_text(json.dumps(data_before,indent=2)+'\n')
    assert invoke(second,app,out/'update.log')==0
    assert tree(original)==expected_old and tree(updated)==expected_new
    assert tree(external)==data_before
    (out/'external-after-update.json').write_text(json.dumps(tree(external),indent=2)+'\n')
    # Reopen the actual old populated profile with the new normal executable.
    # Never omit --data-root: Known Folder resolution would select owner data.
    from tests.settings.gui_native_roundtrip import facts
    oracle=json.loads((external/'portable-facts.json').read_text())
    assert facts(data/'profiles/normal01/backend')==oracle
    backup=external/'normal-export.zip';backup_hash=digest(backup)
    export_hashes={name:digest(external/name) for name in ('library-reference.txt','individual-quiz.txt')}
    subprocess.run([sys.executable,'-m','tests.webview2.normal_walkthrough_launch',
                    '--exe',str(updated/'DLMS-Desktop-WebView2.exe'),'--inventory',str(new_inventory),
                    '--data-root',str(data),'--profile','normal01','--expected-workflow',str(external/'result.json'),
                    '--output',str(out/'updated-normal-reopen')],cwd=ROOT,check=True,timeout=120)
    assert facts(data/'profiles/normal01/backend')==oracle and digest(backup)==backup_hash
    assert all(digest(external/name)==value for name,value in export_hashes.items())
    assert json.loads((data/'profiles/normal01/backend/config/portal.json').read_text())['theme']=='dark'
    data_before_uninstall=tree(external)
    (out/'external-before-uninstall.json').write_text(json.dumps(data_before_uninstall,indent=2)+'\n')
    # Substitution after installation also refuses uninstall before any file deletion.
    actual=original/'_internal';moved=original/'_internal.retained'
    if not actual.resolve(strict=True).is_relative_to(WORK) or not moved.absolute().is_relative_to(WORK):
        raise ValueError('Refuse moving an installation directory outside the isolated workspace')
    actual.rename(moved);junction(actual,outside)
    uninstaller=app/'uninstall/unins000.exe'
    try:
        code=invoke(uninstaller,app,out/'unsafe-uninstall.log',uninstall=True)
        assert code!=0 and tree(outside)==expected and (original/'DLMS-Desktop-WebView2.exe').is_file()
        assert tree(external)==data_before_uninstall
        records.append({'case':'post-install substitution','refused':True,'exit':code})
    finally:actual.rmdir();moved.rename(actual)
    assert invoke(uninstaller,app,out/'uninstall.log',uninstall=True)==0
    assert tree(external)==data_before_uninstall and tree(outside)==expected
    (out/'external-after-uninstall.json').write_text(json.dumps(tree(external),indent=2)+'\n')
    assert not list(app.rglob('DLMS-Desktop-WebView2.exe'))
    # Inno's normal uninstaller helper removes its running image asynchronously.
    deadline=time.monotonic()+15
    while app.exists() and time.monotonic()<deadline:time.sleep(.1)
    assert not [x for x in app.rglob('*') if x.is_file()], 'Unexpected installed files remain'
    assert not (app/'versions').exists(), 'Empty application payload directories remain'
    assert not app.exists(), 'The clean isolated application directory remains after helper exit'
    result={'isolated_variant_only':True,'real_user_integration_tested':False,'normal_installed_payload_tested':True,
            'same_payload_update':expected_old==expected_new,'initial_candidate':old_candidate,'updated_candidate':args.candidate,
            'initial_inventory_sha256':digest(old_inventory),'updated_inventory_sha256':digest(new_inventory),
            'prior_version_retained':True,'external_data_preserved':True,'updated_existing_profile_reopened':True,
            'portable_rows_assets_theme_preserved':True,'external_backup_sha256':backup_hash,
            'external_text_export_hashes':export_hashes,
            'uninstalled':True,'guards':records,'remaining_empty_directories':[str(x) for x in app.rglob('*') if x.is_dir()]}
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print('Isolated installer/update/uninstall, path refusal and external-data preservation passed')

if __name__=='__main__':main()

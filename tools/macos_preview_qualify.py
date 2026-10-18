"""Focused changed-package and quarantined-opening checks; no installations.

Reuses completed runtime/owner evidence. New empty preview storage only; no
installed Candidate, existing profiles, credentials or production connections.
"""
from __future__ import annotations
import ctypes
import hashlib
import http.server
import json
import os
from pathlib import Path
import plistlib
import socket
import subprocess
import sys
import tempfile
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from package_macos.build import app_inventory,digest,create_dmg,runtime_inventory
from package_macos.preview_materials import verify
from desktop import macos_processes as native
from desktop.macos_paths import real_home,default_data_root

CACHE=real_home()/'.cache/dlms-desktop-macos-preview'


def require(value,message):
    if not value: raise RuntimeError(message)


def run(args,timeout=90,allowed=(0,)):
    env={key:value for key,value in os.environ.items()
         if not key.startswith(('DLMS_','QUIZAPP_','QT','DYLD_','PYTHON'))}
    env.update(HOME=str(real_home()),PATH='/usr/bin:/bin:/usr/sbin:/sbin',TMPDIR='/private/tmp')
    result=subprocess.run([str(a) for a in args],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE,env=env,timeout=timeout)
    require(result.returncode in allowed,'Bounded native check failed: '+result.stderr.decode(errors='replace')+result.stdout.decode(errors='replace'))
    return result


def save(path,value):
    path.write_text(json.dumps(value,indent=2)+'\n');path.chmod(0o600)


def candidate():
    require(sys.platform=='darwin' and os.getuid()==os.geteuid()!=0,'Native normal user only')
    pointer=json.loads((ROOT/'.gate1/macos/CANDIDATE.json').read_text())
    stage=Path(pointer['stage']);app=Path(pointer['app'])
    require(stage.parent==CACHE and stage.name.startswith('build-') and app==stage/'dist/DLMS Desktop.app',
            'Unexpected preview artifact path')
    require(not app.is_symlink(),'Aliased preview app refused')
    manifest=app_inventory(app)
    require(hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()==pointer['app_manifest_sha256'],
            'Preview artifact manifest changed')
    run(['/usr/bin/codesign','--verify','--deep','--strict',app])
    verify(stage/'notices')
    return stage,app,pointer


def package():
    stage,app,pointer=candidate()
    require(not (stage/'PACKAGE_CHECK.json').exists(),'Preserve previous check; do not repeat automatically')
    info=plistlib.loads((app/'Contents/Info.plist').read_bytes())
    require(info['CFBundleIdentifier']=='io.github.drakahari.DLMSDesktop.MacPreview'
            and info['CFBundleName']=='DLMS Desktop','Expected single preview identity')
    require([p.name for p in app.parent.iterdir()]==['DLMS Desktop.app'],'Unexpected second app entry')
    require(digest(app/'Contents/Resources/desktop_assets/icons/macos/DLMSDesktop.icns')==
            digest(ROOT/'desktop_assets/icons/macos/DLMSDesktop.icns'),'Cleared bundled icon changed')
    help_result=run([app/'Contents/MacOS/DLMS-Desktop','--help'],timeout=25)
    require(b'DLMS Desktop Apple Silicon preview' in help_result.stdout,'Wrong frozen entry/help')
    fixtures=real_home()/'Documents/DLMS-Mac-walkthrough-20261017'
    for line in (ROOT/'tests/fixtures/macos_handoff/SHA256SUMS').read_text().splitlines():
        expected,name=line.split(maxsplit=1)
        file=fixtures/name.removeprefix('*')
        require(file.is_file() and digest(file)==expected,'Visible fixture differs: '+str(file))
    tess=list(app.glob('Contents/Frameworks/ocr/**/tesseract'))
    tess=[p for p in tess if p.is_file() and os.access(p,os.X_OK)]
    require(len(tess)==1,'Expected one bundled OCR executable')
    models=list(app.glob('Contents/Resources/ocr/**/eng.traineddata'))
    require(len(models)==1,'Expected exact bundled English model')
    ocr=run([tess[0],fixtures/'ocr-question.png','stdout','--tessdata-dir',models[0].parent,'--psm','6'])
    text=ocr.stdout.decode(errors='replace')
    require('Which protocol secures web traffic?' in text and 'HTTPS' in text,
            'Bundled OCR omitted synthetic fixture content')
    pdfium=list(app.glob('Contents/Frameworks/pypdfium2_raw/libpdfium.dylib'))
    if not pdfium: pdfium=list(app.glob('Contents/Resources/pypdfium2_raw/libpdfium.dylib'))
    require(len(pdfium)==1,'Expected bundled PDFium library')
    library=ctypes.CDLL(str(pdfium[0]))
    library.FPDF_InitLibrary()
    load=library.FPDF_LoadDocument;load.argtypes=[ctypes.c_char_p,ctypes.c_char_p];load.restype=ctypes.c_void_p
    doc=load(os.fsencode(fixtures/'scanned.pdf'),None)
    require(bool(doc),'Bundled PDFium failed to read synthetic scanned PDF')
    count=library.FPDF_GetPageCount;count.argtypes=[ctypes.c_void_p];count.restype=ctypes.c_int
    require(count(doc)==1,'Unexpected synthetic scanned PDF pages')
    close=library.FPDF_CloseDocument;close.argtypes=[ctypes.c_void_p];close(doc)
    library.FPDF_DestroyLibrary()
    save(stage/'PACKAGE_CHECK.json',{'status':'pass','single_entry':True,'cleared_icon':True,
        'frozen_help':True,'bundled_ocr':True,'bundled_pdfium':True,'fixtures':str(fixtures),
        'reused_runtime_evidence':True,'broad_tests_repeated':False})
    image=create_dmg(stage,app)
    print('Package passed; verified DMG:',image,flush=True)


def opening(resume=False):
    stage,app,pointer=candidate()
    require(json.loads((stage/'PACKAGE_CHECK.json').read_text())['status']=='pass','Package check required')
    image=stage/'DLMS-Desktop-3.3.0-macos-arm64-preview1.dmg'
    require(image.is_file(),'Verified DMG missing')
    require(not default_data_root().exists() and not default_data_root().is_symlink(),
            'Preview default storage already exists; preserve it and stop before normal launch')
    require(resume or not (CACHE/'OPENING_INPUT.json').exists(),'Preserve existing opening configuration and evidence')
    helper=CACHE/'opening'
    require(helper.is_file() and not helper.is_symlink(),'Reviewed native opening helper missing')
    previous=json.loads((CACHE/'OPENING_INPUT.json').read_text()) if resume else None
    directory=Path(previous['download']).parent if resume else Path(tempfile.mkdtemp(prefix='DLMS-Mac-preview-opening-',dir=real_home()/'Downloads'))
    require(directory.parent==real_home()/'Downloads' and directory.name.startswith('DLMS-Mac-preview-opening-')
            and not directory.is_symlink(),'Unsafe opening check directory')
    download=directory/image.name;target=directory/'DLMS Desktop.app'
    require(not target.exists(),'Preserve existing opening app; inspect before another attempt')
    evidence={'status':'running','scope':'Controlled loopback download plus native OS quarantine; no Safari/GitHub end-to-end claim',
              'dmg_sha256':digest(image),'helper_sha256':digest(helper),'steps':[],
              'global_security_changes':False,'manual_quarantine_removal':False,'installed_apps_changed':False,
              'production_access':False,'existing_profiles_changed':False}
    output=directory/('OPENING-RESUME.json' if resume else 'OPENING.json')
    require(not output.exists(),'Preserve existing opening evidence')
    mount=directory/'mount';mount.mkdir(mode=0o700,exist_ok=True)
    device=None
    launched_identity=None

    def action(name,allow_stop=False):
        print('OPENING',name,flush=True)
        result=run([helper,name],timeout=110,allowed=(0,1) if allow_stop else (0,))
        value=json.loads(result.stdout)
        evidence['steps'].append(value);save(output,evidence)
        return value

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path!='/'+image.name:
                self.send_error(404);return
            self.send_response(200);self.send_header('Content-Type','application/x-apple-diskimage')
            self.send_header('Content-Length',str(image.stat().st_size));self.end_headers()
            with image.open('rb') as stream:
                while block:=stream.read(1024*1024): self.wfile.write(block)
        def log_message(self,*args): pass

    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
    server.daemon_threads=True
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    config=previous or {'url':f'http://127.0.0.1:{server.server_port}/{image.name}','download':str(download),'app':str(target)}
    require(config['download']==str(download) and config['app']==str(target),'Opening configuration changed')
    if not resume: save(CACHE/'OPENING_INPUT.json',config)
    save(output,evidence)
    try:
        if resume: action('inspect-quarantine')
        else: action('download')
        require(digest(download)==digest(image),'Downloaded DMG bytes differ')
        server.shutdown();server.server_close();thread.join(3)
        attached=run(['/usr/bin/hdiutil','attach',download,'-readonly','-nobrowse','-noautoopen','-verify',
                      '-plist','-mountpoint',mount],timeout=45)
        entities=plistlib.loads(attached.stdout)['system-entities']
        device=next(row['dev-entry'] for row in entities if row.get('dev-entry','').startswith('/dev/disk') and
                    row['dev-entry'].removeprefix('/dev/disk').isdigit())
        source=mount/'DLMS Desktop.app'
        require(app_inventory(source)==app_inventory(app),'Downloaded image payload differs')
        run(['/usr/bin/ditto','--rsrc','--extattr','--qtn','--acl',source,target])
        require(app_inventory(target)==app_inventory(app),'Task opening copy payload differs')
        run(['/usr/bin/codesign','--verify','--deep','--strict',target])
        action('mark-app')
        run(['/usr/bin/hdiutil','detach',device],timeout=30);device=None
        before=action('inspect-dialog')
        require(not before['target_dialogs'] and not before['preview_processes']
                and not before['frontmost_is_authentication'],
                'An existing matching warning/app/authentication is present; do not approve it')
        assessment=run(['/usr/sbin/spctl','--assess','--type','execute','--verbose=4',target],allowed=(0,1,2,3,4))
        evidence['assessment_before']={'returncode':assessment.returncode,'text':assessment.stderr.decode(errors='replace')}
        action('double-click')
        time.sleep(3)
        state=action('inspect-dialog')
        if state['target_dialogs'] or not state['preview_processes']:
            require(not state['frontmost_is_authentication'],'Opening requires interactive owner authentication; stop')
            require(state['target_dialogs'],'No running app or inspectable target warning; stop without bypass')
            require(not any(x.get('refusal') for x in state['target_dialogs']),
                    'macOS warning refuses safe automation: '+repr(state['target_dialogs']))
            action('open-settings');time.sleep(2)
            action('dismiss-warning');time.sleep(1)
            approval=action('open-anyway',allow_stop=True)
            require(approval.get('status')=='ok','Normal per-app approval unavailable: '+approval.get('reason',''))
            time.sleep(2)
            state=action('inspect-dialog')
            require(not state['frontmost_is_authentication'],'Normal approval needs interactive owner authentication; stop')
            if state['target_dialogs']:
                action('confirm-open');time.sleep(4)
                state=action('inspect-dialog')
            require(not state['frontmost_is_authentication'],
                    'Normal per-app approval requires owner authentication; leave it to the owner and resume finish-opening')
        require(len(state['preview_processes'])==1,'Normal per-app approval did not open exactly one preview')
        process=state['preview_processes'][0];identity=native.identity(process['pid'])
        launched_identity=identity
        require(identity['uid']==os.getuid(),'Unexpected running preview identity')
        actual_bundle=Path(process['bundle_path'])
        require(digest(actual_bundle/'Contents/MacOS/DLMS-Desktop')==digest(app/'Contents/MacOS/DLMS-Desktop'),
                'Running/translocated executable differs')
        deadline=time.monotonic()+25
        manifest=default_data_root()/'profiles/default/desktop-profile.json'
        while not manifest.exists() and time.monotonic()<deadline: time.sleep(.2)
        require(manifest.exists(),'Normal Finder entry failed to initialize its isolated default profile')
        saved=json.loads(manifest.read_text());require(saved['name']=='default','Wrong preview default profile')
        evidence['normal_finder_launch']={'passed':True,'profile':'default','separate_default_root':True,
                                         'app_translocation':'/AppTranslocation/' in str(actual_bundle)}
        action('cmd-q')
        deadline=time.monotonic()+25
        while time.monotonic()<deadline:
            try: current=native.identity(identity['pid'])
            except OSError: break
            if not native._same_birth(identity,current) or current['status']==5: break
            time.sleep(.1)
        else: raise RuntimeError('Preview survived actual Cmd-Q')
        evidence.update(status='pass',app_left_closed=True,downloaded_payload_verified=True,
                        quarantined_normal_opening=True)
    except BaseException as exc:
        evidence.update(status='stopped',error=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        if evidence['status']!='pass':
            try:
                state=action('inspect-dialog',allow_stop=True)
                evidence['preview_processes_on_failure']=state.get('preview_processes',[])
            except Exception as diagnostic:
                evidence['failure_state_error']=str(diagnostic)
        if evidence['status']!='pass' and launched_identity:
            try:
                current=native.identity(launched_identity['pid'])
                if native._same_birth(launched_identity,current) and current['status']!=5:
                    cleanup=action('cmd-q',allow_stop=True)
                    evidence['failure_graceful_cleanup']=cleanup
                    evidence['task_identity_at_failure']=launched_identity
            except Exception as cleanup_error:
                evidence['failure_cleanup_error']=str(cleanup_error)
        server.shutdown();server.server_close()
        if device: run(['/usr/bin/hdiutil','detach',device],timeout=30)
        save(output,evidence)
        save(stage/'OPENING_CHECK.json',evidence)
        print('Opening evidence:',output,flush=True)


def finish_opening():
    """Complete the existing owner-approved opening; never start a new attempt.

    No approval controls are pressed here. A new warning/authentication stops the
    check. Earlier stopped-attempt receipts remain separate and unchanged.
    """
    import fcntl
    stage,app,pointer=candidate()
    config=json.loads((CACHE/'OPENING_INPUT.json').read_text())
    target=Path(config['app']);download=Path(config['download'])
    require(target.parent==download.parent and target.parent.parent==real_home()/'Downloads'
            and target.parent.name.startswith('DLMS-Mac-preview-opening-')
            and not target.parent.is_symlink(),'Unexpected task opening paths')
    output=target.parent/'OPENING_FINAL.json'
    require(not output.exists(),'Preserve final opening evidence; do not repeat')
    require(app_inventory(target)==app_inventory(app),'Downloaded app payload changed')
    require(digest(download)==digest(stage/download.name),'Downloaded DMG changed')
    evidence={'status':'running','scope':'Controlled loopback HTTP download with native macOS quarantine; not Safari/GitHub end-to-end',
              'dmg_sha256':digest(download),'steps':[],
              'owner_authenticated_per_app_exception':True,
              'global_security_changes':False,'manual_quarantine_removal':False,
              'installed_apps_changed':False,'production_access':False,
              'existing_profiles_changed':False,'broad_tests_repeated':False,
              'earlier_receipts':['OPENING.json','OPENING-RESUME.json']}
    manifest=default_data_root()/'profiles/default/desktop-profile.json'
    require(manifest.is_file() and not manifest.is_symlink(),'Expected new preview default profile missing')
    saved=manifest.read_bytes()

    def action(name):
        result=json.loads(run([CACHE/'opening',name],timeout=110).stdout)
        evidence['steps'].append(result);save(output,evidence)
        return result

    def ready():
        state=action('inspect-dialog')
        require(not state['target_dialogs'] and not state['frontmost_is_authentication'],
                'New warning/authentication present: stop without further approval')
        require(len(state['preview_processes'])==1,'Expected one public preview')
        process=state['preview_processes'][0]
        bundle=Path(process['bundle_path'])
        require('/AppTranslocation/' in str(bundle) or bundle==target,'Unexpected running bundle')
        require(app_inventory(bundle)==app_inventory(app),'Running/translocated app differs')
        deadline=time.monotonic()+25
        while time.monotonic()<deadline:
            windows=process['windows']
            if len(windows)==1 and 'Local' in windows[0]['title'] and 'profile default' in windows[0]['title'] \
                    and 'Training & Practice Center' in windows[0]['text']:
                break
            time.sleep(.5)
            state=action('inspect-dialog')
            require(not state['target_dialogs'] and not state['frontmost_is_authentication'],
                    'Reopen produced a new warning/authentication; stop')
            require(len(state['preview_processes'])==1,'Preview disappeared before normal window')
            process=state['preview_processes'][0]
        else: raise RuntimeError('Normal Local dashboard did not become ready')
        identities=[]
        for value in run(['/bin/ps','-axo','pid=']).stdout.split():
            try: found=native.identity(int(value))
            except OSError: continue
            if found['uid']==os.getuid() and Path(found['image']).is_relative_to(bundle): identities.append(found)
        require(any(item['pid']==process['pid'] for item in identities),'Cannot identify task process birth')
        return identities,'/AppTranslocation/' in str(bundle)

    def close(identities):
        action('cmd-q')
        deadline=time.monotonic()+25
        while time.monotonic()<deadline:
            live=[]
            for found in identities:
                try: current=native.identity(found['pid'])
                except OSError: continue
                if native._same_birth(found,current) and current['status']!=5: live.append(found['pid'])
            if not live: break
            time.sleep(.1)
        else: raise RuntimeError('Task-owned app/helpers survived Cmd-Q')
        state=action('inspect-dialog')
        require(not state['preview_processes'],'A preview remains after Cmd-Q')
        path=manifest.parent/'backend-writer.lock'
        fd=os.open(path,os.O_RDWR|os.O_NOFOLLOW)
        try: fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        finally: os.close(fd)
        require(not (manifest.parent/'instance.lock').exists(),'Instance lock remains after Cmd-Q')
        require(not (default_data_root()/'shell/default/instance.lock').exists(),
                'Shell instance lock remains after Cmd-Q')

    try:
        first,translocated=ready()
        close(first)
        require(manifest.read_bytes()==saved,'Profile identity changed during shutdown')
        action('double-click');time.sleep(3)
        second,reopened_translocated=ready()
        require(manifest.read_bytes()==saved,'Finder reopen changed the default profile identity')
        close(second)
        action('inspect-quarantine')
        for path in (target,download):
            require(run(['/usr/bin/xattr','-p','com.apple.quarantine',path]).stdout.strip(),
                    'Expected quarantine missing after normal approval')
        require(app_inventory(target)==app_inventory(app),'Approved app payload changed')
        run(['/usr/bin/codesign','--verify','--deep','--strict',target])
        evidence.update(status='pass',normal_finder_launch=True,local_dashboard_ready=True,
                        app_translocation=translocated,reopened_app_translocation=reopened_translocated,
                        actual_cmd_q_and_finder_reopen=True,default_profile_identity_reused=True,
                        task_app_and_helpers_stopped=True,writer_and_instance_locks_released=True,
                        quarantine_retained=True,signature_and_payload_verified=True,app_left_closed=True)
    except BaseException as exc:
        evidence.update(status='stopped',error=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        save(output,evidence);save(stage/'OPENING_FINAL.json',evidence)
        print('Final opening evidence:',output,flush=True)


def finalize_receipt():
    """Verify metadata after the recorded GUI pass, without repeating GUI input.

    Python on this Mac does not expose os.getxattr. The first completion stopped
    only at that final metadata API after both Cmd-Q operations. Preserve it and
    use the native read-only xattr command for the remaining checks.
    """
    import fcntl
    stage,app,pointer=candidate()
    config=json.loads((CACHE/'OPENING_INPUT.json').read_text())
    target=Path(config['app']);download=Path(config['download'])
    previous=target.parent/'OPENING_FINAL.json'
    output=target.parent/'OPENING_ACCEPTANCE.json'
    require(not output.exists(),'Preserve accepted receipt; do not repeat')
    evidence=json.loads(previous.read_text())
    require(evidence.get('error')=="AttributeError: module 'os' has no attribute 'getxattr'",
            'Only the known final metadata API interruption may resume here')
    steps=evidence['steps']
    names=[step['action'] for step in steps]
    # Readiness may take more than one observation after reopen.
    collapsed=[name for i,name in enumerate(names) if i==0 or name!='inspect-dialog' or names[i-1]!=name]
    require(collapsed==['inspect-dialog','cmd-q','inspect-dialog','double-click','inspect-dialog',
                    'cmd-q','inspect-dialog','inspect-quarantine'],
            'Expected completed GUI sequence missing; no pass inferred')
    quits=[i for i,name in enumerate(names) if name=='cmd-q']
    for index in quits:
        preceding=steps[index-1]
        require(len(preceding['preview_processes'])==1 and steps[index]['app_translocation'],
                'Expected translocated app and normal-window observation missing')
        windows=preceding['preview_processes'][0]['windows']
        require(len(windows)==1 and 'profile default' in windows[0]['title']
                and 'Training & Practice Center' in windows[0]['text'],
                'Recorded normal Local dashboard readiness missing')
    require(not steps[-2]['preview_processes'] and not steps[-2]['target_dialogs'],
            'Final recorded app stop missing')
    state=json.loads(run([CACHE/'opening','inspect-dialog']).stdout)
    require(not state['preview_processes'] and not state['target_dialogs'],'Preview or warning remains')
    for path in (target,download):
        require(run(['/usr/bin/xattr','-p','com.apple.quarantine',path]).stdout.strip(),'Quarantine missing')
    require(app_inventory(target)==app_inventory(app),'Approved payload changed')
    require(digest(download)==digest(stage/download.name),'Approved DMG changed')
    run(['/usr/bin/codesign','--verify','--deep','--strict',target])
    profile=default_data_root()/'profiles/default'
    fd=os.open(profile/'backend-writer.lock',os.O_RDWR|os.O_NOFOLLOW)
    try: fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    finally: os.close(fd)
    require(not (profile/'instance.lock').exists(),'Instance lock remains')
    require(not (default_data_root()/'shell/default/instance.lock').exists(),
            'Shell instance lock remains')
    evidence.pop('error')
    evidence.update(status='pass',normal_finder_launch=True,local_dashboard_ready=True,
                    app_translocation=True,actual_cmd_q_and_finder_reopen=True,
                    default_profile_identity_reused=True,task_app_and_helpers_stopped=True,
                    writer_and_instance_locks_released=True,quarantine_retained=True,
                    signature_and_payload_verified=True,app_left_closed=True,
                    final_metadata_api_fix='Native read-only xattr; GUI checks were not repeated',
                    earlier_completion_receipt='OPENING_FINAL.json')
    save(output,evidence);save(stage/'OPENING_ACCEPTANCE.json',evidence)
    print('Quarantined opening passed; app closed. Evidence:',output,flush=True)


if __name__=='__main__':
    require(len(sys.argv)==2 and sys.argv[1] in ('package','opening','resume-opening','finish-opening','finalize-receipt'),'Fixed qualification action only')
    if sys.argv[1]=='package': package()
    elif sys.argv[1]=='finish-opening': finish_opening()
    elif sys.argv[1]=='finalize-receipt': finalize_receipt()
    else: opening(resume=sys.argv[1]=='resume-opening')

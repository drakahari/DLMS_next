"""External normal-package workflows plus read-only owned renderer inspection."""
import json,time
from pathlib import Path
import sys
import re

FORBIDDEN={'--no-sandbox','--disable-gpu','--disable-web-security','--ignore-certificate-errors',
           '--allow-running-insecure-content','--disable-site-isolation-trials','--single-process',
           '--no-zygote','--in-process-gpu'}


def argument_metadata(argv):
    """Retain bounded graphics choices and feature names, never full argv."""
    graphics=[]
    for item in argv:
        name,separator,value=item.partition('=')
        if name in {'--use-angle','--use-gl'} and separator:
            graphics.append({'flag':name,'value':value if re.fullmatch(r'[A-Za-z0-9_.-]{1,48}',value) else '<unrecognized>'})
        elif name in {'--enable-features','--disable-features','--enable-blink-features','--disable-blink-features'} and separator:
            features=[part.split('<',1)[0].split(':',1)[0] for part in value.split(',')[:128]]
            graphics.append({'flag':name,'feature_names':[part for part in features if re.fullmatch(r'[A-Za-z0-9_.-]{1,96}',part)]})
    role=next((item for item in argv if item.startswith('--type=')),'main')
    if role!='main' and re.fullmatch(r'--type=[a-z0-9-]{1,48}',role) is None:role='<unrecognized>'
    return {'arguments_read':True,'security_bypass_flags':[item.partition('=')[0] for item in argv if item.partition('=')[0] in FORBIDDEN],
            'role':role,
            'graphics_flags':graphics}


def file_version(path):
    import ctypes as c
    from ctypes import wintypes as w
    from desktop.windows_processes import api,checked
    library=c.WinDLL('version',use_last_error=True)
    size=api(library,'GetFileVersionInfoSizeW',w.DWORD,w.LPCWSTR,c.POINTER(w.DWORD))
    load=api(library,'GetFileVersionInfoW',w.BOOL,w.LPCWSTR,w.DWORD,w.DWORD,w.LPVOID)
    query=api(library,'VerQueryValueW',w.BOOL,w.LPCVOID,w.LPCWSTR,c.POINTER(w.LPVOID),c.POINTER(w.UINT))
    ignored=w.DWORD();length=size(str(path),c.byref(ignored))
    if not length:raise c.WinError(c.get_last_error())
    data=c.create_string_buffer(length);checked(load(str(path),0,length,data))
    pointer=w.LPVOID();count=w.UINT();checked(query(data,'\\',c.byref(pointer),c.byref(count)))
    if count.value<52:raise ValueError('Incomplete file-version resource')
    fields=c.cast(pointer,c.POINTER(w.DWORD*13)).contents
    if fields[0]!=0xFEEF04BD:raise ValueError('Invalid file-version resource')
    return '.'.join(map(str,(fields[2]>>16,fields[2]&65535,fields[3]>>16,fields[3]&65535)))


def coverage_by_parent(samples):
    coverage={}
    for sample in samples:
        found=coverage.setdefault(sample['parent'],set())
        for row in sample['processes']:
            if 'identity' not in row:continue
            image=Path(row['identity']['image']).name.lower()
            if image=='qtwebengineprocess.exe':raise AssertionError('Owned Qt WebEngine renderer found')
            if row.get('security_bypass_flags'):raise AssertionError('Sampled browser security bypass found')
            if not row.get('arguments_read'):continue
            if image=='dlms-webview2-host.exe':found.add('host')
            version=row.get('selected_file_versions',{}).get(row['identity']['image'],{}).get('version')
            if image=='msedgewebview2.exe' and row.get('role')=='main' and version:found.add('browser-main')
            if image=='msedgewebview2.exe' and row.get('role')=='--type=gpu-process':found.add('gpu')
    return coverage


def renderer_ready(samples,parent):
    return coverage_by_parent(samples).get(parent,set()) == {'host','browser-main','gpu'}


def inspection_coverage(samples):
    coverage=coverage_by_parent(samples)
    if len(coverage)<2 or any(found!={'host','browser-main','gpu'} for found in coverage.values()):
        raise AssertionError('Incomplete owned host/browser-main/GPU argument coverage')
    return {str(parent):sorted(found) for parent,found in coverage.items()}


def main():
    from package_windows_webview2.acceptance import payload_binding
    import argparse
    parser=argparse.ArgumentParser(add_help=False,allow_abbrev=False)
    parser.add_argument('--inventory',type=Path,required=True)
    parsed,remaining=parser.parse_known_args(sys.argv[1:])
    sys.argv=[sys.argv[0],*remaining]
    exe=Path(sys.argv[sys.argv.index('--exe')+1])
    before=payload_binding(exe,parsed.inventory)
    from tests.windows import normal_candidate as workflows
    from desktop.windows_processes import arguments
    from tests.windows.normal_processes import modules
    original=workflows.descendants;original_nonce=workflows.backend_nonce;samples=[];last=[0]
    versions={}
    def inspect(parent):
        result=original(parent)
        if time.monotonic()-last[0]>1:
            last[0]=time.monotonic();rows=modules(parent)
            for row in rows:
                if 'identity' not in row:continue
                try:
                    argv=arguments(row['pid'])
                    row.update(argument_metadata(argv))
                except (OSError,ValueError) as exc:
                    row['argument_inspection_error']={'type':type(exc).__name__,'winerror':getattr(exc,'winerror',None)}
                image=row['identity']['image']
                selected=[image] if Path(image).name.lower()=='msedgewebview2.exe' else []
                selected.extend(row.get('modules',[]))
                row['selected_file_versions']={}
                for path in selected:
                    if path not in versions:
                        try:versions[path]={'version':file_version(path)}
                        except (OSError,ValueError) as exc:versions[path]={'error':type(exc).__name__,'winerror':getattr(exc,'winerror',None)}
                    row['selected_file_versions'][path]=versions[path]
            samples.append({'parent':parent,'processes':rows})
        return result
    workflows.descendants=inspect
    renderer_wait_started={}
    def ready_nonce(parent,expected_image,diagnostics=None):
        value=original_nonce(parent,expected_image,diagnostics)
        if value:
            inspect(parent)
            if renderer_ready(samples,parent):return value
            started=renderer_wait_started.setdefault(parent,time.monotonic())
            if time.monotonic()-started>=30:
                raise TimeoutError('Normal package did not provide complete owned renderer inspection within 30 seconds')
            if diagnostics is not None:diagnostics['renderer_readiness']='Awaiting complete owned host/browser-main/GPU argument and runtime-version inspection'
        return None
    workflows.backend_nonce=ready_nonce
    out=Path(sys.argv[sys.argv.index('--output')+1])
    try:
        workflows.main()
    finally:
        workflows.descendants=original
        workflows.backend_nonce=original_nonce
        if out.is_dir():
            (out/'renderer-inspection.json').write_text(json.dumps({'normal_package':True,
                'app_test_hooks':False,'physical_acceptance':False,'samples':samples},indent=2)+'\n')
    coverage=inspection_coverage(samples)
    inspection=json.loads((out/'renderer-inspection.json').read_text())
    inspection.update({'complete_argument_coverage':coverage,
                       'rendering_backend':'Use only observed allowlisted flags; loaded graphics DLLs do not establish the active backend or correct pixels.'})
    (out/'renderer-inspection.json').write_text(json.dumps(inspection,indent=2)+'\n')
    after=payload_binding(exe,parsed.inventory)
    if after!=before:raise ValueError('Payload identity changed during normal executable testing')
    receipt=json.loads((out/'result.json').read_text())
    receipt.update(after)
    receipt['payload_verified_before_and_after']=True
    receipt['owned_webview2_renderer_verified']=True
    (out/'result.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print('Normal package uses owned WebView2 processes; no owned Qt WebEngine renderer or sampled security-bypass flags.')


if __name__=='__main__':main()

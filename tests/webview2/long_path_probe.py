"""Native WebView2 path-boundary IO and refusal checks; synthetic GUI only."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
from tests.webview2.host_security import AREA, Fixture, Host, fresh
from tests.webview2.focus_blob_probe import rpc
from tests.webview2.blob_download_probe import create_link, click_download, terminal, BODY

KNOWN_HOSTS = {
    'webview2-host-candidate-40': 'cffbd1c5db3f01994dea12f3dd92bdeae9d76143475f3cc7bcfc9ae4e9b7e1cc',
    'webview2-host-candidate-37': '46ff7e41389396ca73b43eb3f6d2d6c1833002b5c4073fb9a5ddb3544d82fd11',
    'webview2-host-candidate-38': 'eb318d53839df5bbb3e41389c7073b7cf9a641d08b2bac5f7c5186f5a628dbd6',
    'webview2-host-candidate-39': '7194225fa4046d8c7368244e1da775000cf9f61819c4bc977111d6a053151860',
}


def deep_directory(base,minimum=285):
    current = base
    number = 0
    while len(str(current)) < minimum:
        number += 1
        remaining=minimum-len(str(current))-1
        if remaining==0:remaining=1
        name=f'segment-{number:02d} 日本語 and spaces'
        if remaining<len(name):name='p'*remaining
        current = fresh(current/name)
    return current


def api_name(parent,prefix,suffix,target_characters):
    if target_characters is None:return prefix+suffix
    padding=target_characters-len(str(parent/prefix).encode('utf-16-le'))//2-len(suffix)
    if padding<0:raise ValueError('Requested path cannot preserve synthetic basename')
    name=prefix+'p'*padding+suffix
    assert len(str(parent/name).encode('utf-16-le'))//2==target_characters
    return name


def run_case(executable, output, mode, long_storage=False,parent_characters=285,bounded_api_names=False,api_path_characters=None):
    case = fresh(output/mode)
    deep = deep_directory(case,parent_characters)
    fixture = Fixture(secrets.token_hex(32), policy=mode == 'local').start()
    host, result = None, {'mode': mode, 'physical_acceptance': False,'failures':[]}
    try:
        # This additionally exercises the native pinned-policy/metadata APIs at
        # long paths rather than only the managed download path check.
        storage = fresh((deep if long_storage else case)/'browser-storage')
        host = Host(executable, case, fixture, mode, reuse_storage=storage)
        host.loaded()
        result['long_storage'] = {'characters': len(str(storage)), 'ready': True}
        link = create_link(host)
        download, index = click_download(host, link)
        target = deep/(('.wv-'+'a'*32+'.part') if bounded_api_names else ('.dlms-webview2-'+'a'*48+'.partial'))
        assert (len(str(target)) < 260) if bounded_api_names else (len(str(target)) > 260)
        accepted = rpc(host, 'download', download_id=download['download_id'], action='accept', path=str(target))
        assert accepted.get('ok'), accepted
        done = terminal(host, download['download_id'], index)
        success=done['state']=='completed' and target.exists() and target.read_bytes()==BODY
        if not success:result['failures'].append('download')
        result['download'] = {'characters': len(str(target)), 'expected_bytes': len(BODY),
                              'parent_characters':len(str(target.parent)),
                              'native_file_present': target.exists(),
                              'native_bytes': target.stat().st_size if target.exists() else None,
                              'sha256': hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else None,
                              'terminal': done,'passed':success}
        if not target.exists():target.write_bytes(BODY) # Explicit sentinel for independent overwrite-refusal check.
        existing, index = click_download(host, link)
        refused = rpc(host, 'download', download_id=existing['download_id'], action='accept', path=str(target))
        assert refused.get('ok') is False and target.read_bytes() == BODY, refused
        assert terminal(host, existing['download_id'], index)['state'] == 'cancelled'
        result['existing_download_refused'] = refused
        source = deep/(api_name(deep,'synthetic 日本語 ','.txt',api_path_characters) if bounded_api_names else ('synthetic input '+'i'*75+' 日本語.txt'))
        source.write_bytes(BODY)
        setup = host.evaluate("document.body.innerHTML='<input id=probe-file type=file>';"
                              "(()=>{const r=document.getElementById('probe-file').getBoundingClientRect();return {x:r.x+20,y:r.y+r.height/2}})()")
        assert setup.get('ok'), setup
        start = len(host.events)
        assert rpc(host, 'click', **setup['value']).get('ok')
        picker = host.wait(lambda rows: next((row for row in rows[start:] if row.get('event') == 'file-picker'), None))
        applied = rpc(host, 'files', ticket=picker['ticket'], paths=[str(source)])
        assert applied.get('ok') and applied.get('value', {}).get('files_applied') is True, applied
        read = host.evaluate("(async()=>{const f=document.getElementById('probe-file').files[0];try{const h=await crypto.subtle.digest('SHA-256',await f.arrayBuffer());return {name:f.name,size:f.size,sha256:Array.from(new Uint8Array(h)).map(v=>v.toString(16).padStart(2,'0')).join('')}}catch(e){return {error:e.name,size:f.size}}})()")
        success=read.get('ok') and read['value']=={'name':source.name,'size':len(BODY),'sha256':hashlib.sha256(BODY).hexdigest()}
        if not success:result['failures'].append('input-read')
        result['input'] = {'characters': len(str(source)), 'read': read.get('value'), 'handback': applied,'passed':success}
        pdf = deep/(api_name(deep,'render 日本語 ','.pdf',api_path_characters) if bounded_api_names else ('native printed '+'p'*65+' 日本語.pdf'))
        printed = rpc(host, 'print', path=str(pdf))
        success=printed.get('ok') and printed.get('value') is True and pdf.exists() and pdf.read_bytes().startswith(b'%PDF-')
        if not success:result['failures'].append('print')
        native_pdf_present=pdf.exists()
        native_pdf_bytes=pdf.stat().st_size if native_pdf_present else None
        if not native_pdf_present:pdf.write_bytes(b'%PDF-synthetic-existing-sentinel')
        digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
        refused = rpc(host, 'print', path=str(pdf))
        assert refused.get('ok') is False and hashlib.sha256(pdf.read_bytes()).hexdigest() == digest, refused
        result['print'] = {'characters': len(str(pdf)), 'bytes': pdf.stat().st_size, 'sha256': digest,
                           'native_file_present': native_pdf_present,'native_bytes': native_pdf_bytes,
                           'oracle_sentinel_created':not native_pdf_present,
                           'existing_output_refused': refused,'native_reply':printed,'passed':success}
        # The junction is short and targets another synthetic short directory.
        # Its deep descendant still gives a >260-character refused request.
        outside = fresh(case/'junction-target')
        outside_deep = deep_directory(outside)
        outside_file = outside_deep/'input.txt'
        outside_file.write_bytes(b'synthetic junction sentinel')
        junction = case/'junction'
        subprocess.run(['cmd.exe', '/c', 'mklink', '/J', str(junction), str(outside)],
                       check=True, capture_output=True, timeout=10)
        alias = junction/outside_deep.relative_to(outside)
        assert len(str(alias/'blocked.partial')) > 260
        link = create_link(host)
        download, index = click_download(host, link)
        refused = rpc(host, 'download', download_id=download['download_id'], action='accept', path=str(alias/'blocked.partial'))
        assert refused.get('ok') is False and not (outside_deep/'blocked.partial').exists(), refused
        assert terminal(host, download['download_id'], index)['state'] == 'cancelled'
        printed = rpc(host, 'print', path=str(alias/'blocked.pdf'))
        assert printed.get('ok') is False and not (outside_deep/'blocked.pdf').exists(), printed
        host.evaluate("document.body.innerHTML='<input id=probe-file type=file>';true")
        clicked = host.evaluate("document.getElementById('probe-file').getBoundingClientRect().toJSON()")
        start = len(host.events)
        assert rpc(host, 'click', x=clicked['value']['x']+20, y=clicked['value']['y']+10).get('ok')
        picker = host.wait(lambda rows: next((row for row in rows[start:] if row.get('event') == 'file-picker'), None))
        inputs = rpc(host, 'files', ticket=picker['ticket'], paths=[str(alias/'input.txt')])
        assert inputs.get('ok') is False and inputs.get('value', {}).get('files_exposed') is False, inputs
        assert outside_file.read_bytes() == b'synthetic junction sentinel'
        result['long_reparse_refused'] = {'characters': len(str(alias/'blocked.partial')),
                                         'download': refused, 'print': printed, 'input': inputs,
                                         'sentinel_unchanged': True}
        result['passed'] = not result['failures']
        return result
    finally:
        (case/'result.json').write_text(json.dumps(result, indent=2)+'\n')
        try:
            if host: host.close()
        finally:
            (case/'requests.json').write_text(json.dumps(fixture.snapshot(), indent=2)+'\n')
            fixture.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--host', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--long-storage', action='store_true', help='Additionally place browser storage itself beyond MAX_PATH')
    p.add_argument('--parent-characters',type=int,default=285)
    p.add_argument('--bounded-api-names',action='store_true',help='Same parent/storage; shorter browser API names below260, while long reparse refusals remain')
    p.add_argument('--api-path-characters',type=int,help='With bounded names, pad input/PDF to this exact UTF16 path length')
    args = p.parse_args()
    if os.name != 'nt': raise RuntimeError('Native Windows only')
    from desktop.windows_processes import own_launcher
    from desktop.windows_files import assert_path
    from package_windows_webview2.build import verify_host
    own_launcher()
    executable, output = args.host.absolute(), args.output.absolute()
    assert_path(executable, leaf=True)
    expected = KNOWN_HOSTS.get(executable.parent.parent.name)
    if not executable.is_relative_to(AREA) or expected is None or hashlib.sha256(executable.read_bytes()).hexdigest() != expected:
        raise ValueError('Exact known project-local host required')
    verify_host(executable.parent)
    fresh(output)
    results, complete = [], False
    try:
        for mode in ('local', 'server'): results.append(run_case(executable, output, mode,args.long_storage,args.parent_characters,args.bounded_api_names,args.api_path_characters))
        complete = True
    finally:
        (output/'summary.json').write_text(json.dumps({'host': str(executable), 'host_sha256': expected,
            'harness_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'bounded_api_names':args.bounded_api_names,
            'api_path_characters':args.api_path_characters,
            'cases': results, 'complete': complete, 'physical_acceptance': False}, indent=2)+'\n')
    print('Native long-path checks closed. Evidence: '+str(output))
    if not all(row['passed'] for row in results):raise AssertionError('Native long-path boundary failed; independent results preserved')


if __name__ == '__main__': main()

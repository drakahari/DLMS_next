"""Explicit native download-only blob checks; synthetic standalone host, not UI acceptance."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import time
from tests.webview2.host_security import AREA, Fixture, Host, fresh
from tests.webview2.focus_blob_probe import rpc

KNOWN_HOSTS = {
    'webview2-host-candidate-51': '39afa03a2a7aa3deb6c7957d597238d4a7b3f2b688df3a964545186550488416',
    'webview2-host-candidate-40': 'cffbd1c5db3f01994dea12f3dd92bdeae9d76143475f3cc7bcfc9ae4e9b7e1cc',
    'webview2-host-candidate-34': '465de737982a075db33bba3482b877692756876803df29a5d35d8b280796860a',
    'webview2-host-candidate-36': 'a78935aa90284db131d1e606da4f6a0b1010d231e1d6b5de94b712f685ebc1e8',
    'webview2-host-candidate-38': 'eb318d53839df5bbb3e41389c7073b7cf9a641d08b2bac5f7c5186f5a628dbd6',
    'webview2-host-candidate-39': '7194225fa4046d8c7368244e1da775000cf9f61819c4bc977111d6a053151860',
}
BODY = ('Synthetic DLMS blob bytes 日本語\r\n'*128).encode('utf-8')


def create_link(host, name='synthetic-export.txt', body=BODY, kind='text/plain'):
    script = ("(()=>{document.body.replaceChildren();const a=document.createElement('a');"
              "a.href=URL.createObjectURL(new Blob([new Uint8Array("+json.dumps(list(body))+")],{type:"+json.dumps(kind)+"}));"
              "a.id='blob-export';a.download="+json.dumps(name)+";a.textContent='Synthetic export';"
              "a.style.cssText='display:block;padding:20px';document.body.append(a);"
              "const r=a.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2,url:a.href}})()")
    reply = host.evaluate(script)
    assert reply.get('ok'), reply
    return reply['value']


def click_download(host, link):
    index = len(host.events)
    reply = rpc(host, 'click', x=link['x'], y=link['y'])
    assert reply.get('ok'), reply
    event = host.wait(lambda rows: next((row for row in rows[index:]
                                        if row.get('event') == 'download'), None))
    assert event.get('blob') is True and event.get('context') == 'stable-exact-main-document', event
    assert event.get('document_url') == host.fixture.origin+'/', event
    return event, index


def terminal(host, identifier, index):
    return host.wait(lambda rows: next((row for row in rows[index:]
                                       if row.get('event') == 'download-state'
                                       and row.get('download_id') == identifier), None))


def run_case(executable, output, mode):
    case = fresh(output/mode)
    fixture = Fixture(secrets.token_hex(32), policy=mode == 'local').start()
    host, result = None, {'mode': mode, 'physical_acceptance': False}
    try:
        host = Host(executable, case, fixture, mode)
        host.loaded()
        stamp = host.evaluate('({url:location.href,time_origin:performance.timeOrigin})')
        link = create_link(host)
        download, index = click_download(host, link)
        target = fresh(case/'staging')/'held bytes 日本語.partial'
        accepted = rpc(host, 'download', download_id=download['download_id'], action='accept', path=str(target))
        assert accepted.get('ok'), accepted
        done = terminal(host, download['download_id'], index)
        assert done['state'] == 'completed', done
        actual = target.read_bytes()
        assert actual == BODY, 'Actual browser-written blob bytes differ'
        after = host.evaluate('({url:location.href,time_origin:performance.timeOrigin})')
        assert after.get('ok') and stamp['value'] == after['value'], (stamp, after)
        events = list(host.events)[index:]
        assert not [x for x in events if x.get('event') in ('load-start', 'navigation-blocked')], events
        result['positive'] = {'download': download, 'terminal': done,
                              'bytes': len(actual), 'sha256': hashlib.sha256(actual).hexdigest(),
                              'document_unchanged': True, 'navigation_events': 0,
                              'private_staging_only': True, 'final_publication_tested': False}
        cancelled, index = click_download(host, link)
        assert rpc(host, 'download', download_id=cancelled['download_id'], action='cancel').get('ok')
        cancelled_done = terminal(host, cancelled['download_id'], index)
        assert cancelled_done['state'] == 'cancelled', cancelled_done
        assert len(list(target.parent.iterdir())) == 1, 'Cancelled operation published another file'
        result['cancelled'] = cancelled_done
        stale, index = click_download(host, link)
        request = host.command('navigate', url=fixture.origin+'/replacement')
        host.wait(lambda rows: any(row.get('event') == 'load-finish' and row.get('ok')
                                  and row.get('url') == fixture.origin+'/replacement' for row in rows[index:]))
        forbidden = target.parent/'stale.partial'
        refused = rpc(host, 'download', download_id=stale['download_id'], action='accept', path=str(forbidden))
        assert refused.get('ok') is False and not forbidden.exists(), refused
        result['stale_accept_refused'] = refused
        # A real blob HTML document remains forbidden as a navigation.
        html = create_link(host, 'forbidden.html', b'<!doctype html><p>Must not navigate</p>', 'text/html')
        stamp = host.evaluate('({url:location.href,time_origin:performance.timeOrigin})')
        index = len(host.events)
        attempted = host.evaluate('location.href='+json.dumps(html['url'])+';true')
        assert attempted.get('ok'), attempted
        # Current host rejects non-HTTP navigation without treating a generic
        # blocked notification as external-browser authority. Observe actual
        # document preservation and subsequent liveness instead.
        time.sleep(.5)
        after = host.evaluate('({url:location.href,time_origin:performance.timeOrigin})')
        assert after.get('ok') and stamp['value'] == after['value'], (stamp, after)
        assert not [row for row in list(host.events)[index:] if row.get('event') == 'load-start'], 'Forbidden blob document began navigation'
        alive_index = len(host.events)
        assert rpc(host, 'navigate', url=fixture.origin+'/after-blob-refusal').get('ok')
        host.wait(lambda rows: any(row.get('event') == 'load-finish' and row.get('ok')
            and row.get('url') == fixture.origin+'/after-blob-refusal' for row in rows[alive_index:]))
        result['blob_navigation_still_blocked'] = {'actual_location_attempt': True,
            'document_unchanged': True, 'no_navigation_started': True,
            'subsequent_allowed_navigation_completed': True, 'observation_seconds': .5}
        result['passed'] = True
        return result
    finally:
        (case/'result.json').write_text(json.dumps(result, indent=2)+'\n')
        try:
            if host: host.close()
        finally:
            (case/'requests.json').write_text(json.dumps(fixture.snapshot(), indent=2)+'\n')
            fixture.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if os.name != 'nt': raise RuntimeError('Native Windows only')
    from desktop.windows_processes import own_launcher
    from desktop.windows_files import assert_path
    from package_windows_webview2.build import verify_host
    own_launcher()
    executable, output = args.host.absolute(), args.output.absolute()
    assert_path(executable, leaf=True)
    expected = KNOWN_HOSTS.get(executable.parent.parent.name)
    if (not executable.is_relative_to(AREA) or expected is None
            or hashlib.sha256(executable.read_bytes()).hexdigest() != expected):
        raise ValueError('Explicit exact known project-local host required')
    verify_host(executable.parent)
    fresh(output)
    results, complete = [], False
    try:
        for mode in ('local', 'server'): results.append(run_case(executable, output, mode))
        complete = True
    finally:
        (output/'summary.json').write_text(json.dumps({'host': str(executable), 'host_sha256': expected,
            'harness_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'cases': results, 'complete': complete, 'physical_acceptance': False}, indent=2)+'\n')
    print('Native blob checks complete; windows closed. Evidence: '+str(output))


if __name__ == '__main__': main()

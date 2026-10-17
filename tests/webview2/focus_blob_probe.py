"""Explicit standalone host33 measurements; no OS input or functional fixes.

This fixture does not contain the Qt toolbar or the full DLMS application.
It can measure browser/Form boundary behavior, not physical keyboard acceptance.
No native window is created merely by importing this module.
"""
from __future__ import annotations

import argparse
import ctypes as c
from ctypes import wintypes as w
import hashlib
import json
import os
from pathlib import Path
import secrets
import time

from tests.webview2.host_security import AREA, Fixture, Host, fresh


EXPECTED_HOST_SHA256 = '43318f9dbe11074901148650fbec9d5d663d282b2e505ac2cac2727a5d2e1b03'


class GuiThreadInfo(c.Structure):
    _fields_ = [('cbSize', w.DWORD), ('flags', w.DWORD),
                ('hwndActive', w.HWND), ('hwndFocus', w.HWND),
                ('hwndCapture', w.HWND), ('hwndMenuOwner', w.HWND),
                ('hwndMoveSize', w.HWND), ('hwndCaret', w.HWND),
                ('rcCaret', w.RECT)]


def native_focus(host):
    """Query only this owned Form's GUI thread; never read window text/input."""
    from desktop.windows_processes import api, checked
    user = c.WinDLL('user32', use_last_error=True)
    thread_for_window = api(user, 'GetWindowThreadProcessId', w.DWORD,
                            w.HWND, c.POINTER(w.DWORD))
    get_info = api(user, 'GetGUIThreadInfo', w.BOOL, w.DWORD,
                   c.POINTER(GuiThreadInfo))
    is_child = api(user, 'IsChild', w.BOOL, w.HWND, w.HWND)
    ready = next(row for row in host.events if row.get('event') == 'ready')
    hwnd, pid = ready['hwnd'], w.DWORD()
    thread = thread_for_window(w.HWND(hwnd), c.byref(pid))
    if pid.value != host.proc.pid or not thread:
        raise ValueError('Focus query target is outside the retained host process')
    info = GuiThreadInfo(cbSize=c.sizeof(GuiThreadInfo))
    checked(get_info(thread, c.byref(info)))
    focused = int(info.hwndFocus or 0)
    return {'host_hwnd': hwnd, 'host_pid': pid.value, 'thread': thread,
            'active_hwnd': int(info.hwndActive or 0), 'focused_hwnd': focused,
            'focused_in_host_tree': bool(focused == hwnd or
                                         is_child(w.HWND(hwnd), w.HWND(focused)))}


def rpc(host, operation, **values):
    identifier = host.command(operation, **values)
    reply = host.wait(lambda rows: next((row for row in rows
                                        if row.get('event') == 'reply'
                                        and row.get('id') == identifier), None))
    return reply


def dom_focus(host):
    reply = host.evaluate("({active:document.activeElement?.id||null,"
                          "tag:document.activeElement?.tagName||null,"
                          "document_has_focus:document.hasFocus()})")
    if not reply.get('ok'):
        raise AssertionError('Synthetic focus reader failed: '+str(reply))
    return reply['value']


def run_case(executable, output, mode):
    case = fresh(output/mode)
    fixture = Fixture(secrets.token_hex(32), policy=mode == 'local').start()
    host = None
    result = {'mode': mode, 'standalone_host': True, 'physical_acceptance': False,
              'qt_toolbar_present': False, 'focus_steps': []}
    try:
        host = Host(executable, case, fixture, mode)
        host.loaded()
        setup = host.evaluate("(()=>{document.body.replaceChildren();"
                              "for(const id of ['first','last']){const input=document.createElement('input');"
                              "input.id=id;input.type='text';document.body.append(input)}"
                              "return {inputs:document.querySelectorAll('input').length}})()")
        assert setup.get('ok') and setup.get('value', {}).get('inputs') == 2, setup
        assert rpc(host, 'focus').get('ok')
        for name, target, backward in [('forward-interior', 'first', False),
                                       ('forward-boundary', 'last', False),
                                       ('backward-interior', 'last', True),
                                       ('backward-boundary', 'first', True)]:
            focused = host.evaluate('document.getElementById('+json.dumps(target)+').focus();true')
            assert focused.get('ok')
            assert rpc(host, 'focus').get('ok')
            before = {'dom': dom_focus(host), 'native': native_focus(host)}
            sequence = len(host.events)
            started = time.monotonic()
            reply = rpc(host, 'tab', backward=backward)
            assert reply.get('ok'), reply
            immediate = {'dom': dom_focus(host), 'native': native_focus(host)}
            time.sleep(.2)
            settled = {'dom': dom_focus(host), 'native': native_focus(host)}
            result['focus_steps'].append({'name': name, 'backward': backward,
                                          'before': before, 'reply': reply,
                                          'immediate': immediate, 'settled': settled,
                                          'duration_ms': round((time.monotonic()-started)*1000, 2),
                                          'events': list(host.events)[sequence:]})
        blob = host.evaluate("(()=>{const a=document.createElement('a');a.id='blob-export';"
                             "a.href=URL.createObjectURL(new Blob(['DLMS synthetic blob export\\n'],{type:'text/plain'}));"
                             "a.download='synthetic-export.txt';a.textContent='Synthetic blob export';"
                             "a.style.cssText='display:block;padding:20px';document.body.append(a);"
                             "const r=a.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2,"
                             "scheme:new URL(a.href).protocol,creator_origin:new URL(a.href).origin===location.origin}})()")
        assert blob.get('ok') and blob['value']['scheme'] == 'blob:' and blob['value']['creator_origin'], blob
        sequence = len(host.events)
        before = host.evaluate('({url:location.href,time_origin:performance.timeOrigin})')
        click = rpc(host, 'click', x=blob['value']['x'], y=blob['value']['y'])
        assert click.get('ok'), click
        try:
            host.wait(lambda rows: next((row for row in rows[sequence:]
                                        if row.get('event') in ('download-blocked', 'download',
                                                                'navigation-blocked')), None), timeout=5)
        except TimeoutError:
            result['blob_terminal_event_missing'] = True
        time.sleep(.5)
        events = list(host.events)[sequence:]
        after = host.evaluate('({url:location.href,time_origin:performance.timeOrigin})')
        assert before.get('ok') and after.get('ok'), (before, after)
        result['blob'] = {'synthetic_link': blob['value'], 'click_reply': click,
                          'events': events,
                          'load_start_count': sum(row.get('event') == 'load-start' for row in events),
                          'navigation_blocked_count': sum(row.get('event') == 'navigation-blocked' for row in events),
                          'download_blocked_count': sum(row.get('event') == 'download-blocked' for row in events),
                          'download_count': sum(row.get('event') == 'download' for row in events),
                          'document_unchanged': before['value'] == after['value']}
        result['runtime'] = [row for row in host.events if row.get('event') == 'runtime']
        result['policy'] = [row for row in host.events if row.get('event') == 'socket-policy']
        result['scope'] = ('Standalone browser/Form focus and synthetic a.download event measurement; '
                           'no Qt toolbar handoff, Anki-format fidelity or normal-package acceptance claim')
        (case/'result.json').write_text(json.dumps(result, indent=2)+'\n')
        return result
    finally:
        try:
            if not (case/'result.json').exists():
                result['incomplete'] = True
                (case/'result.json').write_text(json.dumps(result, indent=2)+'\n')
            if host:
                host.close()
        finally:
            (case/'requests.json').write_text(json.dumps(fixture.snapshot(), indent=2)+'\n')
            fixture.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if os.name != 'nt':
        raise RuntimeError('Native Windows only')
    from desktop.windows_processes import own_launcher
    from desktop.windows_files import assert_path
    from package_windows_webview2.build import verify_host
    own_launcher()
    executable, output = args.host.absolute(), args.output.absolute()
    assert_path(executable, leaf=True)
    if not executable.is_relative_to(AREA) or executable.name != 'DLMS-WebView2-Host.exe':
        raise ValueError('Explicit project-local host required')
    if hashlib.sha256(executable.read_bytes()).hexdigest() != EXPECTED_HOST_SHA256:
        raise ValueError('This measurement requires the exact unchanged host33')
    verify_host(executable.parent)
    fresh(output)
    results, complete = [], False
    try:
        for mode in ('local', 'server'):
            results.append(run_case(executable, output, mode))
        complete = True
    finally:
        (output/'summary.json').write_text(json.dumps({
            'host': str(executable), 'host_sha256': EXPECTED_HOST_SHA256,
            'harness_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'complete': complete, 'cases': results,
            'physical_acceptance': False, 'functional_fix': False,
        }, indent=2)+'\n')
    print('Standalone focus/blob measurements closed. Evidence: '+str(output))


if __name__ == '__main__':
    main()

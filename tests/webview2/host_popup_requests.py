"""Standalone source-only request/popup probe; no external browser dispatcher.

Only synthetic loopback recorders receive fixed paths and empty JSON. Native
HTTP observations, not fetch readability, establish whether a request was sent.
This diagnostic never qualifies an application save or physical acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import urlsplit

from tests.webview2.host_security import AREA, Fixture, Handler, Host, fresh

ACTION = '/_desktop/recovery/action'
POPUP = 'https://dlms-popup-probe.invalid/synthetic-no-content'
OPTIONS = "{method:'POST',headers:{'Content-Type':'application/json','X-DLMS-Recovery-Client':'1'},body:'{}'}"
FETCH = 'fetch(' + json.dumps(ACTION) + ',' + OPTIONS + ')'
STATUS = "r=>({status:r.status,type:r.type})"
START = '/autonomous-start'
TERMINAL = '/autonomous-complete'
GATE = '/autonomous-gate'


class AutonomousHandler(Handler):
    def respond(self, status, body, kind='text/plain'):
        path = urlsplit(self.path).path
        if path == '/':
            body, kind = self.server.html, 'text/html; charset=utf-8'
        elif path == GATE:
            if not self.server.release.wait(15):
                status = 504
            body = b'synthetic gate'
        return super().respond(status, body, kind)


class AutonomousFixture(Fixture):
    def __init__(self, token, foreign, with_popup, trigger):
        super().__init__(token)
        self.RequestHandlerClass = AutonomousHandler
        self.release = threading.Event()
        target = json.dumps(foreign.origin + '/probe')
        popup = 'window.open('+json.dumps(POPUP)+',"_blank","noopener,noreferrer");' if with_popup else ''
        action = ('window.__syntheticAction=()=>{fetch('+json.dumps(START)+');'
            'const work=[()=>'+FETCH+',()=>fetch("/probe",'+OPTIONS+'),'
            '()=>fetch('+target+',{mode:"no-cors"}),'
            '()=>fetch('+target+',{method:"POST",mode:"no-cors",headers:{"Content-Type":"text/plain"},body:"synthetic"})]'
            '.map(fn=>Promise.resolve().then(fn));'+popup+
            'Promise.allSettled(work).then(()=>fetch('+json.dumps(TERMINAL)+'));};')
        start = ('fetch('+json.dumps(GATE)+').then(r=>{if(!r.ok)throw Error("gate failed");window.__syntheticAction();});'
                 if trigger == 'autonomous' else '')
        self.html = ('<!doctype html><title>Synthetic autonomous popup diagnostic</title><body>Neutral fixture'
                     '<script>'+action+start+'</script></body>').encode()


def run_autonomous(executable, output, mode, *, with_popup, trigger):
    label = trigger + ('-popup' if with_popup else '-no-popup')
    case = fresh(output / (mode + '-' + label))
    foreign = Fixture(secrets.token_hex(32)).start()
    fixture = AutonomousFixture(secrets.token_hex(32), foreign, with_popup, trigger).start()
    host = None
    result = {'mode': mode, 'case': label, 'source_only': True,
              'application_save_acceptance': False, 'external_dispatcher_present': False,
              'physical_acceptance': False, 'harness_input_commands': False,
              'harness_eval_commands': 0 if trigger == 'autonomous' else 1}
    try:
        host = Host(executable, case, fixture, mode)
        host.wait(lambda rows: any(e.get('event') == 'ready' for e in rows))
        identifier = host.command('policy', blocked_paths=['/probe'])
        configured = host.wait(lambda rows: next((e for e in rows if e.get('event') == 'reply' and e.get('id') == identifier), None))
        assert configured.get('ok')
        host.loaded()
        loaded = time.monotonic()
        time.sleep(2.1)
        result['seconds_after_native_load_finish_before_release'] = time.monotonic()-loaded
        if trigger == 'autonomous':
            fixture.release.set()
        else:
            result['timer_schedule_reply'] = host.evaluate('setTimeout(()=>window.__syntheticAction(),100);true', gesture=True)
            result['timer_eval_returned_monotonic'] = time.monotonic()
            assert result['timer_schedule_reply'].get('ok')
        host.wait(lambda _: any(r['path'] == TERMINAL for r in fixture.snapshot()), 20)
        observed, outside = fixture.snapshot(), foreign.snapshot()
        own = [r for r in observed if r['path'] == ACTION]
        blocked = [r for r in observed if r['path'] == '/probe']
        result.update(terminal_marker_observed=True,
            start_marker_observed=any(r['path'] == START for r in observed),
            own_requests=own, blocked_path_requests=blocked, foreign_requests=outside,
            request_authentication_passed=len(own) == 1 and all(r['authenticated'] if mode == 'local' else not r['has_token'] for r in own),
            negative_controls_passed=not blocked and not outside,
            native_user_flags_observed=[e.get('user') for e in host.events if e.get('event') in ('external-request', 'external-refused', 'popup-blocked')],
            diagnostic_completed=True)
    finally:
        fixture.release.set()
        try:
            if host is not None:
                host.close()
                result['cleanup'] = json.loads((case/'cleanup.json').read_text())
        finally:
            result['requests'] = fixture.snapshot()
            result['foreign_requests'] = foreign.snapshot()
            result['host_events'] = list(host.events) if host is not None else []
            fixture.close()
            foreign.close()
            (case/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


def request_scripts():
    popup = 'window.open(' + json.dumps(POPUP) + ",'_blank','noopener,noreferrer');"
    return [
        ('ordinary-await', '(async()=>{return [' + 'await ' + FETCH + '.then(' + STATUS + ')];})()', 1, False),
        ('queued-then-popup', '(()=>{const work=[Promise.resolve().then(()=>'+FETCH+'),'
         'Promise.resolve().then(()=>'+FETCH+')];'+popup+
         'return Promise.all(work.map(p=>p.then('+STATUS+')));})()', 2, True),
        ('await-after-popup', '(async()=>{'+popup+'return [await '+FETCH+'.then('+STATUS+')];})()', 1, True),
        ('synchronous-before-popup', '(()=>{const work='+FETCH+';'+popup+
         'return work.then('+STATUS+').then(r=>[r]);})()', 1, True),
    ]


def negatives(host, foreign, stage, *, with_popup=False):
    before = len(foreign.snapshot())
    target = json.dumps(foreign.origin + '/probe')
    script = ("(async()=>{const outcomes=[];for(const options of [{mode:'no-cors'},"
              "{method:'POST',mode:'no-cors',headers:{'Content-Type':'text/plain'},body:'synthetic'}]){"
              'try{const r=await fetch('+target+',options);outcomes.push({resolved:true,status:r.status,type:r.type});}'
              'catch(e){outcomes.push({resolved:false,error_name:e.name});}}return outcomes;})()')
    if with_popup:
        script = ('(()=>{const options=[{mode:"no-cors"},{method:"POST",mode:"no-cors",'
                  'headers:{"Content-Type":"text/plain"},body:"synthetic"}];'
                  'const work=options.map(o=>Promise.resolve().then(()=>fetch('+target+',o))'
                  '.then(r=>({resolved:true,status:r.status,type:r.type}),e=>({resolved:false,error_name:e.name})));'
                  'window.open('+json.dumps(POPUP)+',"_blank","noopener,noreferrer");return Promise.all(work);})()')
    reply = host.evaluate(script, gesture=with_popup)
    time.sleep(.15)
    observed = foreign.snapshot()[before:]
    # The receiver has no permissive CORS response headers. These no-cors
    # probes deliberately distinguish sending from readable response access.
    return {'stage': stage, 'same_task_popup': with_popup, 'reply': reply, 'foreign_requests': observed,
            'no_foreign_request_sent': not observed}


def blocked_path(host, fixture, stage, *, with_popup=False):
    before = len(fixture.snapshot())
    identifier = host.command('policy', blocked_paths=[ACTION])
    changed = host.wait(lambda rows: next((e for e in rows if e.get('event') == 'reply' and e.get('id') == identifier), None))
    assert changed.get('ok'), 'Blocked-path setup did not complete'
    try:
        script = '(async()=>{const r=await '+FETCH+';return {status:r.status,type:r.type};})()'
        if with_popup:
            script = ('(()=>{const work=Promise.resolve().then(()=>'+FETCH+');'
                      'window.open('+json.dumps(POPUP)+',"_blank","noopener,noreferrer");return work.then('+STATUS+');})()')
        reply = host.evaluate(script, gesture=with_popup)
        time.sleep(.1)
        observed = [r for r in fixture.snapshot()[before:] if r['path'] == ACTION]
        return {'stage': stage, 'same_task_popup': with_popup, 'reply': reply, 'requests': observed, 'blocked_before_receiver': not observed}
    finally:
        identifier = host.command('policy', blocked_paths=[])
        restored = host.wait(lambda rows: next((e for e in rows if e.get('event') == 'reply' and e.get('id') == identifier), None))
        assert restored.get('ok'), 'Blocked-path restoration did not complete'


def run(executable, output, mode, definition):
    name, script, expected, gesture = definition
    case = fresh(output / (mode + '-' + name))
    fixture = Fixture(secrets.token_hex(32)).start()
    foreign = Fixture(secrets.token_hex(32)).start()
    host = None
    result = {'mode': mode, 'case': name, 'fresh_host_per_case': True,
              'source_only': True, 'application_save_acceptance': False,
              'external_dispatcher_present': False, 'physical_acceptance': False, 'cases': []}
    try:
        host = Host(executable, case, fixture, mode)
        host.loaded()
        baseline_start = len(fixture.snapshot())
        result['baseline_reply'] = host.evaluate(request_scripts()[0][1])
        result['baseline_requests'] = [r for r in fixture.snapshot()[baseline_start:] if r['path'] == ACTION]
        result['foreign_controls'] = [negatives(host, foreign, 'before-popup')]
        result['blocked_path_controls'] = [blocked_path(host, fixture, 'before-popup')]
        before, event_start = len(fixture.snapshot()), len(host.events)
        reply = host.evaluate(script, gesture=gesture)
        time.sleep(.15)
        requests = [r for r in fixture.snapshot()[before:] if r['path'] == ACTION]
        events = list(host.events)[event_start:]
        result['cases'].append({'case': name, 'supplied_renderer_gesture': gesture,
            'expected_requests': expected, 'reply': reply, 'requests': requests, 'events': events,
            'expected_requests_received': len(requests) == expected,
            'all_authenticated': bool(requests) and all(r['authenticated'] for r in requests),
            'any_token_present': any(r['has_token'] for r in requests)})
        result['foreign_controls'].append(negatives(host, foreign, 'after-popup'))
        result['blocked_path_controls'].append(blocked_path(host, fixture, 'after-popup'))
        result['foreign_controls'].append(negatives(host, foreign, 'within-popup-task', with_popup=True))
        result['blocked_path_controls'].append(blocked_path(host, fixture, 'within-popup-task', with_popup=True))
        result['diagnostic_completed'] = True
        result['baseline_qualified'] = (len(result['baseline_requests']) == 1 and
            all(r['authenticated'] if mode == 'local' else not r['has_token'] for r in result['baseline_requests']))
        result['request_authentication_passed'] = all(r['expected_requests_received'] and
            (r['all_authenticated'] if mode == 'local' else not r['any_token_present']) for r in result['cases']) and result['baseline_qualified']
        result['negative_controls_passed'] = (all(r['no_foreign_request_sent'] for r in result['foreign_controls'])
            and all(r['blocked_before_receiver'] for r in result['blocked_path_controls']))
    finally:
        try:
            if host is not None:
                host.close()
                result['cleanup'] = json.loads((case / 'cleanup.json').read_text())
        finally:
            result['requests'] = fixture.snapshot()
            result['foreign_requests'] = foreign.snapshot()
            result['host_events'] = list(host.events) if host is not None else []
            fixture.close()
            foreign.close()
            (case / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mode', choices=('local', 'server', 'both'), default='both')
    parser.add_argument('--case', choices=('all', *(r[0] for r in request_scripts())), default='all')
    parser.add_argument('--autonomous', action='store_true', help='Page-owned action after native-ready plus two seconds; no harness eval/input')
    parser.add_argument('--deferred-eval', action='store_true', help='One completed gesture eval schedules action100ms later, with no promise held')
    args = parser.parse_args()
    if os.name != 'nt':
        raise RuntimeError('Native Windows source-only diagnostic')
    from desktop.windows_processes import own_launcher
    from desktop.windows_files import assert_path
    from package_windows_webview2.build import verify_host
    own_launcher()
    executable, output = args.host.absolute(), args.output.absolute()
    assert_path(executable, leaf=True)
    if not executable.is_relative_to(AREA) or executable.name != 'DLMS-WebView2-Host.exe':
        raise ValueError('Explicit inventoried project-local host required')
    verify_host(executable.parent)
    fresh(output)
    results = []
    try:
        for mode in ('local', 'server') if args.mode == 'both' else (args.mode,):
            if args.autonomous or args.deferred_eval:
                for trigger in ('autonomous', 'deferred-eval'):
                    if not (args.autonomous if trigger == 'autonomous' else args.deferred_eval):
                        continue
                    for popup in (False, True):
                        result = run_autonomous(executable, output, mode, with_popup=popup, trigger=trigger)
                        results.append(result)
                        print(json.dumps({key: result.get(key) for key in ('mode', 'case', 'diagnostic_completed',
                            'request_authentication_passed', 'negative_controls_passed', 'native_user_flags_observed')}), flush=True)
                continue
            for definition in request_scripts():
                if args.case != 'all' and definition[0] != args.case:
                    continue
                result = run(executable, output, mode, definition)
                results.append(result)
                print(json.dumps({key: result.get(key) for key in ('mode', 'case', 'diagnostic_completed',
                    'request_authentication_passed', 'negative_controls_passed')}), flush=True)
    finally:
        summary = {'host': str(executable), 'host_sha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
                   'harness_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   'diagnostic_only': True, 'normal_package': False, 'physical_acceptance': False,
                   'modes': results}
        (output / 'result.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({'diagnostic_only': True, 'results': [
        {key: r.get(key) for key in ('mode', 'diagnostic_completed', 'request_authentication_passed', 'negative_controls_passed')}
        for r in results]}, indent=2), flush=True)


if __name__ == '__main__':
    main()

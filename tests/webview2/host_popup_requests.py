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



class AveryHandler(Handler):
    """Bounded extension of the existing recorder, never production data."""
    def end_headers(self):
        if urlsplit(self.path).path == '/anki/custom':
            self.send_header('Set-Cookie','avery_fixture=synthetic-profile-cookie; HttpOnly; SameSite=Strict; Path=/')
        super().end_headers()

    def do_GET(self):
        if urlsplit(self.path).path == '/anki/custom':
            body = ("<!doctype html><title>Synthetic Avery source</title><body>"
                "<form id='deck' action='/anki/printable' method='post' target='_blank'>"
                "<input name='csrf' value='synthetic-csrf-only'>"
                "<input name='deck_name' value='Windows Avery two only'>"
                "<input name='question_ids' type='checkbox' value='1'>"
                "<input name='question_ids' type='checkbox' value='2' checked>"
                "<input name='duplex' value='long-edge'><button>Render Avery</button></form></body>")
            self.respond(200, body.encode(), 'text/html; charset=utf-8')
        elif urlsplit(self.path).path == '/anki/printable':
            self.respond(405, b'POST required')
        else:
            super().do_GET()

    def do_POST(self):
        if urlsplit(self.path).path != '/anki/printable':
            return super().do_POST()
        from datetime import datetime, timezone
        from urllib.parse import parse_qs
        length = int(self.headers.get('Content-Length', '0'))
        if not 0 < length <= 4096:
            return self.respond(413, b'bounded fixture')
        raw = self.rfile.read(length)
        values = parse_qs(raw.decode('ascii'), strict_parsing=True)
        valid = values == {'csrf':['synthetic-csrf-only'], 'deck_name':['Windows Avery two only'],
                           'question_ids':['2'], 'duplex':['long-edge']}
        with self.server.lock:
            self.server.rows.append({'utc':datetime.now(timezone.utc).isoformat(), 'method':'POST',
                'path':'/anki/printable', 'raw_body':raw.decode('ascii'), 'fields':values,
                'exact_fields':valid, 'cookie_preserved':self.headers.get('Cookie')=='avery_fixture=synthetic-profile-cookie', 'authenticated':self.headers.get('X-DLMS-Desktop-Token')==self.server.token,
                'has_token':'X-DLMS-Desktop-Token' in self.headers, 'origin':self.headers.get('Origin'),
                'referer':self.headers.get('Referer')})
        # Native renderer completion and marker are separate from POST receipt.
        body = ("<!doctype html><title>Synthetic selected Avery Q2</title><body>"
                "<h1>Windows Avery two only</h1><article>Card Q2 only</article>"
                "<a href='/anki/custom'>Return to custom deck</a>"
                "<script>setTimeout(()=>window.close(),650)</script></body>")
        self.respond(200 if valid else 400, body.encode(), 'text/html; charset=utf-8')


class NoReferrerAveryHandler(AveryHandler):
    def end_headers(self):
        self.send_header('Referrer-Policy','no-referrer')
        super().end_headers()


def run_avery(executable, output, mode, *, held_retire=False, no_referrer=False):
    case = fresh(output / (mode + ('-avery-held-retire' if held_retire else '-avery')))
    fixture = Fixture(secrets.token_hex(32))
    fixture.RequestHandlerClass = NoReferrerAveryHandler if no_referrer else AveryHandler
    fixture.start()
    host = None
    result = {'mode':mode, 'source_only':True, 'physical_acceptance':False,
              'original_engine_form_submission':True, 'no_referrer_response_policy':no_referrer, 'transport_checks':[]}
    def posts():
        return [r for r in fixture.snapshot() if r['path']=='/anki/printable']
    def navigate(path):
        start = len(host.events)
        host.command('navigate',url=fixture.origin+path)
        host.wait(lambda rows:any(e.get('event')=='load-finish' and e.get('ok') and
                    e.get('url')==fixture.origin+path for e in rows[start:]))
    try:
        host = Host(executable, case, fixture, mode)
        host.loaded()
        # A user gesture on a wrong source must not authorize Avery.
        host.evaluate("window.open('/anki/printable','_blank');true", gesture=True)
        time.sleep(.2)
        assert not posts(), 'Wrong source sent an Avery request'
        navigate('/anki/custom')
        if held_retire:
            host.evaluate("document.getElementById('deck').requestSubmit();true",gesture=True)
            host.wait(lambda rows:any(e.get('event')=='avery-state' and e.get('state')=='original-post-held' for e in rows))
            navigate('/')
            host.wait(lambda rows:any(e.get('event')=='avery-state' and e.get('state')=='closed' for e in rows))
            time.sleep(1)
            assert not posts(), 'Held retired original POST reached receiver'
            assert not any(e.get('event')=='fatal' for e in host.events), list(host.events)
            assert host.evaluate('document.body.textContent').get('ok'), 'Parent not usable after held retirement'
            result.update(passed=True,held_retirement_no_post=True,parent_usable=True,marked_source_timing_probe=True)
            return result
        # No native user gesture: an automatic form submission is refused.
        host.evaluate("document.getElementById('deck').requestSubmit();true")
        time.sleep(.2)
        assert not posts(), 'Script-only request sent Avery POST'
        original = host.evaluate("Array.from(new FormData(document.getElementById('deck')).entries())")
        for iteration in (1,2):
            start = len(host.events)
            reply = host.evaluate("document.getElementById('deck').requestSubmit();document.getElementById('deck').requestSubmit();true" if iteration==1 else "document.getElementById('deck').requestSubmit();true", gesture=True)
            assert reply.get('ok'), reply
            host.wait(lambda rows:any(e.get('event')=='avery-state' and e.get('state') in ('closed','load-failed')
                                         for e in rows[start:]))
            events = list(host.events)[start:]
            states = [e.get('state') for e in events if e.get('event')=='avery-state']
            assert all(x in states for x in ('policy-ready','opened','rendered','closed')), states
            # Cached/native scheduling may deliver the original after policy
            # readiness. The held path is required only when observed; receiver
            # cardinality/bytes/cookies remain mandatory in either ordering.
            assert states.count('original-post-allowed')<=1, states
            if 'original-post-held' in states:
                assert states.count('original-post-allowed')==1, states
            received = posts()
            assert len(received)==iteration and all(r['exact_fields'] and r['cookie_preserved'] for r in received), received
            assert all(r['authenticated'] if mode=='local' else not r['has_token'] for r in received)
            if no_referrer:
                assert mode=='server'
                assert all(r['origin'] in (None,'null') and r['referer'] is None for r in received),received
            else:
                assert all(r['origin']==fixture.origin and r['referer']==fixture.origin+'/anki/custom' for r in received)
            assert host.evaluate("Array.from(new FormData(document.getElementById('deck')).entries())").get('value')==original.get('value')
            result['transport_checks'].append({'iteration':iteration, 'states':states,
                'exactly_one_original_post':True, 'source_form_unchanged':True})
        # Navigation immediately after opening invalidates the cached source lease.
        start = len(host.events);before=len(posts())
        host.evaluate("document.getElementById('deck').requestSubmit();location.href='/';true", gesture=True)
        host.wait(lambda rows:any(e.get('event')=='load-finish' and e.get('ok') and e.get('url')==fixture.origin+'/' for e in rows[start:]))
        time.sleep(.2)
        assert len(posts())==before, 'Retired source leaked Avery POST'
        result['wrong_source_refused']=result['script_only_refused']=result['stale_source_refused']=True
        navigate('/anki/custom')
        before=len(posts())
        host.evaluate("const f=document.createElement('iframe');f.src='about:blank';document.body.append(f);true")
        host.evaluate("document.getElementById('deck').requestSubmit();true",gesture=True)
        time.sleep(.2)
        assert len(posts())==before,'Frame-ambiguous source sent Avery POST'
        result['frame_ambiguous_refused']=True
        result['passed']=True
    finally:
        try:
            if host is not None:
                host.close()
                result['cleanup']=json.loads((case/'cleanup.json').read_text(encoding='utf-8'))
        finally:
            result['requests']=fixture.snapshot()
            result['host_events']=list(host.events) if host else []
            fixture.close()
            (case/'result.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return result


def run_embedded_avery(executable, output, mode):
    """Existing QtChecks adapter: production native ancestry, no OS input hook."""
    from desktop import webview2_browser as browser
    from desktop.webview2_shell import DesktopWindow
    import desktop.shell
    import package_windows_webview2
    package_windows_webview2.ACTIVE=True
    browser.host_executable=lambda:executable
    desktop.shell.DesktopWindow=DesktopWindow
    from tests.gate1.qt_checks import QtChecks
    from tests.six_item.gui_clipboard import QUIZ_TEXT
    from desktop.server_mode import configured_server,write_config
    from PySide6.QtCore import QUrl
    case=fresh(output/(mode+'-embedded-avery'));events=[];q=None;fixture=None
    result={'source_instrumented':True,'normal_package':False,'physical_acceptance':False,'mode':mode}
    try:
        q=QtChecks('wrembed'+secrets.token_hex(4),automated=True,normal_identity=True)
        def attach(view):
            original=view._event
            def record(event):
                if event.get('event')!='reply':events.append(dict(event))
                return original(event)
            view._event=record
        attach(q.window.view)
        if mode=='server':
            fixture=Fixture(secrets.token_hex(32));fixture.RequestHandlerClass=AveryHandler;fixture.start()
            config=dict(q.window.mode_config)
            config['server']=configured_server(config,fixture.origin,'Synthetic embedded Avery',private_http_opt_in=True)
            write_config(q.window.profile_name,config);q.window.mode_config=config
            assert q.window.switch_to_server()
            attach(q.window.view)
            q.window.view.setUrl(QUrl(fixture.origin+'/anki/custom'))
            q.wait("location.pathname==='/anki/custom' && document.readyState==='complete'")
            q.js("document.querySelector('input[name=deck_name]').value='Windows Avery two only';true")
            action="document.getElementById('deck').requestSubmit();true"
        else:
            status=q.js('(async()=>{let f=new FormData();f.append("quiz_title","Embedded native regression");f.append("file",new File(['+json.dumps(QUIZ_TEXT)+'],"neutral.txt"));return (await fetch("/process",{method:"POST",body:f})).status})()')
            assert status==200,status;q.go('/anki/custom')
            q.js("document.querySelector('input[name=deck_name]').value='Embedded selected Q2';document.querySelectorAll('input[name=quiz_cards]')[1].checked=true;document.querySelector('select[name=duplex_flip]').value='short';true")
            action='document.querySelector(\'button[formaction="/anki/printable"]\').click();true'
        q.wait("document.readyState==='complete'")
        deadline=time.monotonic()+12
        while q.window.view.page().isLoading() and time.monotonic()<deadline:q.delay(.05)
        before=q.js("Array.from(new FormData(document.querySelector('form')).entries())")
        q.window.view.command('eval',world=0,gesture=True,script=action)
        deadline=time.monotonic()+15
        while time.monotonic()<deadline and not any(e.get('event')=='avery-state' and e.get('state') in ('rendered','initialization-refused') for e in events):q.delay(.05)
        states=[e.get('state') for e in events if e.get('event')=='avery-state']
        assert 'rendered' in states and 'initialization-refused' not in states,events
        assert states.count('original-post-allowed')==1,states
        assert q.js("Array.from(new FormData(document.querySelector('form')).entries())")==before
        q.window.resize(1100,780);q.delay(.2)
        q.window.view.setUrl(QUrl((fixture.origin if fixture else f'http://127.0.0.1:{q.window.port}')+'/'))
        q.wait("location.pathname==='/' && document.readyState==='complete'")
        deadline=time.monotonic()+5
        while time.monotonic()<deadline and not any(e.get('event')=='avery-state' and e.get('state')=='closed' for e in events):q.delay(.05)
        assert any(e.get('state')=='closed' for e in events) and not any(e.get('event')=='fatal' for e in events),events
        if fixture:
            posts=[r for r in fixture.snapshot() if r['path']=='/anki/printable']
            assert len(posts)==1 and posts[0]['exact_fields'] and posts[0]['cookie_preserved'] and not posts[0]['has_token'],posts
        result.update(passed=True,stable_embedded_native_parent=True,exact_form_retained=True,original_post_policy_once=True,navigation_retires_child=True)
    finally:
        if q:q.close();q.delay(.3)
        if fixture:result['requests']=fixture.snapshot();fixture.close()
        result['events']=events
        (case/'result.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return result

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mode', choices=('local', 'server', 'both'), default='both')
    parser.add_argument('--case', choices=('all', *(r[0] for r in request_scripts())), default='all')
    parser.add_argument('--embedded-avery',action='store_true',help='Existing QtChecks with actual embedded HWND ancestry; choose one mode per process')
    parser.add_argument('--avery-held-retire', action='store_true', help='Existing marked source lifetime build only: retire during held original POST')
    parser.add_argument('--avery', action='store_true', help='Original Avery POST into the policy-bound transient controller')
    parser.add_argument('--avery-no-referrer', action='store_true', help='Server-only matching application response policy regression')
    parser.add_argument('--autonomous', action='store_true', help='Page-owned action after native-ready plus two seconds; no harness eval/input')
    parser.add_argument('--deferred-eval', action='store_true', help='One completed gesture eval schedules action100ms later, with no promise held')
    args = parser.parse_args()
    if args.avery_no_referrer and (not args.avery or args.mode!='server'):
        raise ValueError('No-referrer fixture requires --avery --mode server')
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
    if args.embedded_avery:
        if args.mode=='both':raise ValueError('One embedded QApplication/mode per source process')
        print(json.dumps(run_embedded_avery(executable,output,args.mode),indent=2),flush=True);return
    results = []
    try:
        for mode in ('local', 'server') if args.mode == 'both' else (args.mode,):
            if args.avery or args.avery_held_retire:
                if args.avery_held_retire and not (executable.parent.parent/'AI-RACE-PROBE').is_file():
                    raise ValueError('Held retirement requires separately marked source timing build')
                result=run_avery(executable, output, mode,held_retire=args.avery_held_retire,no_referrer=args.avery_no_referrer);results.append(result)
                print(json.dumps({'mode':mode,'avery_passed':result.get('passed')}),flush=True)
                continue
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

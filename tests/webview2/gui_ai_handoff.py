"""Owned-pipe AI handoff probes. Synthetic content; dispatch normally intercepted.

The dispatch boundary is intercepted. This is source/instrumented renderer input,
not normal-package or physical keyboard/default-browser acceptance.
Only explicit baseline --native-dispatch requests one reserved no-content URL.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import time
import sqlite3
from urllib.parse import urlencode, urlsplit


def until(q, predicate, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate(): return
        q.delay(.05)
    raise TimeoutError('Synthetic AI handoff checkpoint did not arrive')


def native_dialog_hit(dialog):
    """Read-only hit metadata at our own modal and button coordinates."""
    import ctypes as c
    from ctypes import wintypes as w
    from PySide6.QtWidgets import QMessageBox
    user=c.WinDLL('user32',use_last_error=True)
    user.WindowFromPoint.argtypes=(w.POINT,);user.WindowFromPoint.restype=w.HWND
    user.GetAncestor.argtypes=(w.HWND,w.UINT);user.GetAncestor.restype=w.HWND
    user.GetForegroundWindow.argtypes=();user.GetForegroundWindow.restype=w.HWND
    hwnd=int(dialog.winId())
    expected=int(user.GetAncestor(hwnd,2) or hwnd)
    def hit(widget):
        point=widget.mapToGlobal(widget.rect().center())
        handle=user.WindowFromPoint(w.POINT(point.x(),point.y()))
        root=user.GetAncestor(handle,2) if handle else None
        return {'hit_owned_dialog_root':bool(root and int(root)==expected)}
    button=dialog.button(QMessageBox.StandardButton.Yes)
    return {'dialog_center':hit(dialog),'yes_center':hit(button) if button is not None else None,
            'foreground_is_dialog_root':int(user.GetForegroundWindow() or 0)==expected}


def study_response_probe(q):
    # Preserve fetch behavior; retain endpoint/status only, never request bodies,
    # credentials or returned content. This diagnoses synthetic session setup.
    q.js('''(()=>{window.__syntheticStudyStatuses=[];const original=window.fetch;
      window.fetch=(...args)=>original(...args).then(response=>{
        const path=new URL(String(args[0]),location.href).pathname;
        if(path.startsWith('/api/study/')||path.startsWith('/_desktop/recovery/')||path.startsWith('/api/learning-events/'))window.__syntheticStudyStatuses.push({path,status:response.status});
        return response;});return true})()''')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile', required=True)
    parser.add_argument('--host-build', default='webview2-host-candidate-51')
    parser.add_argument('--baseline', action='store_true')
    parser.add_argument('--native-dispatch', action='store_true')
    parser.add_argument('--helper-transport', action='store_true', help='Exercise the production URL/environment transport; intercept only the final helper process')
    parser.add_argument('--full', action='store_true')
    parser.add_argument('--direct-ai', action='store_true', help='Require verified Local AI direct actions; Server and generic links still confirm')
    parser.add_argument('--native-ai', action='store_true', help='Exercise host-owned fixed AI website menu; no physical acceptance claimed')
    parser.add_argument('--signal-probe', action='store_true', help='Measure existing native signals before any Server direct-policy change')
    parser.add_argument('--server-direct', action='store_true', help='Require direct existing Server AI controls for the closed HTTPS providers')
    parser.add_argument('--server-races', action='store_true', help='Marked source-only forced AI lifetime tests; never a normal build')
    parser.add_argument('--server-focus', action='store_true', help='Focused Server lifetime/security cases, separate from full matrix')
    parser.add_argument('--arming-race', action='store_true', help='Separate marked source-host readiness timing probe only')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--pointer-only', action='store_true')
    parser.add_argument('--server-only', action='store_true')
    parser.add_argument('--auth-probe', action='store_true')
    args = parser.parse_args()
    if args.helper_transport and (args.native_dispatch or args.baseline):
        raise ValueError('Helper transport cannot open a real browser or use the old baseline')
    import sys
    if args.native_dispatch and (not args.baseline or args.full or args.server_only or getattr(sys,'frozen',False)):
        raise ValueError('Native dispatch is limited to the one-click source baseline probe')
    if args.auth_probe and (args.native_dispatch or args.full or args.server_only or args.baseline):
        raise ValueError('The focused authentication probe has a separate isolated workflow')
    if args.output:args.output.mkdir(mode=0o700,parents=True,exist_ok=False)
    import package_windows_webview2
    package_windows_webview2.ACTIVE = True
    from desktop.isolation import PROJECT, profile_paths
    if profile_paths(args.profile, create=False)['root'].exists():
        raise ValueError('Use a fresh disposable profile; preserve prior evidence')
    if not re.fullmatch(r'webview2-host-candidate-[0-9]{2}', args.host_build):
        raise ValueError('Reviewed task-local host build required')
    from desktop import webview2_browser as browser
    import sys
    executable = browser.host_executable() if getattr(sys,'frozen',False) else PROJECT / '.gate1/windows-native' / args.host_build / 'payload/DLMS-WebView2-Host.exe'
    from package_windows_webview2.build import verify_host
    if not getattr(sys,'frozen',False):verify_host(executable.parent)
    browser.host_executable = lambda: executable
    from desktop.webview2_shell import DesktopWindow
    import desktop.shell
    desktop.shell.DesktopWindow = DesktopWindow
    from tests.gate1.qt_checks import QtChecks
    from tests.windows.normal_candidate import request, multipart
    q = QtChecks(args.profile, automated=True)
    report = {'source_instrumented': not getattr(sys,'frozen',False), 'frozen_instrumented': bool(getattr(sys,'frozen',False)), 'normal_package': False, 'physical_acceptance': False,
              'host': 'bundled' if getattr(sys,'frozen',False) else args.host_build, 'host_sha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
              'baseline': args.baseline, 'rows': []}
    if args.server_direct and args.output:report['fixture_output']=str(args.output/'server-fixture.json')
    if args.arming_race and (getattr(sys,'frozen',False) or not (executable.parent.parent/'AI-RACE-PROBE').is_file()):
        raise ValueError('Readiness timing probe requires its separately marked source host')
    if args.server_races and (getattr(sys,'frozen',False) or not (executable.parent.parent/'AI-RACE-PROBE').is_file() or not args.server_direct):
        raise ValueError('Forced Server races require the separately marked source host')
    race={'clicked':False,'loading_at_click':None,'native_after_load_finish':None}
    events, external = [], []
    original = q.window.view._event
    def record(event):
        if event.get('event') != 'reply': events.append(dict(event))
        if args.arming_race and not race['clicked'] and event.get('event')=='ai-policy' and event.get('state')=='observer-configured':
            def point_ready(point):
                if not point or race['clicked']:return
                race['clicked']=True;race['loading_at_click']=q.window.view.page().isLoading()
                q.window.view.command('click',**point)
            q.window.view.command('eval',world=0,script='(()=>{let e=document.querySelector("button[onclick^=copyAndOpen]");if(!e)return null;e.scrollIntoView({block:"center",behavior:"instant"});let r=e.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()',callback=point_ready)
        if args.arming_race and race['clicked'] and event.get('kind')=='ai-action' and race['native_after_load_finish'] is None:
            race['native_after_load_finish']=any(e.get('event')=='load-finish' and e.get('generation')==event.get('generation') for e in events)
        return original(event)
    q.window.view._event = record
    # Let the existing native confirmation execute. Only the final external
    # application dispatch is replaced, so no provider/default browser opens.
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox
    confirmations = []
    helper_calls = []
    import subprocess
    original_run = subprocess.run
    from PySide6.QtGui import QDesktopServices
    original_qt_open = QDesktopServices.openUrl
    if args.helper_transport:
        def no_qt_fallback(url):
            raise AssertionError('The helper transport test must never open a real browser')
        QDesktopServices.openUrl = no_qt_fallback
        def helper_run(argv, **kwargs):
            if isinstance(argv, list) and argv[1:] == ['--external-browser']:
                assert Path(argv[0]) == executable
                assert set(kwargs['env']) == {'SystemRoot', 'WINDIR', 'PATH'}
                assert kwargs['close_fds'] and kwargs['timeout'] == 10
                wire = kwargs['input']
                assert wire.endswith(b'\n') and b'\n' not in wire[:-1]
                helper_calls.append({'url':wire[:-1].decode('ascii'), 'private_environment_forwarded':False,
                                     'profile_arguments':False, 'only_standard_pipes':True})
                from types import SimpleNamespace
                return SimpleNamespace(returncode=0, stdout=b'accepted\r\n', stderr=b'')
            return original_run(argv, **kwargs)
        subprocess.run = helper_run
    original_dispatch = desktop.shell.dispatch_external
    def dispatch(url):
        record = {'url': url.toString(), 'native': args.native_dispatch}
        external.append(record)
        if args.native_dispatch or args.helper_transport:
            try:
                record['helper_transport'] = args.helper_transport
                record['returned'] = bool(original_dispatch(url))
                return record['returned']
            except BaseException as exc:
                record['exception'] = repr(exc)
                raise
        return True
    desktop.shell.dispatch_external = dispatch
    if not args.baseline:
        import desktop.webview2_external as external_module
        external_module.dispatch_external = dispatch
    def acknowledge():
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, QMessageBox) and widget.isVisible():
                confirmations.append({'title': widget.windowTitle(), 'default_no': bool(widget.defaultButton() and widget.standardButton(widget.defaultButton()) == QMessageBox.StandardButton.No),
                                      'native_hit':native_dialog_hit(widget)})
                button = widget.button(getattr(q.app,'_ai_test_answer',QMessageBox.StandardButton.Yes))
                if button is not None: button.click()
    timer = QTimer(q.app); timer.timeout.connect(acknowledge); timer.start(40)
    try:
        port, nonce = q.window.port, q.window.nonce
        headers = {'Origin': f'http://127.0.0.1:{port}', 'Sec-Fetch-Site': 'same-origin', 'X-DLMS-CSRF-Refresh': '1'}
        status, body, response = request(port, nonce, 'GET', '/api/csrf-token', headers=headers)
        assert status == 200
        csrf = json.loads(body)['csrf_token']
        headers.update(Cookie='; '.join(x.split(';', 1)[0] for x in response['_set_cookies']), **{'X-CSRFToken': csrf})
        payload, media = multipart('file', 'neutral.txt', 'text/plain',
            (PROJECT / 'fixtures/gate1-neutral-quiz.txt').read_bytes(),
            {'quiz_title': 'Synthetic AI handoff', 'csrf_token': csrf})
        assert request(port, nonce, 'POST', '/process', payload, headers | {'Content-Type': media})[0] in (200, 302)
        q.go('/library'); q.wait("Boolean(document.querySelector('a[href^=\"/quizzes/\"]'))")
        q.go(q.js("document.querySelector('a[href^=\"/quizzes/\"]').getAttribute('href')"))
        q.wait('quizRecoveryReady===true')
        if not args.auth_probe:study_response_probe(q)
        q.js("document.querySelector('.study-mode-btn').click();true")
        q.wait("document.getElementById('studyAiBtn').offsetParent!==null")
        # Only the configured URL changes; the captured Review control and
        # synchronous prompt-copy implementation remain intact.
        q.js("studyAIConfig={ai_helper_enabled:true,ai_provider:'local',ai_custom_url:'https://dlms-ai-handoff.invalid/synthetic-no-content'};true")
        q.window.view.command('focus')
        q.delay(.2)
        activations=() if args.server_only or args.auth_probe else (('coordinate',) if args.native_dispatch else ('coordinate','eval-gesture') if args.pointer_only or args.baseline else ('coordinate', 'eval-gesture','keyboard'))
        for activation in activations:
            event_start, launch_start, confirm_start = len(events), len(external), len(confirmations)
            before = q.js('({url:location.href,timeOrigin:performance.timeOrigin,index})')
            if activation == 'coordinate':
                point = q.js("(()=>{let e=document.getElementById('studyAiBtn');e.scrollIntoView({block:'center'});let r=e.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()")
                q.window.view.command('click', **point)
            elif activation=='eval-gesture':
                q.window.view.command('eval', script="document.getElementById('studyAiBtn').click();true", world=0, gesture=True)
            else:
                q.window.view.command('focus')
                q.js("window.__syntheticKeys=[];document.addEventListener('keydown',e=>window.__syntheticKeys.push({type:e.type,key:e.key,trusted:e.isTrusted,target:e.target.id}));document.getElementById('studyAiBtn').focus();true")
                q.window.view.command('enter')
            q.delay(2)
            row = {'mode': 'local', 'entry': 'Review with AI', 'activation': activation,
                   'events': events[event_start:], 'external_requests': external[launch_start:],
                   'native_confirmations': confirmations[confirm_start:],
                   'page_preserved': before == q.js('({url:location.href,timeOrigin:performance.timeOrigin,index})')}
            row['study_response_statuses']=q.js('window.__syntheticStudyStatuses')
            if activation=='keyboard':row['renderer_key_events']=q.js('window.__syntheticKeys')
            report['rows'].append(row)
        report['runtime'] = q.window.view.runtime_info
        if args.auth_probe:
            auth_probe(q,report,external,confirmations)
        if args.full or args.server_only:
            full_checks(q, report, events, external, confirmations, headers, csrf, request,
                        pointer_only=args.pointer_only,server_only=args.server_only,direct_ai=args.direct_ai,
                        native_ai=args.native_ai,signal_probe=args.signal_probe,server_direct=args.server_direct,
                        server_races=args.server_races,server_focus=args.server_focus)
        if args.helper_transport:
            assert len(helper_calls) == sum(bool(row.get('returned')) for row in external)
        if args.arming_race:
            assert race=={'clicked':True,'loading_at_click':True,'native_after_load_finish':True},race
            report['arming_race']=race
        report['passed'] = report['auth_probe']['authentication_passed'] if args.auth_probe else True
    finally:
        subprocess.run = original_run
        QDesktopServices.openUrl = original_qt_open
        report['helper_transport'] = args.helper_transport
        if args.arming_race:report['arming_race']=race
        report['helper_calls'] = helper_calls
        q.close(); q.delay(.4)
        report['close_complete'] = q.window._close_complete
        report['nonreply_events'] = events[-4096:]
        (q.paths['root'] / 'wv-ai-handoff.json').write_text(json.dumps(report, indent=2) + '\n')
        if args.output:(args.output/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({key:report[key] for key in ('passed','host','host_sha256','source_instrumented',
        'frozen_instrumented','normal_package','physical_acceptance','close_complete')}
        | {'diagnostic_only':bool(report.get('diagnostic_only')),
           'entry_checks':len(report.get('entry_checks',[])), 'receipt':str((args.output/'result.json') if args.output else q.paths['root']/'wv-ai-handoff.json')},indent=2),flush=True)
    assert (report.get('auth_probe',{}).get('diagnostic_completed') if args.auth_probe else report.get('passed')) and report['close_complete']


def auth_probe(q, report, external, confirmations):
    """Copy-first comparison with untouched fetch and no default browser launch."""
    from PySide6.QtWidgets import QApplication
    import desktop.webview2_external as external_module
    q.wait('durableStudySession!==null && durableStudySession.id===learningSessionId',25)
    report['auth_probe']={'fetch_replaced':False,'fresh_claim_confirmed':True,'steps':[]}
    log=q.paths['logs']/'backend.log'
    def state():
        browser=q.js(r'''(()=>{const records=[...studyLearningEventSaves.values()];
          return {sequence:studyLearningEventSequence,pending:records.length,
            saving:records.filter(e=>e.state==='saving').length,
            failed:records.filter(e=>e.state==='failed').length,
            failure_http_codes:[...new Set(records.flatMap(e=>{const m=String(e.error||'').match(/HTTP (\d{3})/);return m?[Number(m[1])]:[]}))],
            errors_without_http_code:records.filter(e=>e.error&&!/HTTP \d{3}/.test(e.error)).length};})()''')
        text=log.read_text(encoding='utf-8',errors='replace') if log.exists() else ''
        browser['backend_token_rejections']=sum('denied missing or wrong launcher token' in line and '/_desktop/recovery/action' in line for line in text.splitlines())
        with sqlite3.connect(q.paths['backend']/'results.db') as connection:
            browser['committed_learning_kinds']=dict(connection.execute('SELECT kind,count(*) FROM study_responses GROUP BY kind'))
        return browser
    report['auth_probe']['initial']=state()
    stages=(('copy-before-popup','#studyCopyBtn',1,{'prompt_copy':1},0,False),
            ('review-native-consent','#studyAiBtn',2,{'prompt_copy':1,'ai_open':1},1,False),
            ('copy-after-popup','#studyCopyBtn',1,{'prompt_copy':1},0,False),
            ('review-no-dialog-diagnostic','#studyAiBtn',2,{'prompt_copy':1,'ai_open':1},1,True))
    for name,selector,expected_sequence,expected_kinds,expected_dispatches,skip_consent in stages:
        before=state();launches=len(external);dialogs=len(confirmations)
        before_document=q.js('performance.timeOrigin')
        encoded=json.dumps(selector)
        QApplication.clipboard().setText('synthetic-before-auth-copy')
        q.window.view.command('focus')
        q.js('document.querySelector('+encoded+').scrollIntoView({block:"center",behavior:"instant"});true')
        q.delay(.12)
        point=q.js('(()=>{const e=document.querySelector('+encoded+');let r=e.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()')
        done,errors=[],[]
        saved_confirm=external_module.confirm
        try:
            if skip_consent:external_module.confirm=lambda *args:True
            q.window.view.command('click',**point,callback=done.append,on_error=errors.append)
            until(q,lambda:done or errors);assert not errors
            q.delay(2)
            until(q,lambda:q.js('[...studyLearningEventSaves.values()].every(e=>e.state!=="saving")'),12)
        finally:external_module.confirm=saved_confirm
        after=state()
        kind_deltas={kind:after['committed_learning_kinds'].get(kind,0)-before['committed_learning_kinds'].get(kind,0)
                     for kind in set(after['committed_learning_kinds'])|set(before['committed_learning_kinds'])}
        kind_deltas={kind:count for kind,count in kind_deltas.items() if count}
        row={'action':name,'before':before,'after':after,
             'new_external_dispatches':len(external)-launches,'new_native_consents':len(confirmations)-dialogs,
             'clipboard_changed':QApplication.clipboard().text()!='synthetic-before-auth-copy',
             'new_token_rejections':after['backend_token_rejections']-before['backend_token_rejections'],
             'sequence_delta':after['sequence']-before['sequence'],
             'committed_kind_deltas':kind_deltas,'expected_kind_deltas':expected_kinds,
             'expected_sequence_delta':expected_sequence,'expected_external_dispatches':expected_dispatches,
             'native_consent_skipped_diagnostic':skip_consent,
             'page_preserved':before_document==q.js('performance.timeOrigin'),
             'activation':'owned renderer CDP pointer'}
        row['control_activated']=row['sequence_delta']==expected_sequence and row['clipboard_changed']
        row['handoff_expected']=row['new_external_dispatches']==expected_dispatches and row['new_native_consents']==(0 if skip_consent else expected_dispatches)
        row['authentication_passed']=row['control_activated'] and row['handoff_expected'] and kind_deltas==expected_kinds and row['new_token_rejections']==0 and row['page_preserved']
        if len(confirmations)>dialogs:row['native_hit']=confirmations[-1]['native_hit']
        report['auth_probe']['steps'].append(row)
        print(json.dumps({'auth_probe':name,'pending':after['pending'],'failed':after['failed'],
                          'failure_http_codes':after['failure_http_codes'],
                          'backend_token_rejections':after['backend_token_rejections']}),flush=True)
    report['auth_probe']['page_available']=q.js('document.readyState==="complete" && document.getElementById("studyAiBtn")!==null')
    report['auth_probe']['diagnostic_completed']=True
    report['auth_probe']['authentication_passed']=all(row['authentication_passed'] for row in report['auth_probe']['steps']) and report['auth_probe']['page_available']
    report['diagnostic_only']=True


def full_checks(q, report, events, external, confirmations, headers, csrf, request, *, pointer_only=False,server_only=False,direct_ai=False,native_ai=False,signal_probe=False,server_direct=False,server_races=False,server_focus=False):
    """Actual generated Local pages, then identical pages on a synthetic Server."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from PySide6.QtCore import QUrl
    from desktop.isolation import PROJECT
    from desktop.server_mode import configured_server, write_config
    import desktop.webview2_external as module
    pages = {}
    destination = 'https://dlms-ai-handoff.invalid/synthetic-no-content'
    def api(path, data=None):
        body = urlencode(dict(data or {}, csrf_token=csrf)).encode() if data is not None else None
        status, content, _ = request(q.window.port, q.window.nonce, 'POST' if body is not None else 'GET', path, body,
            headers | ({'Content-Type': 'application/x-www-form-urlencoded'} if body is not None else {}))
        assert status < 400, (path, status)
        return content
    api('/settings/ai/save', {'ai_helper_enabled':'on', 'ai_provider':'local', 'ai_custom_url':destination, 'ai_auto_copy_prompt':'on'})
    pages['/config/portal.json'] = api('/config/portal.json')
    quiz_path = q.window.view.url().path()
    pages[quiz_path] = api(quiz_path)
    quiz_file=q.js('QUIZ_FILE')
    pages[quiz_file]=api(quiz_file)
    quiz_identifier=q.js('String(window.QUIZ_ID)')
    pages['/api/study/quiz/'+quiz_identifier]=json.dumps({'generation':'synthetic-server-generation',
        'session':None,'readiness':{'ready':True}}).encode()
    # Generate a real completed attempt through the captured controls.
    q.go(quiz_path); q.wait('quizRecoveryReady===true')
    q.js("window.confirm=()=>true;document.querySelector('.exam-mode-btn').click();true")
    q.wait("Boolean(document.getElementById('submitBtn'))")
    q.js("document.getElementById('submitBtn').click();true")
    def attempts():
        with sqlite3.connect(q.paths['backend']/'results.db') as db:
            return db.execute('SELECT count(*) FROM attempts').fetchone()[0]
    until(q, lambda: attempts() > 0)
    # A committed SQL row precedes the renderer's response/cleanup chain. This
    # matrix needs a completed attempt for Explain, not navigation mid-save.
    # Do not substitute a sleep or weaken native request/recovery guards.
    q.wait('pendingExamAttempt===null&&examAttemptSaveInProgress===false&&examAttemptSettlePromise===null',30)
    q.wait("document.getElementById('result').textContent.includes('Your attempt was saved successfully.')")
    report['exam_setup_settled_before_history']=True
    q.go('/history'); q.wait("Boolean(document.querySelector('a[href^=\"/review?\"]'))")
    review_path = q.js("document.querySelector('a[href^=\"/review?\"]').getAttribute('href')")
    pages[review_path] = api(review_path)
    q.go(review_path); q.wait("document.querySelectorAll('.ai-select').length===4")
    attempt = q.js("new URLSearchParams(location.search).get('attempt')")
    for path in (f'/api/attempts/{attempt}', f'/api/missed_questions?attempt={attempt}'):
        pages[path] = api(path)
    for domain in ('IT / Cybersecurity','General','Science','Medical','History','Language','Other'):
        path = '/study-packs/ai-builder?domain=' + domain.replace(' ', '%20')
        pages[path] = api('/study-packs/ai-builder', {'topic':'Synthetic neutral topic', 'domain':domain,
            'ai_provider':'local','include_multiple_choice':'on'})
    pages['/law/create'] = api('/law/create', {'case_name':'Synthetic case', 'course':'General',
        'ai_provider':'local','include_case_brief':'on'})
    for kind in ('quiz','matching'):
        pages['/external-ai/quiz-builder?synthetic='+kind] = api('/external-ai/quiz-builder/prompt',
            {'content_type':kind,'topic':'Synthetic neutral topic','question_count':'4'})
    # Real certification receiver creates its own normalized cycle/identity.
    q.go('/certifications/new')
    q.js("(()=>{let f=document.querySelector('form.cert-form');f.elements.field_name.value='Synthetic credential';f.elements.field_issuer.value='Synthetic issuer';f.elements.field_earned.value='2025-01-01';f.elements.field_expiration.value='2027-01-01';f.requestSubmit();return true})()")
    def credential():
        with sqlite3.connect(q.paths['backend']/'results.db') as db:
            row = db.execute('SELECT id FROM certifications').fetchone()
            return row[0] if row else None
    until(q, credential)
    cid = credential()
    pages['/certifications/matches'] = api('/certifications/matches', {'credentials':cid,'question':'Synthetic planning question'})
    single = f'/certifications/{cid}/ai'
    pages[single] = api(single, {'include_certification':'on','include_cycle':'on','question':'Synthetic planning question'})
    # Cache only our synthetic rendered pages. No Local authentication nonce is
    # handed to the synthetic Server or written into the result receipt.
    assert all(q.window.nonce.encode() not in body for body in pages.values())
    report['rendered_fixture_pages'] = len(pages)
    rows = report.setdefault('entry_checks', [])
    native_modes = set()
    def native_menu_check(name, keyboard=False, provider=0):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication
        from desktop.webview2_native_ai import DESTINATIONS
        menu = q.window.ai_website_menu
        before = q.js('({href:location.href,timeOrigin:performance.timeOrigin})')
        clipboard = QApplication.clipboard().text()
        count, consents = len(external), len(confirmations)
        menu.popup(q.window.ai_website_button.mapToGlobal(q.window.ai_website_button.rect().topLeft()))
        q.delay(.04)
        action = menu.actions()[provider]
        assert action.isEnabled()
        if keyboard:
            menu.setActiveAction(action)
            QTest.keyClick(menu, Qt.Key.Key_Return)
        else:
            QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(action).center())
        until(q, lambda: len(external) > count)
        assert len(external) == count+1 and external[-1]['url'] == DESTINATIONS[provider][2]
        action.trigger(); q.delay(.06)
        assert len(external) == count+1 and len(confirmations) == consents
        assert QApplication.clipboard().text() == clipboard
        assert before == q.js('({href:location.href,timeOrigin:performance.timeOrigin})')
        report.setdefault('native_ai_checks', []).append({'mode':q.window.mode,'page_action':name,
            'provider':DESTINATIONS[provider][0], 'activation':'app-local QTest Enter' if keyboard else 'app-local QTest mouse',
            'dispatches':1,'confirmations':0,'replayed_signal_dispatches':0,
            'clipboard_unchanged':True,'page_preserved':True,'physical_acceptance':False})
    def go(path):
        url = ('http://127.0.0.1:' + str(q.window.port)) if q.window.mode == 'local' else origin
        start=len(events)
        q.window.view.setUrl(QUrl(url + path))
        until(q, lambda:any(e.get('event')=='load-finish' and e.get('ok') and e.get('url')==url+path for e in events[start:]))
        q.wait('document.readyState==="complete"')
        return True
    def activate(selector, keyboard=False):
        encoded = json.dumps(selector)
        q.window.view.command('focus')
        q.js('document.querySelector(' + encoded + ').scrollIntoView({block:"center",behavior:"instant"});true')
        q.delay(.1)
        if keyboard:
            q.js('document.querySelector(' + encoded + ').focus();true')
            done,errors=[],[]
            q.window.view.command('enter',callback=done.append,on_error=errors.append)
        else:
            point = q.js('(()=>{let r=document.querySelector('+encoded+').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()')
            done,errors=[],[]
            q.window.view.command('click', **point,callback=done.append,on_error=errors.append)
        until(q,lambda:done or errors)
        assert not errors,(selector,errors)
    def check(name, selector, copy_expected=True, setup=None, expected_url=None):
        if server_only and q.window.mode=='local':return
        report['stage']=q.window.mode+': '+name
        for keyboard in ((False,) if pointer_only else (False, True)):
            if setup: q.js(setup)
            before = q.js('({href:location.href,timeOrigin:performance.timeOrigin})')
            launches, consents, start = len(external), len(confirmations), len(events)
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText('synthetic-before-copy')
            activate(selector, keyboard)
            until(q, lambda: len(external) > launches)
            assert len(external) == launches+1, (name, 'duplicate dispatch')
            assert bytes(QUrl(external[-1]['url']).toEncoded())==bytes(QUrl(expected_url or destination).toEncoded()),name
            assert before == q.js('({href:location.href,timeOrigin:performance.timeOrigin})'), name
            direct=(direct_ai and q.window.mode=='local' or server_direct and q.window.mode=='server') and name.startswith((
                'Study Review','Study provider','Explain','Study Pack Copy Prompt & Open',
                'Law Copy Prompt & Open','Portfolio Copy &','Portfolio Open AI',
                'Single certification Copy &','Single certification Open AI'))
            assert len(confirmations)==consents+(0 if direct else 1), (name,events[start:])
            if not direct:assert confirmations[-1]['default_no'],name
            if direct:assert any(e.get('kind')=='ai-action' and e.get('verified_ai') is True for e in events[start:]),name
            changed = QApplication.clipboard().text() != 'synthetic-before-copy'
            if copy_expected: assert changed, (name, 'copy behavior lost')
            rows.append({'mode':q.window.mode,'entry':name,'keyboard':keyboard,
                'activation':'owned renderer CDP Enter' if keyboard else 'owned renderer CDP pointer',
                'dispatches':1,'native_default_no_consent':not direct,'direct_verified_ai':direct,'page_preserved':True,
                'native_hit':None if direct else confirmations[-1]['native_hit'],
                'prompt_copy_changed_clipboard':changed,
                'event_kinds':[item.get('event') for item in events[start:]]})
            print(json.dumps({'checkpoint':len(rows),'mode':q.window.mode,'entry':name,'keyboard':keyboard}),flush=True)
            if native_ai and name.startswith(('Study Review', 'Explain', 'Study Pack Copy', 'Law Copy',
                                              'Portfolio Copy &', 'Portfolio Open AI', 'Single certification')):
                if q.window.mode not in native_modes:
                    for provider in range(3):
                        native_menu_check(name, keyboard=False, provider=provider)
                        native_menu_check(name, keyboard=True, provider=provider)
                    native_modes.add(q.window.mode)
                else:
                    native_menu_check(name, keyboard=keyboard)
    # Local dynamically generated previews use an explicit form POST, retaining
    # actual backend rendering and original source handlers.
    def local_post(path, values, ready):
        q.go(path)
        js = '(()=>{let f=document.querySelector("form[method=POST],form[method=post]");'
        for key, value in values.items(): js += 'f.elements['+json.dumps(key)+'].value='+json.dumps(value)+';'
        q.js(js+'f.requestSubmit();return true})()')
        q.wait(ready)
        until(q,lambda:not q.window.view.page().isLoading())
    def copy_only(name, selector):
        if server_only and q.window.mode=='local':return
        report['stage']=q.window.mode+': '+name
        from PySide6.QtWidgets import QApplication
        q.js('window.alert=()=>{};true')
        for keyboard in ((False,) if pointer_only else (False,True)):
            count=len(external)
            QApplication.clipboard().setText('synthetic-before-copy')
            activate(selector,keyboard)
            until(q,lambda:QApplication.clipboard().text()!='synthetic-before-copy')
            q.delay(.2);assert len(external)==count
            rows.append({'mode':q.window.mode,'entry':name,'copy_only':True,'keyboard':keyboard,'dispatches':0,'clipboard_changed':True})
    def generic_checks():
        from PySide6.QtWidgets import QMessageBox
        # Exceeds the host's bounded 32-entry navigation history. Every new
        # current document must survive eviction of historical records.
        for iteration in range(41):
            path='/?synthetic_ai_history='+str(iteration)
            start=len(events)
            if q.window.mode=='local':q.go(path)
            else:go(path)
            new=events[start:]
            begins=[e for e in new if e.get('event')=='load-start']
            ends=[e for e in new if e.get('event')=='load-finish' and e.get('ok')]
            assert begins and ends and begins[-1]['generation']==ends[-1]['generation']
        rows.append({'mode':q.window.mode,'entry':'navigation history beyond 32 records','completed_navigations':41,
                     'every_start_finish_matched':True})
        q.js('''(()=>{let host=document.createElement('section');host.id='synthetic-links';host.style.cssText='position:fixed;left:250px;top:80px;width:600px;padding:30px;background:white;color:black;z-index:999999';
          const url='''+json.dumps(destination)+''';
          host.innerHTML='<a id="ai-same">Synthetic ordinary AI resource</a> <a id="ai-blank" target="_blank">Synthetic blank AI resource</a> <button id="ai-open">Synthetic window.open</button> <a id="ai-file" target="_blank" href="file:///C:/synthetic-not-readable.txt">Unsupported file</a> <a id="ai-exe" target="_blank" href="file:///C:/synthetic-never.exe">Unsupported executable</a> <a id="ai-custom" target="_blank" href="dlms-test-invalid:synthetic">Unsupported scheme</a> <a id="ai-userinfo" target="_blank" href="https://user:synthetic@example.invalid/">Unsupported credentials</a>';
          document.body.append(host);host.querySelector('#ai-same').href=url;host.querySelector('#ai-blank').href=url;
          host.querySelector('#ai-open').onclick=()=>window.open(url,'_blank','noopener,noreferrer');return true})()''')
        for label,selector in (('ordinary resource link','#ai-same'),('target blank resource link','#ai-blank'),('window.open resource button','#ai-open')):
            check(label,selector,False)
        before=q.js('({href:location.href,timeOrigin:performance.timeOrigin})')
        count=len(external)
        q.app._ai_test_answer=QMessageBox.StandardButton.No
        activate('#ai-open');q.delay(.6)
        assert len(external)==count
        assert 'canceled' in q.window.statusBar().currentMessage().lower()
        assert before==q.js('({href:location.href,timeOrigin:performance.timeOrigin})')
        q.app._ai_test_answer=QMessageBox.StandardButton.Yes
        rows.append({'mode':q.window.mode,'entry':'native consent cancellation','page_preserved':True,'dispatches':0,
                     'dom_focus_returned':bool(q.js('document.hasFocus()'))})
        saved_dispatch=module.dispatch_external
        module.dispatch_external=lambda url:False
        try:
            activate('#ai-open');q.delay(.6)
            assert 'could not open' in q.window.statusBar().currentMessage().lower()
            assert before==q.js('({href:location.href,timeOrigin:performance.timeOrigin})')
            rows.append({'mode':q.window.mode,'entry':'launch failure feedback','page_preserved':True,
                         'error_visible':True,'dom_focus_returned':bool(q.js('document.hasFocus()'))})
        finally:module.dispatch_external=saved_dispatch
        for selector in ('#ai-file','#ai-exe','#ai-custom','#ai-userinfo'):
            count=len(external);activate(selector);q.delay(.4);assert len(external)==count
            rows.append({'mode':q.window.mode,'entry':selector,'dispatches':0})
        count=len(external)
        q.js('window.open('+json.dumps(destination)+',"_blank","noopener,noreferrer");true');q.delay(.6)
        assert len(external)==count
        rows.append({'mode':q.window.mode,'entry':'non-user scripted popup','dispatches':0})
        q.js('setTimeout(()=>window.open('+json.dumps(destination)+',"_blank","noopener,noreferrer"),250);true');q.delay(.7)
        assert len(external)==count
        rows.append({'mode':q.window.mode,'entry':'non-user timer popup','dispatches':0})
    def native_signal_probe():
        """Controlled variants of the actual Study control, no browser launch."""
        from PySide6.QtWidgets import QApplication
        q.js('window.__signalOriginal=reviewCurrentQuestionWithAI;studyAIConfig={ai_helper_enabled:true,ai_provider:"chatgpt"};true')
        cases = [
            ('actual-pointer',None,False,True),('actual-enter',None,True,True),
            ('delayed-copy-completion', 'async()=>{await new Promise(r=>setTimeout(r,200));await __signalOriginal()}',False,True),
            ('delayed-popup-200ms','()=>setTimeout(()=>window.open("https://chatgpt.com/","_blank","noopener,noreferrer"),200)',False,True),
            ('three-popups-one-click','()=>{for(let i=0;i<3;i++)window.open("https://chatgpt.com/","_blank","noopener,noreferrer")}',False,True),
            ('script-only','()=>window.open("https://chatgpt.com/","_blank","noopener,noreferrer")',False,False),
            ('script-timer','()=>setTimeout(()=>window.open("https://chatgpt.com/","_blank","noopener,noreferrer"),200)',False,False)]
        for name, replacement, keyboard, user in cases:
            # Navigate to retire Chromium's transient activation between cases.
            go(quiz_path);q.wait('quizRecoveryReady===true')
            q.js("document.querySelector('.study-mode-btn').click();studyAIConfig={ai_helper_enabled:true,ai_provider:'chatgpt'};window.__signalOriginal=reviewCurrentQuestionWithAI;true")
            q.wait("document.getElementById('studyAiBtn').offsetParent!==null")
            if replacement:q.js('reviewCurrentQuestionWithAI='+replacement+';true')
            start, count, consents = len(events), len(external), len(confirmations)
            if user:activate('#studyAiBtn', keyboard)
            else:q.js('reviewCurrentQuestionWithAI();true')
            q.delay(1)
            signals=[e for e in events[start:] if e.get('event')=='external-request']
            row={'case':name,'trusted_renderer_input':user,'keyboard':keyboard,
                 'native_user_flags':[e.get('user') for e in signals],
                 'native_kinds':[e.get('kind') for e in signals],
                 'dispatches':len(external)-count,'confirmations':len(confirmations)-consents,
                 'normal_package':False,'frozen_instrumented':report['frozen_instrumented']}
            report.setdefault('native_signal_probe',[]).append(row)
            print(json.dumps({'signal_probe':row}),flush=True)
            if name.startswith('actual-'):assert signals and all(e['user'] is True for e in signals)
            if not user:assert not signals and len(external)==count
    def server_action_checks():
        from PySide6.QtWidgets import QApplication
        go(quiz_path);q.wait('quizRecoveryReady===true')
        q.js("document.querySelector('.study-mode-btn').click();studyAIConfig={ai_helper_enabled:true,ai_provider:'chatgpt'};window.__savedReview=reviewCurrentQuestionWithAI;true")
        q.wait("document.getElementById('studyAiBtn').offsetParent!==null")
        assert q.js("typeof __dlmsAIRequest==='undefined'&&typeof __dlmsTakeServerAI==='undefined'&&typeof __dlmsValidateServerAI==='undefined'")
        q.js('window.__savedCopy=dlmsManualAI.copyWithFallback;dlmsManualAI.copyWithFallback=text=>{const copied=dlmsManualAI.copySynchronously(text);return new Promise(resolve=>setTimeout(()=>resolve(copied),300))};true')
        start, consents = len(external), len(confirmations)
        activate('#studyCopyBtn');q.delay(.7)
        assert len(external)==start and len(confirmations)==consents
        assert q.js("document.getElementById('questionCopyStatus').textContent.toLowerCase().includes('copied')")
        rows.append({'mode':'server','entry':'actual Copy Question delayed completion','dispatches':0,'copy_only':True})
        q.js('reviewCurrentQuestionWithAI=async()=>{await dlmsManualAI.copyWithFallback(buildCurrentQuestionAIPrompt());__savedReview()};true')
        for keyboard in (False,True):
            start, consents = len(external), len(confirmations)
            activate('#studyAiBtn',keyboard);until(q,lambda:len(external)>start)
            assert len(external)==start+1 and len(confirmations)==consents
            rows.append({'mode':'server','entry':'existing Review control delayed copy acknowledgement',
                         'keyboard':keyboard,'dispatches':1,'confirmations':0})
        q.js('reviewCurrentQuestionWithAI=__savedReview;dlmsManualAI.copyWithFallback=__savedCopy;true')
        q.js("document.getElementById('studyAiBtn').focus();true")
        start=len(external);q.window.view.command('enter',repeat=True);q.delay(.4)
        assert len(external)==start
        q.window.view.command('space');until(q,lambda:len(external)>start)
        rows.append({'mode':'server','entry':'held Enter refused; fresh Space works','repeat_dispatches':0,'dispatches':1})
        for bad in ('http://chatgpt.com/','https://chatgpt.com.evil.invalid/',
                    'https://claude.ai.evil.invalid/','https://gemini.google.com.evil.invalid/',
                    'https://chatgpt.com/?prompt=synthetic','https://chatgpt.com/#synthetic',
                    'https://chatgpt.com:444/','https://user:synthetic@chatgpt.com/',
                    'file:///C:/synthetic.exe','ms-settings:appsfeatures'):
            q.js('studyAIConfig={ai_helper_enabled:true,ai_provider:"local",ai_custom_url:'+json.dumps(bad)+'};true')
            start,consents=len(external),len(confirmations)
            activate('#studyAiBtn');q.delay(.4)
            assert len(external)==start and len(confirmations)==consents,bad
            rows.append({'mode':'server','entry':'unsupported AI destination','target':bad,'dispatches':0,'confirmations':0})
        q.js('studyAIConfig={ai_helper_enabled:true,ai_provider:"chatgpt"};reviewCurrentQuestionWithAI=()=>{for(let i=0;i<5;i++)window.open("https://chatgpt.com/","_blank","noopener,noreferrer");setTimeout(()=>window.open("https://chatgpt.com/","_blank","noopener,noreferrer"),200)};true')
        start,consents=len(external),len(confirmations)
        activate('#studyAiBtn');q.delay(.9)
        assert len(external)==start+1 and len(confirmations)==consents
        rows.append({'mode':'server','entry':'five popup burst and delayed replay','dispatches':1,'confirmations':0})
        # New document: no retained real activation. Forged messages/clicks and
        # timers cannot borrow the native signal from an earlier document.
        go(quiz_path);q.wait('quizRecoveryReady===true')
        q.js("document.querySelector('.study-mode-btn').click();studyAIConfig={ai_helper_enabled:true,ai_provider:'chatgpt'};true")
        start,consents=len(external),len(confirmations)
        q.js('reviewCurrentQuestionWithAI();document.dispatchEvent(new CustomEvent("__dlms_ai_open",{detail:"https://chatgpt.com/"}));setTimeout(()=>window.open("https://chatgpt.com/","_blank","noopener,noreferrer"),200);true')
        q.delay(.8);assert len(external)==start and len(confirmations)==consents
        rows.append({'mode':'server','entry':'script-only/forged relay/timer on fresh document','dispatches':0})
        # Attachment navigation must preserve and rearm this actual AI page.
        from desktop import windows_backup_chooser as chooser
        old=chooser.choose_export;chooser.choose_export=lambda *a,**kw:('','')
        before=q.js('({href:location.href,timeOrigin:performance.timeOrigin})');start=len(events)
        try:
            q.window.view.setUrl(QUrl(origin+'/export/all_quizzes.txt'))
            until(q,lambda:any(e.get('event')=='load-finish' and e.get('download') for e in events[start:]))
            until(q,lambda:not q.window.view.page().isLoading())
            assert before==q.js('({href:location.href,timeOrigin:performance.timeOrigin})')
            check('Study Review with AI after attachment','#studyAiBtn',expected_url='https://chatgpt.com/')
        finally:chooser.choose_export=old
    def server_lifetime_races():
        for stage in ('before-take','after-take'):
            for change in ('blur','unrelated-click','second-ai-click','navigation'):
                go(quiz_path);q.wait('quizRecoveryReady===true')
                q.js("document.querySelector('.study-mode-btn').click();studyAIConfig={ai_helper_enabled:true,ai_provider:'chatgpt'};true")
                q.wait("document.getElementById('studyAiBtn').offsetParent!==null")
                points=q.js('(()=>{let p=s=>{let e=document.querySelector(s);e.scrollIntoView({block:"center",behavior:"instant"});let r=e.getBoundingClientRect();return{x:r.x+r.width/2,y:r.y+r.height/2}};return {ai:p("#studyAiBtn"),copy:p("#studyCopyBtn")}})()')
                done=[];q.window.view.command('server-ai-race',stage=stage,callback=done.append)
                until(q,lambda:done)
                old=q.window.view._event;changed=[]
                def on_event(event):
                    result=old(event)
                    if not changed and event.get('event')=='ai-policy' and event.get('state')=='server-test-'+stage:
                        changed.append(change)
                        if change=='blur':q.window.view.command('eval',world=0,script='window.dispatchEvent(new Event("blur"));true')
                        elif change=='navigation':q.window.view.command('navigate',url=origin+'/?race')
                        elif change=='unrelated-click':q.window.view.command('click',**points['copy'])
                        else:
                            q.window.view.command('eval',world=0,script='studyAIConfig={ai_helper_enabled:true,ai_provider:"claude"};true',
                                callback=lambda _:q.window.view.command('click',**points['ai']))
                    return result
                q.window.view._event=on_event
                start,consents=len(external),len(confirmations)
                try:
                    activate('#studyAiBtn');q.delay(1.1)
                    assert changed==[change],(stage,change)
                    expected=1 if change=='second-ai-click' else 0
                    assert len(external)==start+expected and len(confirmations)==consents,(stage,change,external[start:])
                    if expected:assert external[-1]['url']=='https://claude.ai/'
                    report.setdefault('forced_server_races',[]).append({'stage':stage,'change':change,
                        'old_action_dispatches':0,'new_action_dispatches':expected,'confirmations':0,'source_only':True})
                finally:q.window.view._event=old
        go(quiz_path);q.wait('quizRecoveryReady===true')
        q.js("document.querySelector('.study-mode-btn').click();studyAIConfig={ai_helper_enabled:true,ai_provider:'chatgpt'};true")
        done=[];q.window.view.command('server-ai-race',stage='stale-input',callback=done.append);until(q,lambda:done)
        start,consents=len(external),len(confirmations)
        activate('#studyAiBtn');q.delay(.6)
        assert len(external)==start and len(confirmations)==consents
        report['stale_input_epoch_refused']=True
    def direct_activation_checks():
        """Adversarial main-world probes cannot mint isolated activation."""
        q.go(quiz_path);q.wait('quizRecoveryReady===true')
        q.js("(document.querySelector('#durableStudyResume button')||document.querySelector('.study-mode-btn')).click();true")
        q.wait("document.getElementById('studyAiBtn').offsetParent!==null")
        assert q.js("typeof __dlmsAIRequest==='undefined'&&typeof __dlmsConfigureAI==='undefined'")
        q.js('window.__originalAI=reviewCurrentQuestionWithAI;true')
        def probe(name,body,*,activation=True,direct_count=0,consent_count=None):
            q.js('reviewCurrentQuestionWithAI=()=>{'+body+'};true')
            count,start,consents=len(external),len(events),len(confirmations)
            if activation:activate('#studyAiBtn')
            else:q.js(body+';true')
            q.delay(.65)
            direct=[e for e in events[start:] if e.get('kind')=='ai-action']
            assert len(direct)==direct_count,(name,events[start:])
            if consent_count is not None:assert len(confirmations)==consents+consent_count,name
            assert len(external)-count==len(direct)+len(confirmations)-consents,(name,'unconsented launch')
            rows.append({'mode':'local','entry':name,'direct_actions':len(direct),
                'confirmations':len(confirmations)-consents,'dispatches':len(external)-count})
        url=json.dumps(destination)
        relay="document.dispatchEvent(new CustomEvent('__dlms_ai_open',{cancelable:true,detail:"+url+"}))"
        probe('forged relay without activation',relay,activation=False,consent_count=0)
        probe('synthetic click without gesture','document.getElementById("studyAiBtn").click()',activation=False,consent_count=0)
        probe('trusted click plus exact relay',relay,direct_count=1,consent_count=0)
        probe('two exact relays in one click',relay+';'+relay,direct_count=1,consent_count=0)
        probe('trusted click plus delayed relay','setTimeout(()=>{'+relay+'},100)',consent_count=0)
        probe('trusted click plus delayed popup','setTimeout(()=>window.open('+url+',"_blank","noopener,noreferrer"),100)')
        probe('wrong URL cannot become direct','window.open("https://unexpected-ai.invalid/","_blank","noopener,noreferrer")',consent_count=1)
        probe('unsupported window.open shape stays generic','window.open('+url+',"_blank")',consent_count=1)
        probe('synthetic eventPhase shadow cannot revive expired click',
            'document.addEventListener("click",e=>{Object.defineProperty(e,"eventPhase",{value:2});setTimeout(()=>{'+relay+'},100)},{once:true});',consent_count=0)
        # Inspect the engine's actual microtask boundary rather than claiming all
        # asynchronous work is excluded from an in-flight trusted dispatch.
        count,start=len(external),len(events)
        q.js('reviewCurrentQuestionWithAI=()=>queueMicrotask(()=>{'+relay+'});true')
        activate('#studyAiBtn');q.delay(.6)
        micros=[e for e in events[start:] if e.get('kind')=='ai-action']
        assert len(micros)<=1 and len(external)-count==len(micros)
        rows.append({'mode':'local','entry':'microtask dispatch-boundary observation','direct_actions':len(micros),
            'boundary':'original trusted Event native eventPhase, not a clock lease'})
        q.js('reviewCurrentQuestionWithAI=__originalAI;true')
        count,start,consents=len(external),len(events),len(confirmations)
        done,errors=[],[]
        q.window.view.command('eval',script='document.getElementById("studyAiBtn").click();true',
            world=0,gesture=True,callback=done.append,on_error=errors.append)
        until(q,lambda:done or errors);assert not errors
        until(q,lambda:len(external)>count)
        assert len(confirmations)==consents+1 and not any(e.get('kind')=='ai-action' for e in events[start:])
        rows.append({'mode':'local','entry':'synthetic click with supplied engine gesture','direct_actions':0,'confirmations':1})
        count,start=len(external),len(confirmations)
        q.js("document.getElementById('studyAiBtn').textContent='Unrelated action';true")
        activate('#studyAiBtn');until(q,lambda:len(external)>count)
        assert len(confirmations)==start+1
        q.js("document.getElementById('studyAiBtn').textContent='✨ Review with AI';true")
        count=len(external);start=len(confirmations)
        q.js("document.getElementById('studyAiBtn').setAttribute('onclick','reviewCurrentQuestionWithAI();');true")
        activate('#studyAiBtn');until(q,lambda:len(external)>count)
        assert len(confirmations)==start+1
        q.js("document.getElementById('studyAiBtn').setAttribute('onclick','reviewCurrentQuestionWithAI()');true")
        # Renderer-only key probes: Enter repeat is suppressed, a later pointer
        # and Space activation remain separate genuine actions.
        q.js("document.getElementById('studyAiBtn').focus();true")
        count=len(external);q.window.view.command('enter',repeat=True);q.delay(.5)
        assert len(external)==count
        activate('#studyAiBtn');until(q,lambda:len(external)>count)
        q.js("document.getElementById('studyAiBtn').focus();true")
        count=len(external);q.window.view.command('space');until(q,lambda:len(external)>count)
        rows.append({'mode':'local','entry':'mutated controls / Enter repeat / pointer / Space',
            'changed_controls_confirmed':2,'repeat_dispatches':0,'pointer_and_space_direct':True})
        # A same-URL XHR cannot obtain a document contract by supplying a tag.
        value=q.js('fetch(location.href,{headers:{"X-DLMS-AI-Document":"'+('b'*32)+'"}}).then(r=>r.headers.has("X-DLMS-AI-Contract"))')
        assert value is False
        rows.append({'mode':'local','entry':'same-URL XHR forged document tag','contract_returned':False})
        q.wait('studyLearningEventSaves.size===0',30)
        # Attachment navigation preserves this exact AI-capable document. Cancel
        # the chooser at its boundary; verify the newly active nav re-arms only
        # the independently known actions of that unchanged document.
        from desktop import windows_backup_chooser as chooser_module
        original_chooser=chooser_module.choose_export
        chooser_module.choose_export=lambda *a,**kw:('','')
        before=q.js('({href:location.href,timeOrigin:performance.timeOrigin})');start=len(events)
        try:
            q.window.view.setUrl(QUrl('http://127.0.0.1:'+str(q.window.port)+'/export/all_quizzes.txt'))
            until(q,lambda:any(e.get('event')=='load-finish' and e.get('download') for e in events[start:]))
            until(q,lambda:not q.window.view.page().isLoading())
            q.delay(.3)
            assert before==q.js('({href:location.href,timeOrigin:performance.timeOrigin})')
            count,consents,start=len(external),len(confirmations),len(events)
            activate('#studyAiBtn');until(q,lambda:len(external)>count)
            assert len(confirmations)==consents and any(e.get('kind')=='ai-action' for e in events[start:])
            rows.append({'mode':'local','entry':'AI after canceled attachment download','page_preserved':True,'direct_actions':1})
        finally:chooser_module.choose_export=original_chooser
        q.wait('studyLearningEventSaves.size===0',30)
        # Repeated same-URL navigation exercises canceled request/cache overlap;
        # it is bounded evidence, not a proof of every engine callback ordering.
        start=len(events);url='http://127.0.0.1:'+str(q.window.port)+quiz_path
        for _ in range(8):q.window.view.command('navigate',url=url)
        q.delay(.7);until(q,lambda:not q.window.view.page().isLoading())
        q.wait('quizRecoveryReady===true')
        q.js("(document.querySelector('#durableStudyResume button')||document.querySelector('.study-mode-btn')).click();true")
        q.wait("document.getElementById('studyAiBtn').offsetParent!==null")
        count,consents=len(external),len(confirmations)
        activate('#studyAiBtn');until(q,lambda:len(external)>count)
        assert len(confirmations)==consents
        rows.append({'mode':'local','entry':'eight overlapping same-URL/cache navigations',
            'load_starts':sum(e.get('event')=='load-start' for e in events[start:]),'final_direct_action':True})
        q.wait('studyLearningEventSaves.size===0',30)
    q.go(quiz_path); q.wait('quizRecoveryReady===true')
    study_response_probe(q)
    report['study_resumed_existing_review']=q.js('Boolean(document.querySelector("#durableStudyResume button"))')
    q.js("(document.querySelector('#durableStudyResume button')||document.querySelector('.study-mode-btn')).click();studyAIConfig={ai_helper_enabled:true,ai_provider:'local',ai_custom_url:"+json.dumps(destination)+"};true")
    q.wait('durableStudySession!==null',20)
    q.wait("document.getElementById('studyAiBtn').offsetParent!==null")
    check('Study Review with AI','#studyAiBtn')
    for provider,url in (('chatgpt','https://chatgpt.com/'),('claude','https://claude.ai/'),('gemini','https://gemini.google.com/')):
        if direct_ai:
            api('/settings/ai/save',{'ai_helper_enabled':'on','ai_provider':provider,'ai_auto_copy_prompt':'on'})
            q.go(quiz_path);q.wait('quizRecoveryReady===true')
            q.js("(document.querySelector('#durableStudyResume button')||document.querySelector('.study-mode-btn')).click();true")
            q.wait("document.getElementById('studyAiBtn').offsetParent!==null")
        q.js('studyAIConfig={ai_helper_enabled:true,ai_provider:'+json.dumps(provider)+'};true')
        check('Study provider '+provider,'#studyAiBtn',expected_url=url)
    if direct_ai:
        api('/settings/ai/save',{'ai_helper_enabled':'on','ai_provider':'local','ai_custom_url':destination,'ai_auto_copy_prompt':'on'})
    q.js('studyAIConfig={ai_helper_enabled:true,ai_provider:"local",ai_custom_url:'+json.dumps(destination)+'};true')
    copy_only('Study Copy Question','#studyCopyBtn')
    q.wait('studyLearningEventSaves.size===0',30)
    report['synthetic_study_learning_events']=q.js('({pending:studyLearningEventSaves.size,failed:[...studyLearningEventSaves.values()].filter(e=>e.state==="failed").length,errors:[...new Set([...studyLearningEventSaves.values()].map(e=>e.error).filter(Boolean))],responses:window.__syntheticStudyStatuses})')
    q.go(review_path); q.wait("document.querySelectorAll('.ai-select').length===4")
    check('Explain with AI','button[onclick^="openAIExplain"]')
    check('Explain Selected with AI','button[onclick^="explainSelectedWithAI"]', setup="document.querySelector('.ai-select').checked=true;true")
    copy_only('Review Copy Explain Prompt','button[onclick^="copyAIExplainPrompt"]')
    for domain in ('IT / Cybersecurity','General','Science','Medical','History','Language','Other'):
        local_post('/study-packs/ai-builder', {'topic':'Synthetic neutral topic','domain':domain,'ai_provider':'local'}, 'Boolean(document.querySelector("#studyPrompt"))')
        check('Study Pack Copy Prompt & Open AI: '+domain,'button[onclick^="copyAndOpen"]')
        if domain=='General':copy_only('Study Pack Copy Prompt','button[onclick="copyPrompt()"]')
    local_post('/law/create', {'case_name':'Synthetic case','ai_provider':'local'}, 'Boolean(document.querySelector("#lawPromptBox"))')
    check('Law Copy Prompt & Open AI','button[onclick^="copyPromptAndOpenAi"]')
    copy_only('Law Copy Prompt','button[onclick="copyLawPrompt()"]')
    for path, label in (('/certifications/matches','Portfolio'), (single,'Single certification')):
        q.go(path)
        # The correct native page form owns a prepared prompt request.
        if path.endswith('/matches'):
            q.js("document.querySelector('[name=credentials]').checked=true;true")
        q.js("document.querySelector('[name=question]').value='Synthetic planning question';document.querySelectorAll('[name=include_certification],[name=include_cycle]').forEach(e=>e.checked=true);true")
        q.js("document.querySelector('form[data-match-selection],form.cert-ai-form,form[method=POST],form[method=post]').requestSubmit();true")
        q.wait('Boolean(document.querySelector("[data-cert-launch]"))')
        check(label+' Copy & open AI','[data-cert-launch]')
        check(label+' Open AI manually','#certProviderLink',False, "document.querySelector('#certLaunchRecovery').open=true;true")
        copy_only(label+' Copy only','[data-cert-copy]')
    if direct_ai and not server_only:
        for target in ('https://dlms-ai-handoff.invalid','https://dlms-ai-handoff.invalid/AI 日本語?q=hello%20world'):
            api('/settings/ai/save',{'ai_helper_enabled':'on','ai_provider':'local','ai_custom_url':target,'ai_auto_copy_prompt':'on'})
            q.go('/certifications/matches')
            q.js("document.querySelector('[name=credentials]').checked=true;document.querySelector('[name=question]').value='Synthetic canonical target';document.querySelector('form[data-match-selection]').requestSubmit();true")
            q.wait('Boolean(document.querySelector("[data-cert-launch]"))');until(q,lambda:not q.window.view.page().isLoading())
            check('Portfolio Copy & open AI canonical custom','[data-cert-launch]',expected_url=target)
            check('Portfolio Open AI manually canonical custom','#certProviderLink',False,
                "document.querySelector('#certLaunchRecovery').open=true;true",expected_url=target)
        api('/settings/ai/save',{'ai_helper_enabled':'on','ai_provider':'local','ai_custom_url':destination,'ai_auto_copy_prompt':'on'})
    for kind in ('quiz','matching'):
        q.go('/external-ai/quiz-builder')
        q.js('(()=>{let f=document.querySelector("#externalAiBuilderForm");f.elements.topic.value="Synthetic neutral topic";f.elements.content_type.value='+json.dumps(kind)+';f.requestSubmit(f.querySelector("button[formaction*=prompt]"));return true})()')
        q.wait('Boolean(document.querySelector("#externalAiCopyPrompt:not(:disabled)"))')
        copy_only('External AI Builder '+kind+' Copy Prompt','#externalAiCopyPrompt')
    if direct_ai and not server_only:direct_activation_checks()
    if not server_only:generic_checks()

    if server_direct:
        old_destination = destination
        destination = 'https://chatgpt.com/'
        pages = {path:body.replace(old_destination.encode(), destination.encode()) for path,body in pages.items()}
        if args_output := report.get('fixture_output'):
            import base64
            Path(args_output).write_text(json.dumps({'kind':'dlms-synthetic-ai-pages','version':1,'quiz_path':quiz_path,'pages':{
                path:base64.b64encode(body).decode() for path,body in pages.items()}},indent=2))
    class Fixture(BaseHTTPRequestHandler):
        requests=[]
        def log_message(self,*_): pass
        def do_GET(self):
            type(self).requests.append({'method':'GET','path':self.path,'local_token':bool(self.headers.get('X-DLMS-Desktop-Token'))})
            body = pages.get(self.path)
            if self.path=='/export/all_quizzes.txt':
                body=b'1. Synthetic question\nA. One\nB. Two\nANSWER: A\n'
                self.send_response(200);self.send_header('Content-Type','text/plain')
                self.send_header('Content-Disposition','attachment; filename="synthetic.txt"')
                self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body);return
            media = 'application/json' if self.path.startswith(('/api/','/config/','/data/')) else 'text/html; charset=utf-8'
            if self.path.startswith('/static/'):
                import mimetypes
                from desktop.isolation import FROZEN
                source=PROJECT if FROZEN else PROJECT
                path = source/self.path.lstrip('/')
                if path.resolve().is_relative_to((source/'static').resolve()) and path.is_file():
                    body=path.read_bytes();media=mimetypes.guess_type(path)[0] or 'application/octet-stream'
            if urlsplit(self.path).path == '/': body=b'<html><body id="server-ready">Synthetic AI Server</body></html>'
            if self.path == '/child':body=('<html><body><button id="child-open" onclick="window.open(\''+destination+'\',\'_blank\',\'noopener,noreferrer\')">Synthetic child AI</button></body></html>').encode()
            if body is None: self.send_error(404);return
            self.send_response(200);self.send_header('Content-Type',media);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def do_POST(self):
            type(self).requests.append({'method':'POST','path':self.path,'local_token':bool(self.headers.get('X-DLMS-Desktop-Token'))})
            size=int(self.headers.get('Content-Length','0'))
            if size>65536:self.send_error(413);return
            raw=self.rfile.read(size)
            payload=json.loads(raw or b'{}')
            # Only synthetic web receiver acknowledgements needed to expose
            # the original Study controls. This fixture does not qualify saves.
            if self.path=='/api/study/session':
                body={'ok':True,'session':{'sequence':0,'answers':{},'position':0,'assessment_revision':'synthetic-revision'}}
            elif self.path=='/api/learning-events/study-response':
                body={'ok':True,'event_id':payload.get('eventId')}
            else:self.send_error(404);return
            encoded=json.dumps(body).encode();self.send_response(200);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(encoded)));self.end_headers();self.wfile.write(encoded)
    server=ThreadingHTTPServer(('127.0.0.2',0),Fixture)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    origin='http://127.0.0.2:'+str(server.server_port)
    # A fresh independent Server profile establishes the remote boundary without
    # discarding a Local test's saved recovery evidence or weakening its guard.
    from desktop.isolation import profile_paths,isolated_environment
    from desktop.server_mode import read_config
    from tests.gate1.qt_checks import QtChecks
    import desktop.shell
    import os
    local_q=q
    server_name=q.window.profile_name+'s'
    if profile_paths(server_name,create=False)['root'].exists():raise ValueError('Server test profile must also be fresh')
    server_paths=profile_paths(server_name)
    prior=read_config(server_name)
    config=dict(prior,mode='server',server=configured_server(prior,origin,'Synthetic AI Server',private_http_opt_in=True))
    write_config(server_name,config)
    local_q.close();until(local_q,lambda:local_q.window._close_complete,30)
    report['local_close_complete']=True
    report['separate_fresh_server_profile']=server_name
    environment=isolated_environment(server_paths)
    os.environ.clear();os.environ.update(environment);os.environ['DLMS_DESKTOP_AUTOMATED']='1'
    q=QtChecks.__new__(QtChecks)
    q.paths,q.app=server_paths,local_q.app
    q.window=desktop.shell.DesktopWindow(server_paths,server_name)
    try:
        q.window.show();q.window.start()
        until(q,lambda:q.window._server_page_exposed and not q.window.view.page().isLoading())
        assert q.window.backend is None and q.window.mode=='server'
        report['server_runtime']=q.window.view.runtime_info
        # Rebind event recording after replacement of Local's owned browser.
        original=q.window.view._event
        def record(event):
            if event.get('event')!='reply':events.append(dict(event))
            return original(event)
        q.window.view._event=record
        for path,label,selector,setup in [
            (quiz_path,'Study Review with AI','#studyAiBtn',"document.querySelector('.study-mode-btn').click();studyAIConfig={ai_helper_enabled:true,ai_provider:'local',ai_custom_url:"+json.dumps(destination)+"};true"),
            (review_path,'Explain with AI','button[onclick^="openAIExplain"]',None),
            (review_path,'Explain Selected with AI','button[onclick^="explainSelectedWithAI"]',"document.querySelector('.ai-select').checked=true;true"),
            *[(path,'Study Pack Copy Prompt & Open AI: '+urlsplit(path).query,'button[onclick^="copyAndOpen"]',None) for path in pages if path.startswith('/study-packs/')],
            ('/law/create','Law Copy Prompt & Open AI','button[onclick^="copyPromptAndOpenAi"]',None),
            ('/certifications/matches','Portfolio Copy & open AI','[data-cert-launch]',None),
            (single,'Single certification Copy & open AI','[data-cert-launch]',None),
            ('/certifications/matches','Portfolio Open AI manually','#certProviderLink',"document.querySelector('#certLaunchRecovery').open=true;true"),
            (single,'Single certification Open AI manually','#certProviderLink',"document.querySelector('#certLaunchRecovery').open=true;true")]:
            go(path)
            if path==quiz_path:q.wait('quizRecoveryReady===true')
            if path==review_path:q.wait("document.querySelectorAll('.ai-select').length===4")
            if setup:q.js(setup)
            q.wait('Boolean(document.querySelector('+json.dumps(selector)+'))')
            if signal_probe:
                assert label=='Study Review with AI'
                native_signal_probe()
                return
            if server_focus:
                server_action_checks()
                if server_races:server_lifetime_races()
                return
            check(label,selector,'manually' not in label)
            if label=='Study Review with AI':
                for provider,url in (('chatgpt','https://chatgpt.com/'),('claude','https://claude.ai/'),('gemini','https://gemini.google.com/')):
                    q.js('studyAIConfig={ai_helper_enabled:true,ai_provider:'+json.dumps(provider)+'};true')
                    check('Study provider '+provider,'#studyAiBtn',expected_url=url)
                q.js('studyAIConfig={ai_helper_enabled:true,ai_provider:"local",ai_custom_url:'+json.dumps(destination)+'};true')
                copy_only('Study Copy Question','#studyCopyBtn')
            if label=='Explain with AI':copy_only('Review Copy Explain Prompt','button[onclick^="copyAIExplainPrompt"]')
            if label=='Law Copy Prompt & Open AI':copy_only('Law Copy Prompt','button[onclick="copyLawPrompt()"]')
            if path.endswith('domain=General'):copy_only('Study Pack Copy Prompt','button[onclick="copyPrompt()"]')
            if label.endswith('Copy & open AI'):copy_only(label+' Copy only','[data-cert-copy]')
        for kind in ('quiz','matching'):
            go('/external-ai/quiz-builder?synthetic='+kind)
            copy_only('External AI Builder '+kind+' Copy Prompt','#externalAiCopyPrompt')
        if server_direct:server_action_checks()
        if server_races:server_lifetime_races()
        generic_checks()
        count=len(external)
        q.js('(()=>{let f=document.createElement("iframe");f.id="synthetic-child";f.src="/child";document.body.append(f);return true})()')
        q.wait('Boolean(document.getElementById("synthetic-child").contentDocument?.querySelector("#child-open"))')
        done,errors=[],[]
        q.window.view.command('eval',script='document.getElementById("synthetic-child").contentDocument.querySelector("#child-open").click();true',world=0,gesture=True,callback=done.append,on_error=errors.append)
        until(q,lambda:done or errors);assert not errors
        q.delay(.6);assert len(external)==count
        assert 'frame cannot be verified' in q.window.statusBar().currentMessage().lower()
        rows.append({'mode':'server','entry':'child-frame popup with supplied gesture','dispatches':0,'privileged_bridge':False})
        q.js('document.getElementById("synthetic-child").remove();true')
        go('/')
        count=len(external);done,errors=[],[]
        q.window.view.command('eval',script='window.open('+json.dumps(destination)+',"_blank","noopener,noreferrer");true',world=0,gesture=True,callback=done.append,on_error=errors.append)
        until(q,lambda:done or errors);assert not errors
        q.delay(.5);assert len(external)==count
        assert 'frame cannot be verified' in q.window.statusBar().currentMessage().lower()
        rows.append({'mode':'server','entry':'frame removal/navigation does not restore unverified authority','dispatches':0,'actionable_refusal':True})
        assert not any(row['local_token'] for row in Fixture.requests)
        report['server_local_token_absent']=True
    finally:
        q.close();until(q,lambda:q.window._close_complete,30)
        report['server_close_complete']=True
        server.shutdown();server.server_close()


if __name__ == '__main__': main()

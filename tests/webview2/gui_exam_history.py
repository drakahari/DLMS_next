"""Actual Local Exam→History commit-boundary probe; source renderer input only.

SQL commit is deliberately not treated as browser settlement. No test barriers,
browser launch, OS input, owner data or weakened request/recovery checks.
"""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import time

def main():
    p=argparse.ArgumentParser();p.add_argument('--profile',required=True)
    p.add_argument('--host',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--reopen',action='store_true');a=p.parse_args()
    import package_windows_webview2;package_windows_webview2.ACTIVE=True
    from desktop.isolation import PROJECT,profile_paths
    from package_windows_webview2.build import verify_host
    host=a.host.resolve(strict=True);verify_host(host.parent)
    if not host.is_relative_to(PROJECT/'.gate1/windows-native'):raise ValueError('Task-local host required')
    out=a.output.absolute()
    if not out.is_relative_to(PROJECT/'.gate1/windows-native') or out.exists():raise ValueError('Fresh evidence required')
    if not a.reopen and profile_paths(a.profile,create=False)['root'].exists():raise ValueError('Fresh profile required')
    out.mkdir(mode=0o700)
    from desktop import webview2_browser as browser
    browser.host_executable=lambda:host
    from desktop.webview2_shell import DesktopWindow
    import desktop.shell;desktop.shell.DesktopWindow=DesktopWindow
    from tests.gate1.qt_checks import QtChecks
    from tests.windows.normal_candidate import request,multipart
    q=QtChecks(a.profile,automated=True);events=[];original=q.window.view._event
    def event(value):
        if value.get('event')!='reply':events.append(dict(value))
        return original(value)
    q.window.view._event=event
    report={'source_instrumented':True,'normal_package':False,'physical_acceptance':False,
        'host_sha256':hashlib.sha256(host.read_bytes()).hexdigest(),'reopen':a.reopen,'rows':[]}
    def attempts():
        with closing(sqlite3.connect(q.paths['backend']/'results.db')) as db:
            return db.execute('SELECT count(*) FROM attempts').fetchone()[0]
    try:
        if a.reopen:
            assert attempts()==6
            q.go('/history');q.wait("Boolean(document.querySelector('a[href^=\"/review?\"]'))")
            report['six_attempts_after_separate_reopen']=True
        else:
            port,nonce=q.window.port,q.window.nonce
            headers={'Origin':f'http://127.0.0.1:{port}','Sec-Fetch-Site':'same-origin','X-DLMS-CSRF-Refresh':'1'}
            status,body,response=request(port,nonce,'GET','/api/csrf-token',headers=headers);assert status==200
            csrf=json.loads(body)['csrf_token'];headers.update(Cookie='; '.join(x.split(';',1)[0] for x in response['_set_cookies']),**{'X-CSRFToken':csrf})
            payload,media=multipart('file','neutral.txt','text/plain',(PROJECT/'fixtures/gate1-neutral-quiz.txt').read_bytes(),{'quiz_title':'Synthetic Exam History','csrf_token':csrf})
            assert request(port,nonce,'POST','/process',payload,headers|{'Content-Type':media})[0] in (200,302)
            q.go('/library');q.wait("Boolean(document.querySelector('a[href^=\"/quizzes/\"]'))")
            quiz=q.js("document.querySelector('a[href^=\"/quizzes/\"]').getAttribute('href')")
            for iteration in range(6):
                q.go(quiz);q.wait('quizRecoveryReady===true')
                q.js("window.confirm=()=>true;document.querySelector('.exam-mode-btn').click();true")
                q.wait("Boolean(document.getElementById('submitBtn'))")
                q.js("document.getElementById('submitBtn').click();true")
                end=time.monotonic()+30
                while attempts()!=iteration+1 and time.monotonic()<end:q.delay(.01)
                assert attempts()==iteration+1
                settled=q.js('pendingExamAttempt===null&&examAttemptSaveInProgress===false&&examAttemptSettlePromise===null')
                row={'iteration':iteration,'attempts':attempts(),'renderer_settled_before_history':settled,'history_completed':False}
                report['rows'].append(row)
                q.go('/history');q.wait("Boolean(document.querySelector('a[href^=\"/review?\"]'))")
                assert not q.window.failed_reason
                row['history_completed']=True
        report['passed']=True
    finally:
        q.close();q.delay(.2);report.update(close_complete=q.window._close_complete,events=events)
        (out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report.get(k) for k in ('passed','close_complete','reopen','rows')},indent=2))
    assert report.get('passed') and report['close_complete']

if __name__=='__main__':main()

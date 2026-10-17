"""WebView2 pending-save/restart drill with explicit captured-UI readiness."""
import argparse,json,time,sqlite3
from urllib.parse import urlsplit


def main():
    p=argparse.ArgumentParser();p.add_argument('--profile',required=True)
    p.add_argument('--case',choices=('study-create','study-recover','exam-create','exam-recover'),required=True)
    p.add_argument('--crash',action='store_true');a=p.parse_args()
    import package_windows_webview2
    package_windows_webview2.ACTIVE=True
    from desktop.webview2_shell import DesktopWindow
    import desktop.shell
    desktop.shell.DesktopWindow=DesktopWindow
    from tests.gate1.qt_checks import QtChecks
    q=QtChecks(a.profile,automated=True);report={'source_instrumented':True,'normal_package':False,'case':a.case}
    def rows(table):
        with sqlite3.connect(q.paths['backend']/'results.db') as db:
            return db.execute('SELECT count(*) FROM '+table).fetchone()[0]
    try:
        url=json.loads((q.paths['root']/'foundation-create.json').read_text())['quiz_url']
        q.go(urlsplit(url).path);q.wait("quizRecoveryReady===true")
        study=a.case.startswith('study')
        pending="JSON.parse(localStorage.getItem('dlms.quiz-progress.v1:'+window.QUIZ_ID)||'null')"
        expression=f"({pending})?.unacknowledgedStudyEvents?.length===1" if study else f"Boolean(({pending})?.pendingAttempt)"
        table='study_responses' if study else 'attempts'
        if a.case.endswith('create'):
            before=rows(table)
            if q.js("Boolean(document.querySelector('.quiz-recovery-resume'))"):
                q.js("document.querySelector('.quiz-recovery-resume').click();true")
            else:
                q.js("document.querySelector('.study-mode-btn').click();true")
            q.wait("Boolean(document.querySelector('button.choice'))")
            if not study:
                q.js("window.confirm=()=>true;document.querySelector('.exam-mode-btn').click();true")
                q.delay(.2)
            q.window.interceptor.blocked_internal_paths.add('/_desktop/recovery/action')
            q.js("document.querySelector('button.choice').click();true")
            if not study:q.js("window.confirm=()=>true;document.getElementById('submitBtn').click();true")
            q.wait(expression,20)
            assert rows(table)==before
            report.update(pending_retained=True,before=before,unchanged_rows=True)
            (q.paths['root']/(a.case+'-oracle.json')).write_text(json.dumps({'before':before})+'\n')
        else:
            previous=a.case.replace('recover','create')
            before=json.loads((q.paths['root']/(previous+'-oracle.json')).read_text())['before']
            assert q.js(expression)
            q.wait("Boolean(document.querySelector('.quiz-recovery-resume'))")
            q.js("document.querySelector('.quiz-recovery-resume').click();true")
            cleared=f"({pending})?.unacknowledgedStudyEvents?.length===0" if study else f"!({pending})?.pendingAttempt"
            q.wait(cleared,30)
            assert rows(table)==before+1,(rows(table),before)
            report.update(pending_replayed_once=True,rows=rows(table))
        report['passed']=True
        if a.crash:
            assert a.case.endswith('create')
            report['forced_source_owner_exit']=True
            (q.paths['root']/('wv-'+a.case+'.json')).write_text(json.dumps(report,indent=2)+'\n')
            import os
            os._exit(79)  # Only this synthetic source launcher; inherited job owns helpers.
    finally:
        q.close();q.delay(.3)
        report['close_complete']=q.window._close_complete
        (q.paths['root']/('wv-'+a.case+'.json')).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2),flush=True)
    assert report.get('passed') and report['close_complete']


if __name__=='__main__':main()

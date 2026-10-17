"""Actual WebView2 source interactions; synthetic, instrumented, not physical acceptance."""
import argparse,json,time,sqlite3,sys
from pathlib import Path


def until(q,fn,timeout=30):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        result=fn()
        if result:return result
        q.delay(.08)
    raise TimeoutError('Expected synthetic interaction did not complete')


def main():
    p=argparse.ArgumentParser();p.add_argument('--profile',required=True);p.add_argument('--reopen',action='store_true');a=p.parse_args()
    import package_windows_webview2
    package_windows_webview2.ACTIVE=True
    from desktop.webview2_shell import DesktopWindow
    from desktop.webview2_browser import View
    protocol=[]
    original=View._event
    def traced(view,event):
        if event.get('event')!='reply':protocol.append(dict(event))
        return original(view,event)
    View._event=traced
    from desktop.webview2_file_selection import _known_private_roots
    from PySide6.QtCore import QStandardPaths
    roots=_known_private_roots()
    documents=Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation))
    import desktop.shell
    desktop.shell.DesktopWindow=lambda *a,**k:DesktopWindow(*a,selection_private_roots=roots,documents_folder=documents,**k)
    from tests.gate1.qt_checks import QtChecks
    from desktop.isolation import PROJECT
    q=QtChecks(a.profile,automated=True)
    import PySide6
    report={'source_instrumented':True,'normal_package':False,'profile':a.profile,'reopen':a.reopen,
            'python_version':sys.version,'python_executable':sys.executable,'pyside_version':PySide6.__version__}
    def count():
        with sqlite3.connect(q.paths['backend']/'results.db') as db:
            return db.execute("SELECT count(*) FROM study_responses WHERE kind='response'").fetchone()[0]
    try:
        from tests.webview2.gui_native_followup import assert_no_mix_diagnostic
        assert_no_mix_diagnostic(q.window)
        if not a.reopen:
            q.go('/upload')
            q.window.file_selection_for_test=PROJECT/'fixtures/gate1-neutral-quiz.txt'
            # This app-local synthetic interaction supplies browser activation;
            # no OS mouse/keyboard event or normal page privilege is changed.
            completed=[]
            q.window.view.command('eval',script="document.querySelector('input[name=file]').click();true",world=0,
                                  gesture=True,callback=completed.append)
            until(q,lambda:completed)
            q.wait("document.querySelector('input[name=file]').files[0]?.name==='gate1-neutral-quiz.txt'")
            assert q.window.file_selection_for_test is None
            q.js("document.querySelector('input[name=quiz_title]').value='Gate 1 Neutral Quiz';document.querySelector('form.build-upload-form').requestSubmit();true")
            until(q,lambda:any(e.get('event')=='load-finish' and e.get('url','').endswith('/process') for e in protocol)
                  or (q.window.view.url().path()=='/library' and not q.window.view.page().isLoading()))
            if q.window.view.page().last_http_status>=400:
                report['form_status']=q.window.view.page().last_http_status
                q.go('/')
                raise RuntimeError('Synthetic form navigation failed; preserved protocol has HTTP/network status')
            q.wait("location.pathname!=='/upload' && document.readyState==='complete'",30)
            until(q,lambda:not q.window.view.page().isLoading())
            q.go('/library');q.wait("document.body.innerText.includes('Gate 1 Neutral Quiz')")
            link=q.js("document.querySelector('a[href^=\"/quizzes/\"]').getAttribute('href')")
            q.go(link);q.wait('quizRecoveryReady===true')
            q.js("document.querySelector('.study-mode-btn').click();true")
            q.wait("Boolean(document.querySelector('button.choice'))")
            q.js("document.querySelector('button.choice').click();true")
            until(q,lambda:count()==1)
            q.js("document.getElementById('nextBtn').click();true")
            q.wait("document.body.innerText.includes('Which shape has three sides?')")
            q.js("fetch('/api/theme',{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':decodeURIComponent(document.cookie.split('; ').find(x=>x.startsWith('dlms_csrf_token='))?.split('=')[1]||'')},body:JSON.stringify({theme:'dark'})}).then(r=>r.json()).then(r=>window.__savedTheme=r.theme);true")
            q.wait("window.__savedTheme==='dark'")
            (q.paths['root']/'foundation-create.json').write_text(json.dumps({'quiz_url':f'http://127.0.0.1:{q.window.port}'+link})+'\n')
            q.js('window.print();true')
            until(q,lambda:q.window.pdf_files)
            assert q.window.pdf_files[-1].read_bytes().startswith(b'%PDF-')
            report.update(real_file_picker_bridge=True,quiz_import=True,study_saved=True,theme_saved=True,pdf_print=True)
        else:
            previous=json.loads((q.paths['root']/'foundation-create.json').read_text())
            from urllib.parse import urlsplit
            q.go(urlsplit(previous['quiz_url']).path)
            assert count()==1
            q.wait("Boolean(document.querySelector('.quiz-recovery-resume'))")
            q.js("document.querySelector('.quiz-recovery-resume').click();true")
            q.wait("document.body.innerText.includes('Which shape has three sides?')")
            theme=json.loads((q.paths['backend']/'config/portal.json').read_text()).get('theme')
            assert theme=='dark',theme
            report.update(study_resume=True,theme_persisted=True)
        report['runtime']=q.window.view.runtime_info
        report['passed']=True
    finally:
        report['status_message']=q.window.statusBar().currentMessage()
        report['nonreply_events']=protocol
        if q.window.view is not None:
            report['protocol_events']=list(q.window.view.protocol_events)
            report['chooser_consumed']=q.window.file_selection_for_test is None
        q.close();q.delay(.4)
        report['close_complete']=q.window._close_complete
        (q.paths['root']/('wv-local-reopen.json' if a.reopen else 'wv-local-create.json')).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('nonreply_events','protocol_events')},indent=2),flush=True)
    assert report.get('passed') and report['close_complete']


if __name__=='__main__':main()

"""Actual app-local Qt shutdown cases; no desktop-wide input or owner data."""
import argparse
import hashlib
import json
import sqlite3
import time
from urllib.parse import urlsplit
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog
from tests.gate1.qt_checks import QtChecks


def responses(root):
    with sqlite3.connect(root/'backend/results.db') as c:
        return c.execute("SELECT event_id,sequence,payload_json FROM study_responses ORDER BY saved_at,event_id").fetchall()


def main():
    p = argparse.ArgumentParser();p.add_argument('--profile',required=True)
    p.add_argument('--case',choices=['idle','window','app','pending','uncertain','reopen','layout','chooser','transition','late-dialog','retirement-timeout','switch-refusal','pending-app','uncertain-app','platform'],required=True)
    a = p.parse_args()
    q = QtChecks(a.profile, automated=True,
                 pause_action='accepted' if a.case in {'pending','uncertain','pending-app','uncertain-app'} else None,
                 normal_identity=a.case=='platform')
    root = q.paths['root'];result={'case':a.case,'profile':a.profile,'source_or_instrumented_Qt':True}
    owned_backend = q.window.backend
    timer = None
    from tests.blocka.gui_durable_crash import source_hashes
    content_before=source_hashes(q.paths['backend'])
    try:
        if a.case == 'platform':
            import ctypes
            import os
            import sys
            from pathlib import Path
            from PySide6.QtGui import QFontDatabase, QFontInfo, QFontMetrics
            from PySide6.QtWidgets import QFileDialog
            rows=Path('/proc/self/maps').read_text().splitlines()
            libraries=sorted(set(line.split()[-1] for line in rows if any(name in line for name in
                ['libfontconfig.so','libgbm.so','libfreetype.so','libxml2.so','libexpat.so','libEGL','libGLX'])))
            for name in ['libfontconfig.so','libgbm.so']:
                resolved=[Path(x) for x in libraries if name in Path(x).name]
                assert resolved
                if getattr(sys,'frozen',False):
                    assert all(not x.is_relative_to(Path(sys._MEIPASS)) for x in resolved),resolved
            fc=ctypes.CDLL('libfontconfig.so.1');fc.FcGetVersion.restype=ctypes.c_int
            font=QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont)
            info=QFontInfo(font);metrics=QFontMetrics(font)
            assert QFontDatabase.families() and info.family() and metrics.height()>0 and metrics.horizontalAdvance('DLMS Desktop')>0
            q.wait("document.fonts.status==='loaded'")
            web=json.loads(q.js("JSON.stringify({family:getComputedStyle(document.body).fontFamily,width:(()=>{let c=document.createElement('canvas');let x=c.getContext('2d');x.font='16px sans-serif';return x.measureText('DLMS Desktop').width})()})"))
            assert web['width']>0
            q.go('/settings/backup')
            result.update(platform=q.app.platformName(),desktop_file_id=q.app.desktopFileName(),
                fontconfig_version=fc.FcGetVersion(),libraries=libraries,font_family=info.family(),
                font_height=metrics.height(),font_count=len(QFontDatabase.families()),web_font=web)
            (root/'platform-font-probe.json').write_text(json.dumps(result,indent=2)+'\n')
            button=q.window.settings_buttons['backup'];button.setFocus();q.delay(.1)
            assert button.hasFocus(),'Active window/initial Import focus is required before testing focus return'
            dialogs=[]
            def cancel_picker():
                for dialog in q.app.topLevelWidgets():
                    if isinstance(dialog,QFileDialog) and dialog.parent() is q.window:
                        dialogs.append(type(dialog).__name__);dialog.reject()
            timer=QTimer();timer.setInterval(200);timer.timeout.connect(cancel_picker);timer.start()
            button.click();timer.stop();q.delay(.2)
            assert dialogs and not q.window.import_in_progress
            assert button.hasFocus(),'Actual chooser cancellation must restore Import focus'
            assert not (q.paths['root']/'dataset-transition.json').exists()
            screenshot=q.paths['root']/'native-platform-settings.png';q.window.grab().save(str(screenshot))
            result.update(platform=q.app.platformName(),fontconfig_version=fc.FcGetVersion(),
                libraries=libraries,font_family=info.family(),font_height=metrics.height(),
                font_count=len(QFontDatabase.families()),web_font=web,chooser_cancel_focus=True,
                screenshot=str(screenshot),security_overrides_present=[key for key in ['QTWEBENGINE_DISABLE_SANDBOX','QTWEBENGINE_CHROMIUM_FLAGS','GBM_BACKEND','GBM_BACKENDS_PATH','FONTCONFIG_FILE','FONTCONFIG_PATH'] if key in os.environ])
            q.close()
        elif a.case == 'app':
            dialog_observed = []
            def dismiss():
                if q.window._browser_dialog_depth:
                    dialog_observed.append(True)
                    assert q.window._close_after_dialog, 'Backend close must arrive while the alert is still open'
                    assert q.window.view is not None and not q.window.browser_retirements
                    # Application-local native dialog acceptance, not host input.
                    for w in q.app.topLevelWidgets():
                        if isinstance(w,QDialog):w.accept()
            timer=QTimer();timer.setInterval(1200);timer.timeout.connect(dismiss);timer.start()
            q.js("window.confirm=()=>true; document.getElementById('shutdownBtn').click(); true")
            until=time.monotonic()+15
            while q.window.isVisible() and time.monotonic()<until:q.delay(.05)
            assert not q.window.isVisible() and dialog_observed
            assert q.window._close_complete
            result['browser_shutdown_alert_preserved']=True
            result['closed_after_dialog_unwind']=True
        elif a.case == 'switch-refusal':
            from desktop.server_mode import configured_server,write_config
            updated=dict(q.window.mode_config,server=configured_server(q.window.mode_config,
                'http://127.0.0.2:1','Uncontacted synthetic refusal target',private_http_opt_in=True))
            write_config(a.profile,updated);q.window.mode_config=updated
            original=q.window._quiesce_browser
            q.window._quiesce_browser=lambda:False
            try:assert not q.window.switch_to_server()
            finally:q.window._quiesce_browser=original
            assert q.window._mode_switch_busy and q.window._browser_operation_depth==0
            assert q.window.mode=='local' and q.window.local_lock is not None
            q.close()
            result['retained_switch_refusal_allows_close_recovery']=True
        elif a.case == 'retirement-timeout':
            from desktop.browser_lifetime import BrowserRetirement
            original=BrowserRetirement.start
            def delayed(retirement):
                QTimer.singleShot(5500,lambda:original(retirement))
            BrowserRetirement.start=delayed
            try:q.window.close()
            finally:BrowserRetirement.start=original
            assert not q.window._close_complete and q.window._retiring_browser is not None
            assert q.window.local_lock is not None and owned_backend.poll() is None
            q.delay(1)
            assert q.window._retiring_browser.done
            q.close()
            result['timed_out_retirement_retained_ownership_then_safe_retry']=True
        elif a.case == 'chooser':
            from PySide6.QtWidgets import QFileDialog
            original = QFileDialog.getOpenFileName
            observations=[]
            def picker(*args):
                dialog=QFileDialog(q.window);dialog.setOption(QFileDialog.Option.DontUseNativeDialog)
                def attempt_close():
                    q.window.close()
                    observations.append(q.window._close_after_dialog and q.window.view is not None)
                    dialog.reject()
                QTimer.singleShot(100,attempt_close)
                dialog.exec()
                return '', ''
            QFileDialog.getOpenFileName=picker
            try:
                page=q.window.view.page()
                assert page.chooseFiles(page.FileSelectionMode.FileSelectOpen,[],[])==[]
            finally:QFileDialog.getOpenFileName=original
            q.delay(.3)
            assert observations==[True] and q.window._close_complete
            result['native_chooser_close_after_virtual_return']=True
        elif a.case == 'late-dialog':
            # Notice delivered after close entered its browser save wait. It
            # remains visible/logged; no nested modal and no implied save ack.
            original=q.window._quiesce_browser
            def quiesce():
                QTimer.singleShot(0, lambda:q.window.view.page().javaScriptAlert(None,'Synthetic late notice'))
                return original()
            q.window._quiesce_browser=quiesce
            q.close()
            assert len(q.window.close_browser_notices)==1
            result['late_notice_retained']=q.window.close_browser_notices
        elif a.case == 'transition':
            from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
            from threading import Thread
            from desktop.server_mode import configured_server,write_config
            class Handler(BaseHTTPRequestHandler):
                def do_GET(self):
                    b=b'<html><body>SYNTHETIC MODE TRANSITION</body></html>'
                    self.send_response(200);self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
                def log_message(self,*args):pass
            server=ThreadingHTTPServer(('127.0.0.2',0),Handler)
            thread=Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                updated=dict(q.window.mode_config,server=configured_server(q.window.mode_config,
                    f'http://127.0.0.2:{server.server_port}', 'Synthetic shutdown test',private_http_opt_in=True))
                write_config(a.profile,updated);q.window.mode_config=updated
                assert q.window.switch_to_server()
                q.wait("document.body.innerText.includes('SYNTHETIC MODE TRANSITION')")
                original=q.window._dispose_webview;observations=[];late=[]
                def retire():
                    page=q.window.view.page()
                    def late_notice():
                        page.javaScriptAlert(None,'Synthetic queued transition notice')
                        late.append(page.javaScriptConfirm(None,'Must not open while retiring'))
                    QTimer.singleShot(0,late_notice)
                    def attempt_close():
                        q.window.close()
                        observations.append(not q.window._close_complete and q.window.local_lock is not None)
                    QTimer.singleShot(0,attempt_close)
                    original()
                q.window._dispose_webview=retire
                assert q.window.switch_to_local()
                q.window._dispose_webview=original
                q.wait("location.origin.startsWith('http://127.0.0.1:') && document.readyState==='complete'",30)
                assert late==[False] and len(q.window.close_browser_notices)==2
                assert observations==[True] and q.window.isVisible() and q.window.local_lock is not None
                owned_backend=q.window.backend
                assert owned_backend.poll() is None
                result['close_refused_during_server_to_local_retirement']=True
                q.close()
            finally:server.shutdown();server.server_close();thread.join(3)
        elif a.case in {'pending','uncertain','pending-app','uncertain-app'}:
            path=urlsplit(json.loads((root/'foundation-create.json').read_text())['quiz_url']).path
            q.go(path)
            q.wait("quizRecoveryReady===true && quiz.length===4 && rawQuiz.length===4 && !!durableStudyGeneration && !document.querySelector('.study-mode-btn').disabled")
            def snapshot(label):
                value=q.js("""JSON.stringify((()=>{
                  const record=JSON.parse(localStorage.getItem('dlms.quiz-progress.v1:'+window.QUIZ_ID)||'null');
                  const state=captureQuizRecoveryState();
                  return {url:location.pathname,body:document.body.innerText,record,state,
                    rawQuiz,quiz,ready:quizRecoveryReady,durableStudySession,
                    generation:durableStudyGeneration,owner:durableStudyOwner,
                    completionMessage:studyCompletionMessage,
                    recordEnvelope:record?DLMSQuizRecovery.validateRecordEnvelope(record):null};
                })())""")
                (root/('snapshot-'+label+'.json')).write_text(value+'\n', encoding='utf-8')
                (root/('interceptor-'+label+'.json')).write_text(json.dumps(q.window.interceptor.denied_initiators)+'\n')
            snapshot('before-resume')
            q.js("(()=>{const resume=document.querySelector('.quiz-recovery-resume');if(resume)resume.click();else document.querySelector('.study-mode-btn').click();return true})()")
            try:q.wait("!!durableStudySession && !!learningSessionId && !!recoverySessionId && !document.querySelector('#quiz').classList.contains('hidden') && document.querySelector('button.choice')!==null")
            except Exception:
                snapshot('failed-resume');raise
            before=responses(root);q.js("document.querySelector('button.choice').click();true")
            marker=root/'recovery-pause-accepted.json';until=time.monotonic()+15
            while not marker.exists() and time.monotonic()<until:q.delay(.1)
            assert marker.exists()
            action=json.loads(marker.read_text())['id']
            if a.case=='pending':QTimer.singleShot(350,lambda:(root/'recovery-pause-release').write_text('release'))
            if a.case.endswith('-app'):
                # Invoke the captured application's shutdown request + native
                # alert while this Study document still owns its pending save.
                # The ordinary Dashboard button is separately tested by 'app'.
                dialogs=[]
                def dismiss():
                    if q.window._browser_dialog_depth:
                        assert q.window._close_after_dialog and q.window.view is not None
                        dialogs.append(True)
                        if a.case=='pending-app':(root/'recovery-pause-release').write_text('release')
                        for w in q.app.topLevelWidgets():
                            if isinstance(w,QDialog):w.accept()
                timer=QTimer();timer.setInterval(1200);timer.timeout.connect(dismiss);timer.start()
                q.js("void fetch('/api/shutdown',{method:'POST'}).then(r=>r.json()).then(d=>{if(d.status==='ok')alert('DLMS is shutting down.');else throw new Error('Shutdown refused')});true")
                until=time.monotonic()+20
                while q.window.isVisible() and time.monotonic()<until:q.delay(.05)
                assert dialogs and q.window._close_complete
                result['app_shutdown_alert_unwound']=True
            else:q.close()
            saved=responses(root)
            result.update(action=action,before=before,after=saved,
                journal=[x.name for x in (root/'durable-actions').glob('*.json')],
                checkpoint_present=(root/'recovery-evidence.json').is_file(),
                source_hashes_before=content_before,source_hashes_after=source_hashes(q.paths['backend']))
            assert result['source_hashes_before']==result['source_hashes_after']
            if a.case in {'pending','pending-app'}:
                assert len(saved)==len(before)+1 and not result['journal']
                if a.case=='pending':assert all(q.window.close_result.values())
                else:assert q.window.close_result['drained'] and q.window.close_result['checkpoint']
            else:
                assert len(saved)==len(before) and result['journal']
                if a.case=='uncertain':assert not q.window.close_result['quiesced']
                else:assert not q.window.close_result['drained']
            assert result['checkpoint_present']
            result['checkpoint_sha256']=hashlib.sha256((root/'recovery-evidence.json').read_bytes()).hexdigest()
            (root/'pending-shutdown-expected.json').write_text(json.dumps(result,indent=2)+'\n')
        elif a.case=='reopen':
            expected=json.loads((root/'pending-shutdown-expected.json').read_text())
            saved=responses(root)
            assert sum(x[0]==expected['action'] for x in saved)==1
            assert len(saved)==len(expected['before'])+1
            assert not list((root/'durable-actions').glob('*.json'))
            assert source_hashes(q.paths['backend'])==expected['source_hashes_before']
            assert all(tuple(row) in saved for row in expected['before'])
            path=urlsplit(json.loads((root/'foundation-create.json').read_text())['quiz_url']).path
            q.go(path)
            q.wait("quizRecoveryReady===true && quiz.length===4 && !document.querySelector('.study-mode-btn').disabled")
            assert q.js("!!document.querySelector('.quiz-recovery-resume')")
            q.js("document.querySelector('.quiz-recovery-resume').click();true")
            q.wait("!!durableStudySession && studyLearningEventSaves.size===0 && !document.getElementById('quiz').classList.contains('hidden')",20)
            assert responses(root)==saved,'Browser retry must preserve exact durable identifiers/payloads'
            try:q.go('/study-history')
            except Exception:
                page=q.window.view.page()
                info={'page_loading':page.isLoading(),'page_url':page.url().toString(),
                    'renderer_pid':page.renderProcessPid(),'lifecycle':str(page.lifecycleState()),
                    'window_visible':q.window.isVisible(),'view_visible':q.window.view.isVisible(),
                    'browser_dialog_depth':q.window._browser_dialog_depth,
                    'status':q.window.statusBar().currentMessage(),
                    'dialogs':[{'type':type(w).__name__,'title':w.windowTitle(),
                                'text':w.text() if hasattr(w,'text') else ''} for w in q.app.topLevelWidgets() if isinstance(w,QDialog)]}
                (root/'history-navigation-failure.json').write_text(json.dumps(info,indent=2)+'\n')
                raise
            result['same_action_once_after_restart']=True
            result['browser_resume_retry_no_duplicates']=True
            result['source_hashes_unchanged']=True
            q.close()
        elif a.case=='layout':
            checks=[]
            for theme in ['light','dark','ethereal']:
                q.wait("document.querySelector('#dlmsQuickTheme')?.disabled===false")
                q.js(f"(()=>{{let s=document.querySelector('#dlmsQuickTheme');s.value={theme!r};s.dispatchEvent(new Event('change'));return true}})()")
                q.wait(f"document.querySelector('.dashboard-sidebar')?.dataset.theme==={theme!r}")
                for width,zoom in [(1280,1),(640,1),(400,1),(1280,2)]:
                    q.window.resize(width,850);q.window.view.setZoomFactor(zoom);q.delay(.25)
                    value=json.loads(q.js("JSON.stringify((()=>{const box=s=>{let r=document.querySelector(s).getBoundingClientRect();return {top:r.top,bottom:r.bottom,left:r.left,right:r.right}};return {menu:box('#menuButton'),welcome:box('.dashboard-welcome'),header:box('.dashboard-header'),viewport:innerWidth,overflow:document.documentElement.scrollWidth>innerWidth+1,visible:getComputedStyle(document.querySelector('#menuButton')).display!=='none'}})())"))
                    assert not value['overflow'],value
                    if value['visible']:
                        assert value['menu']['bottom']<=value['header']['bottom']<=value['welcome']['top'],value
                        q.js("document.getElementById('menuButton').focus();document.getElementById('menuButton').click();true")
                        q.wait("document.getElementById('menuButton').getAttribute('aria-expanded')==='true'")
                        q.js("document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}));true")
                        q.wait("document.getElementById('menuButton').getAttribute('aria-expanded')==='false'")
                    checks.append(dict(theme=theme,width=width,zoom=zoom,geometry=value))
            result['layout_geometry_and_navigation']=checks
            result['screenshot']=str(q.screenshot('dashboard-half-width.png',width=640))
            q.close()
        else:
            # A second close delivered during the nested save wait must be ignored.
            QTimer.singleShot(1,q.window.close)
            q.close()
        if a.case!='layout':
            assert q.window._close_complete and not q.window.isVisible()
            assert len(q.window.browser_retirements)==(3 if a.case=='transition' else 1)
            assert all(sorted(x)==['page','profile','view'] and x[-1]=='profile' for x in q.window.browser_retirements)
            assert owned_backend.poll() is not None
            result.update(close_result=getattr(q.window,'close_result',None),retirement=q.window.browser_retirements)
        result['passed']=True
        (root/f'shutdown-{a.case}.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result,indent=2),flush=True)
    finally:
        if timer:timer.stop()
        if q.window.isVisible():q.close()


if __name__=='__main__':main()

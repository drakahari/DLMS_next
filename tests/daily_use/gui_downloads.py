"""Application-local attachment navigation regression; no desktop input injection."""
import argparse, json, subprocess, sys, time, socket, hashlib
from pathlib import Path
from PySide6.QtCore import QUrl
from desktop.isolation import PROJECT, AREA
from desktop.server_mode import configured_server, write_config
from tests.gate1.qt_checks import QtChecks


def main():
    p=argparse.ArgumentParser();p.add_argument('--profile',required=True);p.add_argument('--baseline',action='store_true');p.add_argument('--local-only',action='store_true');a=p.parse_args()
    out=AREA/'daily-use-20261015'/a.profile;out.mkdir(parents=True,exist_ok=False)
    q=QtChecks(a.profile,automated=True);assert not any('Capture Mix' in x.text() for x in q.window.mode_menu.actions());events=[];server=None;report={}
    def wire():
        page=q.window.view.page()
        page.loadingChanged.connect(lambda info:events.append(dict(kind='load',status=str(info.status()),download=info.isDownload(),url=info.url().toString(),page=page.url().toString(),error=info.errorCode())))
        page.loadFinished.connect(lambda ok:events.append(dict(kind='finished',ok=ok)))
        q.window.profile.downloadRequested.connect(lambda r:events.append(dict(kind='download',url=r.url().toString())))
    def download(mode,selector):
        before=len(q.window.download_results);url=q.window.view.url().toString();events.clear()
        q.js('document.querySelector('+json.dumps(selector)+').click(); true')
        deadline=time.monotonic()+15
        while (len(q.window.download_results)==before or q.window.download_results[-1]['state']=='in_progress') and time.monotonic()<deadline:q.delay(.05)
        q.delay(.3)
        record=q.window.download_results[-1]
        assert record['state']=='completed', record
        data=Path(record['path']).read_bytes()
        assert b'Neutral' in data or b'Browser' in data,data[:200]
        if mode=='local':
            expected=['What is two plus two?','A. Three','B. Four','C. Five','Correct Answer: B',
                      'Which shape has three sides?','A. Square','B. Circle','C. Triangle','Correct Answer: C',
                      'Which word names a color?','A. Blue','B. Table','C. Window','Correct Answer: A',
                      'Which item is a fruit?','A. Pencil','B. Apple','C. Chair','Correct Answer: B']
            cursor=0
            for text in expected:
                cursor=data.index(text.encode(),cursor)+len(text)
        assert len({r['path'] for r in q.window.download_results})==len(q.window.download_results)
        usable=(q.window.view.isVisible() and q.window.view.isEnabled() and not q.window.server_unreachable and (q.window.settings_fallback is None or not q.window.settings_fallback.isVisible()))
        report.setdefault(mode,[]).append(dict(record=record,sha256=hashlib.sha256(data).hexdigest(),bytes=len(data),events=list(events),usable=usable,url_unchanged=q.window.view.url().toString()==url))
        (out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
        assert q.js("location.pathname==='/library'"),events
        if not a.baseline:assert usable,events
    try:
        text=(PROJECT/'fixtures/gate1-neutral-quiz.txt').read_text()
        q.js("""(async()=>{const f=new FormData();f.append('quiz_title','Daily Neutral Quiz');f.append('file',new File([TEXT],'neutral.txt',{type:'text/plain'}));f.append('csrf_token',decodeURIComponent(document.cookie.split('; ').find(x=>x.startsWith('dlms_csrf_token='))?.split('=')[1]||''));window.importStatus=(await fetch('/process',{method:'POST',body:f})).status;})()""".replace('TEXT',json.dumps(text)))
        q.wait('window.importStatus===200');q.go('/library');wire()
        for selector in ['a[href="/export/all_quizzes.txt"]','a[href="/export/all_quizzes.txt"]','a[href^="/export/quiz/"]']:
            download('local',selector)
        if a.local_only:
            print(json.dumps(report,indent=2));return
        # Separate captured-application Server data and origin.
        for name in ['home','cache','tmp']:(out/name).mkdir()
        with socket.socket() as s:s.bind(('127.0.0.2',0));port=s.getsockname()[1]
        import os
        env=dict({k:v for k,v in os.environ.items() if not k.startswith(('DLMS_','QUIZAPP_'))},DLMS_NO_BROWSER='1',QUIZAPP_DATA_DIR=str(out/'server-data'),DLMS_BROWSER_TEST_PORT=str(port),DLMS_BROWSER_TEST_BIND_HOST='127.0.0.2',HOME=str(out/'home'),XDG_CACHE_HOME=str(out/'cache'),TMPDIR=str(out/'tmp'))
        log=(out/'server.log').open('w')
        server=subprocess.Popen([sys.executable,str(PROJECT/'tests/browser/_server.py')],env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        deadline=time.monotonic()+25
        while not (out/'server-data/browser_fixture.json').exists() and time.monotonic()<deadline:
            assert server.poll() is None, (out/'server.log').read_text()
            q.delay(.1)
        assert server.poll() is None
        config=dict(q.window.mode_config,server=configured_server(q.window.mode_config,f'http://127.0.0.2:{port}','Synthetic downloads',private_http_opt_in=True))
        write_config(a.profile,config);q.window.mode_config=config;assert q.window.switch_to_server()
        q.wait("location.pathname==='/' && document.readyState==='complete'",30)
        q.window.view.setUrl(QUrl(f'http://127.0.0.2:{port}/library'));q.wait("location.pathname==='/library' && document.readyState==='complete'",30);q.delay(.2);wire()
        for selector in ['a[href="/export/all_quizzes.txt"]','a[href="/export/all_quizzes.txt"]','a[href^="/export/quiz/"]']:
            download('server',selector)
        print(json.dumps(report,indent=2))
    finally:
        q.close()
        if server is not None:
            server.terminate();server.wait(timeout=15)
if __name__=='__main__':main()

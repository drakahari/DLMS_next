"""Source-Qt Local text attachment acceptance; no host input or owner data."""
import argparse
import json
import time
from pathlib import Path
from tests.gate1.qt_checks import QtChecks
from tests.windows.normal_candidate import ROOT,request,multipart


def main():
    p=argparse.ArgumentParser();p.add_argument('--profile',required=True);p.add_argument('--cancel',action='store_true');a=p.parse_args()
    q=QtChecks(a.profile,automated=True);report={}
    try:
        port=q.window.port;nonce=q.window.nonce
        headers={'Origin':f'http://127.0.0.1:{port}','Sec-Fetch-Site':'same-origin','X-DLMS-CSRF-Refresh':'1'}
        _,body,response=request(port,nonce,'GET','/api/csrf-token',headers=headers)
        csrf=json.loads(body)['csrf_token'];headers['Cookie']='; '.join(x.split(';',1)[0] for x in response['_set_cookies']);headers['X-CSRFToken']=csrf
        form,media=multipart('file','neutral.txt','text/plain',(ROOT/'fixtures/gate1-neutral-quiz.txt').read_bytes(),{'quiz_title':'Local synthetic export','csrf_token':csrf})
        assert request(port,nonce,'POST','/process',form,headers|{'Content-Type':media})[0] in (200,302)
        q.go('/library');before=q.js('performance.timeOrigin')
        if a.cancel:q.window.profile.downloadRequested.connect(lambda req:req.cancel())
        q.js("document.querySelector('a[href=\"/export/all_quizzes.txt\"]').click();true")
        end=time.monotonic()+15
        while not any(r['state']!='in_progress' for r in q.window.download_results) and time.monotonic()<end:q.delay(.1)
        q.delay(.2);state='cancelled' if a.cancel else 'completed'
        assert len(q.window.download_results)==1 and q.window.download_results[0]['state']==state
        record=q.window.download_results[0]
        if not a.cancel:
            text=Path(record['path']).read_text(encoding='utf-8');assert 'QUIZ: Local synthetic export' in text
        assert q.js("location.pathname==='/library' && performance.timeOrigin==="+str(before))
        assert q.window.view.isVisible() and q.window.view.isEnabled()
        report={'source_instrumented':True,'normal_package':False,'native_chooser_used':False,
            'outcome':state,'download':record,'same_library_document':True,
            'page_usable':True,'feedback':q.window.statusBar().currentMessage()}
    finally:
        (q.paths['root']/'local-text-export.json').write_text(json.dumps(report,indent=2)+'\n');q.close()
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()

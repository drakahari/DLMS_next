"""Actual Qt second inner-bundle crash and retry while first 100 remain committed."""
import argparse
import hashlib
import json
import sqlite3
import time
from desktop.isolation import AREA
from tests.gate1.qt_checks import QtChecks


def rows(path):
    with sqlite3.connect(path/'results.db') as conn:
        return [list(x) for x in conn.execute('SELECT id,title,source_file FROM quizzes ORDER BY id')]


def main():
    p=argparse.ArgumentParser();p.add_argument('--profile',required=True)
    p.add_argument('--phase',choices=('stage','crash','retry'),required=True)
    a=p.parse_args();q=QtChecks(a.profile,abort_import_at='before_item_receipt' if a.phase=='crash' else None)
    root,backend=q.paths['root'],q.paths['backend']
    out={'phase':a.phase,'before_count':len(rows(backend))}
    try:
        if a.phase=='stage':
            first=(root/'gate-a-token.txt').read_text().strip()
            (root/'gate-a-first-token.txt').write_text(first+'\n')
            q.go('/quiz-bundles')
            q.window.file_selection_for_test=AREA/'fixtures/gate-a-collection-inner-002.zip'
            q.click_css('input[name="bundle_zip"]')
            q.js('document.querySelector(\'form[action="/quiz-bundles/import"]\').requestSubmit();true')
            q.wait("location.pathname.startsWith('/quiz-bundles/import/')",25)
            token=q.js("location.pathname.split('/').pop()")
            assert token!=first
            (root/'gate-a-token.txt').write_text(token+'\n')
            out['token']=token
            out['screenshot']=str(q.screenshot('gate-a-collection-second-stage.png',width=1050,height=780))
        else:
            token=(root/'gate-a-token.txt').read_text().strip()
            q.go('/quiz-bundles/import/'+token)
            out['progress']=q.js('document.body.innerText')
            out['review_screenshot']=str(q.screenshot('gate-a-collection-second-'+a.phase+'-review.png',width=1050,height=780))
            q.js("(()=>{let f=document.querySelector('form[action$=\"/confirm\"]');f.elements.confirm_import.checked=true;f.requestSubmit();return true})()")
            if a.phase=='crash':
                deadline=time.monotonic()+25
                while time.monotonic()<deadline and not (root/'gate-a-checkpoint.json').exists():q.delay(.1)
                assert (root/'gate-a-checkpoint.json').exists()
                out['checkpoint']=json.loads((root/'gate-a-checkpoint.json').read_text())
                assert out['checkpoint']['stage']=='before_item_receipt'
                assert len(rows(backend))==102
            else:
                q.wait("location.pathname === '/quiz-bundles'",30)
                out['after_count']=len(rows(backend))
                assert out['after_count']==102
                out['result_screenshot']=str(q.screenshot('gate-a-collection-second-result.png',width=1050,height=780))
                first=(root/'gate-a-first-token.txt').read_text().strip()
                original=AREA/'retained'/(a.profile+'-before-second')/'portable-import-operations'
                current=root/'portable-import-operations'
                old=next(original.rglob(first+'.json'));now=next(current.rglob(first+'.json'))
                assert old.read_bytes()==now.read_bytes(), 'first inner-bundle receipt changed'
                operation=json.loads(now.read_text())
                assert operation['state']=='complete' and len(operation['items'])==100
                for item in operation['items']:
                    receipt=item['receipt'];html=receipt['html'];stem=html[:-5]
                    assert hashlib.sha256((backend/'quizzes'/html).read_bytes()).hexdigest()==receipt['hashes']['html']
                    assert hashlib.sha256((backend/'data'/(stem+'.json')).read_bytes()).hexdigest()==receipt['hashes']['json']
                out['first_part_unchanged']=True
                out['pass']=True
    finally:
        (root/('gate-a-collection-second-'+a.phase+'.json')).write_text(json.dumps(out,indent=2)+'\n')
        q.close()
    print(json.dumps({k:out.get(k) for k in ('phase','pass','before_count','after_count','first_part_unchanged','checkpoint')},indent=2))

if __name__=='__main__':main()

"""Real Qt must display a rejected credential form without hiding its diagnosis."""
from __future__ import annotations
import argparse
import json
import sqlite3
import sys
import time
from tests.gate1.qt_checks import QtChecks


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--profile',required=True)
    a=p.parse_args()
    if not a.profile.startswith('dailyjourney'):
        raise ValueError('Dedicated synthetic dailyjourney profile required')
    q=QtChecks(a.profile,automated=True)
    out={'profile':a.profile,'kind':'instrumented-frozen-Qt' if getattr(sys,'frozen',False) else 'source-app-local-Qt'}
    db=q.paths['backend']/'results.db'
    events=[]
    def loading(info):
        events.append(dict(url=info.url().toString(),status=info.status().name,
                           error_domain=info.errorDomain().name,error_code=info.errorCode(),
                           error_page=info.isErrorPage(),download=info.isDownload(),error=info.errorString()))
    q.window.view.page().loadingChanged.connect(loading)
    try:
        with sqlite3.connect(db) as conn:
            before=conn.execute('SELECT * FROM certifications ORDER BY id').fetchall()
        q.go('/certifications/new')
        q.js("""(()=>{const f=document.querySelector('form.cert-form');
           f.elements.field_name.value='Invalid Synthetic Credential';
           f.elements.field_issuer.value='Synthetic Issuer';
           f.elements.field_earned.value='2026-01-03';
           f.elements.field_expiration.value='2025-01-03';
           f.requestSubmit();return true})()""")
        q.wait("location.pathname==='/certifications/save' && document.readyState==='complete' && !!document.querySelector('.cert-warning')",20)
        deadline=time.monotonic()+2
        while time.monotonic()<deadline:q.delay(.05)
        out['loading_events']=events
        out['error_message']=q.js("document.querySelector('.cert-warning').innerText")
        out['view_visible']=q.window.view.isVisible()
        out['fallback_visible']=q.window.settings_fallback.isVisible()
        out['fallback_message']=q.window.settings_fallback.text()
        out['status_message']=q.window.statusBar().currentMessage()
        out['retained_earned']=q.js("document.querySelector('[name=field_earned]').value")
        out['retained_name']=q.js("document.querySelector('[name=field_name]').value")
        with sqlite3.connect(db) as conn:
            out['unchanged_records']=conn.execute('SELECT * FROM certifications ORDER BY id').fetchall()==before
        shot=q.paths['root']/'daily-validation.png'
        q.window.grab().save(str(shot))
        out['screenshot']=str(shot)
        out['pass']=bool('earned' in out['error_message'] and out['view_visible'] and not out['fallback_visible'] and out['unchanged_records']
                         and out['retained_earned']=='2026-01-03' and out['retained_name']=='Invalid Synthetic Credential')
        if out['pass']:
            q.js("(()=>{const f=document.querySelector('form.cert-form');f.elements.field_expiration.value='2028-01-03';f.requestSubmit();return true})()")
            q.wait("location.pathname.startsWith('/certifications/') && location.pathname!=='/certifications/save' && document.readyState==='complete'",20)
            with sqlite3.connect(db) as conn:
                saved=conn.execute('SELECT * FROM certifications ORDER BY id').fetchall()
            out['corrected_submission_committed_once']=len(saved)==len(before)+1
            out['pass']=out['corrected_submission_committed_once']
    finally:
        (q.paths['root']/'daily-validation.json').write_text(json.dumps(out,indent=2)+'\n')
        q.close()
    print(json.dumps(out,indent=2))
    return 0 if out.get('pass') else 1

if __name__=='__main__':raise SystemExit(main())

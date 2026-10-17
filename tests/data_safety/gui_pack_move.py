"""Qt Study Pack stage, exact move crash, and separate-process catalog recovery."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from PySide6.QtCore import QUrl

from desktop.isolation import AREA
from tests.gate1.qt_checks import QtChecks


def hashes(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--profile',required=True)
    parser.add_argument('--phase',choices=('stage','crash','reopen','retry'),required=True)
    parser.add_argument('--checkpoint',default='pack_after_move')
    args=parser.parse_args();assert args.profile.startswith('datasafety')
    q=QtChecks(args.profile,abort_import_at=args.checkpoint if args.phase=='crash' else None)
    root,backend=q.paths['root'],q.paths['backend']
    result={'profile':args.profile,'phase':args.phase,'checkpoint':args.checkpoint}
    try:
        if args.phase=='stage':
            q.go('/content-packs')
            q.window.file_selection_for_test=AREA/'fixtures/closure-pack-datasets.zip'
            q.click_css('input[name="pack_zip"]')
            q.js('document.querySelector(\'form[action="/content-packs/import"]\').requestSubmit();true')
            q.wait("location.pathname.startsWith('/content-packs/import/')",25)
            token=q.js("location.pathname.split('/').pop()")
            assert q.js("!!document.getElementById('packReviewInstallForm')")
            (root/'gate-a-pack-token.txt').write_text(token+'\n')
            result['token']=token
            result['screenshot']=str(q.screenshot('gate-a-pack-stage.png',width=1050,height=780))
        elif args.phase=='crash':
            token=(root/'gate-a-pack-token.txt').read_text().strip()
            q.go('/content-packs/import/'+token)
            q.js("(()=>{let f=document.getElementById('packReviewInstallForm');f.elements.confirm_install.checked=true;f.requestSubmit();return true})()")
            deadline=time.monotonic()+25
            while time.monotonic()<deadline and not (root/'gate-a-checkpoint.json').exists():q.delay(.1)
            assert (root/'gate-a-checkpoint.json').exists()
            result['checkpoint_record']=json.loads((root/'gate-a-checkpoint.json').read_text())
            assert result['checkpoint_record']['stage']==args.checkpoint
            result['installed_exists']=(backend/'content_packs/DLMS_Study_closure_datasets').is_dir()
        elif args.phase=='retry':
            token=(root/'gate-a-pack-token.txt').read_text().strip()
            q.go('/content-packs/import/'+token)
            assert q.js("!!document.getElementById('packReviewInstallForm')")
            q.js("(()=>{let f=document.getElementById('packReviewInstallForm');f.elements.confirm_install.checked=true;f.requestSubmit();return true})()")
            q.wait("location.pathname === '/content-packs'",25)
            result['catalog_visible']=q.js("document.body.innerText.includes('Closure Dataset Pack')")
            result['installed_hashes']=hashes(backend/'content_packs/DLMS_Study_closure_datasets')
            retained=AREA/'retained'/(args.profile+'-before')/'backend'
            stage=retained/'content_pack_staging'/token/'stage.json'
            result['expected_hashes']=hashes(stage.parent/json.loads(stage.read_text())['root_name'])
            result['pass']=result['catalog_visible'] and result['installed_hashes']==result['expected_hashes']
            assert result['pass']
        else:
            token=(root/'gate-a-pack-token.txt').read_text().strip()
            q.go('/content-packs')
            result['catalog_visible']=q.js("document.body.innerText.includes('Closure Dataset Pack')")
            destination=backend/'content_packs/DLMS_Study_closure_datasets'
            result['installed_hashes']=hashes(destination) if destination.exists() else {}
            retained=AREA/'retained'/(args.profile+'-before')/'backend'
            stage=retained/'content_pack_staging'/token/'stage.json'
            assert stage.is_file()
            meta=json.loads(stage.read_text())
            source=stage.parent/meta['root_name']
            result['expected_hashes']=hashes(source)
            result['stage_remaining']=(backend/'content_pack_staging'/token).exists()
            result['screenshot']=str(q.screenshot('gate-a-pack-reopen.png',width=1050,height=780))
            if args.checkpoint=='pack_before_move':
                assert not result['catalog_visible'] and not result['installed_hashes'] and result['stage_remaining']
            else:
                assert result['catalog_visible'] and result['installed_hashes']==result['expected_hashes'] and not result['stage_remaining']
                receipts=list((root/'pack-install-receipts').rglob(token+'.json'))
                assert len(receipts)==1
                result['receipt']=json.loads(receipts[0].read_text())
                assert result['receipt']['pack_id']=='closure_datasets' and result['receipt']['state']=='installed'
                q.window.view.setUrl(QUrl(f"http://127.0.0.1:{q.window.port}/content-packs/import/{token}"))
                q.wait("location.pathname === '/content-packs'",20)
                q.delay(0.7)
                result['same_token_message']=q.js('document.body.innerText')
                assert 'already committed' in result['same_token_message'] and 'No second copy' in result['same_token_message']
                result['receipt_screenshot']=str(q.screenshot('gate-a-pack-receipt.png',width=1050,height=760))
            with sqlite3.connect(backend/'results.db') as conn:
                result['quiz_count']=conn.execute('SELECT COUNT(*) FROM quizzes').fetchone()[0]
            assert result['quiz_count']==0
            result['pass']=True
    finally:
        (root/('gate-a-pack-'+args.phase+'.json')).write_text(json.dumps(result,indent=2)+'\n')
        q.close()
    print(json.dumps({k:result.get(k) for k in ('profile','phase','checkpoint','pass','catalog_visible','installed_exists','stage_remaining','quiz_count')},indent=2))

if __name__=='__main__':main()

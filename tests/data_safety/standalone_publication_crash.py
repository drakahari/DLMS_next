"""Separate-process exact journal checkpoints for standalone source publication."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import zipfile

from desktop.backend import acquire_writer_lock
from desktop.isolation import AREA, PROJECT, isolated_environment, profile_paths
from desktop.profile_state import atomic_json, new_manifest, publish_manifest


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--profile',required=True)
    parser.add_argument('--phase',choices=('seed','crash','inspect'),required=True)
    parser.add_argument('--checkpoint',default='db_committed')
    args=parser.parse_args();assert args.profile.startswith('datasafety')
    paths=profile_paths(args.profile);root=paths['root'];backend=paths['backend']
    if args.phase=='inspect':
        from tests.gate1.qt_checks import QtChecks
        q=QtChecks(args.profile)
        try:
            q.go('/quiz-bundles')
            with sqlite3.connect(backend/'results.db') as conn:
                rows=[list(row) for row in conn.execute('SELECT id,title,source_file FROM quizzes ORDER BY id')]
                contents=[]
                for quiz_id,_,_ in rows:
                    for qid,kind,text in conn.execute('SELECT id,question_type,question_text FROM questions WHERE quiz_id=? ORDER BY question_number',(quiz_id,)):
                        contents.append([quiz_id,qid,kind,text,[list(r) for r in conn.execute('SELECT label,text,is_correct,choice_order FROM choices WHERE question_id=? ORDER BY choice_order',(qid,))],
                                         [list(r) for r in conn.execute('SELECT pair_order,left_text,right_text FROM matching_pairs WHERE question_id=? ORDER BY pair_order',(qid,))]])
            registry=json.loads((backend/'config/quizzes.json').read_text())
            output={"profile":args.profile,"checkpoint":args.checkpoint,"rows":rows,"content":contents,
                    "registry":registry,"journal_remaining":[p.name for p in (backend/'.quiz_publications').glob('publication_*.json')],
                    "screenshot":str(q.screenshot('standalone-'+args.checkpoint+'.png',width=1050,height=750))}
            expected=2 if args.checkpoint=='registry_published' else 1
            assert len(rows)==expected and len(registry)==expected and not output['journal_remaining']
            from tests.data_safety.audit_managed_import import sentinel
            assert sentinel(AREA/'retained'/(args.profile+'-before')/'backend') == sentinel(backend)
            source_asset=backend/'quiz_assets/standalone_input/pic.png'
            assert source_asset.is_file()
            assert source_asset.read_bytes()==(AREA/'retained'/(args.profile+'-before')/'backend/quiz_assets/standalone_input/pic.png').read_bytes()
            for entry in registry:
                assert (backend/'quizzes'/entry['html']).is_file()
                assert (backend/'data'/entry['html'].replace('.html','.json')).is_file()
            assert rows[0][1]=='Unrelated Sentinel'
            if expected==2:
                assert rows[1][1]=='Interrupted Standalone'
                assert len([r for r in contents if r[0]==rows[1][0]])==2
                published=[r for r in contents if r[0]==rows[1][0]]
                assert published[0][4] == [['C','Blue',1,0],['A','Red',0,1]]
                assert published[1][5] == [[1,'Alpha','First'],[2,'Beta','Second']]
                asset=backend/'quiz_assets'/rows[1][2].removesuffix('.html')/'pic.png'
                assert asset.is_file()
                output['asset_sha256']=hashlib.sha256(asset.read_bytes()).hexdigest()
                assert output['asset_sha256']==hashlib.sha256(source_asset.read_bytes()).hexdigest()
                payload=json.loads((backend/'data'/rows[1][2].replace('.html','.json')).read_text())
                assert payload[0]['media']['image_url'].endswith('/pic.png') and payload[1]['pairs'][0]['left']=='Alpha'
            output['pass']=True
            (root/('standalone-'+args.checkpoint+'.json')).write_text(json.dumps(output,indent=2)+'\n')
            print(json.dumps({k:output.get(k) for k in ('profile','checkpoint','pass','rows','asset_sha256')}))
        finally:q.close()
        return
    if not (root/'desktop-profile.json').exists():publish_manifest(paths,new_manifest(args.profile,49123))
    env=isolated_environment(paths);os.environ.clear();os.environ.update(env)
    os.environ.update(DLMS_DESKTOP_NONCE='a'*32,DLMS_DESKTOP_PORT='49123',PYTHONNOUSERSITE='1')
    lock=acquire_writer_lock(root/'backend-writer.lock')
    sys.path.insert(0,str(PROJECT))
    import app
    if args.phase=='seed':
        app._publish_quiz('Unrelated Sentinel',[{'number':1,'type':'choice','question':'Keep this unrelated quiz?',
            'choices':[{'label':'A','text':'Yes','is_correct':True},{'label':'B','text':'No','is_correct':False}]}],registry_folder='Uncategorized')
        source=backend/'quiz_assets/standalone_input/pic.png';source.parent.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(AREA/'fixtures/closure-portable-media.zip') as archive:
            source.write_bytes(archive.read('assets/quiz-001/asset-001.png'))
        print(json.dumps({'seeded':args.profile,'asset_sha256':hashlib.sha256(source.read_bytes()).hexdigest()}))
        lock.close();return
    original=app._quiz_publication_checkpoint
    def abort(stage,journal):
        original(stage,journal)
        if stage==args.checkpoint:
            atomic_json(root/'standalone-checkpoint.json',{'stage':stage,'pid':os.getpid(),
                                                             'quiz_id':journal['quiz']['id']})
            os._exit(78)
    app._quiz_publication_checkpoint=abort
    app._publish_quiz('Interrupted Standalone',[
        {'number':1,'type':'choice','question':'Which tile is shown?','media':{'image_url':'/quiz-assets/standalone_input/pic.png','image_alt':'Synthetic tile'},
         'choices':[{'label':'C','text':'Blue','is_correct':True},{'label':'A','text':'Red','is_correct':False}]},
        {'number':2,'type':'matching','question':'Match terms','round_size':2,'direction':'term_to_definition',
         'pairs':[{'left':'Alpha','right':'First'},{'left':'Beta','right':'Second'}]}
    ],filename_prefix='standalone',snapshot_existing_assets=True,registry_folder='Uncategorized')
    raise AssertionError('checkpoint was not reached')

if __name__=='__main__':main()

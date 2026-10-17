"""Run source publication process exits and separate Qt reconciliation."""
from __future__ import annotations
import json
import argparse
import subprocess
import sys
from desktop.isolation import AREA, PROJECT


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--prefix',default='datasafetypub')
    args=parser.parse_args()
    cases=['journal_created','db_committed','artifacts_promoted','registry_published']
    logs=AREA/'retained/gate-a-repair/logs';logs.mkdir(parents=True,exist_ok=True)
    output=[]
    for index,checkpoint in enumerate(cases):
        name=f'{args.prefix}{index+10:02d}'
        steps=[('seed',[sys.executable,'-m','tests.data_safety.standalone_publication_crash','--profile',name,'--phase','seed']),
               ('retain',[sys.executable,'-m','tests.completion.retain_fixture','--profile',name]),
               ('crash',[sys.executable,'-m','tests.data_safety.standalone_publication_crash','--profile',name,'--phase','crash','--checkpoint',checkpoint]),
               ('inspect',[sys.executable,'-m','tests.data_safety.standalone_publication_crash','--profile',name,'--phase','inspect','--checkpoint',checkpoint])]
        record={'profile':name,'checkpoint':checkpoint,'steps':{}}
        print(name,checkpoint,flush=True)
        for label,command in steps:
            log=logs/f'{name}-{label}.log'
            with log.open('w') as stream:
                done=subprocess.run(command,cwd=PROJECT,stdout=stream,stderr=subprocess.STDOUT,timeout=70)
            record['steps'][label]={'exit':done.returncode,'log':str(log)}
            print(' ',label,done.returncode,flush=True)
            if done.returncode!=(78 if label=='crash' else 0):break
        record['pass']=len(record['steps'])==4 and all(v['exit']==(78 if k=='crash' else 0) for k,v in record['steps'].items())
        output.append(record)
        (logs.parent/'standalone-matrix.json').write_text(json.dumps(output,indent=2)+'\n')
    assert all(x['pass'] for x in output)

if __name__=='__main__':main()

"""Qt Study Pack move-intent process crash and restart matrix."""
import json
import argparse
import subprocess
import sys
from desktop.isolation import AREA, PROJECT


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--prefix',default='datasafetypackmove')
    args=parser.parse_args()
    cases=['pack_before_move','pack_after_move','pack_after_discovery','pack_after_cleanup']
    logs=AREA/'retained/gate-a-repair/logs';logs.mkdir(parents=True,exist_ok=True)
    result=[]
    for index,stage in enumerate(cases):
        name=f'{args.prefix}{index+10:02d}'
        steps=[('stage',[sys.executable,'-m','tests.data_safety.gui_pack_move','--profile',name,'--phase','stage']),
               ('retain',[sys.executable,'-m','tests.completion.retain_fixture','--profile',name]),
               ('crash',[sys.executable,'-m','tests.data_safety.gui_pack_move','--profile',name,'--phase','crash','--checkpoint',stage]),
               ('reopen',[sys.executable,'-m','tests.data_safety.gui_pack_move','--profile',name,'--phase','reopen','--checkpoint',stage])]
        if stage=='pack_before_move':
            steps.append(('retry',[sys.executable,'-m','tests.data_safety.gui_pack_move','--profile',name,'--phase','retry','--checkpoint',stage]))
        item={'profile':name,'checkpoint':stage,'steps':{}}
        print(name,stage,flush=True)
        for label,command in steps:
            path=logs/f'{name}-{label}.log'
            with path.open('w') as stream:
                done=subprocess.run(command,cwd=PROJECT,stdout=stream,stderr=subprocess.STDOUT,timeout=80)
            item['steps'][label]={'exit':done.returncode,'log':str(path)}
            print(' ',label,done.returncode,flush=True)
            if done.returncode:break
        item['pass']=len(item['steps'])==len(steps) and all(v['exit']==0 for v in item['steps'].values())
        result.append(item)
        (logs.parent/'pack-matrix.json').write_text(json.dumps(result,indent=2)+'\n')
    assert all(x['pass'] for x in result)

if __name__=='__main__':main()

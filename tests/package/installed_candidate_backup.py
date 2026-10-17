"""Instrumented native backup actions, then normal installed reopen; fixtures only."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

from package_fedora import manual_replace as m
from package_fedora.install_pilot import paths,sha256
from tests.package.installed_pilot_smoke import launch


def main():
    p=argparse.ArgumentParser();p.add_argument('--instrumented',type=Path,required=True);p.add_argument('--instrumented-archive',type=Path,required=True);p.add_argument('--normal',type=Path,required=True);p.add_argument('--normal-archive',type=Path,required=True);p.add_argument('--fixture-folder',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    out=a.output.resolve();project=Path(__file__).resolve().parents[2]
    if not out.is_relative_to(project/'.gate1'):raise ValueError('Synthetic project output required')
    out.mkdir(parents=True,exist_ok=False,mode=0o700)
    iexe=a.instrumented.resolve()/'DLMS-Desktop';nexe=a.normal.resolve()/'DLMS-Desktop'
    def env(home):
        value={'PATH':'/nonexistent','HOME':str(home),'LANG':'C.UTF-8','QT_QPA_PLATFORM':'offscreen'}
        for key,rel in [('XDG_DATA_HOME','xdg/data'),('XDG_CONFIG_HOME','xdg/config'),('XDG_CACHE_HOME','xdg/cache'),('TMPDIR','tmp'),('XDG_RUNTIME_DIR','xdg/runtime')]:
            path=home/rel;path.mkdir(parents=True,exist_ok=True,mode=0o700);value[key]=str(path)
        return value
    def cli(exe,home,*args):
        r=subprocess.run([str(exe),'--manage',*args,'--home',str(home)],cwd=out,env=env(home),capture_output=True,text=True,timeout=180)
        if r.returncode:raise RuntimeError((args,r.stdout,r.stderr))
        return json.loads(r.stdout)
    def application(home,phase,folder):
        exe=paths(home)['current']/'DLMS-Desktop/DLMS-Desktop'
        cmd=[str(exe),'--packaged-check','installed-daily-backup','--profile','pilot01','--installed-pilot-root',str(paths(home)['data']),'--folder',str(folder),'--phase',phase]
        with (out/f'{home.name}-{phase}-{folder.name}.log').open('w') as log:
            r=subprocess.run(cmd,cwd=out,env=env(home),stdout=log,stderr=subprocess.STDOUT,timeout=150)
        assert r.returncode==0,(cmd,r.returncode)
    homes=[]
    for name in ('source-home','destination-home'):
        home=out/name;home.mkdir(mode=0o700);homes.append(home)
        proposal=cli(iexe,home,'install','--artifact',str(a.instrumented_archive.resolve()),'--sha256',sha256(a.instrumented_archive))
        cli(iexe,home,'apply','--plan',proposal['plan_file'],'--confirm',proposal['plan']['confirmation'])
        (home/'Documents').mkdir(mode=0o700)
    source,destination=homes
    for name in ('daily-backup.zip','portable-facts.json'):shutil.copyfile(a.fixture_folder/name,source/'Documents'/name)
    application(source,'import',source/'Documents')
    export=source/'Documents/Export';export.mkdir(mode=0o700)
    application(source,'export',export)
    for name in ('daily-backup.zip','portable-facts.json'):shutil.copyfile(export/name,destination/'Documents'/name)
    application(destination,'import',destination/'Documents');application(destination,'reopen',destination/'Documents')
    before=m.old._data_fingerprint(destination)
    proposal=cli(nexe,destination,'update','--artifact',str(a.normal_archive.resolve()),'--sha256',sha256(a.normal_archive))
    cli(nexe,destination,'apply','--plan',proposal['plan_file'],'--confirm',proposal['plan']['confirmation'])
    assert m.old._data_fingerprint(destination)==before
    ordinary=out/'normal-reopen';ordinary.mkdir(mode=0o700)
    runs=[launch(m.normal_launcher_path(destination),paths(destination)['data'],ordinary,i,session_wayland=False) for i in (1,2)]
    assert runs[0]['profile_uuid']==runs[1]['profile_uuid'] and runs[0]['origin_port']==runs[1]['origin_port']
    result={'passed':True,'native_actions':'separate instrumented00ceaf1 build; exact unchanged Desktop action modules',
            'normal_candidate_reopen':runs,'source_destination_data_preserved_during_normal_activation':True,'physical_input':False}
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))

if __name__=='__main__':main()

"""Frozen manager/launcher acceptance in explicit synthetic homes only.

Source checkpoint injection is labeled separately; the normal executable has no
fault hooks. No writes to the actual per-user installation or desktop input.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

from package_fedora import installation as n, manual_replace as m
from package_fedora.install_pilot import inventory,sha256,paths,install
from tests.package.normal_lock_smoke import launch
from tests.package.installed_pilot_smoke import launch as ordinary_launch


def main():
    p=argparse.ArgumentParser();p.add_argument('--archive',type=Path,required=True);p.add_argument('--extraction',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--old-payload',type=Path,required=True);p.add_argument('--old-archive',type=Path,required=True);a=p.parse_args()
    project=Path(__file__).resolve().parents[2];out=a.output.resolve()
    if not out.is_relative_to(project/'.gate1'):raise ValueError('Synthetic project output required')
    out.mkdir(parents=True,exist_ok=False,mode=0o700);archive=a.archive.resolve();payload=a.extraction.resolve()/'DLMS-Desktop'
    exe=payload/'DLMS-Desktop';digest=sha256(archive);result={};calls=[]
    def cli(home,*args,fail=False):
        env={'PATH':'/nonexistent','HOME':str(home),'LANG':'C.UTF-8','QT_QPA_PLATFORM':'offscreen'}
        for key,rel in [('XDG_DATA_HOME','data'),('XDG_CONFIG_HOME','config'),('XDG_CACHE_HOME','cache'),('TMPDIR','tmp'),('XDG_RUNTIME_DIR','runtime')]:
            leaf=out/'manager-env'/rel;leaf.mkdir(parents=True,exist_ok=True,mode=0o700);env[key]=str(leaf)
        run=subprocess.run([str(exe),'--manage',*args,'--home',str(home)],cwd=out,env=env,capture_output=True,text=True,timeout=180)
        index=len(calls);(out/f'cli-{index:02d}.stdout').write_text(run.stdout);(out/f'cli-{index:02d}.stderr').write_text(run.stderr)
        calls.append({'argv':list(args),'exit':run.returncode})
        if fail:assert run.returncode!=0,(args,run.stdout);return run.stderr
        assert run.returncode==0,(args,run.stdout,run.stderr)
        return json.loads(run.stdout)
    def planned(home,kind,arc=archive):
        return cli(home,kind,'--artifact',str(arc),'--sha256',sha256(arc))
    def apply(home,proposal):return cli(home,'apply','--plan',proposal['plan_file'],'--confirm',proposal['plan']['confirmation'])
    home=out/'normal-home';home.mkdir(mode=0o700)
    preview=cli(home,'preview');assert preview['name']=='DLMS Desktop'
    first=planned(home,'install');apply(home,first);base=m.verify(home)[0];p0=paths(home)
    assert base['manifest_format']==4 and len(base['releases'])==1
    assert 'Name=DLMS Desktop\n' in p0['entry'].read_text() and 'Icon='+str(p0['icon_64']) in p0['entry'].read_text()
    # Derive a second explicit release of the same runtime for update fixtures;
    # it is not the owner artifact and is labeled as such in build metadata.
    other=out/'fixture-release';other.mkdir();shutil.copytree(payload,other/'DLMS-Desktop')
    info=other/'DLMS-Desktop/_internal/desktop_assets/build-info.json';build=json.loads(info.read_text());build['release']='synthetic-next-release';build['support']='Synthetic update fixture only';info.write_text(json.dumps(build,sort_keys=True,indent=2)+'\n')
    meta=json.loads((a.extraction/'candidate.json').read_text());meta.update(release=build['release'],build=build,payload_inventory=inventory(other/'DLMS-Desktop'))
    (other/'candidate.json').write_text(json.dumps(meta,indent=2));arc2=out/'synthetic-next-release.tar.zst'
    with tarfile.open(arc2,'w:zst') as tar:tar.add(other/'DLMS-Desktop',arcname='DLMS-Desktop');tar.add(other/'candidate.json',arcname='candidate.json')
    second=planned(home,'update',arc2)
    # Normal frozen launcher readiness, duplicate writer exclusion, exact lock
    # descriptor flags, abnormal parent cleanup, then separate-process reopen.
    staged=m.stage(home,'synthetic-next-release',Path(second['plan']['prepared']['archive']),sha256(arc2),Path(second['plan']['prepared']['payload']),meta['payload_inventory'])
    normal=out/'normal-lifecycle';normal.mkdir(mode=0o700)
    runs=[launch(home,normal,index,staged['operation_id'],crash=index==1) for index in (1,2)]
    assert runs[0]['profile_uuid']==runs[1]['profile_uuid'] and runs[0]['port']==runs[1]['port']
    before=m.old._data_fingerprint(home)
    # Source callback produces a real interrupted installation; the distinct
    # normal frozen manager reconciles it. No hook is shipped in normal build.
    try:m.transition(home,stage_operation=staged['operation_id'],fail_at='pointer');raise AssertionError('No checkpoint')
    except RuntimeError:pass
    assert cli(home,'reconcile')=='rolled_back'
    assert m.old._data_fingerprint(home)==before
    assert not (p0['opt']/m.ACTIVE).exists()
    # Fresh operation-bound update after rollback; confirmed normal manager.
    second=cli(home,'resume','--operation',staged['operation_id']);apply(home,second)
    rollback=cli(home,'rollback');cli(home,'rollback','--confirm',rollback['confirmation'])
    assert m.verify(home)[0]['active_release']==base['active_release']
    changed=p0['data']/'profiles/pilot01/later-synthetic-record';changed.write_bytes(b'later result')
    refusal=cli(home,'rollback','--confirm',cli(home,'rollback')['confirmation'],fail=True)
    assert 'Data changed' in refusal and changed.read_bytes()==b'later result'
    result['normal']={'runs':runs,'app_menu_entry_validated':True,'physical_menu_pending':True,'update_passed':True,'interrupted_source_boundary_frozen_reconcile':True,'later_data_rollback_refused':True}
    # Full-payload uninstall/reinstall exercises exact file preview and receipt
    # size; all original data/identity bytes must survive.
    before=m.old._data_fingerprint(home);iid=m.verify(home)[0]['install_id']
    remove=cli(home,'uninstall');removed=apply(home,remove)
    work=n.state_root(home)/'operations'/removed['operation_id'];intent_size=(work/'intent.json').stat().st_size
    assert intent_size<n.MAX_INTENT and not p0['opt'].exists() and m.old._data_fingerprint(home)==before
    restore=cli(home,'reinstall','--artifact',str(archive),'--sha256',digest,'--operation',removed['operation_id']);apply(home,restore)
    assert m.verify(home)[0]['install_id']==iid and m.old._data_fingerprint(home)==before
    reopen=out/'reinstall-reopen';reopen.mkdir(mode=0o700)
    restored=ordinary_launch(m.normal_launcher_path(home),p0['data'],reopen,1,session_wayland=False)
    assert restored['profile_uuid']==runs[0]['profile_uuid'] and restored['origin_port']==runs[0]['port']
    result['uninstall_reinstall']={'intent_bytes':intent_size,'exact_opt_files':len(remove['plan']['exact_opt_files']),'data_preserved':True,'identity_origin_preserved':True,'code_quarantine_retained':True}
    # Actual retained old normal package creates a compatible v2/v3 pilot
    # fixture. Promotion keeps its existing browser UUID/origin and data bytes.
    pilot=out/'pilot-home';pilot.mkdir(mode=0o700);oldpayload=a.old_payload.resolve();oldarc=a.old_archive.resolve()
    install(pilot,oldpayload,oldarc,sha256(oldarc),inventory(oldpayload))
    pp=paths(pilot);legacy=out/'pilot-before';legacy.mkdir(mode=0o700)
    prior=ordinary_launch(pp['launcher'],pp['data'],legacy,1,session_wayland=False)
    # Convert using the reviewed v1 -> v2 -> v3 bootstrap, same actual payload,
    # then prove explicit normal promotion rather than collision overwrite.
    from package_fedora import replace_pilot
    replace_pilot.stage(pilot,oldarc,sha256(oldarc),oldpayload,inventory(oldpayload));replace_pilot.activate(pilot,sha256(oldarc))
    staged=m.stage(pilot,'synthetic-retained-pilot',oldarc,sha256(oldarc),oldpayload,inventory(oldpayload));m.transition(pilot,stage_operation=staged['operation_id'])
    before=m.old._data_fingerprint(pilot);identity=m.verify(pilot)[0]['install_id'];old_versions=m.verify(pilot)[0]['releases']
    promoted=planned(pilot,'transition-pilot');apply(pilot,promoted)
    assert m.old._data_fingerprint(pilot)==before and m.verify(pilot)[0]['install_id']==identity
    assert all(m.verify(pilot)[0]['releases'][k]==v for k,v in old_versions.items())
    after=out/'pilot-after';after.mkdir(mode=0o700)
    current=ordinary_launch(m.normal_launcher_path(pilot),pp['data'],after,1,session_wayland=False)
    assert current['profile_uuid']==prior['profile_uuid'] and current['origin_port']==prior['origin_port']
    result['pilot_transition']={'manifest_format':m.verify(pilot)[0]['manifest_format'],'data_preserved':True,'uuid_origin_preserved':True,'retained_versions_preserved':True,'physical_taskbar_pending':True}
    result.update(passed=True,calls=calls,normal_package=True,checkout_pythonpath_and_helper_path_absent=True,physical_input=False)
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))

if __name__=='__main__':main()

"""Reusable manual replacement: only isolated synthetic installation homes."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import pytest

from tests.package.test_replace_pilot import prepared, _check_root_in_separate_process
from package_fedora import replace_pilot as legacy, manual_replace as m
from package_fedora.install_pilot import inventory, sha256, removal_plan, remove
from desktop.install_manifest import decode


def v2(tmp):
    home,p,digest,sentinel=prepared(tmp)
    legacy.activate(home,digest)
    return home,p,sentinel


def staged(home,p,tmp,name='daily-backup-20261012'):
    import shutil
    payload=tmp/name
    shutil.copytree(p['opt']/'versions/pilot-02/DLMS-Desktop',payload)
    (payload/'DLMS-Desktop').write_text('#!/bin/sh\nexit 3\n')
    cap=payload/'_internal/desktop_assets/install-format.json';cap.parent.mkdir(parents=True,exist_ok=True);cap.write_text('{"manifest_formats":[3],"guard_protocol":1}')
    archive=tmp/(name+'.tar.zst');archive.write_bytes(name.encode())
    return m.stage(home,name,archive,sha256(archive),payload,inventory(payload))


def test_two_releases_rollback_then_new_activation_retains_all(tmp_path):
    home,p,s=v2(tmp_path);before=s.read_bytes()
    old_evidence={x.name:sha256(x) for x in p['opt'].glob('*.json') if x!=p['manifest']}
    a=staged(home,p,tmp_path);first=m.transition(home,stage_operation=a['operation_id'])
    assert first['manifest_format']==3 and first['version']==2
    b=staged(home,p,tmp_path,'review-build-b');second=m.transition(home,stage_operation=b['operation_id'])
    assert second['active_release']=='review-build-b' and len(second['releases'])==4
    assert _check_root_in_separate_process(p['data']).returncode==0
    assert m.transition(home,rollback=True)['active_release']=='daily-backup-20261012'
    c=staged(home,p,tmp_path,'third-build-c');m.transition(home,stage_operation=c['operation_id'])
    assert len(m.verify(home)[0]['releases'])==5
    assert s.read_bytes()==before
    assert all(sha256(p['opt']/k)==v for k,v in old_evidence.items())
    assert len(list(p['opt'].glob('manual-resolved-*.json')))==4
    plan=removal_plan(home)
    assert len(plan['retained_versions'])==5 and plan['data_preserved']==str(p['data'])
    with pytest.raises(ValueError,match='plan-only'):remove(home)
    assert s.read_bytes()==before


@pytest.mark.parametrize('boundary',['receipt','updating','launcher','pointer','commit'])
@pytest.mark.parametrize('rollback',[False,True])
def test_interrupted_separate_process_reconcile(tmp_path,boundary,rollback):
    home,p,s=v2(tmp_path);a=staged(home,p,tmp_path)
    if rollback:m.transition(home,stage_operation=a['operation_id'])
    before=s.read_bytes()
    with pytest.raises(RuntimeError):
        m.transition(home,stage_operation=None if rollback else a['operation_id'],rollback=rollback,fail_at=boundary)
    assert _check_root_in_separate_process(p['data']).returncode!=0
    run=subprocess.run([sys.executable,'-m','package_fedora.manual_replace','reconcile','--home',str(home)],capture_output=True,text=True)
    assert run.returncode==0,run.stderr
    assert json.loads(run.stdout)['outcome']==('committed' if boundary=='commit' else 'rolled_back')
    assert s.read_bytes()==before
    assert _check_root_in_separate_process(p['data']).returncode==0
    m.verify(home)


@pytest.mark.parametrize('name',['../escape','/tmp/a','a/b','A','a..b','a_b','x'*65,'pilot-02'])
def test_bad_release_identity(tmp_path,name):
    home,p,s=v2(tmp_path)
    with pytest.raises(ValueError): m.stage(home,name,tmp_path/'missing','0'*64,tmp_path/'missing','0'*64)
    assert s.exists()


def test_unknown_format_projection_pointer_and_payload_tamper(tmp_path):
    home,p,s=v2(tmp_path);a=staged(home,p,tmp_path);m.transition(home,stage_operation=a['operation_id'])
    raw=p['manifest'].read_bytes();original=json.loads(raw)
    for mutation in ({'manifest_format':99},{'active_release':'../../escape'},{'guard_release':'not-retained'},
                     {'version_inventories':{'pilot-01':'0'*64,'pilot-02':'0'*64}}):
        p['manifest'].write_text(json.dumps(dict(original,**mutation)))
        with pytest.raises(ValueError):m.verify(home)
        assert _check_root_in_separate_process(p['data']).returncode!=0
    p['manifest'].write_bytes(raw)
    with pytest.raises(ValueError,match='legacy tool refused'):legacy.verify(home)
    p['current'].unlink();p['current'].symlink_to('/tmp')
    with pytest.raises(ValueError,match='pointer'):m.verify(home)
    p['current'].unlink();p['current'].symlink_to(original['current_target'])
    (p['opt']/original['current_target']/'DLMS-Desktop/DLMS-Desktop').write_text('tampered')
    with pytest.raises(ValueError,match='payload'):m.verify(home)


def test_stale_stage_collision_pending_and_changed_data(tmp_path):
    home,p,s=v2(tmp_path);a=staged(home,p,tmp_path)
    pending=p['data']/'profiles/pilot01/durable-actions';pending.mkdir();leaf=pending/'x.json';leaf.write_text('{}')
    with pytest.raises(ValueError,match='reconciliation'):m.transition(home,stage_operation=a['operation_id'])
    leaf.unlink();m.transition(home,stage_operation=a['operation_id'])
    with pytest.raises(ValueError,match='stale'):m.transition(home,stage_operation=a['operation_id'])
    s.write_text('later durable result')
    with pytest.raises(ValueError,match='Data changed'):m.transition(home,rollback=True)
    assert s.read_text()=='later durable result'


def test_reconcile_refuses_unknown_manifest_or_later_data(tmp_path):
    home,p,s=v2(tmp_path);a=staged(home,p,tmp_path)
    with pytest.raises(RuntimeError):m.transition(home,stage_operation=a['operation_id'],fail_at='pointer')
    raw=p['manifest'].read_bytes();p['manifest'].write_text('{}')
    with pytest.raises(ValueError,match='Unknown manifest'):m.reconcile(home)
    p['manifest'].write_bytes(raw);s.write_text('new result')
    with pytest.raises(ValueError,match='Data changed'):m.reconcile(home)
    assert (p['opt']/m.ACTIVE).exists()


def test_launch_excluded_through_guard_exec_and_activation(tmp_path):
    home,p,s=v2(tmp_path);a=staged(home,p,tmp_path)
    # New guard explicitly hands off SH; active entry seals it after real exec.
    script="""import sys,os
from pathlib import Path
from desktop.package_entry import _installation_read_lock, _exec_active
_installation_read_lock(Path(sys.argv[1]))
_exec_active(sys.executable,[sys.executable,'-c',"from desktop.package_entry import _seal_private_descriptors; _seal_private_descriptors(); print('held',flush=True); input()"])
"""
    proc=subprocess.Popen([sys.executable,'-c',script,str(p['opt'])],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
    try:
        assert proc.stdout.readline().strip()=='held'
        with pytest.raises(ValueError,match='lock is held'):m.transition(home,stage_operation=a['operation_id'])
    finally:
        proc.stdin.write('\n');proc.stdin.flush();assert proc.wait(timeout=5)==0
    entered=threading.Event();release=threading.Event();result=[]
    def callback(name):
        if name=='updating':entered.set();assert release.wait(10)
    def run():
        try:result.append(m.transition(home,stage_operation=a['operation_id'],checkpoint=callback))
        except BaseException as e:result.append(e)
    t=threading.Thread(target=run);t.start()
    try:
        assert entered.wait(10)
        command="import sys;sys.frozen=True;sys._MEIPASS='/tmp/fixture';from desktop.package_entry import _root;_root(sys.argv[1],kind='installed-pilot',profile='pilot01')"
        attempts=[subprocess.Popen([sys.executable,'-c',command,str(p['data'])],stdout=subprocess.PIPE,stderr=subprocess.PIPE) for _ in range(4)]
        assert all(x.communicate(timeout=5)[1] and x.returncode!=0 for x in attempts)
    finally:release.set();t.join(10)
    assert not t.is_alive() and len(result)==1 and isinstance(result[0],dict),result
    assert m.verify(home)[0]['active_release']==a['release']


def test_legacy_rollback_manifest_size_limit_and_symlink(tmp_path):
    home,p,s=v2(tmp_path);a=staged(home,p,tmp_path);m.transition(home,stage_operation=a['operation_id'])
    m.transition(home,rollback=True);manifest=m.verify(home)[0]
    assert manifest['current_target']=='versions/pilot-02'
    assert len(p['manifest'].read_bytes())<=8192
    with pytest.raises(ValueError,match='8192'):m.manifest_bytes(dict(manifest,padding='x'*8192))
    versions=p['opt']/'versions';versions.rename(p['opt']/'saved-versions');versions.symlink_to(p['opt']/'saved-versions')
    with pytest.raises(ValueError,match='plain'):m.verify(home)

@pytest.mark.parametrize('boundary',['intent','copy','rename'])
def test_staging_interruption_preserves_evidence_and_reconciles_complete_copy(tmp_path,boundary):
    home,p,s=v2(tmp_path)
    # Prepare a separate artifact, not a stage from another installation.
    import shutil
    payload=tmp_path/'capable';shutil.copytree(p['opt']/'versions/pilot-02/DLMS-Desktop',payload)
    cap=payload/'_internal/desktop_assets/install-format.json';cap.parent.mkdir(parents=True,exist_ok=True)
    cap.write_text('{"manifest_formats":[3],"guard_protocol":1}')
    archive=tmp_path/'artifact';archive.write_bytes(b'synthetic artifact')
    with pytest.raises(RuntimeError):m.stage(home,'interrupt-build',archive,sha256(archive),payload,inventory(payload),fail_at=boundary)
    sp=next(p['opt'].glob('manual-stage-*.json'));op=json.loads(sp.read_text())['operation_id']
    assert m.verify(home)[0]['current_target']=='versions/pilot-02'
    with pytest.raises(ValueError,match='incomplete'):m.transition(home,stage_operation=op)
    if boundary=='intent':
        with pytest.raises(ValueError,match='Stage baseline'):m.reconcile_stage(home,op)
    else:
        assert m.reconcile_stage(home,op)['phase']=='staged'
        assert m.transition(home,stage_operation=op)['active_release']=='interrupt-build'
    assert s.read_text()=='original synthetic quiz and Study history\n'


def test_stage_symlink_collision_and_changed_receipt(tmp_path):
    home,p,s=v2(tmp_path);a=staged(home,p,tmp_path)
    sp=m.stage_path(home,a['operation_id']);record=json.loads(sp.read_text())
    record['release']='../../escape';sp.write_text(json.dumps(record))
    with pytest.raises(ValueError,match='release identifier'):m.transition(home,stage_operation=a['operation_id'])
    assert m.verify(home)[0]['current_target']=='versions/pilot-02'
    source=tmp_path/'rename-source';source.mkdir();target=tmp_path/'collision';target.mkdir()
    (target/'sentinel').write_text('keep')
    with pytest.raises(FileExistsError):m._rename_noreplace(source,target)
    assert (target/'sentinel').read_text()=='keep' and source.exists()


def test_near_limit_manifest_refuses_before_active_receipt(tmp_path):
    home,p,s=v2(tmp_path);a=staged(home,p,tmp_path);m.transition(home,stage_operation=a['operation_id'])
    v=json.loads(p['manifest'].read_text());v['padding']=''
    v['padding']='x'*(8180-len(m.pack(v)))
    p['manifest'].write_bytes(m.manifest_bytes(v));before=p['manifest'].read_bytes()
    assert len(before)==8180
    with pytest.raises(ValueError,match='8192'):m.transition(home,rollback=True)
    assert p['manifest'].read_bytes()==before and not (p['opt']/m.ACTIVE).exists()
    assert m.verify(home)[0]['active_release']==a['release']


def test_fifo_installation_lock_refuses_without_blocking(tmp_path):
    home,p,s=v2(tmp_path);os.mkfifo(p['opt']/m.LOCK,0o600)
    with pytest.raises(ValueError,match='private and owned'):
        with m.gate(home):pass
    script="from pathlib import Path;import sys;from desktop.package_entry import _installation_read_lock;_installation_read_lock(Path(sys.argv[1]))"
    result=subprocess.run([sys.executable,'-c',script,str(p['opt'])],capture_output=True,text=True,timeout=3)
    assert result.returncode!=0 and 'unsafe' in result.stderr
    assert s.exists()


def test_existing_stage_parent_not_reused(tmp_path,monkeypatch):
    home,p,s=v2(tmp_path)
    import shutil
    payload=tmp_path/'capable';shutil.copytree(p['opt']/'versions/pilot-02/DLMS-Desktop',payload)
    cap=payload/'_internal/desktop_assets/install-format.json';cap.parent.mkdir(parents=True,exist_ok=True)
    cap.write_text('{"manifest_formats":[3],"guard_protocol":1}')
    archive=tmp_path/'artifact';archive.write_bytes(b'artifact')
    op='a'*32;temp=p['opt']/'versions'/('.stage-'+op);temp.mkdir();(temp/'keep').write_text('unrelated')
    class Fixed:
        hex=op
    monkeypatch.setattr(m.uuid,'uuid4',lambda:Fixed())
    with pytest.raises(FileExistsError):m.stage(home,'new-release',archive,sha256(archive),payload,inventory(payload))
    assert list(temp.iterdir())==[temp/'keep'] and (temp/'keep').read_text()=='unrelated'
    assert not (p['opt']/'versions/new-release').exists()
    shutil.copytree(payload,temp/'DLMS-Desktop')
    with pytest.raises(ValueError,match='Stage baseline'):m.reconcile_stage(home,op)
    assert (temp/'keep').read_text()=='unrelated' and not (p['opt']/'versions/new-release').exists()


def test_recovery_stage_receipt_tamper_refuses_before_mutation(tmp_path):
    home,p,s=v2(tmp_path);a=staged(home,p,tmp_path)
    with pytest.raises(RuntimeError):m.transition(home,stage_operation=a['operation_id'],fail_at='pointer')
    before=p['manifest'].read_bytes();pointer=p['current'].readlink()
    sp=m.stage_path(home,a['operation_id']);v=json.loads(sp.read_text());v['archive_sha256']='0'*64;sp.write_text(json.dumps(v))
    with pytest.raises(ValueError,match='stage lineage'):m.reconcile(home)
    assert p['manifest'].read_bytes()==before and p['current'].readlink()==pointer
    assert (p['opt']/m.ACTIVE).exists() and s.exists()


def test_fifo_manifest_refuses_before_read(tmp_path):
    home,p,s=v2(tmp_path);p['manifest'].rename(p['opt']/'manifest-evidence.json');os.mkfifo(p['manifest'],0o600)
    with pytest.raises(ValueError,match='missing, linked or not owned'):m.verify(home)
    assert s.exists()


@pytest.mark.parametrize('boundary',['receipt','updating','launcher','pointer','commit'])
def test_actual_replacer_process_exit_retains_then_reconciles_locks(tmp_path,boundary):
    home,p,s=v2(tmp_path);a=staged(home,p,tmp_path)
    script="""import os,sys
from pathlib import Path
from package_fedora.manual_replace import transition
transition(Path(sys.argv[1]),stage_operation=sys.argv[2],checkpoint=lambda name: os._exit(73) if name==sys.argv[3] else None)
"""
    child=subprocess.run([sys.executable,'-c',script,str(home),a['operation_id'],boundary],capture_output=True,text=True)
    assert child.returncode==73,child.stderr
    with pytest.raises(ValueError,match='lock evidence'):m.reconcile(home)
    retired=m.retire_transition_locks(home)
    assert retired['active_receipt_retained'] and len(list(Path(retired['evidence']).glob('*.lock')))==2
    assert m.reconcile(home)==('committed' if boundary=='commit' else 'rolled_back')
    assert s.read_text()=='original synthetic quiz and Study history\n'
    m.verify(home)


def test_lock_retirement_refuses_live_pid_and_changed_lock(tmp_path):
    home,p,s=v2(tmp_path);a=staged(home,p,tmp_path)
    with pytest.raises(RuntimeError):m.transition(home,stage_operation=a['operation_id'],fail_at='pointer')
    with pytest.raises(ValueError,match='PID exists'):m.retire_transition_locks(home)
    assert (p['opt']/m.ACTIVE).exists()


@pytest.mark.parametrize('change',['parent-symlink','lock-bytes','marker'])
def test_dead_replacer_lock_retirement_refuses_path_or_evidence_changes(tmp_path,change):
    home,p,s=v2(tmp_path);a=staged(home,p,tmp_path)
    script="from pathlib import Path;import os,sys;from package_fedora.manual_replace import transition;transition(Path(sys.argv[1]),stage_operation=sys.argv[2],checkpoint=lambda n:os._exit(73) if n=='pointer' else None)"
    child=subprocess.run([sys.executable,'-c',script,str(home),a['operation_id']],capture_output=True)
    assert child.returncode==73
    lock=m.old._lock_paths(home)[0];original=lock.read_bytes()
    if change=='parent-symlink':
        moved=home/'retained-shell';lock.parent.rename(moved);lock.parent.symlink_to(moved,target_is_directory=True)
    elif change=='lock-bytes':lock.write_bytes(original+b'changed')
    else:p['marker'].write_text('{}')
    with pytest.raises(ValueError):m.retire_transition_locks(home)
    assert lock.exists() and (p['opt']/m.ACTIVE).exists()
    if change!='lock-bytes':assert lock.read_bytes()==original

"""Bounded per-user installer lifecycle. Synthetic homes and small artifacts."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

import pytest
from package_fedora import installation as n, manual_replace as m
from package_fedora.install_pilot import inventory,sha256,paths
from tests.package.test_install_pilot import fixture_inputs
from tests.package.test_manual_replace import v2


def artifact(tmp,name='daily-use-a'):
    tmp.mkdir(parents=True,exist_ok=True)
    _,payload,_,_,_=fixture_inputs(tmp)
    assets=payload/'_internal/desktop_assets'
    (assets/'install-format.json').write_text('{"manifest_formats":[3,4],"guard_protocol":1}')
    (assets/'install-compatibility.json').write_text(json.dumps(m.COMPATIBILITY))
    build={'application_version':'0.1.0-candidate','release':name,'source_commit':'synthetic-fixture','target':'Fedora 44 x86_64','support':'Private fixture'}
    (assets/'build-info.json').write_text(json.dumps(build))
    candidate={'format':1,'release':name,'target':'fedora44-x86_64','payload_inventory':inventory(payload),'compatibility':m.COMPATIBILITY,'build':build}
    meta=tmp/'candidate.json';meta.write_text(json.dumps(candidate))
    archive=tmp/'candidate.tar.zst'
    with tarfile.open(archive,'w:zst') as tar:
        tar.add(payload,arcname='DLMS-Desktop');tar.add(meta,arcname='candidate.json')
    return archive,sha256(archive)


def home_at(tmp):
    home=tmp/'normal-home';home.mkdir(mode=0o700);return home


def install(home,archive,digest):
    prepared=n.prepare_archive(home,archive,digest);plan=n.install_plan(home,prepared)
    n.apply_install(home,plan,plan['confirmation']);return prepared,plan


def test_fresh_single_release_remove_reinstall_keeps_identity_and_data(tmp_path):
    archive,digest=artifact(tmp_path/'artifact');home=home_at(tmp_path)
    prepared,plan=install(home,archive,digest);p=paths(home);manifest=m.verify(home)[0]
    assert manifest['manifest_format']==4 and set(manifest['releases'])=={'daily-use-a'}
    assert 'Name=DLMS Desktop\n' in p['entry'].read_text()
    assert m.normal_launcher_path(home).read_bytes()==m.normal_launcher_bytes(home)
    data=p['data']/'profiles/pilot01/synthetic-record';data.write_bytes(b'quiz, history, browser origin and asset evidence')
    before=m.old._data_fingerprint(home);iid=manifest['install_id']
    remove=n.uninstall_plan(home);result=n.apply_uninstall(home,remove,remove['confirmation'])
    assert result['outcome']=='removed' and not p['opt'].exists() and not p['entry'].exists()
    assert m.old._data_fingerprint(home)==before and data.read_bytes().startswith(b'quiz')
    assert result['code_retained_for_recovery'] and Path(result['quarantine']).exists()
    restored=n.install_plan(home,prepared,reinstall=result['operation_id']);n.apply_install(home,restored,restored['confirmation'])
    assert m.verify(home)[0]['install_id']==iid and m.old._data_fingerprint(home)==before


@pytest.mark.parametrize('point',['intent','data','opt','launcher','normal_launcher','icon_32','entry','commit'])
def test_install_interrupt_reconcile_separate_process(tmp_path,point):
    archive,digest=artifact(tmp_path/'artifact');home=home_at(tmp_path)
    prepared=n.prepare_archive(home,archive,digest);plan=n.install_plan(home,prepared)
    with pytest.raises(RuntimeError):n.apply_install(home,plan,plan['confirmation'],fail_at=point)
    from desktop.management_state import assert_resolved
    with pytest.raises(ValueError,match='incomplete'):assert_resolved(home)
    run=subprocess.run([sys.executable,'-m','package_fedora.manage','reconcile','--home',str(home)],capture_output=True,text=True)
    assert run.returncode==0,run.stderr
    assert_resolved(home);assert m.verify(home)[0]['active_release']=='daily-use-a'


@pytest.mark.parametrize('point',['intent','opt','launcher','entry','icon_48','normal_launcher','commit'])
def test_uninstall_interrupt_and_reconcile_preserve_data(tmp_path,point):
    archive,digest=artifact(tmp_path/'artifact');home=home_at(tmp_path);install(home,archive,digest)
    p=paths(home);leaf=p['data']/'profiles/pilot01/history';leaf.write_bytes(b'unchanged')
    before=m.old._data_fingerprint(home);plan=n.uninstall_plan(home)
    with pytest.raises(RuntimeError):n.apply_uninstall(home,plan,plan['confirmation'],fail_at=point)
    run=subprocess.run([sys.executable,'-m','package_fedora.manage','reconcile','--home',str(home)],capture_output=True,text=True)
    assert run.returncode==0,run.stderr
    assert not p['opt'].exists() and leaf.read_bytes()==b'unchanged' and m.old._data_fingerprint(home)==before


def test_pilot_promotion_update_and_safe_rollback(tmp_path):
    (tmp_path/'pilot').mkdir();home,p,leaf=v2(tmp_path/'pilot');original=leaf.read_bytes();old=m.verify(home)[0]
    archive,digest=artifact(tmp_path/'artifact');prepared=n.prepare_archive(home,archive,digest)
    plan=n.update_plan(home,prepared,promote=True);result=n.apply_update(home,plan,plan['confirmation'])
    assert result['manifest_format']==3 and result['version_inventories']==old['version_inventories']
    assert leaf.read_bytes()==original and result['normal_integration']
    with pytest.raises((ValueError,OSError)):m.transition(home,rollback=True)  # legacy unknown compatibility
    archive2,digest2=artifact(tmp_path/'second','daily-use-b');next_artifact=n.prepare_archive(home,archive2,digest2)
    plan2=n.update_plan(home,next_artifact);n.apply_update(home,plan2,plan2['confirmation'])
    assert m.transition(home,rollback=True)['active_release']=='daily-use-a'
    leaf.write_bytes(b'later durable result')
    with pytest.raises(ValueError,match='Data changed'):m.transition(home,rollback=True)
    assert leaf.read_bytes()==b'later durable result'


@pytest.mark.parametrize('point',['receipt','updating','launcher','pointer','normal-launcher','entry','commit'])
def test_promotion_reconciliation_exact_branding_states(tmp_path,point):
    (tmp_path/'pilot').mkdir();home,p,leaf=v2(tmp_path/'pilot')
    original=leaf.read_bytes();entry=p['entry'].read_bytes();archive,digest=artifact(tmp_path/'artifact')
    prepared=n.prepare_archive(home,archive,digest);plan=n.update_plan(home,prepared,promote=True)
    with pytest.raises(RuntimeError):n.apply_update(home,plan,plan['confirmation'],fail_at=point)
    outcome=m.reconcile(home)
    assert outcome==('committed' if point=='commit' else 'rolled_back')
    assert leaf.read_bytes()==original
    if point!='commit':assert p['entry'].read_bytes()==entry and not m.normal_launcher_path(home).exists()
    else:assert m.verify(home)[0]['normal_integration']


def test_changed_plan_payload_collision_and_unauthorized_paths(tmp_path):
    archive,digest=artifact(tmp_path/'artifact');home=home_at(tmp_path)
    prepared=n.prepare_archive(home,archive,digest);plan=n.install_plan(home,prepared)
    with pytest.raises(ValueError,match='stale'):n.apply_install(home,plan,'0'*64)
    collision=m.normal_launcher_path(home);collision.parent.mkdir(parents=True);collision.write_text('unrelated launcher')
    with pytest.raises(FileExistsError):n.apply_install(home,plan,plan['confirmation'])
    assert collision.read_text()=='unrelated launcher' and not paths(home)['data'].exists()
    collision.unlink();Path(prepared['payload'],'DLMS-Desktop').write_text('tampered')
    with pytest.raises(ValueError,match='payload changed'):n.apply_install(home,plan,plan['confirmation'])


def test_accepted_pending_and_changed_uninstall_preview_refuse(tmp_path):
    archive,digest=artifact(tmp_path/'artifact');home=home_at(tmp_path);install(home,archive,digest)
    p=paths(home);plan=n.uninstall_plan(home)
    pending=p['data']/'profiles/pilot01/durable-actions';pending.mkdir();(pending/'a.json').write_text('{}')
    with pytest.raises(ValueError,match='reconciliation'):n.apply_uninstall(home,plan,plan['confirmation'])
    (pending/'a.json').unlink();p['entry'].write_text('unrelated change')
    with pytest.raises(ValueError):n.apply_uninstall(home,plan,plan['confirmation'])
    assert p['opt'].exists()


def test_reinstall_changed_data_refused_and_symlink_state(tmp_path):
    archive,digest=artifact(tmp_path/'artifact');home=home_at(tmp_path);prepared,_=install(home,archive,digest)
    plan=n.uninstall_plan(home);result=n.apply_uninstall(home,plan,plan['confirmation'])
    leaf=paths(home)['data']/'profiles/pilot01/history';leaf.write_bytes(b'later')
    with pytest.raises(ValueError,match='data changed'):n.install_plan(home,prepared,reinstall=result['operation_id'])
    assert leaf.read_bytes()==b'later'


def test_archive_checksum_and_unsafe_member_rejected(tmp_path):
    archive,digest=artifact(tmp_path/'artifact');home=home_at(tmp_path)
    with pytest.raises(ValueError,match='checksum'):n.prepare_archive(home,archive,'0'*64)
    unsafe=tmp_path/'unsafe.tar.zst'
    with tarfile.open(unsafe,'w:zst') as tar:
        info=tarfile.TarInfo('../escape');info.size=0;tar.addfile(info)
    with pytest.raises(ValueError,match='Unsafe'):n.prepare_archive(home,unsafe,sha256(unsafe))
    assert not paths(home)['opt'].exists() and not (tmp_path/'escape').exists()


def test_unrecorded_versions_are_not_uninstalled(tmp_path):
    archive,digest=artifact(tmp_path/'artifact');home=home_at(tmp_path);install(home,archive,digest)
    unrelated=paths(home)['opt']/'versions/unrelated';unrelated.mkdir();(unrelated/'owner-file').write_bytes(b'preserve me')
    with pytest.raises(ValueError,match='Unrecorded'):n.uninstall_plan(home)
    assert (unrelated/'owner-file').read_bytes()==b'preserve me'


def test_reconcile_refuses_self_removal(tmp_path,monkeypatch):
    home=home_at(tmp_path)
    monkeypatch.setattr(sys,'_MEIPASS',str(paths(home)['opt']/'versions/build/DLMS-Desktop/_internal'),raising=False)
    with pytest.raises(ValueError,match='extracted candidate'):n.reconcile(home)


def test_artifact_format_capability_and_member_bound(tmp_path,monkeypatch):
    archive,digest=artifact(tmp_path/'artifact');home=home_at(tmp_path)
    monkeypatch.setattr(n,'MAX_MEMBERS',2)
    with pytest.raises(ValueError,match='archive limits'):n.prepare_archive(home,archive,digest)
    monkeypatch.setattr(n,'MAX_MEMBERS',20000)
    payload=tmp_path/'artifact/source-payload';assets=payload/'_internal/desktop_assets'
    (assets/'install-format.json').write_text('{"manifest_formats":[3],"guard_protocol":1}')
    candidate=json.loads((tmp_path/'artifact/candidate.json').read_text());candidate['payload_inventory']=inventory(payload)
    (tmp_path/'artifact/candidate.json').write_text(json.dumps(candidate))
    bad=tmp_path/'format3-only.tar.zst'
    with tarfile.open(bad,'w:zst') as tar:
        tar.add(payload,arcname='DLMS-Desktop');tar.add(tmp_path/'artifact/candidate.json',arcname='candidate.json')
    with pytest.raises(ValueError,match='compatibility'):n.prepare_archive(home,bad,sha256(bad))
    assert not paths(home)['opt'].exists()


@pytest.mark.parametrize('point',['intent','data','opt','entry','commit'])
def test_retained_reinstall_interruption_uses_locks_and_preserves_data(tmp_path,point):
    archive,digest=artifact(tmp_path/'artifact');home=home_at(tmp_path);prepared,_=install(home,archive,digest)
    p=paths(home);leaf=p['data']/'profiles/pilot01/history';leaf.write_bytes(b'unchanged history')
    plan=n.uninstall_plan(home);removed=n.apply_uninstall(home,plan,plan['confirmation'])
    before=m.old._data_fingerprint(home);plan=n.install_plan(home,prepared,reinstall=removed['operation_id'])
    with pytest.raises(RuntimeError):n.apply_install(home,plan,plan['confirmation'],fail_at=point)
    n.reconcile(home)
    assert m.old._data_fingerprint(home)==before and leaf.read_bytes()==b'unchanged history'


def test_resume_rolled_back_stage_is_identity_bound_and_single_application(tmp_path):
    archive,digest=artifact(tmp_path/'first');home=home_at(tmp_path);install(home,archive,digest)
    second,sha=artifact(tmp_path/'second','resumed-update');prepared=n.prepare_archive(home,second,sha)
    plan=n.update_plan(home,prepared)
    with pytest.raises(RuntimeError):n.apply_update(home,plan,plan['confirmation'],fail_at='pointer')
    assert m.reconcile(home)=='rolled_back'
    records=list(paths(home)['opt'].glob('manual-stage-*.json'));assert len(records)==1
    op=m.read(records[0])['operation_id'];resume=n.resume_plan(home,op)
    with pytest.raises(ValueError,match='stale'):n.apply_resume(home,resume,'0'*64)
    n.apply_resume(home,resume,resume['confirmation'])
    assert m.verify(home)[0]['active_release']=='resumed-update'
    with pytest.raises(ValueError):n.apply_resume(home,resume,resume['confirmation'])


def test_frozen_readonly_pending_scope_uses_owned_marker_not_environment(tmp_path,monkeypatch):
    archive,digest=artifact(tmp_path/'artifact');home=home_at(tmp_path);install(home,archive,digest)
    monkeypatch.setattr(sys,'frozen',True,raising=False)
    monkeypatch.setenv('DLMS_DESKTOP_DATA_ROOT','/wrong/untrusted')
    monkeypatch.setenv('DLMS_DESKTOP_ROOT_KIND','wrong')
    m.old._ensure_no_pending_data(home)
    assert os.environ['DLMS_DESKTOP_DATA_ROOT']==str(paths(home)['data'])
    assert os.environ['DLMS_DESKTOP_ROOT_KIND']=='installed-pilot'
    marker=paths(home)['marker'];marker.write_text('{}')
    with pytest.raises(ValueError,match='identity'):m.old._ensure_no_pending_data(home)


def test_resume_rechecks_confirmed_data_under_activation_locks(tmp_path,monkeypatch):
    archive,digest=artifact(tmp_path/'first');home=home_at(tmp_path);install(home,archive,digest)
    second,sha=artifact(tmp_path/'second','locked-resume');prepared=n.prepare_archive(home,second,sha)
    plan=n.update_plan(home,prepared)
    with pytest.raises(RuntimeError):n.apply_update(home,plan,plan['confirmation'],fail_at='pointer')
    m.reconcile(home);op=m.read(next(paths(home)['opt'].glob('manual-stage-*.json')))['operation_id']
    resume=n.resume_plan(home,op);original=m.transition
    def changed_after_preview(*args,**kwargs):
        (paths(home)['data']/'profiles/pilot01/later-record').write_bytes(b'confirmed preview is stale')
        return original(*args,**kwargs)
    monkeypatch.setattr(m,'transition',changed_after_preview)
    with pytest.raises(ValueError,match='Confirmed data'):n.apply_resume(home,resume,resume['confirmation'])
    assert m.verify(home)[0]['active_release']=='daily-use-a'
    assert not (paths(home)['opt']/m.ACTIVE).exists()


def test_installer_entry_uses_shell_builtins_with_no_helper_path(tmp_path,monkeypatch):
    from package_fedora import finalize_candidate
    dist=tmp_path/'extracted with spaces';payload=dist/'DLMS-Desktop';assets=payload/'_internal/desktop_assets';assets.mkdir(parents=True)
    (assets/'build-info.json').write_text('{"release":"synthetic-wrapper"}')
    exe=payload/'DLMS-Desktop';exe.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n');exe.chmod(0o755)
    monkeypatch.setattr(sys,'argv',['finalize','--dist',str(dist)]);finalize_candidate.main()
    result=subprocess.run([str(payload/'Install-DLMS-Desktop'),'preview'],cwd=tmp_path,env={'PATH':'/nonexistent'},capture_output=True,text=True)
    assert result.returncode==0 and result.stdout=='--manage\npreview\n' and not result.stderr

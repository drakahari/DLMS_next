from pathlib import Path
import json
import shutil
import subprocess
import os
import tarfile

import pytest


def test_explicit_desktop_mit_grant_does_not_license_unknown_files(tmp_path):
    from package_fedora.distribution_inventory import project_component
    (tmp_path / 'app.py').write_text('APP_VERSION = "3.3.0"\n')
    core = project_component(tmp_path / 'app.py', 'app', tmp_path)
    assert core[0] == 'application:canonical' and core[1]['version'] == '3.3.0'
    assert core[1]['license_expression'] == 'MIT'
    for name in ('desktop/shell.py', 'package_windows/build.py', 'windows_webview2/Host.cs',
                 'tools/run_consolidation_checks.py', 'package_macos/build.py',
                 'tools/macos_qualify_candidate.py'):
        owned = project_component(tmp_path / name, name, tmp_path)
        assert owned[0] == 'application:desktop'
        assert owned[1]['license_expression'] == 'MIT'
        assert 'retain third-party' in owned[1]['license_scope']
    assert project_component(tmp_path / 'unclassified.bin', 'unknown', tmp_path) is None
    assert project_component(tmp_path.parent / 'unrelated', 'unknown', tmp_path) is None
from package_fedora.distribution_inventory import payload_leaves,qt_part
from package_fedora.release_manifest import checksum_manifest
from package_fedora.user_variant import prepare_variant
from package_fedora.manual_replace import payload_inventory
from tests.package.test_installation_manager import artifact,home_at,install


def test_inventory_keeps_unknown_leaves_and_rejects_link_escape(tmp_path):
    (tmp_path/'mystery').write_bytes(b'unclassified input still belongs in inventory')
    rows=payload_leaves(tmp_path);assert len(rows)==1 and rows[0]['path']=='mystery' and rows[0]['sha256']
    (tmp_path/'escape').symlink_to('/etc/passwd')
    with pytest.raises(ValueError,match='Escaping'):payload_leaves(tmp_path)


def test_qt_plugin_and_resource_are_distinct():
    assert qt_part('_internal/PySide6/Qt/plugins/platforms/libqwayland-generic.so')=='plugin:platforms/libqwayland-generic.so'
    assert qt_part('_internal/PySide6/Qt/lib/libQt6WaylandCompositor.so.6')=='WaylandCompositor'
    assert qt_part('_internal/PySide6/Qt/resources/qtwebengine_resources.pak')=='WebEngine-resources'


def test_modified_library_variant_uses_ordinary_manager_and_preserves_data(tmp_path):
    from package_fedora import installation as n,manual_replace as m
    archive,sha=artifact(tmp_path/'base-artifact',name='vendor-one');home=home_at(tmp_path)
    base=tmp_path/'base-artifact/source-payload';assert base.exists()
    library=base/'_internal/library.so';library.write_bytes(b'synthetic ABI fixture original')
    meta=tmp_path/'base-artifact/candidate.json';value=json.loads(meta.read_text());value['payload_inventory']=payload_inventory(base);meta.write_text(json.dumps(value))
    reviewed=tmp_path/'vendor-with-library.tar.zst'
    with tarfile.open(reviewed,'w:zst') as tar:
        tar.add(base,arcname='DLMS-Desktop');tar.add(meta,arcname='candidate.json')
    from package_fedora.install_pilot import sha256
    install(home,reviewed,sha256(reviewed))
    # Make a reviewed base that contains a replaceable shared-library fixture.
    modified=tmp_path/'external-modified';shutil.copytree(base,modified)
    (modified/'_internal/library.so').write_bytes(b'synthetic ABI fixture user modification')
    result=prepare_variant(home,base,modified,tmp_path/'variant-output','user-library-two',payload_inventory(base))
    data=m.paths(home)['data']/'profiles/pilot01/retained-test-record';data.write_bytes(b'unchanged history')
    before=m.old._data_fingerprint(home)
    prepared=n.prepare_archive(home,Path(result['archive']),result['sha256']);plan=n.update_plan(home,prepared)
    n.apply_update(home,plan,plan['confirmation'])
    assert m.verify(home)[0]['active_release']=='user-library-two'
    assert m.old._data_fingerprint(home)==before and data.read_bytes()==b'unchanged history'
    m.transition(home,rollback=True)
    assert m.verify(home)[0]['active_release']=='vendor-one'
    assert data.read_bytes()==b'unchanged history'
    assert not result['publisher_authenticated'] and not result['application_compatibility_tested']


def test_signed_checksums_with_disposable_keys_only(tmp_path):
    keygen=shutil.which('ssh-keygen');assert keygen,'Fedora test prerequisite: OpenSSH ssh-keygen'
    env=os.environ.copy();env.pop('SSH_AUTH_SOCK',None)
    key=tmp_path/'DISPOSABLE-test-key';wrong=tmp_path/'DISPOSABLE-wrong-key'
    for path in (key,wrong):
        subprocess.run([keygen,'-q','-t','ed25519','-N','','-C','DLMS DISPOSABLE TEST ONLY','-f',str(path)],check=True,env=env)
    binary=tmp_path/'candidate.tar.zst';binary.write_bytes(b'synthetic artifact')
    manifest=tmp_path/'SHA256SUMS';manifest.write_bytes(checksum_manifest([binary]))
    subprocess.run([keygen,'-Y','sign','-f',str(key),'-n','dlms-desktop-release',str(manifest)],check=True,env=env,capture_output=True)
    allowed=tmp_path/'test.allowed_signers';allowed.write_text('dlms-disposable '+key.with_suffix('.pub').read_text())
    def verify(namespace='dlms-desktop-release',identity='dlms-disposable',raw=None):
        return subprocess.run([keygen,'-Y','verify','-f',str(allowed),'-I',identity,'-n',namespace,'-s',str(manifest)+'.sig'],input=raw if raw is not None else manifest.read_bytes(),capture_output=True,env=env).returncode
    assert verify()==0
    assert verify(namespace='other-application')!=0 and verify(identity='wrong-publisher')!=0
    assert verify(raw=manifest.read_bytes()+b'tampered')!=0
    allowed.write_text('dlms-disposable '+wrong.with_suffix('.pub').read_text());assert verify()!=0
    binary.write_bytes(b'changed artifact');assert checksum_manifest([binary])!=manifest.read_bytes()


def test_release_checksum_names_refuse_symlink_duplicate_and_unsafe(tmp_path):
    f=tmp_path/'artifact';f.write_bytes(b'x')
    with pytest.raises(ValueError,match='duplicate'):checksum_manifest([f,f])
    link=tmp_path/'link';link.symlink_to(f)
    with pytest.raises(ValueError,match='regular'):checksum_manifest([link])
    weird=tmp_path/'unsafe\nname';weird.write_bytes(b'x')
    with pytest.raises(ValueError,match='Unsafe'):checksum_manifest([weird])


def test_variant_refuses_installed_target_and_parent_traversal(tmp_path):
    home=home_at(tmp_path)
    with pytest.raises(ValueError,match='installed payload'):
        prepare_variant(home,home/'.local/opt/dlms-desktop/versions/existing',tmp_path/'modified',tmp_path/'output','user-variant','0'*64)
    with pytest.raises(ValueError,match='Parent traversal'):
        prepare_variant(home,tmp_path/'x/../base',tmp_path/'modified',tmp_path/'output','user-variant','0'*64)


@pytest.mark.parametrize('case',['protected-ancestor','nested','symlink-parent','existing-output'])
def test_variant_refuses_overlap_and_preserves_existing_output(tmp_path,case):
    home=home_at(tmp_path);base=tmp_path/'base';modified=tmp_path/'modified';output=tmp_path/'output'
    if case=='protected-ancestor':
        with pytest.raises(ValueError,match='installed payload'):
            prepare_variant(home,home,modified,output,'user-variant','0'*64)
    elif case=='nested':
        with pytest.raises(ValueError,match='separate'):
            prepare_variant(home,base,base/'nested',output,'user-variant','0'*64)
    elif case=='symlink-parent':
        actual=tmp_path/'actual';actual.mkdir();base.symlink_to(actual)
        with pytest.raises(ValueError,match='symlink parent'):
            prepare_variant(home,base,modified,output,'user-variant','0'*64)
    else:
        output.mkdir();sentinel=output/'sentinel';sentinel.write_bytes(b'preserve output')
        with pytest.raises(FileExistsError,match='preserve'):
            prepare_variant(home,base,modified,output,'user-variant','0'*64)
        assert sentinel.read_bytes()==b'preserve output'


def test_notice_bundle_hash_manifest_refuses_tampering_and_links(tmp_path):
    from package_fedora.assemble_distribution import assemble,verify_materials
    source=tmp_path/'license';source.write_text('Verified upstream text fixture')
    output=tmp_path/'texts';assemble(output,[('LICENSE',source)])
    assert len(verify_materials(output)['sha256'])==1
    (output/'LICENSE').write_text('tampered')
    with pytest.raises(ValueError,match='differ'):verify_materials(output)
    links=tmp_path/'links';links.mkdir();(links/'bad').symlink_to(source)
    with pytest.raises(ValueError,match='symlinks'):assemble(tmp_path/'rejected',[('licenses',links)])


@pytest.mark.parametrize('case',['duplicate','reserved','nested-output','source-in-output','symlink-parent'])
def test_notice_assembly_preflight_never_mutates_inputs(tmp_path,case):
    from package_fedora.assemble_distribution import assemble
    source=tmp_path/'source';source.mkdir();f=source/'LICENSE';f.write_bytes(b'original')
    output=tmp_path/'output';inputs=[('texts',source)]
    if case=='duplicate':inputs=[('LICENSE',f),('LICENSE',f)]
    elif case=='reserved':inputs=[('MANIFEST.json',f)]
    elif case=='nested-output':output=source/'output'
    elif case=='source-in-output':output=tmp_path;inputs=[('texts',source)]
    else:
        parent=tmp_path/'link';parent.symlink_to(source);output=parent/'output'
    with pytest.raises((ValueError,FileExistsError)):assemble(output,inputs)
    assert f.read_bytes()==b'original'
    if case!='source-in-output':assert not output.exists()


def test_finalizer_creates_prominent_notice_without_overwriting(tmp_path,monkeypatch):
    from package_fedora.assemble_distribution import assemble
    from package_fedora.finalize_candidate import main
    dist=tmp_path/'dist';payload=dist/'DLMS-Desktop';assets=payload/'_internal/desktop_assets';assets.mkdir(parents=True)
    (payload/'DLMS-Desktop').write_bytes(b'synthetic executable')
    (assets/'build-info.json').write_text(json.dumps({'release':'notice-test-01'}))
    f=tmp_path/'LICENSE';f.write_text('License fixture')
    kit=tmp_path/'kit';assemble(kit,[('LICENSE',f)])
    monkeypatch.setattr('sys.argv',['finalize','--dist',str(dist),'--distribution-root',str(kit)])
    main();notice=(payload/'THIRD-PARTY-NOTICES.txt').read_text()
    assert 'NOT PUBLICLY CLEARED' in notice and 'LGPL/GPL' in notice
    with pytest.raises(FileExistsError):main()
    assert (payload/'THIRD-PARTY-NOTICES.txt').read_text()==notice

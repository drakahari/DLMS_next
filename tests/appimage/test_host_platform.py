from pathlib import Path
import pytest
from package_linux.host_platform import platform_library, prune, write_manifest, verify_payload


@pytest.mark.parametrize('name', ['libfontconfig.so', 'libfontconfig.so.1', 'libfontconfig.so.1.15.0',
                                  'libgbm.so', 'libgbm.so.1', 'libgbm.so.1.0.0'])
def test_exact_platform_family_names(name):
    assert platform_library('_internal/' + name)


@pytest.mark.parametrize('name', ['libfreetype.so.6', 'libdrm.so.2', 'libEGL.so.1', 'libGL.so.1',
                                  'libjbig.so.0', 'libfontconfig-tools.so', 'fontconfig.conf', 'LICENSE'])
def test_other_dependencies_and_assets_remain(name):
    assert platform_library(name) is None


def test_binary_and_alias_exclusion_preserves_consumers():
    binaries=[('libgbm.so.1','/build/libgbm.so.1','BINARY'),
              ('PySide6/Qt/lib/libQt6WebEngineCore.so.6','/qt/libQt6WebEngineCore.so.6','BINARY'),
              ('libjbig.so.0','/build/libjbig.so.0','BINARY')]
    datas=[('libfontconfig.so.1','libfontconfig.so.1.15.0','SYMLINK'),
           ('fonts/system.conf','/build/system.conf','DATA')]
    b,d,removed=prune(binaries,datas)
    assert b==binaries[1:] and d==datas[1:]
    assert {x['path'] for x in removed}=={'libgbm.so.1','libfontconfig.so.1'}


def test_final_manifest_and_no_remaining_platform_library(tmp_path):
    folder=tmp_path/'_internal/desktop_assets';folder.mkdir(parents=True)
    write_manifest(folder/'host-platform.json',[])
    assert verify_payload(tmp_path)['host_sonames']==['libfontconfig.so.1','libgbm.so.1']
    rogue=tmp_path/'_internal/libgbm.so.1';rogue.write_bytes(b'library')
    with pytest.raises(ValueError,match='was bundled'):verify_payload(tmp_path)
    rogue.unlink();rogue.symlink_to('missing')
    with pytest.raises(ValueError,match='was bundled'):verify_payload(tmp_path)


def test_manifest_cannot_be_overwritten_or_omitted(tmp_path):
    with pytest.raises(ValueError,match='manifest'):verify_payload(tmp_path)
    folder=tmp_path/'_internal/desktop_assets';folder.mkdir(parents=True)
    p=folder/'host-platform.json';write_manifest(p,[])
    with pytest.raises(FileExistsError):write_manifest(p,[])
    p.write_text('{"format":2}')
    with pytest.raises(ValueError,match='differs'):verify_payload(tmp_path)

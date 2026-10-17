import json
import os
from pathlib import Path
import pytest
from desktop.appimage_runtime import prepare_root, NAMESPACE, MARKER, VALUE


def env(tmp_path):
    home=tmp_path/'home';home.mkdir()
    return {'HOME':str(home),'XDG_DATA_HOME':str(home/'data')}


def test_root_and_reopen(tmp_path):
    e=env(tmp_path);r=prepare_root(e,payload=tmp_path/'image')
    assert r==Path(e['XDG_DATA_HOME'])/NAMESPACE
    (r/'sentinel').write_bytes(b'unchanged')
    assert prepare_root(e,payload=tmp_path/'moved image')==r
    assert (r/'sentinel').read_bytes()==b'unchanged'
    assert r.stat().st_mode&0o777==0o700
    assert json.loads((r/MARKER).read_text())==VALUE


@pytest.mark.parametrize('bad', ['relative','/absolute/../ambiguous'])
def test_relative_or_ambiguous_xdg(tmp_path,bad):
    e=env(tmp_path);e['XDG_DATA_HOME']=bad
    with pytest.raises(ValueError):prepare_root(e,payload=tmp_path/'image')


def test_unmarked_collision_refused(tmp_path):
    e=env(tmp_path);r=Path(e['XDG_DATA_HOME'])/NAMESPACE;r.mkdir(parents=True,mode=0o700)
    (r/'evidence').write_bytes(b'keep')
    with pytest.raises(FileNotFoundError):prepare_root(e,payload=tmp_path/'image')
    assert (r/'evidence').read_bytes()==b'keep'


def test_symlink_namespace_refused(tmp_path):
    e=env(tmp_path);b=Path(e['XDG_DATA_HOME']);b.mkdir();target=tmp_path/'unrelated';target.mkdir()
    (b/NAMESPACE).symlink_to(target,target_is_directory=True)
    with pytest.raises(OSError):prepare_root(e,payload=tmp_path/'image')
    assert list(target.iterdir())==[]


def test_unsafe_mode_refused_without_chmod(tmp_path):
    e=env(tmp_path);r=prepare_root(e,payload=tmp_path/'image');r.chmod(0o755)
    with pytest.raises(ValueError):prepare_root(e,payload=tmp_path/'image')
    assert r.stat().st_mode&0o777==0o755


def test_marker_tamper_and_symlink(tmp_path):
    e=env(tmp_path);r=prepare_root(e,payload=tmp_path/'image');(r/MARKER).write_text('{}')
    with pytest.raises(ValueError):prepare_root(e,payload=tmp_path/'image')
    (r/MARKER).unlink();p=tmp_path/'outside';p.write_text(json.dumps(VALUE));(r/MARKER).symlink_to(p)
    with pytest.raises(OSError):prepare_root(e,payload=tmp_path/'image')
    assert p.read_text()==json.dumps(VALUE)


def test_mount_and_installed_storage_refused(tmp_path):
    e=env(tmp_path);image=tmp_path/'image';e['XDG_DATA_HOME']=str(image/'data')
    with pytest.raises(ValueError):prepare_root(e,payload=image)
    assert not image.exists()
    e['XDG_DATA_HOME']=str(tmp_path/'dlms-desktop-pilot')
    with pytest.raises(ValueError):prepare_root(e,payload=image)
    assert not (tmp_path/'dlms-desktop-pilot').exists()


def test_default_home_has_distinct_namespace(tmp_path):
    e=env(tmp_path);e.pop('XDG_DATA_HOME');r=prepare_root(e,payload=tmp_path/'image')
    assert r==Path(e['HOME'])/'.local/share'/NAMESPACE
    assert not (Path(e['HOME'])/'.local/opt/dlms-desktop').exists()

@pytest.mark.parametrize('relative', ['.local/opt/dlms-desktop', '.local/state/dlms-desktop-management', '.local/share/dlms-desktop-pilot'])
def test_installed_namespaces_remain_untouched(tmp_path,relative):
    e=env(tmp_path);protected=Path(e['HOME'])/relative;protected.mkdir(parents=True)
    sentinel=protected/'owned-evidence';sentinel.write_bytes(b'unchanged')
    e['XDG_DATA_HOME']=str(protected)
    with pytest.raises(ValueError):prepare_root(e,payload=tmp_path/'image')
    assert list(protected.iterdir())==[sentinel] and sentinel.read_bytes()==b'unchanged'

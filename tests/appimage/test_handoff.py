"""Simulated mount identity; real descriptor flags/pipe types, no host mount."""
import os,json,hashlib
from pathlib import Path
from types import SimpleNamespace
import pytest
from desktop import appimage_runtime as runtime, package_entry

@pytest.fixture
def mount(tmp_path,monkeypatch):
    directory=tmp_path/'mounted';directory.mkdir();image=tmp_path/'image';image.write_bytes(b'pinned runtime prefix')
    payload=directory/'payload';assets=payload/'desktop_assets';assets.mkdir(parents=True)
    (assets/'appimage-info.json').write_text(json.dumps({'runtime_bytes':image.stat().st_size,'runtime_sha256':hashlib.sha256(image.read_bytes()).hexdigest()}))
    monkeypatch.setattr(runtime.sys,'_MEIPASS',str(payload),raising=False);monkeypatch.setenv('APPDIR',str(directory));monkeypatch.setenv('APPIMAGE',str(image))
    with pytest.raises(OSError):os.fstat(1023)  # Never overwrite an existing descriptor.
    fd=os.open(directory,os.O_RDONLY|os.O_DIRECTORY);os.dup2(fd,1023);os.close(fd)
    read,write=os.pipe();fds=[1023,read,write]
    for n in fds:os.set_inheritable(n,False)
    old_list=os.listdir
    monkeypatch.setattr(runtime.os,'listdir',lambda p:[str(n) for n in fds] if p=='/proc/self/fd' else old_list(p))
    monkeypatch.setattr(runtime.os,'statvfs',lambda p:SimpleNamespace(f_flag=os.ST_RDONLY))
    yield image,read,write,fds
    for n in fds:
        try:os.close(n)
        except OSError:pass


def test_exact_mount_handoff_only(mount):
    _,read,_,_=mount
    assert runtime.mount_handoff_descriptors()==[1023,read]
    assert not os.get_inheritable(read)


def test_runtime_tamper_refuses(mount):
    image,_,_,_=mount;image.write_bytes(b'wrong runtime')
    with pytest.raises(ValueError,match='runtime identity'):runtime.mount_handoff_descriptors()


def test_extra_readpipe_is_ambiguous(mount,monkeypatch):
    _,_,_,fds=mount;a,b=os.pipe();fds.extend([a,b])
    with pytest.raises(ValueError,match='ambiguous'):runtime.mount_handoff_descriptors()


def test_no_mount_fallback(monkeypatch):
    monkeypatch.delenv('APPIMAGE',raising=False)
    assert runtime.mount_handoff_descriptors()==[]


def test_handoff_reseals_after_failed_exec(mount,tmp_path,monkeypatch):
    _,read,_,_=mount
    monkeypatch.setattr(runtime.sys,'executable',str(tmp_path/'AppDir/usr/lib/dlms-desktop/DLMS-Desktop'))
    monkeypatch.setattr(runtime,'same_image_executable',lambda p:True)
    monkeypatch.setattr(runtime,'prepare_root',lambda *a,**k:tmp_path/'data')
    def fail(path,argv):
        assert os.get_inheritable(1023) and os.get_inheritable(read)
        assert argv[1:]==['--profile','appimage01','--data-root',str(tmp_path/'data')]
        raise OSError('simulated exec failure')
    monkeypatch.setattr(os,'execv',fail)
    with pytest.raises(OSError,match='simulated'):runtime.launch([])
    assert not os.get_inheritable(read) and not os.get_inheritable(1023)


def test_second_entry_seals_mount_handles(mount):
    _,read,_,_=mount
    os.set_inheritable(1023,True);os.set_inheritable(read,True)
    package_entry._seal_private_descriptors()
    assert not os.get_inheritable(1023) and not os.get_inheritable(read)


def test_short_prefix_refuses_even_with_matching_short_digest(mount,monkeypatch):
    import sys
    image,_,_,_=mount;p=Path(sys._MEIPASS)/'desktop_assets/appimage-info.json';x=json.loads(p.read_text());x['runtime_bytes']+=1;p.write_text(json.dumps(x))
    with pytest.raises(ValueError,match='runtime identity'):runtime.mount_handoff_descriptors()


def test_writable_mount_refuses(mount,monkeypatch):
    monkeypatch.setattr(os,'statvfs',lambda p:SimpleNamespace(f_flag=0))
    with pytest.raises(ValueError,match='read-only'):runtime.mount_handoff_descriptors()


def test_directory_mismatch_preserves_no_unknown_handle(mount,tmp_path,monkeypatch):
    other=tmp_path/'other';other.mkdir();monkeypatch.setenv('APPDIR',str(other))
    assert runtime.mount_handoff_descriptors()==[]


def test_no_mount_handles_in_external_exec(mount):
    import subprocess,sys
    _,read,_,_=mount
    os.set_inheritable(1023,True);os.set_inheritable(read,True)
    package_entry._seal_private_descriptors()
    target=os.readlink(f'/proc/self/fd/{read}')
    script="""import os,json
items={}
for name in os.listdir('/proc/self/fd'):
 try:items[name]=os.readlink('/proc/self/fd/'+name)
 except FileNotFoundError:pass
print(json.dumps(items))
"""
    p=subprocess.run([sys.executable,'-c',script],capture_output=True,text=True,close_fds=False)
    assert p.returncode==0,p.stderr
    seen=json.loads(p.stdout)
    assert '1023' not in seen and target not in seen.values()

@pytest.mark.parametrize('alteration',['checksum-only','code','update-info'])
def test_exact_pinned_runtime_checksum_slot(mount,alteration):
    import sys
    source=Path(__file__).resolve().parents[2]/'.gate1/appimage-20261013/tools/runtime-x86_64'
    if not source.exists():pytest.skip('Official pinned AppImage runtime build input required for this integration check')
    original=source.read_bytes();assert hashlib.sha256(original).hexdigest()=='156f4bdbde9c52d01814600013e0a273f0118dc2de98975f3c8c63427ec79074'
    image,read,_,_=mount;data=bytearray(original);data[932096:932112]=b'C'*16
    if alteration=='code':data[10000]^=1
    if alteration=='update-info':data[932112]^=1
    image.write_bytes(data)
    meta=Path(sys._MEIPASS)/'desktop_assets/appimage-info.json';meta.write_text(json.dumps({'runtime_bytes':len(original),'runtime_sha256':hashlib.sha256(original).hexdigest()}))
    if alteration=='checksum-only':assert runtime.mount_handoff_descriptors()==[1023,read]
    else:
        with pytest.raises(ValueError,match='runtime identity'):runtime.mount_handoff_descriptors()

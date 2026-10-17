import fcntl
import hashlib
import os
from pathlib import Path
import pytest
from desktop import file_selection as fs


def test_unicode_original_name_seals_and_source_replacement(tmp_path):
    ordinary=tmp_path/'Visible Documents é';ordinary.mkdir()
    source=ordinary/'quiz α space.txt';source.write_bytes(b'Original choices\n')
    snapshots=fs.Snapshots(tmp_path)
    try:
        selected=Path(snapshots.stage([source])[0])
        assert selected.name==source.name
        source.write_bytes(b'Changed choices!\n')
        assert selected.read_bytes()==b'Original choices\n'
        target=int(os.readlink(selected).rsplit('/',1)[1])
        assert fcntl.fcntl(target,fcntl.F_GET_SEALS)&fs._SEALS==fs._SEALS
        assert not os.get_inheritable(target)
        for mutation in (lambda:os.write(target,b'x'),lambda:os.ftruncate(target,0)):
            with pytest.raises(PermissionError):mutation()
        assert hashlib.sha256(selected.read_bytes()).hexdigest()==snapshots.items[0][3]
    finally:snapshots.close()
    assert not selected.exists() and not snapshots.directory.exists()


@pytest.mark.parametrize('phase',['opened','copying','copied'])
@pytest.mark.parametrize('replacement',[False,True])
def test_mutation_is_atomic_refusal(tmp_path,phase,replacement):
    source=tmp_path/'mutable.txt';source.write_bytes(b'Q'*1500000)
    original=source.stat();mutated=False
    def checkpoint(at,path):
        nonlocal mutated
        if mutated or at!=phase:return
        mutated=True
        if replacement:
            temp=tmp_path/'replacement.txt';temp.write_bytes(b'Z'*original.st_size);os.replace(temp,source)
        else:source.write_bytes(b'Z'*original.st_size)
        os.utime(source,ns=(original.st_atime_ns,original.st_mtime_ns))
    snapshots=fs.Snapshots(tmp_path);retained=fs._retained
    try:
        with pytest.raises(ValueError,match='changed|replaced'):
            snapshots.stage([source],checkpoint=checkpoint)
        assert not snapshots.items and fs._retained==retained
    finally:snapshots.close()


@pytest.mark.parametrize('kind',['symlink','parentlink','fifo','directory','empty','unreadable','invalid','oversize','unsupported','private'])
def test_unsafe_selection_rejected(tmp_path,kind):
    source=tmp_path/'input.txt';source.write_text('Safe source')
    forbidden=()
    if kind=='symlink':
        link=tmp_path/'link.txt';link.symlink_to(source);source=link
    elif kind=='parentlink':
        parent=tmp_path/'linked';parent.symlink_to(tmp_path,target_is_directory=True);source=parent/'input.txt'
    elif kind=='fifo':source.unlink();os.mkfifo(source)
    elif kind=='directory':source.unlink();source.mkdir()
    elif kind=='empty':source.write_bytes(b'')
    elif kind=='unreadable':source.chmod(0)
    elif kind=='invalid':source=tmp_path/'bad.png';source.write_text('Not a PNG')
    elif kind=='oversize':
        with source.open('wb') as stream:stream.truncate(16*fs.MIB+1)
    elif kind=='unsupported':source=tmp_path/'unsafe.exe';source.write_bytes(b'X')
    elif kind=='private':forbidden=(tmp_path,)
    store=fs.Snapshots(tmp_path);before=fs._retained
    try:
        with pytest.raises((ValueError,OSError)):store.stage([source],forbidden=forbidden)
        assert not store.items and fs._retained==before
    finally:store.close()


def test_batch_order_all_or_nothing_cancel_quota(tmp_path,monkeypatch):
    a=tmp_path/'a.txt';b=tmp_path/'b.csv';a.write_bytes(b'A');b.write_bytes(b'B')
    store=fs.Snapshots(tmp_path)
    try:
        selected=store.stage([b,a]);assert [Path(x).read_bytes() for x in selected]==[b'B',b'A']
        before=fs._retained
        with pytest.raises(ValueError):store.stage([a,tmp_path/'bad.exe'])
        assert len(store.items)==2 and fs._retained==before
        with pytest.raises(ValueError,match='canceled'):store.stage([a],valid=lambda:False)
        monkeypatch.setattr(fs,'PAGE_LIMIT',2)
        with pytest.raises(ValueError,match='page limit'):store.stage([a])
        monkeypatch.setattr(fs,'PAGE_LIMIT',1024)
        monkeypatch.setattr(fs,'PROCESS_LIMIT',before)
        with pytest.raises(ValueError,match='Too much'):store.stage([a])
    finally:store.close()


@pytest.mark.parametrize('suffix,payload',[('.zip',b'PKbroken'),('.pdf',b'not pdf'),('.png',b'not image')])
def test_invalid_types_refused(tmp_path,suffix,payload):
    source=tmp_path/('bad'+suffix);source.write_bytes(payload);store=fs.Snapshots(tmp_path)
    try:
        with pytest.raises(ValueError):store.stage([source])
    finally:store.close()


def test_staging_failure_releases_all(tmp_path,monkeypatch):
    source=tmp_path/'file.txt';source.write_text('accepted format');store=fs.Snapshots(tmp_path);before=fs._retained
    monkeypatch.setattr(fs.os,'write',lambda *a: (_ for _ in ()).throw(OSError('synthetic write failure')))
    try:
        with pytest.raises(OSError,match='synthetic'):store.stage([source])
        assert not store.items and fs._retained==before
    finally:store.close()


def test_cleanup_failure_still_releases_every_descriptor(tmp_path,monkeypatch):
    source=tmp_path/'a.txt';source.write_text('A');store=fs.Snapshots(tmp_path)
    paths=store.stage([source,source]);fds=[x[0] for x in store.items];before=fs._retained
    original=Path.unlink
    def fail_one(path,*a,**kw):
        if str(path)==paths[0]:raise PermissionError('bounded cleanup failure')
        return original(path,*a,**kw)
    monkeypatch.setattr(Path,'unlink',fail_one)
    store.close()
    assert fs._retained==before-2 and store.closed and not store.items
    for fd in fds:
        with pytest.raises(OSError):os.fstat(fd)
    assert Path(paths[0]).is_symlink(),'Unexpected cleanup evidence remains, never followed'


def test_read_limit_and_cancel(tmp_path):
    path=tmp_path/'source.txt';path.write_bytes(b'1234567');fd=os.open(path,os.O_RDONLY)
    try:
        with pytest.raises(ValueError):fs._hash(fd,3,lambda:True)
        with pytest.raises(ValueError):fs._hash(fd,7,lambda:False)
    finally:os.close(fd)


def test_gif_allowed_and_batch_discard_retains_existing(tmp_path):
    from PIL import Image
    image=tmp_path/'logo.gif';Image.new('RGB',(5,5),'cyan').save(image)
    store=fs.Snapshots(tmp_path)
    try:
        first=store.stage([image]);second=store.stage([image]);store.discard(second)
        assert Path(first[0]).read_bytes()==image.read_bytes() and not Path(second[0]).exists()
        assert len(store.items)==1
    finally:store.close()


def test_retained_file_count_limit(tmp_path,monkeypatch):
    p=tmp_path/'file.txt';p.write_text('A');store=fs.Snapshots(tmp_path)
    try:
        monkeypatch.setattr(fs,'MAX_RETAINED_FILES',1);store.stage([p])
        with pytest.raises(ValueError,match='Too many selected files'):store.stage([p])
    finally:store.close()


@pytest.mark.parametrize('method',['switch_to_local','switch_to_server'])
def test_mode_switch_refused_before_retirement_while_dialog_open(method):
    from types import SimpleNamespace
    from desktop.shell import DesktopWindow
    calls=[]
    owner=SimpleNamespace(_browser_dialog_depth=1,_switch_refusal=lambda message:calls.append(message) or False)
    assert getattr(DesktopWindow,method)(owner) is False
    assert 'dialog' in calls[0]


@pytest.mark.parametrize('replace',[False,True])
def test_selected_identity_cannot_change_before_worker_starts(tmp_path,replace):
    p=tmp_path/'selected.txt';p.write_bytes(b'Original')
    fd,initial=fs.open_source(p);os.close(fd)
    if replace:
        changed=tmp_path/'new.txt';changed.write_bytes(b'Changed!');os.replace(changed,p)
    else:p.write_bytes(b'Changed!')
    os.utime(p,ns=(initial.st_atime_ns,initial.st_mtime_ns))
    store=fs.Snapshots(tmp_path)
    try:
        with pytest.raises(ValueError,match='after selection'):store.stage([p],expected=[fs._identity(initial)])
        assert not store.items
    finally:store.close()


def test_hardlinks_refused(tmp_path):
    p=tmp_path/'source.txt';p.write_text('Private bytes');other=tmp_path/'other.txt';os.link(p,other)
    with pytest.raises(ValueError,match='hard links'):fs.open_source(other)

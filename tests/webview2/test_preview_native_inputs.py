"""The preview may not take same-name OpenSSL/CRT DLLs from the host."""
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import zipfile

import pytest

from package_windows_webview2.native_inputs import materialize, verify_collected


def test_collected_root_is_exact_producer_and_bytes(tmp_path):
    pinned = tmp_path/'pinned';pinned.mkdir()
    expected = pinned/'libssl-3-x64.dll';expected.write_bytes(b'pinned producer')
    record = {'file':expected.name,'sha256':hashlib.sha256(expected.read_bytes()).hexdigest()}
    verify_collected([(expected.name,str(expected),'BINARY')],pinned,[record])
    ambient = tmp_path/expected.name;ambient.write_bytes(expected.read_bytes())
    with pytest.raises(ValueError,match='Unpinned'):
        verify_collected([(expected.name,str(ambient),'BINARY')],pinned,[record])
    expected.write_bytes(b'changed')
    with pytest.raises(ValueError,match='bytes changed'):
        verify_collected([(expected.name,str(expected),'BINARY')],pinned,[record])


@pytest.mark.skipif(sys.version_info < (3,14),reason='Windows preview producer extraction uses verified CPython3.14 stdlib zstd')
@pytest.mark.parametrize('failure',[None,'digest','missing','link','duplicate'])
def test_archive_members_are_bound_not_extracted_by_path(tmp_path,failure):
    from compression.zstd import compress
    from package_windows_webview2.native_inputs import MEMBERS
    pins=[]
    for package,members in MEMBERS.items():
        buffer=io.BytesIO()
        with tarfile.open(fileobj=buffer,mode='w') as payload:
            for index,name in enumerate(members):
                if failure=='missing' and package=='openssl' and index==0:continue
                for _ in range(2 if failure=='duplicate' and index==0 else 1):
                    item=tarfile.TarInfo(name);data=name.encode();item.size=len(data)
                    if failure=='link' and package=='openssl' and index==0:
                        item.type=tarfile.SYMTYPE;item.linkname='outside';item.size=0
                    payload.addfile(item,io.BytesIO(data))
        archive=tmp_path/(package+'.conda')
        with zipfile.ZipFile(archive,'x') as container:
            container.writestr('pkg-'+package+'.tar.zst',compress(buffer.getvalue()))
        pins.append({'name':package,'url':'https://synthetic.invalid/'+archive.name,
                     'sha256':hashlib.sha256(archive.read_bytes()).hexdigest()})
    if failure=='digest':pins[0]['sha256']='0'*64
    lock=tmp_path/'lock.json';lock.write_text(json.dumps({'packages':pins}))
    target=tmp_path/'bound'
    if failure:
        with pytest.raises((ValueError,FileExistsError)):
            materialize(tmp_path,target,lock)
    else:
        records=materialize(tmp_path,target,lock)
        assert {p.name for p in target.iterdir()}=={Path(name).name for names in MEMBERS.values() for name in names}
        for record in records:
            assert (target/record['file']).read_bytes()==record['member'].encode()

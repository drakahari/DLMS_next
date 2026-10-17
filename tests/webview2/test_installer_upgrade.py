"""Cross-version installer binding refusal before execution; no installer runs."""
import hashlib
import json
import os

import pytest

from package_windows_webview2 import qualify_installer as q

@pytest.mark.skipif(os.name!='nt',reason='Native Windows candidate path validation')
def test_distinct_candidate_inventories_and_scope_validation(tmp_path,monkeypatch):
    monkeypatch.setattr(q,'WORK',tmp_path)
    for name,digest in (('old06','a'*64),('new15','b'*64)):
        root=tmp_path/name;root.mkdir()
        (root/'payload-inventory.json').write_text(json.dumps([{'path':'app.exe','sha256':digest}]))
    old_path,old=q.candidate_inventory('old06');new_path,new=q.candidate_inventory('new15')
    assert old_path!=new_path and old!=new
    for name in ('../old06','old06/subfolder',''):
        with pytest.raises(ValueError):q.candidate_inventory(name)

@pytest.mark.parametrize('changed',[{}, {'isolated_variant':False},
    {'payload_inventory_sha256':'0'*64},{'release':'different'}, {'sha256':'0'*64}])
def test_variant_matches_exact_cross_version_payload_before_execution(tmp_path,monkeypatch,changed):
    monkeypatch.setattr(q,'WORK',tmp_path)
    folder=tmp_path/'installer';folder.mkdir();exe=folder/'setup.exe';exe.write_bytes(b'inert synthetic fixture')
    inventory=tmp_path/'inventory.json';inventory.write_text('[]')
    row={'file':exe.name,'isolated_variant':True,'sha256':hashlib.sha256(exe.read_bytes()).hexdigest(),
        'application':'DLMSDesktopWebView2Candidate','release':'old06',
        'payload_inventory_sha256':hashlib.sha256(inventory.read_bytes()).hexdigest()}
    (folder/'artifacts.json').write_text(json.dumps([row|changed]))
    if changed:
        with pytest.raises(ValueError,match='Only an unchanged'):q.variant(exe,'old06',inventory)
    else:assert q.variant(exe,'old06',inventory)==exe

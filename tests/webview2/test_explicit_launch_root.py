"""Real explicit-root preconditions; no browser, adoption or backend is started."""
import json
import os
from pathlib import Path
import sys
import types

import pytest

pytestmark=pytest.mark.skipif(os.name!='nt',reason='Native Windows explicit-root guard')

@pytest.mark.parametrize('state',['missing','unmarked','marked'])
def test_explicit_walkthrough_root_requires_prior_private_marking(tmp_path,monkeypatch,state):
    from package_windows import entry
    payload=tmp_path/'Synthetic payload';payload.mkdir(mode=0o700)
    root=tmp_path/'Synthetic walkthrough 日本語';sentinel=root/'preserve.txt'
    if state!='missing':
        root.mkdir(mode=0o700);sentinel.write_bytes(b'preserve synthetic evidence')
    if state=='marked':(root/entry.MARKER).write_text(json.dumps(entry.IDENTITY))
    calls=[]
    module=types.ModuleType('desktop.__main__')
    module.main=lambda argv:calls.append(argv) or 41
    monkeypatch.setitem(sys.modules,'desktop.__main__',module)
    monkeypatch.setattr(sys,'executable',str(payload/'DLMS-Desktop-WebView2.exe'))
    monkeypatch.setattr(sys,'argv',[sys.executable,'--data-root',str(root),'--profile','walkexam'])
    for name in ('DLMS_DESKTOP_DATA_ROOT','DLMS_DESKTOP_ROOT_KIND'):
        monkeypatch.setenv(name,'unused test value')
    if state=='missing':
        with pytest.raises(FileNotFoundError) as caught:entry.main()
        assert caught.value.winerror==2 and not root.exists() and calls==[]
    elif state=='unmarked':
        with pytest.raises(ValueError,match='marker is missing or invalid'):entry.main()
        assert not (root/entry.MARKER).exists() and calls==[]
    else:
        assert entry.main()==41 and calls==[['--profile','walkexam']]
        assert Path(os.environ['DLMS_DESKTOP_DATA_ROOT'])==root
    if state!='missing':assert sentinel.read_bytes()==b'preserve synthetic evidence'

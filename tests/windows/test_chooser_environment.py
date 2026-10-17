import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

@pytest.mark.skipif(os.name!='nt',reason='Windows shell places')
def test_scoped_shell_places_are_private_and_reparse_points_refused(tmp_path):
    from desktop.windows_home import prepare
    from desktop.windows_files import owned
    import subprocess
    home=tmp_path/'scoped home 日本語';home.mkdir(mode=0o700)
    prepare(home)
    for name in ('Desktop','Documents','Downloads','Pictures','Music','Videos'):
        assert (home/name).is_dir();owned(home/name,private=True)
    (home/'Desktop').rmdir()
    outside=tmp_path/'outside';outside.mkdir()
    subprocess.run(['cmd.exe','/c','mklink','/J',str(home/'Desktop'),str(outside)],capture_output=True,check=True)
    try:
        with pytest.raises(ValueError,match='reparse'):prepare(home)
        assert not list(outside.iterdir())
    finally:(home/'Desktop').rmdir()

def test_frozen_fixture_start_and_upload_boundary(tmp_path,monkeypatch):
    import desktop.shell as shell
    from PySide6.QtWebEngineCore import QWebEnginePage
    fixture=tmp_path/'payload/fixtures';fixture.mkdir(parents=True)
    allowed=fixture/'neutral.txt';allowed.write_text('synthetic')
    outside=tmp_path/'repository/fixtures/neutral.txt';outside.parent.mkdir(parents=True);outside.write_text('synthetic')
    area=tmp_path/'data';area.mkdir()
    monkeypatch.setattr(shell,'PROJECT',fixture.parent);monkeypatch.setattr(shell,'AREA',area);monkeypatch.setattr(shell,'FROZEN',True)
    assert shell.upload_start_directory()==fixture if os.name=='nt' else shell.upload_start_directory()==area
    messages=[];blocked=[]
    owner=SimpleNamespace(file_selection_for_test=None,note_blocked=blocked.append,
                          statusBar=lambda:SimpleNamespace(showMessage=messages.append))
    page=SimpleNamespace(owner=owner)
    method=shell.LocalPage.chooseFiles.__wrapped__
    for selected,expected in ((allowed,[str(allowed)]),(outside,[])):
        monkeypatch.setattr(shell.QFileDialog,'getOpenFileName',lambda *a,**kw:(str(selected),''))
        assert method(page,QWebEnginePage.FileSelectionMode.FileSelectOpen,[],[])==expected
    assert len(blocked)==1 and messages

def test_diagnostic_option_keeps_strict_launch_binding(tmp_path):
    from desktop.ownership import windows_launch_matches
    args=['app','--profile','test','--data-root',str(tmp_path),'--capture-window-events']
    assert windows_launch_matches(args,'test',tmp_path,tmp_path)
    for extra in (['--capture-window-events'],['--capture-window-events=1'],['--other'],['--profile=test']):
        assert not windows_launch_matches(args+extra,'test',tmp_path,tmp_path)

def test_document_probe_accepts_no_text_urls_or_arbitrary_payload():
    from desktop.window_events import document_sample
    valid={'epoch':123.5,'ready':'complete','visibility':'visible','navigation':'reload'}
    assert document_sample(json.dumps(valid))==valid
    for key,value in (('epoch',float('nan')),('epoch',True),('ready','private question text'),
                      ('navigation','https://example.invalid/secret'),('cookie','secret')):
        assert document_sample(json.dumps(valid|{key:value})) is None

from pathlib import Path
from types import SimpleNamespace as NS
import hashlib,json,os
import pytest
from PySide6.QtCore import QUrl
from desktop import export_output as output
from desktop import exports,external_browser
from desktop.ai_actions import approved,PROVIDERS

@pytest.mark.parametrize('url',sorted(PROVIDERS))
def test_approved_exact_roots(url):assert approved(QUrl(url))

@pytest.mark.parametrize('url',['http://chatgpt.com/','https://chatgpt.com/?prompt=x','https://chatgpt.com/#x',
 'https://chatgpt.com/extra','https://chatgpt.com:8443/','https://user@chatgpt.com/',
 'https://chatgpt.com.evil.invalid/','https://claude.ai.evil.invalid/','file:///tmp/x','javascript:alert(1)'])
def test_unapproved_targets(url):assert not approved(QUrl(url))

@pytest.mark.parametrize('extension',['.txt','.pdf','.zip','.apkg','.png','.json'])
def test_publication_exact_bytes_collision_and_source_preserved(tmp_path,extension):
 source=tmp_path/'private';source.write_bytes(b'bounded fixture bytes\0'*10)
 target=tmp_path/('output space é'+extension);selected=output.select(target)
 result=output.publish(source,selected)
 assert target.read_bytes()==source.read_bytes() and result['sha256']==hashlib.sha256(source.read_bytes()).hexdigest()
 with pytest.raises(FileExistsError):output.select(target)
 assert target.read_bytes()==source.read_bytes()

@pytest.mark.parametrize('phase',['copy','before_publish','published'])
def test_publication_fault_keeps_existing_data_and_truthful_outcome(tmp_path,phase):
 source=tmp_path/'source';source.write_bytes(b'original')
 unrelated=tmp_path/'unrelated.txt';unrelated.write_bytes(b'keep')
 target=tmp_path/'out.txt';selected=output.select(target)
 def fail(at):
  if at==phase:raise OSError('synthetic publication interruption')
 with pytest.raises((OSError,RuntimeError)):output.publish(source,selected,checkpoint=fail)
 assert unrelated.read_bytes()==b'keep' and source.read_bytes()==b'original'
 assert target.exists()==(phase=='published')
 if target.exists():assert target.read_bytes()==b'original'


def test_folder_path_substitution_and_existing_leaf_refused(tmp_path):
 source=tmp_path/'source';source.write_bytes(b'original')
 folder=tmp_path/'folder';folder.mkdir();other=tmp_path/'other';other.mkdir()
 selected=output.select(folder/'file.txt');folder.rename(tmp_path/'old');folder.symlink_to(other,target_is_directory=True)
 with pytest.raises((OSError,ValueError)):output.publish(source,selected)
 assert not (other/'file.txt').exists()


def test_folder_preference_scoped_and_invalid_fallback(tmp_path,monkeypatch):
 private=tmp_path/'profile';private.mkdir(mode=0o700)
 ordinary=tmp_path/'Visible Folder é';ordinary.mkdir()
 owner=NS(mode='local',paths={'root':private},manifest={'uuid':'fixture-uuid','epoch':'first'},_documents_folder=lambda:tmp_path)
 monkeypatch.setattr(exports,'forbidden',lambda:())
 exports.remember(owner,ordinary);assert exports.initial(owner)==(ordinary,'')
 owner.manifest['epoch']='second';start,warning=exports.initial(owner);assert start==tmp_path and warning
 owner.mode='server';owner.server_paths={'root':private};owner.mode_config={'server':{'id':'server01','origin':'https://synthetic.invalid'}}
 assert exports.initial(owner)[1]



def test_generic_browser_oserror_visible_and_modal_owned(monkeypatch):
 from PySide6.QtWidgets import QMessageBox
 from desktop.shell import DesktopWindow
 messages=[]
 from tests.session_browser.test_contract import owner as make_owner
 owner,bar=make_owner();owner.note_blocked=lambda url:None
 monkeypatch.setattr(QMessageBox,'question',lambda *a:QMessageBox.StandardButton.Yes)
 def fail(url):
  assert owner._browser_dialog_depth==1
  raise OSError('Task-only opener failure')
 monkeypatch.setattr('desktop.shell.dispatch_external',fail)
 monkeypatch.setattr(QMessageBox,'warning',lambda *a:messages.append(a[2]))
 DesktopWindow.open_external(owner,QUrl('https://example.invalid/'))
 assert messages==['Task-only opener failure'] and owner._browser_dialog_depth==0

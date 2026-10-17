import json, os, time
from types import SimpleNamespace
import pytest
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication, QMainWindow
from desktop.mix_diagnostics import MixDiagnostics, sanitized, INSTALL, READ

@pytest.fixture(scope="module")
def application():
    app=QApplication.instance() or QApplication([])
    yield app

def snapshot():
    return dict(version=1,timeOrigin=123,elapsed=2,counts=dict(total=6000,shown=250,checked=50,hiddenChecked=50,displayed=50),events=[],dropped=0,active=True)

def test_allowlist_drops_remote_secrets():
    value=snapshot();value.update(url="secret",cookie="secret",question="secret")
    value["counts"]["ids"]=["secret"]
    assert "secret" not in json.dumps(sanitized(value))
    assert "timeOrigin" not in sanitized(value)

@pytest.mark.parametrize("field,value",[("elapsed",float("nan")),("elapsed",-1),("events",[{}]*65),("version",2)])
def test_invalid_or_unbounded_snapshot(field,value):
    data=snapshot();data[field]=value
    with pytest.raises(ValueError):sanitized(data)

from PySide6.QtCore import QObject
class Page(QObject):
    def __init__(self):super().__init__();self.calls=[]
    def url(self):return QUrl("http://127.0.0.2:9090/quiz-composer")
    def runJavaScript(self,*args):self.calls.append(args)

def owner(root):
    w=QMainWindow();p=Page();w.view=SimpleNamespace(page=lambda:p)
    w.owner_root=root;w._server_navigation_serial=3;w._browser_generation=2
    w.mode_config={"server":{"origin":"http://127.0.0.2:9090"}}
    w.mode="server";w._closing=False;w._retiring_browser=None;w._server_page_exposed=True
    w._server_document_identity=(p.url().toString(),123)
    return w,p

def test_late_callbacks_and_document_binding(application,tmp_path):
    w,p=owner(tmp_path);c=MixDiagnostics(w)
    assert not os.get_inheritable(c.resource["fd"])
    c.installed(json.dumps(dict(installed=True,timeOrigin=123)))
    assert p.calls[-1][0]==c.script(READ)
    callback=p.calls[-1][-1];w._server_navigation_serial+=1
    callback(json.dumps(snapshot()))
    assert c.stopped and c.path.read_bytes()==b"" and not c.resource
    callback(json.dumps(snapshot()))
    assert c.path.read_bytes()==b""

def test_stale_snapshot_and_timeout_while_install_hung(application,tmp_path):
    w,p=owner(tmp_path);c=MixDiagnostics(w)
    c.started=time.monotonic()-61;c.poll()
    assert c.stopped and not c.resource
    c.installed(json.dumps(dict(installed=True,timeOrigin=123)))
    assert c.path.read_bytes()==b""
    d=MixDiagnostics(w);d.installed(json.dumps(dict(installed=True,timeOrigin=123)))
    value=snapshot();value["timeOrigin"]=124;p.calls[-1][-1](json.dumps(value))
    assert d.stopped and d.path.read_bytes()==b""

def test_private_storage_and_write_failure(application,tmp_path,monkeypatch):
    w,p=owner(tmp_path);c=MixDiagnostics(w);c.installed(json.dumps(dict(installed=True,timeOrigin=123)))
    def fail(*args):raise OSError("simulated")
    monkeypatch.setattr(os,"write",fail);p.calls[-1][-1](json.dumps(snapshot()))
    assert c.stopped and not c.resource
    if os.name=='nt':
        from desktop.platform_files import owned
        assert owned(c.path,private=True)
    else:assert c.path.stat().st_mode&0o777==0o600

@pytest.mark.skipif(os.name=='nt',reason='POSIX symlink/permission fixtures; Windows ACL/reparse checks use native tests')
def test_symlink_or_public_storage_refused(application,tmp_path):
    w,p=owner(tmp_path);other=tmp_path/"other";other.mkdir()
    (tmp_path/"mix-diagnostics").symlink_to(other,target_is_directory=True)
    with pytest.raises(ValueError):MixDiagnostics(w)
    (tmp_path/"mix-diagnostics").unlink();(tmp_path/"mix-diagnostics").mkdir(mode=0o755)
    with pytest.raises(ValueError):MixDiagnostics(w)


@pytest.mark.skipif(os.name!='nt',reason='Windows directory pinning/ACL boundary')
def test_windows_private_storage_requires_native_owner_validation(application,tmp_path,monkeypatch):
    from desktop import windows_files
    w,p=owner(tmp_path)
    def refuse(*args,**kwargs):raise ValueError('Synthetic untrusted ACL')
    monkeypatch.setattr(windows_files,'owned',refuse)
    with pytest.raises(ValueError,match='untrusted ACL'):MixDiagnostics(w)
    assert not list((tmp_path/'mix-diagnostics').iterdir())


@pytest.mark.skipif(os.name!='nt',reason='Windows inherited child-file DACL boundary')
def test_windows_file_inheriting_public_grant_is_refused_before_write(application,tmp_path,monkeypatch):
    from desktop import windows_files
    w,p=owner(tmp_path);checks=[];fds=[];native_open=os.open
    def ownership(path,**kwargs):
        checks.append(path)
        # Simulate a grant that is INHERIT_ONLY on the directory and becomes
        # effective on its child; no host/test ACL or security setting changes.
        if path.suffix=='.jsonl':raise ValueError('Synthetic inherited public file DACL')
    def opened(*args,**kwargs):
        fd=native_open(*args,**kwargs);fds.append(fd);return fd
    monkeypatch.setattr(windows_files,'owned',ownership);monkeypatch.setattr(os,'open',opened)
    with pytest.raises(ValueError,match='inherited public file DACL'):MixDiagnostics(w)
    assert checks[0].name=='mix-diagnostics' and checks[1].suffix=='.jsonl'
    assert not p.calls and len(fds)==1
    with pytest.raises(OSError):os.fstat(fds[0])
    assert checks[1].read_bytes()==b''

def test_collector_is_application_world_read_only_and_bounded():
    assert "fetch(" not in INSTALL and "dispatchEvent" not in INSTALL
    assert "setInterval" not in INSTALL and "60000" in INSTALL and "events.length===64" in INSTALL
    assert "getComputedStyle" not in INSTALL and "getBoundingClientRect" not in INSTALL


def test_js_binding_cleanup_token_and_deferred_tasks(application,tmp_path):
    from desktop.mix_diagnostics import CLEANUP
    w,p=owner(tmp_path);a=MixDiagnostics(w);b=MixDiagnostics(w)
    assert a.token!=b.token and a.script(CLEANUP)!=b.script(CLEANUP)
    assert a.url in a.script(INSTALL) and str(a.document[1]) in a.script(INSTALL)
    assert "queueMicrotask" not in INSTALL and "deferred-after-event" in INSTALL
    a.stop("stop old");b.stop("stop new")

def test_late_read_deadline_does_not_append(application,tmp_path):
    w,p=owner(tmp_path);c=MixDiagnostics(w);c.installed(json.dumps(dict(installed=True,timeOrigin=123)))
    callback=p.calls[-1][-1];c.started=time.monotonic()-61;callback(json.dumps(snapshot()))
    assert c.stopped and c.path.read_bytes()==b""

def test_native_action_has_no_page_bridge_and_rechecks_consent():
    from pathlib import Path
    s=Path("desktop/shell.py").read_text();action=s.split("def _capture_mix_diagnostics(self):",1)[1].split("def _about_text",1)[0]
    assert "context!=" in action and "QMessageBox.StandardButton.Cancel" in action
    assert "@browser_operation\n    def _capture_mix_diagnostics" in s


def test_template_does_not_reprocess_inserted_url(application,tmp_path):
    w,p=owner(tmp_path);c=MixDiagnostics(w)
    c.url="http://127.0.0.2:9090/quiz-composer?x=CAPTURE_TOKEN&y=EXPECTED_ORIGIN"
    assert "location.href!=="+json.dumps(c.url) in c.script(INSTALL)
    c.stop("done")


@pytest.mark.parametrize("change",["generation","closing","view","document"])
def test_consent_revalidates_context(application,tmp_path,monkeypatch,change):
    from desktop.shell import DesktopWindow
    from PySide6.QtWidgets import QMessageBox
    w,p=owner(tmp_path);p.isLoading=lambda:False;w.view.url=p.url;w.mix_diagnostics=None;w.mix_diagnostic_action=object()
    def consent(*args):
        assert w._browser_operation_depth==1
        if change=="generation":w._browser_generation+=1
        elif change=="closing":w._closing=True
        elif change=="view":w.view=None
        else:w._server_document_identity=(p.url().toString(),124)
        return QMessageBox.StandardButton.Yes
    monkeypatch.setattr(QMessageBox,"question",consent)
    import desktop.mix_diagnostics as module
    def rejected(*args):raise AssertionError("Must not start capture after context changed")
    monkeypatch.setattr(module,"MixDiagnostics",rejected)
    DesktopWindow._capture_mix_diagnostics(w)
    assert w._browser_operation_depth==0 and w.mix_diagnostics is None

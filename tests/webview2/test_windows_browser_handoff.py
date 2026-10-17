"""Association transport does not mutate/forward the application's environment."""
import os
from pathlib import Path
from types import SimpleNamespace
import subprocess

import pytest
from PySide6.QtCore import QUrl

from desktop import windows_browser_handoff as handoff

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Windows association helper')

def context(monkeypatch):
    from desktop import webview2_browser
    monkeypatch.setattr(webview2_browser, 'host_executable', lambda: Path('C:/safe/Host.exe'))
    monkeypatch.setattr(handoff, 'helper_context', lambda: (Path('C:/Windows/System32'),
        {'SystemRoot':'C:/Windows','WINDIR':'C:/Windows','PATH':'C:/Windows/System32'}))


def test_only_confirmed_encoded_url_crosses_private_helper_stdin(monkeypatch):
    context(monkeypatch)
    for name in ('USERPROFILE','HOME','APPDATA','LOCALAPPDATA','DLMS_DESKTOP_NONCE','PYTHONPATH','WEBVIEW2_BROWSER_EXECUTABLE_FOLDER'):
        monkeypatch.setenv(name,'synthetic-private-do-not-inherit')
    before=dict(os.environ)
    calls=[]
    def run(argv, **kwargs):
        calls.append((argv,kwargs));return SimpleNamespace(returncode=0,stdout=b'accepted\r\n',stderr=b'')
    monkeypatch.setattr(handoff.subprocess,'run',run)
    url=QUrl('https://example.invalid/日本語?q=a%20b')
    assert handoff.dispatch(url)
    argv,kwargs=calls[0]
    assert argv==[str(Path('C:/safe/Host.exe')),'--external-browser']
    assert kwargs['input']==bytes(url.toEncoded())+b'\n'
    assert set(kwargs['env'])=={'SystemRoot','WINDIR','PATH'}
    assert kwargs['close_fds'] and kwargs['timeout']==10
    assert kwargs['cwd']==Path('C:/Windows/System32')
    assert kwargs['creationflags']==subprocess.CREATE_NO_WINDOW
    assert dict(os.environ)==before


@pytest.mark.parametrize('url',['file:///C:/Windows/notepad.exe','javascript:alert(1)','ms-settings:defaultapps','https://u:p@example.invalid/','https://localhost/','http://127.0.0.1/','http://a.localhost/'])
def test_invalid_schemes_credentials_and_local_authority_never_start_helper(monkeypatch,url):
    monkeypatch.setattr(handoff.subprocess,'run',lambda *a,**k:pytest.fail('Invalid external launch'))
    with pytest.raises(ValueError):handoff.dispatch(QUrl(url))


@pytest.mark.parametrize('stdout,code',[(b'',0),(b'accepted\r\n',3),(b'accepted\n',0),(b'wrong',0)])
def test_no_fallback_or_retry_on_unconfirmed_activation(monkeypatch,stdout,code):
    context(monkeypatch);calls=[]
    monkeypatch.setattr(handoff.subprocess,'run',lambda *a,**k:calls.append(1) or SimpleNamespace(returncode=code,stdout=stdout))
    with pytest.raises(handoff.HandoffUnconfirmed):handoff.dispatch(QUrl('https://example.invalid/'))
    assert calls==[1]


def test_timeout_does_not_retry_or_claim_nothing_opened(monkeypatch):
    context(monkeypatch);calls=[]
    def timeout(*a,**k):
        calls.append(1);raise subprocess.TimeoutExpired(a[0],10)
    monkeypatch.setattr(handoff.subprocess,'run',timeout)
    with pytest.raises(handoff.HandoffUnconfirmed,match='check your browser before retrying'):
        handoff.dispatch(QUrl('https://example.invalid/'))
    assert calls==[1]


def test_slow_helper_keeps_native_event_loop_responsive(monkeypatch):
    from PySide6.QtCore import QCoreApplication,QTimer
    import time
    app=QCoreApplication.instance() or QCoreApplication([])
    context(monkeypatch);ticks=[]
    def slow(*a,**k):
        time.sleep(.15);return SimpleNamespace(returncode=0,stdout=b'accepted\r\n')
    monkeypatch.setattr(handoff.subprocess,'run',slow)
    timer=QTimer();timer.timeout.connect(lambda:ticks.append(1));timer.start(10)
    try:assert handoff.dispatch(QUrl('https://example.invalid/'))
    finally:timer.stop()
    assert len(ticks)>=5


@pytest.mark.parametrize('active,uri,use_helper',[
    (True,'https://example.invalid/',True),
    (True,'http://example.invalid/',True),
    (False,'https://example.invalid/',False),
    (True,'file:///C:/synthetic-backup-folder',False)])
def test_only_webview2_http_links_change_dispatch_mechanism(monkeypatch,active,uri,use_helper):
    from desktop import shell,package_entry,webview2_runtime
    calls=[]
    monkeypatch.setattr(package_entry,'_seal_private_descriptors',lambda:calls.append('seal'))
    monkeypatch.setattr(webview2_runtime,'active',lambda:active)
    monkeypatch.setattr(handoff,'dispatch',lambda url:calls.append('helper') or True)
    monkeypatch.setattr(shell.QDesktopServices,'openUrl',lambda url:calls.append('qt') or True)
    assert shell.dispatch_external(QUrl(uri))
    assert calls==['seal','helper' if use_helper else 'qt']

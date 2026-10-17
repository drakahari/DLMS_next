from types import SimpleNamespace
import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from shiboken6 import isValid
from desktop.browser_lifetime import BrowserRetirement, browser_dialog
from desktop.shell import DesktopWindow

APP = None


def app():
    global APP
    APP = QApplication.instance() or QApplication([])
    return APP


def test_page_and_view_destroy_before_profile(tmp_path):
    app()
    owner = QWidget()
    profile = QWebEngineProfile('retirement-test', owner)
    profile.setPersistentStoragePath(str(tmp_path/'storage'))
    profile.setCachePath(str(tmp_path/'cache'))
    view = QWebEngineView(owner)
    page = QWebEnginePage(profile, view)
    view.setPage(page)
    retirement = BrowserRetirement(view, profile, owner)
    loop = QEventLoop()
    retirement.finished.connect(loop.quit)
    timeout = QTimer(loop); timeout.setSingleShot(True); timeout.timeout.connect(loop.quit)
    timeout.start(4000)
    retirement.start(); retirement.start()  # Duplicate scheduling is harmless.
    loop.exec(); timeout.stop()
    assert retirement.done
    assert sorted(retirement.events) == ['page', 'profile', 'view']
    assert retirement.events[-1] == 'profile'
    assert not isValid(page) and not isValid(view) and not isValid(profile)
    owner.deleteLater()


def test_reentrant_close_does_not_enter_cleanup_twice():
    calls = []
    event = SimpleNamespace(ignore=lambda: calls.append('ignored'), accept=lambda: calls.append('accepted'))
    window = SimpleNamespace(_close_complete=False, _close_active=False,
                             _browser_dialog_depth=0, _close_after_dialog=False)
    def cleanup(ev):
        calls.append('cleanup')
        DesktopWindow.closeEvent(window, ev)
    window._close_event_impl = cleanup
    DesktopWindow.closeEvent(window, event)
    assert calls == ['cleanup', 'ignored']
    assert not window._close_active


def test_close_waits_until_browser_dialog_returns():
    app()
    calls = []
    owner = SimpleNamespace(_browser_dialog_depth=0, _close_after_dialog=True,
                            close=lambda: calls.append('close'))
    with browser_dialog(owner):
        assert owner._browser_dialog_depth == 1
        APP.processEvents()
        assert not calls
    assert not calls
    APP.processEvents()
    assert calls == ['close'] and not owner._close_after_dialog


def test_late_javascript_callback_cannot_touch_expired_wait(monkeypatch):
    app()
    callbacks = []
    page = SimpleNamespace(runJavaScript=lambda script, callback: callbacks.append(callback))
    view = SimpleNamespace(page=lambda: page)
    owner = SimpleNamespace(view=view, _browser_generation=1)
    monkeypatch.setattr('shiboken6.isValid', lambda obj: True)
    result = DesktopWindow._evaluate_browser(owner, '42', 1)
    assert not result['done']
    owner.view = None; owner._browser_generation += 1
    callbacks[0](42)
    assert not result['done'] and result['value'] is None


@pytest.mark.parametrize('flag', ['_browser_operation_depth', '_settings_action_busy', '_retirement_wait_active'])
def test_close_refuses_nonclose_transition_without_releasing_ownership(flag):
    calls=[]
    owner=SimpleNamespace(_close_complete=False,_close_active=False,_browser_dialog_depth=0,
        statusBar=lambda: SimpleNamespace(showMessage=lambda msg:calls.append(msg)),
        _close_event_impl=lambda event:calls.append('UNSAFE cleanup'))
    setattr(owner,flag,True)
    event=SimpleNamespace(ignore=lambda:calls.append('ignored'),accept=lambda:calls.append('accepted'))
    DesktopWindow.closeEvent(owner,event)
    assert calls[-1]=='ignored' and 'UNSAFE cleanup' not in calls


@pytest.mark.parametrize('closing,retiring',[(True,None),(False,object())])
def test_late_dialog_during_close_preserves_notice_and_refuses_confirmation(closing,retiring):
    from desktop.browser_lifetime import OwnedPage
    messages=[]
    owner=SimpleNamespace(_closing=closing,_retiring_browser=retiring,close_browser_notices=[],
        statusBar=lambda:SimpleNamespace(showMessage=messages.append))
    page=SimpleNamespace(owner=owner)
    page._closing_notice=lambda msg:OwnedPage._closing_notice(page,msg)
    assert OwnedPage.javaScriptAlert(page,None,'Shutdown notice') is None
    assert OwnedPage.javaScriptConfirm(page,None,'Delete?') is False
    assert OwnedPage.javaScriptPrompt(page,None,'Password?','')==(False,'')
    assert len(messages)==3 and len(owner.close_browser_notices)==3
    assert all('no save success implied' in msg for msg in messages)


def test_file_chooser_close_is_deferred_until_page_virtual_returns():
    from desktop.browser_lifetime import browser_file_dialog
    app();calls=[]
    owner=SimpleNamespace(_closing=False,_browser_dialog_depth=0,_close_after_dialog=False,
        _close_complete=False,_close_active=False,close=lambda:calls.append('close'),
        statusBar=lambda:SimpleNamespace(showMessage=lambda msg:None))
    @browser_file_dialog
    def chooser(page):
        event=SimpleNamespace(ignore=lambda:calls.append('ignored'))
        DesktopWindow.closeEvent(owner,event)
        APP.processEvents()
        assert calls==['ignored']
        return []
    assert chooser(SimpleNamespace(owner=owner))==[]
    APP.processEvents()
    assert calls==['ignored','close']


def test_retained_retirement_allows_retry_after_wait_returns():
    calls=[]
    owner=SimpleNamespace(_close_complete=False,_close_active=False,_browser_dialog_depth=0,
        _retiring_browser=object(),_retirement_wait_active=False,_mode_switch_busy=True,
        _close_event_impl=lambda event:calls.append('retry'))
    DesktopWindow.closeEvent(owner,SimpleNamespace(ignore=lambda:calls.append('ignored')))
    assert calls==['retry']


def test_driver_navigation_waits_for_actual_qt_load_not_only_dom():
    from PySide6.QtCore import QObject,Signal,QUrl
    from tests.gate1.qt_checks import QtChecks
    app();events=[]
    class View(QObject):
        loadFinished=Signal(bool)
        current=QUrl('http://127.0.0.1:12345/')
        def url(self):return self.current
        def setUrl(self,url):
            self.current=url
            # URL changes before load completion; old implementation's DOM
            # predicate could already pass here. Only a real load event suffices.
            events.append('requested')
            QTimer.singleShot(1,lambda:(events.append('loaded'),self.loadFinished.emit(True)))
    view=View()
    def delay(seconds):APP.processEvents();loop=QEventLoop();QTimer.singleShot(5,loop.quit);loop.exec()
    def wait(expression):
        assert 'loaded' in events
        events.append('DOM checked')
    owner=SimpleNamespace(window=SimpleNamespace(view=view,port=12345),delay=delay,wait=wait)
    QtChecks.go(owner,'/quizzes/fixture.html')
    assert events==['requested','loaded','DOM checked']

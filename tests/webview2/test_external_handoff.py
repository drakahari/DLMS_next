"""Browser-launch boundary; no browser, network or personal profile access."""
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication, QMessageBox

from desktop import webview2_external as external
from desktop.webview2_browser import View


@pytest.fixture(scope='module', autouse=True)
def application():
    app = QApplication.instance() or QApplication([])
    yield app


def session(monkeypatch, mode='local'):
    calls, queue, feedback, focus = [], [], [], []
    owner = SimpleNamespace(_browser_dialog_depth=0, _browser_operation_depth=0,
        _close_after_dialog=False, _external_handoff_pending=False, _server_page_exposed=True,
        isActiveWindow=lambda: True, _begin_feedback=lambda action: 1,
        _feedback=lambda *a: feedback.append(a) or True)
    view = SimpleNamespace(page=lambda: SimpleNamespace(owner=owner), setFocus=focus.append)
    context = SimpleNamespace(mode=mode, origin='https://synthetic.invalid',
        navigation_generation=4, navigation_id=12, view=view,
        href=b'https://synthetic.invalid/library', valid=lambda: True)
    monkeypatch.setattr(external.SelectionContext, 'capture', lambda page: context)
    monkeypatch.setattr(external.QTimer, 'singleShot', lambda delay, callback: queue.append(callback))
    monkeypatch.setattr(external, 'confirm', lambda *a: True)
    monkeypatch.setattr(external, 'dispatch_external', lambda url: calls.append(url.toString()) or True)
    event = dict(user=True, mode=mode, kind='popup', generation=4, nav_id=12,
                 source='https://synthetic.invalid/library', url='https://chatgpt.com/')
    return owner, view, context, event, calls, queue, feedback, focus


@pytest.mark.parametrize('mode', ['local', 'server'])
@pytest.mark.parametrize('kind', ['navigation', 'popup'])
def test_explicit_consent_for_current_document_launches_only_exact_url(monkeypatch, mode, kind):
    w, view, context, event, calls, queue, feedback, focus = session(monkeypatch, mode)
    event['kind'] = kind
    consent = []
    def confirm(*args):
        consent.append(args)
        assert w._browser_dialog_depth == 1
        return True
    monkeypatch.setattr(external, 'confirm', confirm)
    external.request(view, event)
    assert not calls and len(queue) == 1
    queue.pop()()
    assert calls == [event['url']] and len(consent) == 1
    assert consent[0][2:] == (mode, context.origin)
    assert not w._external_handoff_pending and not w._browser_dialog_depth
    assert not focus  # Do not steal activation from the external browser.
    assert 'requested' in feedback[-1][1]


@pytest.mark.parametrize('changed', [dict(user=False), dict(user=1), dict(mode='other'),
    dict(kind='resource'), dict(source='https://foreign.invalid/library'), dict(source=''),
    dict(generation=3), dict(nav_id=11), dict(generation=True), dict(nav_id=True),
    dict(url='file:///C:/Windows/notepad.exe'), dict(url='javascript:alert(1)'),
    dict(url='ms-settings:apps'), dict(url='data:text/html,bad'),
    dict(url='https://user:secret@chatgpt.com/'), dict(url='http://localhost:8080/'),
    dict(url='http://127.0.0.1:8080/'), dict(url='http://[::1]:8080/'),
    dict(url='http://synthetic.localhost/'), dict(url='https://'+ 'a'*8200 +'.invalid/')])
def test_untrusted_event_or_unsafe_destination_never_launches(monkeypatch, changed):
    w, view, context, event, calls, queue, feedback, focus = session(monkeypatch)
    external.request(view, event | changed)
    assert not calls and not queue and not w._external_handoff_pending


@pytest.mark.parametrize('state', ['dialog', 'operation', 'pending', 'server-cover'])
def test_native_stack_and_server_cover_refuse_handoff(monkeypatch, state):
    w, view, context, event, calls, queue, *_ = session(monkeypatch, 'server')
    if state == 'dialog': w._browser_dialog_depth = 1
    elif state == 'operation': w._browser_operation_depth = 1
    elif state == 'pending': w._external_handoff_pending = True
    else: w._server_page_exposed = False
    external.request(view, event)
    assert not queue and not calls


@pytest.mark.parametrize('when', ['queued', 'modal'])
def test_navigation_mode_or_profile_epoch_change_retires_consent(monkeypatch, when):
    w, view, context, event, calls, queue, feedback, focus = session(monkeypatch)
    external.request(view, event)
    if when == 'queued': context.valid = lambda: False
    else:
        def confirm(*args):
            context.valid = lambda: False
            return True
        monkeypatch.setattr(external, 'confirm', confirm)
    queue.pop()()
    assert not calls and not feedback and not focus and not w._external_handoff_pending


@pytest.mark.parametrize('result', ['cancel', 'false', 'exception'])
def test_cancellation_failure_feedback_focus_and_repeated_clicks(monkeypatch, result):
    w, view, context, event, calls, queue, feedback, focus = session(monkeypatch)
    if result == 'cancel': monkeypatch.setattr(external, 'confirm', lambda *a: False)
    else:
        def dispatch(url):
            calls.append(url.toString())
            if result == 'exception': raise OSError('sensitive native detail')
            return False
        monkeypatch.setattr(external, 'dispatch_external', dispatch)
    external.request(view, event); external.request(view, event)
    assert len(queue) == 1
    queue.pop()()
    assert len(calls) == (0 if result == 'cancel' else 1)
    assert ('canceled' if result == 'cancel' else 'could not open') in feedback[-1][1]
    assert 'sensitive' not in feedback[-1][1] and len(focus) == 1
    assert not w._external_handoff_pending
    external.request(view, event)
    assert len(queue) == 1  # A later independent click remains usable.


def test_generic_blocked_protocol_events_have_no_launcher_authority():
    blocked = []
    view = SimpleNamespace(page=lambda: SimpleNamespace(owner=SimpleNamespace(note_blocked=blocked.append)))
    for kind in ('blocked', 'navigation-blocked', 'popup-blocked'):
        View._event(view, dict(event=kind, user=True, url='https://chatgpt.com/'))
    assert len(blocked) == 3


def test_frame_attribution_refusal_is_actionable_without_launch_authority(monkeypatch):
    w, view, context, event, calls, queue, feedback, focus = session(monkeypatch, 'server')
    event.update(event='external-refused', refusal='frame-attribution')
    external.request(view, event)
    assert not calls and not queue and not focus
    assert 'frame cannot be verified' in feedback[-1][1] and 'Reopen' in feedback[-1][1]
    feedback.clear()
    external.request(view, event | dict(generation=3))
    assert not feedback


@pytest.mark.parametrize('result', ['cancel', 'failure'])
def test_newer_feedback_does_not_lose_focus_to_old_handoff(monkeypatch, result):
    w, view, context, event, calls, queue, feedback, focus = session(monkeypatch)
    w._feedback = lambda *a: False  # A newer operation owns feedback.
    monkeypatch.setattr(external, 'confirm', lambda *a: result != 'cancel')
    monkeypatch.setattr(external, 'dispatch_external', lambda url: False)
    external.request(view, event); queue.pop()()
    assert not focus and not w._external_handoff_pending


def test_dispatch_cannot_publish_feedback_for_replaced_document(monkeypatch):
    w, view, context, event, calls, queue, feedback, focus = session(monkeypatch)
    def dispatch(url):
        context.valid = lambda: False
        return True
    monkeypatch.setattr(external, 'dispatch_external', dispatch)
    external.request(view, event); queue.pop()()
    assert not feedback and not focus


@pytest.mark.parametrize('stale', [False, True])
def test_uncertain_handoff_retains_modal_ownership_and_never_retries(monkeypatch, stale):
    w, view, context, event, calls, queue, feedback, focus = session(monkeypatch)
    def dispatch(url):
        assert w._browser_dialog_depth == 1
        assert w._external_handoff_pending
        calls.append(url.toString())
        if stale:context.valid=lambda:False
        raise external.HandoffUnconfirmed('synthetic timeout')
    monkeypatch.setattr(external,'dispatch_external',dispatch)
    external.request(view,event);queue.pop()()
    assert len(calls)==1 and not queue
    assert not w._browser_dialog_depth and not w._external_handoff_pending
    if stale:
        assert not feedback and not focus
    else:
        assert 'may already have opened' in feedback[-1][1]
        assert 'before retrying' in feedback[-1][1] and len(focus)==1


def test_confirmation_plain_text_no_default_and_no_automatic_submission(monkeypatch):
    observed = {}
    class Dialog:
        def __init__(self, owner): pass
        def setWindowTitle(self, value): observed['title'] = value
        def setTextFormat(self, value): observed['format'] = value
        def setText(self, value): observed['text'] = value
        def setStandardButtons(self, value): pass
        def setDefaultButton(self, value): observed['default'] = value
        def setEscapeButton(self, value): observed['escape'] = value
        def exec(self): return QMessageBox.StandardButton.No
        def deleteLater(self): observed['disposed'] = True
    Dialog.StandardButton = QMessageBox.StandardButton
    monkeypatch.setattr(external, 'QMessageBox', Dialog)
    assert not external.confirm(None, QUrl('https://synthetic.invalid/?q=%3Cb%3E'), 'server', 'https://server.invalid')
    assert observed['default'] == observed['escape'] == QMessageBox.StandardButton.No
    assert 'server.invalid' in observed['text'] and 'will not submit or paste' in observed['text']
    assert observed['format'] == external.Qt.TextFormat.PlainText


@pytest.mark.parametrize('action',sorted(external.AI_ACTIONS))
def test_native_attested_local_ai_action_uses_click_as_consent(monkeypatch,action):
    w,view,context,event,calls,queue,feedback,focus=session(monkeypatch)
    event.update(kind='ai-action',verified_ai=True,ai_action=action)
    monkeypatch.setattr(external,'confirm',lambda *a:pytest.fail('Redundant AI confirmation'))
    external.request(view,event);queue.pop()()
    assert calls==[event['url']] and not focus and not w._external_handoff_pending


@pytest.mark.parametrize('action',sorted(external.AI_ACTIONS))
@pytest.mark.parametrize('url',['https://chatgpt.com/','https://claude.ai/','https://gemini.google.com/'])
def test_native_signal_and_consumed_server_activation_are_direct(monkeypatch,action,url):
    w,view,context,event,calls,queue,*_=session(monkeypatch,'server')
    event.update(kind='ai-action',verified_ai=True,native_user=True,ai_action=action,url=url)
    monkeypatch.setattr(external,'confirm',lambda *a:pytest.fail('Redundant Server AI confirmation'))
    external.request(view,event);queue.pop()()
    assert calls==[url] and not w._external_handoff_pending


@pytest.mark.parametrize('url',[
    'http://chatgpt.com/','https://chatgpt.com.evil.invalid/','https://clаude.ai/',
    'https://gemini.google.com.evil.invalid/','https://user:x@chatgpt.com/',
    'https://chatgpt.com:444/','https://chatgpt.com/?prompt=synthetic','https://chatgpt.com/#x',
    'https://chatgpt.com/extra','file:///C:/test.exe','javascript:alert(1)','ms-settings:apps',
    'https://chatgpt.com./','https://chatgpt.com/\n'])
def test_server_ai_allowlist_refuses_lookalikes_paths_and_unsafe_schemes(monkeypatch,url):
    w,view,context,event,calls,queue,*_=session(monkeypatch,'server')
    event.update(kind='ai-action',verified_ai=True,native_user=True,ai_action='study-review',url=url)
    external.request(view,event)
    assert not calls and not queue


@pytest.mark.parametrize('flag',[False,None,1,'true'])
def test_server_ai_private_classification_without_real_native_flag_is_not_authority(monkeypatch,flag):
    w,view,context,event,calls,queue,*_=session(monkeypatch,'server')
    event.update(kind='ai-action',verified_ai=True,native_user=flag,ai_action='study-review')
    external.request(view,event)
    assert not calls and not queue


@pytest.mark.parametrize('mode,changes',[
    ('server',{}),('local',{'verified_ai':False}),('local',{'verified_ai':1}),
    ('local',{'ai_action':'Open ChatGPT'}),('local',{'user':False}),
    ('local',{'generation':3}),('local',{'url':'file:///C:/no.exe'})])
def test_ai_label_server_or_stale_attestation_never_authorizes(monkeypatch,mode,changes):
    w,view,context,event,calls,queue,*_=session(monkeypatch,mode)
    event.update(kind='ai-action',verified_ai=True,ai_action='study-review');event.update(changes)
    external.request(view,event)
    assert not queue and not calls


@pytest.mark.parametrize('failure',['false','exception','unconfirmed','stale'])
def test_direct_ai_failure_has_feedback_without_a_second_prompt_or_retry(monkeypatch,failure):
    w,view,context,event,calls,queue,feedback,focus=session(monkeypatch)
    event.update(kind='ai-action',verified_ai=True,ai_action='study-review')
    monkeypatch.setattr(external,'confirm',lambda *a:pytest.fail('No redundant confirmation'))
    def dispatch(url):
        assert w._browser_dialog_depth==1
        calls.append(url.toString())
        if failure=='exception':raise OSError('private detail')
        if failure=='unconfirmed':raise external.HandoffUnconfirmed('private detail')
        if failure=='stale':context.valid=lambda:False
        return False
    monkeypatch.setattr(external,'dispatch_external',dispatch)
    external.request(view,event);queue.pop()()
    assert calls==[event['url']] and not queue and not w._external_handoff_pending
    assert not w._browser_dialog_depth
    if failure=='stale':assert not feedback and not focus
    else:
        assert len(feedback)==1 and len(focus)==1 and 'private detail' not in feedback[0][1]

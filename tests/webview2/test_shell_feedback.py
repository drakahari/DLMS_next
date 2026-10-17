"""Controller-only checks: no backend, browser, visible window or owner data."""
from types import SimpleNamespace
from concurrent.futures import Future
from pathlib import Path
import os

import pytest
from PySide6.QtCore import QObject, QUrl, Qt, Signal
from PySide6.QtWidgets import QApplication, QMainWindow

from desktop.operation_feedback import OperationFeedback
from desktop.webview2_browser import Download
from desktop.webview2_shell import DesktopWindow, QtDesktopWindow


@pytest.fixture(scope='module', autouse=True)
def application():
    app = QApplication.instance() or QApplication([])
    yield app


def window(mode='local'):
    w = DesktopWindow.__new__(DesktopWindow)
    QMainWindow.__init__(w)
    for name, value in dict(mode=mode, _feedback_mode=mode, _feedback_writing=False,
                            _browser_generation=2, _server_navigation_serial=4,
                            _wv_status_serial=0, _wv_feedback_context={},
                            operation_feedback=OperationFeedback(), settings_panel=None,
                            failed_reason=None, _settings_transition_refused=False,
                            _closing=False, _retiring_browser=None, download_results=[],
                            mode_config={'server': {'origin': 'https://synthetic.invalid'}},
                            view=SimpleNamespace(page=lambda: 'current-page')).items():
        setattr(w, name, value)
    w.statusBar().messageChanged.connect(w._status_message_changed)
    return w


def test_begin_context_is_captured_after_clear_message_signal():
    w = window()
    w.statusBar().showMessage('Earlier unticketed notice')
    serial = w._wv_status_serial
    ticket = w._begin_feedback('download')
    assert w._wv_status_serial > serial
    assert w._feedback(ticket, 'Download in progress')
    assert w._feedback(ticket, 'Download completed', 'success')
    assert w.statusBar().currentMessage() == 'Download completed'


@pytest.mark.parametrize('newer', ['Loading another page', 'Recovery needs inspection', 'Server unavailable'])
def test_old_local_info_feedback_cannot_overwrite_newer_unticketed_notice(newer):
    w = window()
    ticket = w._begin_feedback('download')
    assert w._feedback(ticket, 'Download in progress')
    w.statusBar().showMessage(newer)
    assert not w._feedback(ticket, 'Old download completed', 'success')
    assert w.statusBar().currentMessage() == newer


class Request(QObject):
    isFinishedChanged = Signal()
    stateChanged = Signal(object)
    DownloadState = Download.DownloadState

    def __init__(self, name='reference.txt'):
        super().__init__()
        self.name, self.current = name, self.DownloadState.DownloadRequested
        self._download_context = (2, 7, '')

    def page(self): return 'current-page'
    def url(self): return QUrl('https://synthetic.invalid/export')
    def downloadFileName(self): return self.name
    def setDownloadFileName(self, value): self.name = value
    def setDownloadDirectory(self, value): self.directory = value
    def state(self): return self.current
    def interruptReasonString(self): return 'Synthetic interrupted transfer'
    def accept(self): self.current = self.DownloadState.DownloadInProgress
    def cancel(self): self.current = self.DownloadState.DownloadCancelled
    def terminal(self, state):
        if state == self.DownloadState.DownloadCompleted and hasattr(self, 'directory'):
            target = Path(self.directory) / self.name
            if not target.exists():
                target.write_bytes(b'Q: Synthetic?\nA: Alpha\nB: Beta\n')
        self.current = state
        self.stateChanged.emit(state)
        self.isFinishedChanged.emit()


def export_window(tmp_path, monkeypatch):
    """Real export controller, with only native selection/result injected."""
    from desktop import windows_backup_chooser
    from desktop.webview2_exports import QTimer
    w = window('server')
    def directory(name):
        path = tmp_path / name
        path.mkdir(mode=0o700)
        return path
    root, staging, documents, downloads, ordinary = map(directory, ('server', 'staging', 'Documents', 'Downloads', 'ordinary'))
    w.server_paths = {'root': root, 'downloads': staging}
    w.selection_private_roots = (root, staging)
    w.backup_chooser_folders = (documents, downloads)
    w.profile_name = 'synthetic'
    w.mode_config['server']['id'] = 'synthetic-server'
    w._browser_dialog_depth = w._browser_operation_depth = 0
    w._close_after_dialog = False
    w.view = SimpleNamespace(page=lambda: 'current-page', url=lambda: QUrl('https://synthetic.invalid/library'),
                             _active_generation=2, _active_navigation=7, setFocus=lambda *_: None)
    class Executor:
        def submit(self, function, *args):
            future = Future()
            try: future.set_result(function(*args))
            except BaseException as exc: future.set_exception(exc)
            return future
    w.backup_selection_executor = Executor()
    w.export_callbacks = []
    # This fixture intentionally constructs a controller without its normal
    # widget tree. Invoke only its export queue, rather than dispatching native
    # events into unrelated half-constructed window fixtures.
    monkeypatch.setattr(QTimer, 'singleShot', lambda delay, callback: w.export_callbacks.append(callback))
    monkeypatch.setattr(windows_backup_chooser, 'choose_export', lambda owner, name, *args, **kwargs: (str(ordinary / name), ''))
    return w


def finish_export_events(w):
    from desktop.webview2_exports import Export
    while w.export_callbacks:
        w.export_callbacks.pop(0)()
    for operation in w.findChildren(Export):
        operation.poll()


@pytest.mark.parametrize('newer', ['navigation', 'outage', 'new-transfer', 'closing', 'mode'])
@pytest.mark.parametrize('state, recorded', [(Download.DownloadState.DownloadCompleted, 'completed'),
                                           (Download.DownloadState.DownloadInterrupted, 'failed'),
                                           (Download.DownloadState.DownloadCancelled, 'cancelled')])
@pytest.mark.skipif(os.name != 'nt', reason='Real WebView2 export controller uses Windows private ACLs, COM chooser and handle publication')
def test_old_server_terminal_is_recorded_without_clobbering_newer_context(tmp_path, monkeypatch, newer, state, recorded):
    w = export_window(tmp_path, monkeypatch)
    old = Request()
    w._server_download(old)
    if newer == 'navigation':
        # Navigation serial is authoritative even if its status repeats or is
        # unchanged, hence no status signal in this case.
        w._server_navigation_serial += 1
    elif newer == 'outage':
        w.statusBar().showMessage('Server unavailable; no Local fallback')
    elif newer == 'new-transfer':
        w._server_download(Request('newer.txt'))
    elif newer == 'closing':
        w._closing = True
    elif newer == 'mode':
        w.mode = 'local'
    current = w.statusBar().currentMessage()
    old.terminal(state)
    finish_export_events(w)
    if state == Download.DownloadState.DownloadCompleted and newer in ('navigation', 'closing', 'mode'):
        # A destination cannot be consented after the exporting page was
        # retired. The staged bytes remain private and no user file is saved.
        recorded = 'failed'
    assert w.download_results[0]['state'] == recorded
    assert w.statusBar().currentMessage() == current
    if state == Download.DownloadState.DownloadInterrupted:
        assert w.download_results[0]['reason'] == 'Synthetic interrupted transfer'
    old.terminal(Download.DownloadState.DownloadCompleted)
    assert w.download_results[0]['state'] == recorded


@pytest.mark.skipif(os.name != 'nt', reason='Real WebView2 export controller uses Windows private ACLs, COM chooser and handle publication')
def test_current_server_terminal_feedback_is_visible(tmp_path, monkeypatch):
    w = export_window(tmp_path, monkeypatch)
    request = Request(); w._server_download(request)
    request.terminal(Download.DownloadState.DownloadCompleted)
    finish_export_events(w)
    assert w.download_results[0]['state'] == 'completed'
    assert 'Server download completed:' in w.statusBar().currentMessage()


@pytest.mark.parametrize('mode', ['local', 'server'])
@pytest.mark.parametrize('invalid', [None, 'unattested', 'generation', 'navigation', 'document', 'loading', 'foreign'])
def test_blob_download_needs_current_native_document_and_cannot_claim_backup(mode, invalid):
    w = window(mode)
    origin = 'http://127.0.0.1:42424' if mode == 'local' else 'https://synthetic.invalid'
    w.port, w.backend = 42424, SimpleNamespace(poll=lambda: None)
    page = SimpleNamespace(isLoading=lambda: invalid == 'loading')
    w.view = SimpleNamespace(page=lambda: page, url=lambda: QUrl(origin + '/review'),
                             _active_generation=2, _active_navigation=7)
    request = Request('synthetic.apkg')
    request.page = lambda: page
    request.url = lambda: QUrl('blob:' + (origin if invalid != 'foreign' else 'https://foreign.invalid')
                               + '/12345678-1234-1234-1234-123456789abc')
    request._blob_download = invalid != 'unattested'
    request._download_context = (3 if invalid == 'generation' else 2,
                                 8 if invalid == 'navigation' else 7,
                                 origin + ('/other' if invalid == 'document' else '/review'))
    w.backup_output_selection = {'operation': 'must-remain-unclaimed'}
    w._backup_creating = True
    calls = []
    w._ordinary_download = lambda request, *, local: calls.append(local)
    (w._download if mode == 'local' else w._server_download)(request)
    assert calls == ([mode == 'local'] if invalid is None else [])
    assert w.backup_output_selection == {'operation': 'must-remain-unclaimed'} and w._backup_creating
    if invalid is not None: assert request.state() == request.DownloadState.DownloadCancelled


def certification_window(status=422, path='/certifications/add'):
    w = window()
    w.port = 42424
    page = SimpleNamespace(last_http_status=status)
    view = SimpleNamespace(url=lambda: QUrl('http://127.0.0.1:42424' + path), page=lambda: page, shown=0)
    view.show = lambda: setattr(view, 'shown', view.shown + 1)
    w.view = view
    panel, fallback = SimpleNamespace(hidden=0), SimpleNamespace(hidden=0)
    panel.hide = lambda: setattr(panel, 'hidden', panel.hidden + 1)
    fallback.hide = lambda: setattr(fallback, 'hidden', fallback.hidden + 1)
    panel.clear_backup_feedback = lambda: None
    w.settings_panel, w.settings_fallback = panel, fallback
    for name, value in dict(_close_active=False, _mode_switch_busy=False, _browser_operation_depth=0,
                            _import_reopen_status=None, import_in_progress=False, maintenance_transition=False,
                            backend=SimpleNamespace(poll=lambda: None), import_worker=None, maintenance_worker=None,
                            removal_worker=None, _settings_generation=5, _settings_kind='backup',
                            _settings_verified_url=b'old-native-authority', _settings_action_busy=False).items():
        setattr(w, name, value)
    return w


@pytest.mark.parametrize('status', [400, 422])
@pytest.mark.parametrize('ok', [True, False])
def test_actionable_certification_response_is_visible_without_native_authority(status, ok):
    w = certification_window(status)
    w._settings_page_loaded(ok, w.view)
    assert w.view.shown and w.settings_panel.hidden and w.settings_fallback.hidden
    assert w._settings_kind is None and w._settings_verified_url is None
    assert 'validation error' in w.statusBar().currentMessage()


@pytest.mark.parametrize('guard,value', [('_closing', True), ('_close_active', True), ('_mode_switch_busy', True),
                                       ('_browser_operation_depth', 1), ('_settings_transition_refused', True),
                                       ('import_in_progress', True), ('maintenance_transition', True),
                                       ('_import_reopen_status', (3, 'pending import feedback')),
                                       ('import_worker', object()), ('maintenance_worker', object()),
                                       ('removal_worker', object()), ('failed_reason', 'failed'),
                                       ('_retiring_browser', object())])
def test_certification_override_preserves_busy_recovery_guards(monkeypatch, guard, value):
    w = certification_window(); setattr(w, guard, value)
    calls = []
    monkeypatch.setattr(QtDesktopWindow, '_settings_page_loaded', lambda owner, *args: calls.append(args))
    w._settings_page_loaded(False, w.view)
    assert calls == [(False, w.view)] and not w.view.shown


@pytest.mark.parametrize('status,path', [(409, '/settings/backup/create?desktop_output=synthetic'),
                                        (400, '/settings/backup'), (422, '/library'), (500, '/certifications/add')])
def test_backup_conflict_and_other_routes_fall_through_unchanged(monkeypatch, status, path):
    w = certification_window(status, path); calls = []
    monkeypatch.setattr(QtDesktopWindow, '_settings_page_loaded', lambda owner, *args: calls.append(args))
    w._settings_page_loaded(False, w.view)
    assert calls == [(False, w.view)] and not w.view.shown


def test_stale_loaded_view_falls_through_without_exposing_current_page(monkeypatch):
    w = certification_window(); calls = []; stale = object()
    monkeypatch.setattr(QtDesktopWindow, '_settings_page_loaded', lambda owner, *args: calls.append(args))
    w._settings_page_loaded(False, stale)
    assert calls == [(False, stale)] and not w.view.shown


@pytest.mark.parametrize('guard', ['missing-backend', 'stopped-backend', 'server-mode', 'foreign-origin'])
def test_certification_override_does_not_cross_backend_or_mode_boundary(monkeypatch, guard):
    w = certification_window(); calls = []
    if guard == 'missing-backend': w.backend = None
    elif guard == 'stopped-backend': w.backend = SimpleNamespace(poll=lambda: 9)
    elif guard == 'server-mode': w.mode = 'server'
    elif guard == 'foreign-origin': w.view.url = lambda: QUrl('https://synthetic.invalid/certifications/add')
    monkeypatch.setattr(QtDesktopWindow, '_settings_page_loaded', lambda owner, *args: calls.append(args))
    w._settings_page_loaded(False, w.view)
    assert calls == [(False, w.view)] and not w.view.shown


def test_native_cover_is_opaque_and_does_not_request_browser_hiding(monkeypatch):
    attributes, calls, queued, covers, shown = [], [], [], [], []
    label = SimpleNamespace(setAttribute=lambda *args: attributes.append(args), text=lambda: 'Synthetic loading')
    DesktopWindow._prepare_server_cover(label)
    assert attributes == [(Qt.WidgetAttribute.WA_NativeWindow, True), (Qt.WidgetAttribute.WA_OpaquePaintEvent, True)]
    w = window('server'); w.server_status = label
    w.view.show = lambda: shown.append(True)
    w.view.setServerCover = lambda *args, **kwargs: covers.append((args, kwargs))
    def base(owner, exposed, **kw):
        owner._server_page_exposed = exposed
        calls.append((exposed, kw))
    monkeypatch.setattr(QtDesktopWindow, '_set_server_page_exposed', base)
    from desktop.webview2_shell import QTimer
    monkeypatch.setattr(QTimer, 'singleShot', lambda delay, callback: queued.append(callback))
    w._set_server_page_exposed(False, loading=True)
    assert calls == [(False, {'loading': True})] and shown == [True]
    queued.pop()()
    assert covers[-1] == ((True, 'Synthetic loading'), {'browser_visible': True})
    w._set_server_page_exposed(False, loading=False); queued.pop()()
    assert covers[-1] == ((True, 'Synthetic loading'), {'browser_visible': False})
    w._set_server_page_exposed(True)
    queued.pop()()
    assert covers[-1] == ((False, 'Synthetic loading'), {'browser_visible': True})


def test_deferred_cover_sync_reads_current_status_and_exposure(monkeypatch):
    w = window('server'); pending, covers, label = [], [], ['Initial connection text']
    w.view.show = lambda: None
    w.view.setServerCover = lambda *a, **kw: covers.append((a, kw))
    w.server_status = SimpleNamespace(text=lambda: label[0])
    from desktop.webview2_shell import QTimer
    monkeypatch.setattr(QTimer, 'singleShot', lambda delay, callback: pending.append(callback))
    monkeypatch.setattr(QtDesktopWindow, '_set_server_page_exposed', lambda owner, exposed, **kw: setattr(owner, '_server_page_exposed', exposed))
    w._set_server_page_exposed(False, loading=True)
    label[0] = 'Newer unavailable message'
    w._set_server_page_exposed(False, loading=False)
    for callback in pending: callback()
    assert covers == [((True, 'Newer unavailable message'), {'browser_visible': False})] * 2


@pytest.mark.parametrize('change', ['local', 'closing', 'retiring', 'missing-view'])
def test_native_cover_sync_cannot_affect_stale_or_local_surface(change):
    w = window('server'); covers = []
    w.view.setServerCover = lambda *a, **kw: covers.append((a, kw))
    w.server_status = SimpleNamespace(text=lambda: 'Synthetic status')
    w._server_page_exposed, w._wv_cover_loading = False, True
    if change == 'local': w.mode = 'local'
    elif change == 'closing': w._closing = True
    elif change == 'retiring': w._retiring_browser = object()
    else: w.view = None
    w._sync_server_cover()
    assert not covers


def declined_backup_window():
    w = certification_window(200, '/settings/backup')
    w._render_backup_feedback = lambda **kwargs: None
    w._backup_creating, w.backup_output_operation = True, 'synthetic-operation'
    w.backup_output_selection = {'operation': w.backup_output_operation}
    w._active_outputs = lambda: []
    w._backup_feedback_ticket = w._begin_feedback('create_backup')
    w._feedback(w._backup_feedback_ticket, 'Synthetic backup in progress')
    calls = []
    w._settings_page_loaded = lambda *a: calls.append(a)
    return w, calls, QUrl('http://127.0.0.1:42424/settings/backup/create?desktop_output=synthetic-operation')


def test_exact_declined_backup_clears_only_intent_and_reverifies_settings_document():
    w, calls, url = declined_backup_window()
    assert w._attachment_declined(w.view, url)
    assert not w._backup_creating and w.backup_output_selection is None
    assert calls == [(True, w.view)]
    assert 'no selected destination was published' in w.statusBar().currentMessage()
    assert not w.download_results


@pytest.mark.parametrize('guard,value', [('_closing', True), ('_close_active', True), ('_mode_switch_busy', True),
                                       ('_browser_operation_depth', 1), ('_settings_transition_refused', True),
                                       ('_import_reopen_status', (3, 'pending import feedback')), ('import_in_progress', True),
                                       ('maintenance_transition', True), ('_retiring_browser', object()),
                                       ('import_worker', object()), ('maintenance_worker', object()),
                                       ('removal_worker', object()), ('failed_reason', 'failed'), ('mode', 'server')])
def test_declined_backup_preserves_recovery_import_and_mode_guards(guard, value):
    w, calls, url = declined_backup_window(); setattr(w, guard, value)
    original = w.backup_output_selection
    assert not w._attachment_declined(w.view, url)
    assert w._backup_creating and w.backup_output_selection is original and not calls


@pytest.mark.parametrize('variant', ['stale-view', 'foreign-origin', 'wrong-route', 'wrong-operation', 'active-output', 'dead-backend', 'missing-backend'])
def test_declined_backup_requires_exact_current_owned_operation(variant):
    w, calls, url = declined_backup_window(); view = w.view
    if variant == 'stale-view': view = object()
    elif variant == 'foreign-origin': url = QUrl('https://synthetic.invalid/settings/backup/create?desktop_output=synthetic-operation')
    elif variant == 'wrong-route': url = QUrl('http://127.0.0.1:42424/export/all_quizzes.txt?desktop_output=synthetic-operation')
    elif variant == 'wrong-operation': url = QUrl('http://127.0.0.1:42424/settings/backup/create?desktop_output=old-operation')
    elif variant == 'active-output': w._active_outputs = lambda: [object()]
    elif variant == 'dead-backend': w.backend = SimpleNamespace(poll=lambda: 9)
    else: w.backend = None
    assert not w._attachment_declined(view, url)
    assert w._backup_creating and w.backup_output_selection is not None and not calls


def test_declined_backup_does_not_overwrite_newer_feedback():
    w, calls, url = declined_backup_window()
    w.statusBar().showMessage('A newer status must remain visible')
    assert w._attachment_declined(w.view, url)
    assert not w._backup_creating and w.backup_output_selection is None
    assert w.statusBar().currentMessage() == 'A newer status must remain visible'


@pytest.mark.parametrize('target', ['local', 'server'])
@pytest.mark.parametrize('depth', ['_browser_dialog_depth', '_browser_operation_depth'])
def test_mode_switch_refuses_owned_modal_stack_before_base_drain(monkeypatch,target,depth):
    w=window('server' if target=='local' else 'local')
    setattr(w,depth,1)
    refused=[]
    w._switch_refusal=lambda message:refused.append(message) or False
    monkeypatch.setattr(QtDesktopWindow,'switch_to_'+target,
                        lambda owner:pytest.fail('Base switch/drain must not run during an owned dialog'))
    assert not getattr(w,'switch_to_'+target)()
    assert len(refused)==1 and 'before switching' in refused[0]


@pytest.mark.parametrize('target', ['local', 'server'])
def test_mode_switch_delegates_without_owning_dialog(monkeypatch,target):
    w=window('server' if target=='local' else 'local')
    w._browser_dialog_depth=w._browser_operation_depth=0
    calls=[]
    monkeypatch.setattr(QtDesktopWindow,'switch_to_'+target,lambda owner:calls.append(owner) or True)
    assert getattr(w,'switch_to_'+target)() and calls==[w]

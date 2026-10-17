"""Protocol/state regressions without creating any native browser or window."""
from types import SimpleNamespace
import os
from pathlib import Path

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEngineLoadingInfo

from desktop.webview2_browser import Download, LoadingInfo, Profile, View


@pytest.fixture(scope='module', autouse=True)
def core_application():
    # QApplication also supports later widget-only suites in this interpreter;
    # constructing a bare QCoreApplication would prevent those from running.
    # No widget is created/shown by these adapter state tests.
    app = QApplication.instance() or QApplication([])
    yield app


class FakeView(QObject):
    def __init__(self):
        super().__init__()
        self.commands = []
        self.document = object()

    def page(self): return self.document
    def command(self, op, **values): self.commands.append((op, values))


def request():
    view = FakeView()
    download = Download(view, {'download_id': 'private-ticket', 'url': 'https://synthetic.invalid/reference.txt', 'name': 'reference.txt'})
    return view, download


def test_attachment_is_stopped_download_not_failure():
    info = LoadingInfo('https://synthetic.invalid/reference.txt', download=True)
    assert info.status() == QWebEngineLoadingInfo.LoadStatus.LoadStoppedStatus
    assert info.isDownload() and not info.isErrorPage()
    assert info.url().path() == '/reference.txt'
    assert LoadingInfo('https://synthetic.invalid/', ok=True).status() == QWebEngineLoadingInfo.LoadStatus.LoadSucceededStatus
    assert LoadingInfo('https://synthetic.invalid/', error=-1).status() == QWebEngineLoadingInfo.LoadStatus.LoadFailedStatus


@pytest.mark.parametrize('width,height,scale,expected', [
    (1280, 816, 1, {'width': 1280, 'height': 816, 'scale': 1.0}),
    (1280, 816, 1.25, {'width': 1600, 'height': 1020, 'scale': 1.25}),
    (1280, 816, 1.5, {'width': 1920, 'height': 1224, 'scale': 1.5}),
    (319, 201, 1.5, {'width': 479, 'height': 302, 'scale': 1.5}),
    (1, 1, .25, {'width': 1, 'height': 1, 'scale': .25}),
])
def test_native_viewport_uses_physical_pixels_and_preserves_qt_scale(width, height, scale, expected):
    from desktop.webview2_browser import physical_viewport
    assert physical_viewport(width, height, scale) == expected


@pytest.mark.parametrize('width,height,scale', [
    (0, 816, 1), (-1, 816, 1), (1280, 0, 1), (True, 816, 1), (1280.5, 816, 1),
    (1280, 816, True), (1280, 816, 0), (1280, 816, .2), (1280, 816, 9),
    (1280, 816, float('nan')), (1280, 816, float('inf')), (9000, 816, 2),
])
def test_native_viewport_refuses_invalid_or_unbounded_geometry(width, height, scale):
    from desktop.webview2_browser import physical_viewport
    with pytest.raises(ValueError): physical_viewport(width, height, scale)


def test_native_resize_command_carries_physical_size_and_failure_feedback():
    commands, failures = [], []
    fake = SimpleNamespace(_ready=True, width=lambda: 1280, height=lambda: 816, devicePixelRatioF=lambda: 1.25,
                           command=lambda op, **values: commands.append((op, values)), _failure=failures.append)
    View._send_physical_resize(fake)
    op, values = commands[-1]
    assert op == 'resize' and {key: values[key] for key in ('width', 'height', 'scale')} == {'width': 1600, 'height': 1020, 'scale': 1.25}
    values['on_error']({'message': 'Synthetic unsupported effective zoom'})
    assert failures == ['WebView2 geometry could not be applied: Synthetic unsupported effective zoom']


def test_native_resize_waits_for_ready_and_refuses_invalid_scale():
    commands, failures = [], []
    fake = SimpleNamespace(_ready=False, width=lambda: 1280, height=lambda: 816, devicePixelRatioF=lambda: float('nan'),
                           command=lambda *args, **kwargs: commands.append(args), _failure=failures.append)
    View._send_physical_resize(fake)
    assert not commands and not failures
    fake._ready = True; View._send_physical_resize(fake)
    assert not commands and len(failures) == 1


def test_qt_dpr_or_screen_change_requests_native_geometry_refresh():
    from PySide6.QtCore import QEvent
    calls = []
    fake = SimpleNamespace(_send_physical_resize=lambda: calls.append(True))
    View._refresh_scale_event(fake, QEvent(QEvent.Type.DevicePixelRatioChange))
    View._refresh_scale_event(fake, QEvent(QEvent.Type.ScreenChangeInternal))
    View._refresh_scale_event(fake, QEvent(QEvent.Type.FocusIn))
    assert calls == [True, True]


def test_download_timeout_terminal_even_when_native_reports_success_later():
    view, download = request()
    terminal = []
    download.isFinishedChanged.connect(lambda: terminal.append(download.state()))
    download._timeout()
    download.finish('completed')
    download.finish('cancelled')
    assert terminal == [download.DownloadState.DownloadInterrupted]
    assert download.isFinished()
    assert '120 seconds' in download.interruptReasonString()
    assert view.commands == [('download', {'download_id': 'private-ticket', 'action': 'cancel'})]


def test_cancel_is_idempotent_and_page_identity_is_fixed():
    view, download = request()
    original = view.document
    view.document = object()
    download.cancel(); download.cancel()
    assert download.page() is original
    assert download.state() == download.DownloadState.DownloadCancelled
    assert len(view.commands) == 1


def test_unknown_download_state_cannot_publish_success():
    view, download = request()
    download.finish('in-progress')
    assert not download.isFinished()
    download.finish('interrupted', 'Synthetic transfer error')
    assert download.interruptReasonString() == 'Synthetic transfer error'


def test_profile_is_plain_qobject_not_webengine_profile():
    profile = Profile('synthetic')
    assert isinstance(profile, QObject)
    profile.setPersistentStoragePath('private-storage')
    profile.setCachePath('private-cache')
    assert profile.storage == 'private-storage'
    assert profile.cache == 'private-cache'


def test_native_progress_only_restarts_live_download_timer():
    view, download = request()
    fake = SimpleNamespace(_downloads={'private-ticket': download})
    View._event(fake, {'event': 'download-progress', 'download_id': 'private-ticket'})
    assert download.timer.isActive()
    download.finish('interrupted', 'Synthetic transfer error')
    View._event(fake, {'event': 'download-progress', 'download_id': 'private-ticket'})
    assert not download.timer.isActive()


def test_reply_preserves_json_types_and_failure_is_none():
    values = []
    fake = SimpleNamespace(_callbacks={1: (1, values.append), 2: (1, values.append)})
    View._event(fake, {'event': 'reply', 'id': 1, 'ok': True, 'value': {'ok': True, 'items': [None, 2, 'text']}})
    View._event(fake, {'event': 'reply', 'id': 2, 'ok': False, 'value': 'untrusted'})
    View._event(fake, {'event': 'reply', 'id': 1, 'ok': True, 'value': 'late'})
    assert values == [{'ok': True, 'items': [None, 2, 'text']}, None]
    assert not fake._callbacks


def test_native_rejection_is_immediate_not_only_idle_watchdog():
    view, download = request()
    download._state = download.DownloadState.DownloadInProgress
    fake = SimpleNamespace(_callbacks={4: (1, None, lambda error: download.finish('interrupted', error['message']))})
    View._event(fake, {'event': 'reply', 'id': 4, 'ok': False, 'value': {'message': 'Synthetic unsafe destination'}})
    assert download.state() == download.DownloadState.DownloadInterrupted
    assert download.interruptReasonString() == 'Synthetic unsafe destination'
    assert not fake._callbacks


def test_script_dialog_during_close_fails_closed_without_modal_stack(monkeypatch):
    import desktop.webview2_browser as adapter
    messages = []
    owner = SimpleNamespace(_closing=True, _retiring_browser=None, close_browser_notices=[],
                            statusBar=lambda: SimpleNamespace(showMessage=messages.append))
    fake = SimpleNamespace(_retiring=False, page=lambda: SimpleNamespace(owner=owner))
    owner.view = fake
    monkeypatch.setattr(adapter, 'QMessageBox', lambda *a, **kw: pytest.fail('Closing must not open a modal dialog'))
    assert View._script_dialog(fake, {'kind': 'Confirm', 'message': 'Synthetic close notice'}) == (False, '')
    assert messages and owner.close_browser_notices == messages


def test_stale_navigation_events_do_not_touch_current_page():
    fake = SimpleNamespace(_active_generation=4, _active_navigation=12,
                           page=lambda: pytest.fail('Stale event must not inspect or modify the current page'))
    for kind, generation, navigation in [('load-start', 3, 11), ('url', 3, 11),
                                         ('load-finish', 3, 11), ('load-finish', 4, 11)]:
        View._event(fake, {'event': kind, 'generation': generation, 'nav_id': navigation})
    assert fake._active_generation == 4 and fake._active_navigation == 12


@pytest.mark.parametrize('value', [True, -1, '4', 4.5])
def test_malformed_navigation_identity_fails_closed(value):
    fake = SimpleNamespace(_active_generation=4, _active_navigation=12)
    with pytest.raises(ValueError, match='navigation identity'):
        View._event(fake, {'event': 'load-finish', 'generation': value, 'nav_id': 12})


def test_application_world_is_distinct_from_main_world(monkeypatch):
    import desktop.webview2_browser as adapter
    from PySide6.QtWebEngineCore import QWebEngineScript
    monkeypatch.setattr(adapter, 'View', FakeView)
    view = FakeView()
    page = adapter.Page(Profile('isolated-world'), QObject(), view)
    callback = lambda value: None
    page.runJavaScript('window.applicationFunction()', callback)
    page.runJavaScript('document.title', QWebEngineScript.ScriptWorldId.ApplicationWorld, callback)
    assert view.commands == [('eval', {'callback': callback, 'script': 'window.applicationFunction()', 'world': 0}),
                             ('eval', {'callback': callback, 'script': 'document.title', 'world': 1})]


def test_retirement_defers_qobject_deletion_until_native_exit(monkeypatch):
    # The native process remains the deletion barrier even when close is stuck.
    writes = []
    from PySide6.QtCore import QProcess
    fake = SimpleNamespace(_retiring=False, process=SimpleNamespace(state=lambda: QProcess.ProcessState.Running),
                           _queue=[{'op': 'navigate'}], _serial=2, _write=writes.append,
                           _detach_position_filters=lambda: None)
    View.deleteLater(fake)
    assert fake._retiring and not fake._queue
    assert writes == [{'id': 3, 'op': 'close'}]


def test_optional_trace_reports_unavailable_renderer_and_lifecycle_honestly():
    from enum import IntEnum
    from desktop import webview2_browser as adapter
    owner = QObject()
    page = adapter.Page(Profile('optional-trace'), owner)
    assert page.renderProcessPid() == 0
    assert isinstance(page.lifecycleState(), IntEnum)
    assert page.lifecycleState().name == 'Unknown' and page.lifecycleState().value == -1


@pytest.mark.skipif(os.name != 'nt', reason='Windows private file publication')
def test_download_pins_parent_and_publishes_exact_bytes_without_overwrite(tmp_path):
    job = tmp_path / 'synthetic export 日本語'
    job.mkdir(mode=0o700)
    view, download = request()
    download.setDownloadDirectory(str(job))
    download.accept()
    assert download.state() == download.DownloadState.DownloadInProgress
    partial = Path(view.commands[-1][1]['path'])
    assert partial.parent == job and partial.name.startswith('.wv-')
    assert not (job / 'reference.txt').exists()
    with pytest.raises(OSError): job.rename(tmp_path / 'substituted-parent')
    content = b'Synthetic question\r\nA) one\r\nB) two\r\n'
    partial.write_bytes(content)
    download.finish('completed')
    assert download.state() == download.DownloadState.DownloadCompleted
    assert (job / 'reference.txt').read_bytes() == content
    assert not partial.exists()
    job.rename(tmp_path / 'unpinned-after-terminal')


@pytest.mark.skipif(os.name != 'nt', reason='Windows private file publication')
def test_download_publication_refuses_newer_target_preserves_partial(tmp_path):
    job = tmp_path / 'no-overwrite'
    job.mkdir(mode=0o700)
    view, download = request()
    download.setDownloadDirectory(str(job)); download.accept()
    partial = Path(view.commands[-1][1]['path'])
    partial.write_bytes(b'synthetic exported bytes')
    target = job / 'reference.txt'
    target.write_bytes(b'newer destination')
    download.finish('completed')
    assert download.state() == download.DownloadState.DownloadInterrupted
    assert 'now exists' in download.interruptReasonString()
    assert target.read_bytes() == b'newer destination'
    assert partial.read_bytes() == b'synthetic exported bytes'


@pytest.mark.skipif(os.name != 'nt', reason='Windows private file publication')
def test_cancel_preserves_partial_and_never_publishes_late_success(tmp_path):
    job = tmp_path / 'cancelled'
    job.mkdir(mode=0o700)
    view, download = request()
    download.setDownloadDirectory(str(job)); download.accept()
    partial = Path(view.commands[-1][1]['path'])
    partial.write_bytes(b'incomplete synthetic bytes')
    download.cancel(); download.finish('completed')
    assert download.state() == download.DownloadState.DownloadCancelled
    assert not (job / 'reference.txt').exists()
    assert partial.read_bytes() == b'incomplete synthetic bytes'


@pytest.mark.skipif(os.name != 'nt', reason='Windows retained file identity')
def test_publication_handle_denies_source_replacement_and_retains_identity(tmp_path):
    from desktop.windows_files import publication_handle, rename_by_handle, pinned_parents
    job = tmp_path / 'retained identity 日本語'
    job.mkdir(mode=0o700)
    source, other, final = job / 'partial', job / 'replacement', job / 'reference😀.txt'
    source.write_bytes(b'exact synthetic bytes')
    other.write_bytes(b'other bytes')
    with pinned_parents(final), publication_handle(source) as handle:
        with pytest.raises(OSError): os.replace(other, source)
        with pytest.raises(OSError): source.write_bytes(b'changed')
        rename_by_handle(handle, final)
    assert final.read_bytes() == b'exact synthetic bytes'
    assert other.read_bytes() == b'other bytes'


@pytest.mark.skipif(os.name != 'nt', reason='Windows retained file identity')
def test_atomic_rename_refuses_existing_final_and_hardlink_source(tmp_path):
    from desktop.windows_files import publication_handle, rename_by_handle, pinned_parents
    job = tmp_path / 'rename never replaces'
    job.mkdir(mode=0o700)
    source, final = job / 'partial', job / 'final'
    source.write_bytes(b'original')
    with pinned_parents(final), publication_handle(source) as handle:
        final.write_bytes(b'newer final')
        with pytest.raises(OSError): rename_by_handle(handle, final)
    assert final.read_bytes() == b'newer final' and source.read_bytes() == b'original'
    os.link(source, job / 'hardlink')
    with pytest.raises(ValueError, match='singly linked'):
        with publication_handle(source): pytest.fail('Hard-linked source must not be accepted')


class PdfPage(QObject):
    pdfPrintingFinished = Signal(str, bool)


class PrintView(QObject):
    def _detach_position_filters(self): View._detach_position_filters(self)
    def __init__(self):
        super().__init__()
        self._prints, self._retiring, self.commands, self.results, self.notices = {}, False, [], [], []
        self.document = PdfPage(self)
        self.document.pdfPrintingFinished.connect(lambda path, ok: self.results.append((path, ok)))

    def page(self): return self.document
    def command(self, op, **values): self.commands.append((op, values))
    def _finish_print(self, path, ok, **kwargs): View._finish_print(self, path, ok, **kwargs)
    def _cancel_prints(self): View._cancel_prints(self)
    def _command_notice(self, message): self.notices.append(message)


@pytest.mark.skipif(os.name != 'nt', reason='Windows private PDF publication')
def test_pdf_print_uses_private_partial_and_atomic_exact_byte_publication(tmp_path):
    target = tmp_path / 'synthetic rendered 日本語😀.pdf'
    view = PrintView(); View.printToPdf(view, str(target))
    partial = Path(view.commands[-1][1]['path'])
    assert partial != target and partial.parent.parent == target.parent
    assert partial.parent.name.startswith('.p-')
    with pytest.raises(OSError): partial.parent.rename(tmp_path / 'substituted-print')
    content = b'%PDF-1.7\nSynthetic test bytes\n%%EOF\n'
    partial.write_bytes(content)
    View._event(view, {'event': 'print-finished', 'path': str(partial), 'ok': True})
    assert view.results == [(str(target), True)]
    assert target.read_bytes() == content and not partial.exists()
    assert not view._prints
    partial.parent.rename(tmp_path / 'unpinned-completed-print')


@pytest.mark.skipif(os.name != 'nt', reason='Windows private PDF publication')
def test_pdf_existing_target_is_refused_before_native_print(tmp_path):
    target = tmp_path / 'existing.pdf'; target.write_bytes(b'newer file')
    view = PrintView(); View.printToPdf(view, str(target))
    assert view.results == [(str(target), False)] and not view.commands and not view._prints
    assert target.read_bytes() == b'newer file'


@pytest.mark.skipif(os.name != 'nt', reason='Windows private PDF publication')
def test_pdf_planted_final_is_not_overwritten_and_partial_is_preserved(tmp_path):
    target = tmp_path / 'print.pdf'
    view = PrintView(); View.printToPdf(view, str(target))
    partial = Path(view.commands[-1][1]['path']); partial.write_bytes(b'%PDF-1.7\noriginal')
    target.write_bytes(b'newer destination')
    View._event(view, {'event': 'print-finished', 'path': str(partial), 'ok': True})
    assert view.results == [(str(target), False)]
    assert target.read_bytes() == b'newer destination' and partial.read_bytes() == b'%PDF-1.7\noriginal'


@pytest.mark.skipif(os.name != 'nt', reason='Windows private PDF publication')
@pytest.mark.parametrize('failure', ['native-failure', 'rpc-failure', 'empty-output', 'writer-held', 'hard-linked'])
def test_pdf_terminal_errors_preserve_evidence_and_ignore_late_success(tmp_path, failure):
    target = tmp_path / 'print.pdf'
    view = PrintView(); View.printToPdf(view, str(target))
    options = view.commands[-1][1]; partial = Path(options['path'])
    partial.write_bytes(b'' if failure == 'empty-output' else b'%PDF-1.7\nsynthetic bytes')
    writer = os.open(partial, os.O_RDWR | os.O_BINARY) if failure == 'writer-held' else None
    if failure == 'hard-linked': os.link(partial, partial.parent / 'hard-link')
    try:
        if failure == 'rpc-failure': options['on_error']({'message': 'Synthetic failure'})
        else: View._event(view, {'event': 'print-finished', 'path': str(partial), 'ok': failure != 'native-failure'})
    finally:
        if writer is not None: os.close(writer)
    View._event(view, {'event': 'print-finished', 'path': str(partial), 'ok': True})
    options['on_error']({'message': 'Late failure'})
    assert view.results == [(str(target), False)] and not target.exists() and partial.exists()
    partial.parent.rename(tmp_path / 'unpinned-failed-print')


@pytest.mark.skipif(os.name != 'nt', reason='Windows private PDF publication')
@pytest.mark.parametrize('cause', ['close', 'process-failure'])
def test_pdf_close_or_process_failure_releases_pins_without_publishing(tmp_path, cause):
    from PySide6.QtCore import QProcess
    target = tmp_path / 'print.pdf'
    view = PrintView(); View.printToPdf(view, str(target))
    partial = Path(view.commands[-1][1]['path']); partial.write_bytes(b'%PDF-1.7\npartial')
    if cause == 'close':
        view.process = SimpleNamespace(state=lambda: QProcess.ProcessState.Running)
        view._queue, view._serial, writes = [], 0, []
        view._write = writes.append
        View.deleteLater(view)
        assert writes == [{'id': 1, 'op': 'close'}]
    else:
        failures = []
        view._downloads, view._callbacks = {}, {}
        view.document.owner = SimpleNamespace(_closing=False, _fail=failures.append)
        View._failure(view, 'Synthetic renderer failure')
        assert failures == ['Synthetic renderer failure']
    # Failure feedback is terminal, but native printing may still be writing.
    # Retain directory identities until terminal acknowledgement or host exit.
    with pytest.raises(OSError): partial.parent.rename(tmp_path / 'must-remain-pinned')
    View._event(view, {'event': 'print-finished', 'path': str(partial), 'ok': True})
    assert view.results == [(str(target), False)] and not target.exists() and partial.exists()
    partial.parent.rename(tmp_path / 'unpinned-terminal-print')


@pytest.mark.skipif(os.name != 'nt', reason='Windows retained browser storage')
def test_webview_storage_and_ancestors_remain_pinned_until_native_retirement(tmp_path):
    from contextlib import ExitStack
    from desktop.webview2_browser import private_storage
    base = tmp_path / 'private storage 日本語'; base.mkdir(mode=0o700)
    pins = ExitStack()
    storage = private_storage(str(base), pins=pins)
    for path in (base, storage):
        with pytest.raises(OSError): path.rename(tmp_path / 'substituted-storage')
    pins.close()
    storage.rename(base / 'released-webview2')
    base.rename(tmp_path / 'released-root')


@pytest.mark.skipif(os.name != 'nt', reason='Windows restored browser storage')
def test_missing_storage_after_restore_is_recreated_under_pinned_private_parent(tmp_path):
    from contextlib import ExitStack
    from desktop.webview2_browser import private_storage
    from desktop.windows_files import owned
    parent = tmp_path / 'restored web 日本語'; parent.mkdir(mode=0o700)
    previous = parent / 'storage'; previous.mkdir(mode=0o700)
    (previous / 'synthetic-old-evidence').write_bytes(b'quarantined evidence remains unchanged')
    quarantine = parent / 'quarantined-storage'; previous.rename(quarantine)
    with ExitStack() as pins:
        storage = private_storage(str(previous), pins=pins)
        assert storage == previous / 'webview2' and storage.is_dir()
        owned(previous, private=True); owned(storage, private=True)
        with pytest.raises(OSError): parent.rename(tmp_path / 'substituted-parent')
        with pytest.raises(OSError): previous.rename(parent / 'substituted-storage')
        assert (quarantine / 'synthetic-old-evidence').read_bytes() == b'quarantined evidence remains unchanged'
    assert sorted(p.name for p in previous.iterdir()) == ['webview2']


@pytest.mark.skipif(os.name != 'nt', reason='Windows restore-to-fresh browser root invariant')
def test_restore_quarantine_then_actual_start_recreates_both_capture_roots(tmp_path, monkeypatch):
    from contextlib import ExitStack
    import uuid
    from desktop import transition
    from desktop import webview2_browser as adapter
    from desktop.windows_browser_quarantine import root_ids
    from desktop.windows_files import owned
    root = tmp_path / 'restored profile 日本語'; root.mkdir(mode=0o700)
    parent = root / 'web'; parent.mkdir(mode=0o700)
    paths = {'root': root, 'web_storage': parent / 'storage', 'web_cache': parent / 'cache'}
    for key in ('web_storage', 'web_cache'):
        paths[key].mkdir(mode=0o700)
        (paths[key] / 'old-browser-evidence').write_bytes(key.encode())
    for key in ('durable-actions', 'pending-requests'): (root / key).mkdir(mode=0o700)
    prior = root_ids(paths)
    record = {'old_epoch': str(uuid.uuid4()), 'token': uuid.uuid4().hex,
              'profile_uuid': str(uuid.uuid4()), 'moved': {}}
    transition._quarantine(paths, record)  # Actual completed-adoption directory lifecycle.
    assert all(not paths[key].exists() for key in ('web_storage', 'web_cache'))
    observed = {}
    class HostBoundary(RuntimeError): pass
    def before_host():
        observed.update(root_ids(paths))  # The exact identity operation fresh capture requires.
        for key in ('web_storage', 'web_cache'):
            owned(paths[key], private=True)
            with pytest.raises(OSError): paths[key].rename(parent / ('replaced-' + key))
        with pytest.raises(OSError): parent.rename(root / 'substituted-web-parent')
        raise HostBoundary('Stop before launching any host or GUI')
    monkeypatch.setattr(adapter, 'host_executable', before_host)
    pins = ExitStack()
    profile = SimpleNamespace(storage=str(paths['web_storage']), cache=str(paths['web_cache']))
    fake = SimpleNamespace(process=None, page=lambda: SimpleNamespace(owner=SimpleNamespace(mode='local'), profile=profile),
                           _storage_pins=pins)
    with pytest.raises(HostBoundary): View._start(fake)
    assert set(observed) == {'web_storage', 'web_cache'} and observed != prior
    assert list(paths['web_cache'].iterdir()) == []
    retained = root / 'quarantine' / record['old_epoch'] / ('adoption-' + record['token'])
    assert root_ids({key: retained / key for key in ('web_storage', 'web_cache')}) == prior
    for key in ('web_storage', 'web_cache'):
        assert (retained / key / 'old-browser-evidence').read_bytes() == key.encode()
        paths[key].rename(parent / ('released-' + key))  # Failed pre-launch preparation releases owned pins.


@pytest.mark.skipif(os.name != 'nt', reason='Windows pinned cache root')
def test_existing_cache_bytes_and_identity_are_preserved_until_retirement(tmp_path):
    from contextlib import ExitStack
    from desktop.webview2_browser import private_root
    from desktop.windows_browser_quarantine import root_ids
    parent = tmp_path / 'web'; parent.mkdir(mode=0o700)
    cache = parent / 'cache'; cache.mkdir(mode=0o700)
    (cache / 'existing.bin').write_bytes(b'unchanged cache evidence')
    original = root_ids({'web_storage': cache, 'web_cache': cache})['web_cache']
    with ExitStack() as pins:
        assert private_root(str(cache), pins=pins) == cache
        assert root_ids({'web_storage': cache, 'web_cache': cache})['web_cache'] == original
        assert (cache / 'existing.bin').read_bytes() == b'unchanged cache evidence'
        with pytest.raises(OSError): cache.rename(parent / 'replaced-cache')
    cache.rename(parent / 'released-cache')


@pytest.mark.skipif(os.name != 'nt', reason='Windows restored cache safety')
@pytest.mark.parametrize('invalid', ['missing-parent', 'file', 'junction', 'unsafe-parent', 'unsafe-root', 'foreign-owner'])
def test_restored_cache_refuses_unsafe_roots_before_native_host(tmp_path, monkeypatch, invalid):
    from contextlib import ExitStack
    import subprocess
    from desktop import webview2_browser as adapter
    from desktop import windows_files
    parent = tmp_path / 'web'; parent.mkdir(mode=0o700)
    storage = parent / 'storage'; cache = parent / 'cache'
    link = acl = None
    if invalid == 'missing-parent': cache = tmp_path / 'missing web' / 'cache'
    elif invalid == 'file': cache.write_bytes(b'not a directory')
    elif invalid == 'junction':
        outside = tmp_path / 'outside'; outside.mkdir(mode=0o700)
        (outside / 'sentinel').write_bytes(b'untouched')
        subprocess.run(['cmd.exe', '/c', 'mklink', '/J', str(cache), str(outside)], capture_output=True, check=True)
        link = cache
    elif invalid in {'unsafe-parent', 'unsafe-root'}:
        if invalid == 'unsafe-root': cache.mkdir(mode=0o700)
        acl = parent if invalid == 'unsafe-parent' else cache
        subprocess.run(['icacls.exe', str(acl), '/grant', '*S-1-1-0:(OI)(CI)R'], capture_output=True, check=True)
    else:
        original = windows_files.owned
        def owner(path, **kwargs):
            if Path(path) == cache: raise ValueError('Windows object is owned by another account')
            return original(path, **kwargs)
        monkeypatch.setattr(windows_files, 'owned', owner)
    monkeypatch.setattr(adapter, 'host_executable', lambda: pytest.fail('Unsafe cache must not start the native host'))
    fake = SimpleNamespace(process=None, _storage_pins=ExitStack(),
        page=lambda: SimpleNamespace(owner=SimpleNamespace(mode='local'),
            profile=SimpleNamespace(storage=str(storage), cache=str(cache))))
    try:
        with pytest.raises((OSError, ValueError)): View._start(fake)
        assert not fake._storage_pins._exit_callbacks
        if invalid == 'missing-parent': assert not cache.parent.exists()
        if invalid == 'file': assert cache.read_bytes() == b'not a directory'
        if invalid == 'junction': assert list(outside.iterdir()) == [outside / 'sentinel']
        if invalid == 'unsafe-parent': assert not cache.exists()
    finally:
        if link: link.rmdir()
        if acl: subprocess.run(['icacls.exe', str(acl), '/remove:g', '*S-1-1-0'], capture_output=True, check=True)


def test_browser_start_requires_explicit_cache_without_path_inference(monkeypatch):
    from contextlib import ExitStack
    from desktop import webview2_browser as adapter
    monkeypatch.setattr(adapter, 'private_storage', lambda *a, **k: pytest.fail('Missing cache must refuse before any creation'))
    fake = SimpleNamespace(process=None, _storage_pins=ExitStack(),
        page=lambda: SimpleNamespace(owner=SimpleNamespace(mode='local'),
            profile=SimpleNamespace(storage='explicit-storage', cache=None)))
    with pytest.raises(ValueError, match='storage/cache'): View._start(fake)


@pytest.mark.skipif(os.name != 'nt', reason='Windows storage reparse refusal')
@pytest.mark.parametrize('alias', ['storage', 'webview2'])
def test_restored_storage_refuses_planted_junction_without_outside_writes(tmp_path, alias):
    import subprocess
    from contextlib import ExitStack
    from desktop.webview2_browser import private_storage
    parent = tmp_path / 'web'; parent.mkdir(mode=0o700)
    outside = tmp_path / 'outside'; outside.mkdir(mode=0o700)
    (outside / 'sentinel').write_bytes(b'unmodified synthetic outside directory')
    root = parent / 'storage'
    if alias == 'webview2': root.mkdir(mode=0o700)
    link = root if alias == 'storage' else root / 'webview2'
    subprocess.run(['cmd.exe', '/c', 'mklink', '/J', str(link), str(outside)], capture_output=True, check=True)
    try:
        with ExitStack() as pins, pytest.raises(ValueError, match='reparse'):
            private_storage(str(root), pins=pins)
        assert [p.name for p in outside.iterdir()] == ['sentinel']
        assert (outside / 'sentinel').read_bytes() == b'unmodified synthetic outside directory'
    finally:
        link.rmdir()


@pytest.mark.skipif(os.name != 'nt', reason='Windows private parent DACL refusal')
def test_missing_storage_refuses_public_parent_before_creating_leaf(tmp_path):
    import subprocess
    from contextlib import ExitStack
    from desktop.webview2_browser import private_storage
    parent = tmp_path / 'synthetic public parent'; parent.mkdir(mode=0o700)
    root = parent / 'storage'
    # Only this disposable fixture's ACL is changed; no host/global policy.
    subprocess.run(['icacls.exe', str(parent), '/grant', '*S-1-1-0:(OI)(CI)R'], capture_output=True, check=True)
    try:
        with ExitStack() as pins, pytest.raises(ValueError, match='another account'):
            private_storage(str(root), pins=pins)
        assert not root.exists()
    finally:
        subprocess.run(['icacls.exe', str(parent), '/remove:g', '*S-1-1-0'], capture_output=True, check=True)


@pytest.mark.skipif(os.name != 'nt', reason='Windows exact missing storage leaf')
def test_storage_creation_never_recursively_creates_missing_ancestors(tmp_path):
    from contextlib import ExitStack
    from desktop.webview2_browser import private_storage
    missing = tmp_path / 'missing parent'
    with ExitStack() as pins, pytest.raises(OSError):
        private_storage(str(missing / 'storage'), pins=pins)
    assert not missing.exists()


@pytest.mark.skipif(os.name != 'nt', reason='Windows retained staging identity')
@pytest.mark.parametrize('cause', ['cancel', 'timeout', 'native-rpc-error'])
def test_download_terminal_feedback_retains_pins_until_writer_acknowledgement(tmp_path, cause):
    job = tmp_path / cause; job.mkdir(mode=0o700)
    view, download = request(); download.setDownloadDirectory(str(job)); download.accept()
    options = view.commands[-1][1]; partial = Path(options['path']); partial.write_bytes(b'incomplete synthetic bytes')
    if cause == 'cancel': download.cancel()
    elif cause == 'timeout': download._timeout()
    else: options['on_error']({'message': 'Synthetic native rejection'})
    assert download.isFinished() and download._native_pending and not (job / 'reference.txt').exists()
    with pytest.raises(OSError): job.rename(tmp_path / 'must-remain-pinned')
    previous = download.state()
    download.finish('completed')  # acknowledgement releases; forbidden success stays forbidden
    assert download.state() == previous and not (job / 'reference.txt').exists()
    assert partial.read_bytes() == b'incomplete synthetic bytes'
    job.rename(tmp_path / 'retired-staging')


@pytest.mark.skipif(os.name != 'nt', reason='Windows retained staging identity')
def test_print_rpc_failure_pins_until_native_writer_acknowledgement(tmp_path):
    target = tmp_path / 'render.pdf'
    view = PrintView(); View.printToPdf(view, str(target))
    options = view.commands[-1][1]; partial = Path(options['path']); partial.write_bytes(b'%PDF-partial')
    options['on_error']({'message': 'Synthetic RPC failure'})
    assert view.results == [(str(target), False)] and str(partial) in view._prints
    with pytest.raises(OSError): partial.parent.rename(tmp_path / 'must-remain-pinned')
    View._event(view, {'event': 'print-finished', 'path': str(partial), 'ok': True})
    assert view.results == [(str(target), False)] and not target.exists() and not view._prints
    partial.parent.rename(tmp_path / 'retired-print')


def test_browser_exit_without_matching_retirement_is_not_clean(monkeypatch):
    import desktop.webview2_browser as adapter
    from PySide6.QtWidgets import QWidget
    released, deleted, failures = [], [], []
    fake = SimpleNamespace(_host_started=True, _retiring=True, _ready=True,
                           _browser_exit_pid=123, _retired_pid=None, runtime_info={'pid': 123},
                           _read=lambda: None, _read_error=lambda: None,
                           _deadline=SimpleNamespace(stop=lambda: None), _failure=failures.append,
                           _release_retired_resources=lambda: released.append(True))
    fake._retirement_confirmed = lambda: View._retirement_confirmed(fake)
    monkeypatch.setattr(QWidget, 'deleteLater', lambda value: deleted.append(True))
    View._exited(fake, 0, None)
    assert failures and not released and not deleted
    fake._retired_pid = 999
    assert not fake._retirement_confirmed()
    fake._retired_pid = 123
    View._exited(fake, 0, None)
    assert released == [True] and deleted == [True]


@pytest.mark.skipif(os.name != 'nt', reason='Windows retained native resources')
def test_confirmed_native_retirement_finalizes_all_outputs_and_storage(tmp_path):
    from contextlib import ExitStack
    from desktop.webview2_browser import private_storage, private_root
    view = PrintView(); view._storage_pins = ExitStack()
    base = tmp_path / 'storage'; base.mkdir(mode=0o700)
    storage = private_storage(str(base), pins=view._storage_pins)
    cache = private_root(str(tmp_path / 'cache'), pins=view._storage_pins)
    with pytest.raises(OSError): cache.rename(tmp_path / 'must-remain-pinned-cache')
    target = tmp_path / 'retired.pdf'; View.printToPdf(view, str(target))
    partial = Path(view.commands[-1][1]['path']); partial.write_bytes(b'%PDF-partial')
    job = tmp_path / 'download'; job.mkdir(mode=0o700)
    download = Download(view, {'download_id': 'retired', 'url': 'https://synthetic.invalid/file', 'name': 'reference.txt'})
    download.setDownloadDirectory(str(job)); download.accept()
    view._downloads = {'retired': download}
    View._release_retired_resources(view)
    assert download.state() == download.DownloadState.DownloadInterrupted and not download.timer.isActive()
    assert view.results == [(str(target), False)] and not view._prints and not target.exists()
    job.rename(tmp_path / 'released-download')
    partial.parent.rename(tmp_path / 'released-print')
    storage.rename(base / 'released-storage')
    cache.rename(tmp_path / 'released-cache')


def test_attachment_declined_notice_requires_current_navigation_and_confirmed_attachment_response():
    notices = []
    owner = SimpleNamespace(_closing=False)
    fake = SimpleNamespace(_active_generation=4, _active_navigation=12, _command_notice=notices.append,
                           _retiring=False, page=lambda: SimpleNamespace(owner=owner))
    owner.view = fake
    event = {'event': 'attachment-declined', 'generation': 4, 'nav_id': 12,
             'http_status': 200, 'reason': 'automatic-downloads-denied'}
    for stale in ({'generation': 3}, {'nav_id': 11}, {'http_status': 503}, {'reason': 'untrusted text'}):
        View._event(fake, event | stale)
    View._event(fake, {key: value for key, value in event.items() if key != 'generation'})
    assert not notices
    View._event(fake, event)
    assert len(notices) == 1 and 'no new file was saved' in notices[0]


def test_server_cover_is_a_closed_owner_command_without_page_privileges():
    calls = []
    owner = SimpleNamespace(mode='server', _closing=False)
    fake = SimpleNamespace(_retiring=False, page=lambda: SimpleNamespace(owner=owner),
                           command=lambda *a, **kw: calls.append((a, kw)))
    owner.view = fake
    View.setServerCover(fake, True, 'Synthetic unavailable message', False)
    assert calls == [(('cover',), {'shown': True, 'text': 'Synthetic unavailable message', 'browser_visible': False})]
    owner.mode = 'local'; View.setServerCover(fake, True, 'must be refused', True)
    owner.mode = 'server'; owner.view = None; View.setServerCover(fake, True, 'must be refused', True)
    owner.view = fake; fake._retiring = True; View.setServerCover(fake, True, 'must be refused', True)
    assert len(calls) == 1

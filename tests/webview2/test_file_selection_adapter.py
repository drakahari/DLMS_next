"""Native selection controller tests; no browser, backend or personal files."""
import os
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

if os.name != 'nt':
    pytest.skip('Windows selection contract', allow_module_level=True)

from PySide6.QtCore import QObject, QUrl
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox
from PySide6.QtWebEngineCore import QWebEnginePage

from desktop import webview2_file_selection as fs


@pytest.fixture(scope='module', autouse=True)
def application():
    app = QApplication.instance() or QApplication([])
    yield app


class Page(QObject):
    def __init__(self, owner):
        super().__init__()
        self.owner, self.href, self.loading = owner, 'https://synthetic.invalid/library', False
    def url(self): return QUrl(self.href)
    def isLoading(self): return self.loading


class View(QObject):
    def __init__(self):
        super().__init__()
        self._active_generation, self._active_navigation = 2, 7
        self._selection_store, self._pending_file_selections = None, {}
    def page(self): return self.current_page


def owner(tmp_path):
    w = QMainWindow()
    for key, value in dict(mode='server', mode_config={'server': {'origin': 'https://synthetic.invalid', 'id': 'test'}},
                          manifest=None, paths={'root': tmp_path / 'absent-local', 'tmp': tmp_path / 'tmp', 'downloads': tmp_path / 'downloads'},
                          server_paths={'root': tmp_path}, profile_name='synthetic', _browser_generation=1,
                          _server_navigation_serial=4, _browser_dialog_depth=0, _close_after_dialog=False,
                          file_selection_for_test=None, documents_folder=tmp_path / 'Configured Documents',
                          selection_private_roots=(tmp_path / 'AppData',), messages=[], feedback_serial=0).items(): setattr(w, key, value)
    w.view = View(); w.view.current_page = Page(w)
    def begin(kind):
        w.feedback_serial += 1
        return w.feedback_serial
    def feedback(ticket, message, severity='info'):
        if ticket != w.feedback_serial: return False
        w.messages.append((message, severity)); return True
    w._begin_feedback, w._feedback = begin, feedback
    return w


class Batch:
    def __init__(self):
        self.files = (SimpleNamespace(name='Z ü.txt'), SimpleNamespace(name='a.csv'))
        self.total_bytes, self.closed = 12, False
    def close(self): self.closed = True; return ()


class Store:
    def __init__(self): self.discarded, self.closed = [], False
    def discard(self, value): self.discarded.append(value); return ()
    def close(self): self.closed = True; return ()


@pytest.fixture
def selection(tmp_path, monkeypatch):
    w, batch, store, calls = owner(tmp_path), Batch(), Store(), []
    snapshots = (SimpleNamespace(path=tmp_path / 'private' / 'Z ü.txt'), SimpleNamespace(path=tmp_path / 'private' / 'a.csv'))
    def capture(paths, **kwargs): calls.append(('capture', paths, kwargs)); return batch
    primitive = SimpleNamespace(capture=capture, SelectionCanceled=type('Canceled', (ValueError,), {}))
    monkeypatch.setattr(fs, '_primitive', lambda: primitive)
    monkeypatch.setattr(fs, 'protected_roots', lambda w: (('protected',), ()))
    def get_store(view, context): view._selection_store = store; return store
    monkeypatch.setattr(fs, '_store', get_store)
    monkeypatch.setattr(fs, '_stage', lambda *args: snapshots)
    monkeypatch.setattr(fs, '_consent', lambda context, batch: calls.append(('consent',)) or True)
    monkeypatch.setattr(fs, '_warning', lambda context, ticket, message: fs._feedback(context, ticket, message, 'error'))
    w.file_selection_for_test = ['Z ü.txt', 'a.csv']
    return w, batch, store, snapshots, calls


def choose(w, ticket=9):
    return fs.choose_files(w.view.page(), QWebEnginePage.FileSelectionMode.FileSelectOpenMultiple, [], ['.exe'], ticket=ticket,
                           requested_url=w.view.page().href)


def test_fresh_server_context_does_not_create_local_profile(tmp_path):
    w = owner(tmp_path)
    context = fs.SelectionContext.capture(w.view.page())
    assert context.valid() and context.identity == (None, None)
    assert not w.paths['root'].exists()


@pytest.mark.parametrize('change', ['url', 'origin', 'page', 'browser', 'generation', 'nav', 'servernav', 'mode', 'profile',
                                   '_closing', '_close_after_dialog', '_retiring_browser', 'failed_reason',
                                   '_import_reopen_status', 'maintenance_transition', 'import_worker', '_browser_operation_depth'])
def test_context_rejects_each_stale_boundary(tmp_path, change):
    w = owner(tmp_path); context = fs.SelectionContext.capture(w.view.page())
    if change == 'url': w.view.page().href += '?new=1'
    elif change == 'origin': w.mode_config['server']['origin'] = 'https://other.invalid'
    elif change == 'page': w.view.current_page = Page(w)
    elif change == 'browser': w._browser_generation += 1
    elif change == 'generation': w.view._active_generation += 1
    elif change == 'nav': w.view._active_navigation += 1
    elif change == 'servernav': w._server_navigation_serial += 1
    elif change == 'mode': w.mode = 'local'
    elif change == 'profile': w.profile_name = 'other'
    else: setattr(w, change, True)
    assert not context.valid()


def test_exact_consent_is_plain_text_and_cancel_default(tmp_path, monkeypatch):
    w, batch, state = owner(tmp_path), Batch(), {}
    class Box:
        StandardButton = QMessageBox.StandardButton
        def __init__(self, parent): pass
        def setWindowTitle(self, value): state['title'] = value
        def setTextFormat(self, value): state['format'] = value
        def setText(self, value): state['text'] = value
        def setStandardButtons(self, value): state['buttons'] = value
        def setDefaultButton(self, value): state['default'] = value
        def setEscapeButton(self, value): state['escape'] = value
        def exec(self): return self.StandardButton.Cancel
    monkeypatch.setattr(fs, 'QMessageBox', Box)
    assert not fs._consent(fs.SelectionContext.capture(w.view.page()), batch)
    assert state['title'] == 'Allow selected files for this Server?'
    assert state['text'] == 'https://synthetic.invalid\n\nZ ü.txt\na.csv\n\n' + fs.CONSENT_WARNING
    assert state['format'] == fs.Qt.TextFormat.PlainText
    assert state['default'] == state['escape'] == QMessageBox.StandardButton.Cancel
    assert state['buttons'] == QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel


def test_capture_before_consent_and_success_only_after_native_receipt(selection):
    w, batch, store, snapshots, calls = selection
    paths = choose(w)
    assert [x[0] for x in calls] == ['capture', 'consent']
    assert paths == [str(x.path) for x in snapshots] and batch.closed
    assert w.messages == [] and w._browser_dialog_depth == 0
    assert fs.prepare_handback(w.view, 9, paths) == paths
    fs.handback_complete(w.view, 9, success=True, result={'files_applied': True, 'files_exposed': True})
    assert w.messages == [(fs.SUCCESS, 'info')] and not store.closed and not store.discarded
    w.view.page().href += '?navigation=1'
    assert not store.closed
    assert fs.retire(w.view) == () and store.closed


def test_server_default_cancel_captures_but_never_stages(selection, monkeypatch):
    w, batch, store, snapshots, calls = selection
    monkeypatch.setattr(fs, '_consent', lambda *args: False)
    monkeypatch.setattr(fs, '_stage', lambda *args: pytest.fail('No staging before consent'))
    assert choose(w) == [] and batch.closed
    assert w.messages == [(fs.SERVER_CANCELED, 'info')] and w.view._selection_store is None


@pytest.mark.parametrize('phase', ['chooser', 'consent', 'staging', 'handback'])
def test_stale_context_discards_only_new_unexposed_batch(selection, monkeypatch, phase):
    w, batch, store, snapshots, calls = selection
    if phase == 'chooser':
        w.file_selection_for_test = None
        def chooser(*args): w._close_after_dialog = True; return ['x.txt'], ''
        monkeypatch.setattr(fs.QFileDialog, 'getOpenFileNames', chooser)
        # Avoid queued close delivery after browser_dialog unwinds in this unit.
        monkeypatch.setattr(fs.QTimer, 'singleShot', lambda *args: None)
    elif phase == 'consent':
        def consent(*args): w.view._active_generation += 1; return True
        monkeypatch.setattr(fs, '_consent', consent)
    elif phase == 'staging':
        def stage(*args): w.view._active_generation += 1; return snapshots
        monkeypatch.setattr(fs, '_stage', stage)
    paths = choose(w)
    if phase == 'handback':
        w.view._active_generation += 1
        assert fs.prepare_handback(w.view, 9, paths) == []
    else: assert paths == []
    assert batch.closed and not w.messages and not store.closed
    assert store.discarded == ([snapshots] if phase in ('staging', 'handback') else [])


@pytest.mark.parametrize('exposed', [False, True, None])
def test_uncertain_native_failure_keeps_seals_and_never_claims_save(selection, exposed):
    w, batch, store, snapshots, calls = selection
    paths = choose(w); fs.prepare_handback(w.view, 9, paths)
    fs.handback_complete(w.view, 9, success=False, result={'files_exposed': exposed})
    assert store.discarded == ([snapshots] if exposed is False else [])
    assert w.messages[-1][1] == 'error' and 'No application save was confirmed' in w.messages[-1][0]
    assert not store.closed


def test_late_success_cannot_replace_newer_feedback(selection):
    w, _, _, _, _ = selection
    paths = choose(w); fs.prepare_handback(w.view, 9, paths)
    w._begin_feedback('newer')
    fs.handback_complete(w.view, 9, success=True, result={'files_applied': True})
    assert not w.messages


def test_new_invalid_batch_does_not_discard_earlier_files(selection, monkeypatch):
    w, batch, store, snapshots, calls = selection
    paths = choose(w); fs.prepare_handback(w.view, 9, paths)
    fs.handback_complete(w.view, 9, success=True, result={'files_applied': True})
    w.file_selection_for_test = ['invalid.exe']
    def refused(*args, **kwargs): raise ValueError('Unsupported selected file type; choose a supported file.')
    monkeypatch.setattr(fs._primitive(), 'capture', refused)
    assert choose(w, 10) == []
    assert not store.discarded and not store.closed
    assert w.messages[-1][1] == 'error' and 'Unsupported' in w.messages[-1][0]
    assert w.messages[-1][0] not in (fs.CANCELED, fs.SERVER_CANCELED)


def test_local_uuid_epoch_change_invalidates_captured_context(tmp_path, monkeypatch):
    w = owner(tmp_path); w.mode, w.port, w.backend = 'local', 51922, SimpleNamespace(poll=lambda: None)
    w.view.page().href = 'http://127.0.0.1:51922/'
    identity = [('uuid', 2), ('uuid', 2)]
    monkeypatch.setattr(fs, '_identity', lambda owner: tuple(identity))
    context = fs.SelectionContext.capture(w.view.page())
    identity[:] = [('uuid', 3), ('uuid', 3)]
    assert not context.valid()


def test_failure_warning_owns_native_modal_stack(tmp_path, monkeypatch):
    w, seen = owner(tmp_path), []
    context = fs.SelectionContext.capture(w.view.page()); ticket = w._begin_feedback('file_selection')
    class Box:
        StandardButton = QMessageBox.StandardButton
        def __init__(self, parent): pass
        def setWindowTitle(self, value): pass
        def setTextFormat(self, value): assert value == fs.Qt.TextFormat.PlainText
        def setText(self, value): pass
        def setStandardButtons(self, value): pass
        def exec(self): seen.append(w._browser_dialog_depth)
    monkeypatch.setattr(fs, 'QMessageBox', Box)
    fs._warning(context, ticket, 'Actionable refusal')
    assert seen == [1] and w._browser_dialog_depth == 0


def test_configured_documents_chooser_start_and_cancel(selection, monkeypatch):
    w, batch, _, _, _ = selection
    w.file_selection_for_test = None
    starts = []
    monkeypatch.setattr(fs.QFileDialog, 'getOpenFileNames', lambda parent, title, start: starts.append(start) or ([], ''))
    assert choose(w) == [] and starts == [str(w.documents_folder)] and not batch.closed
    assert w.messages == [(fs.SERVER_CANCELED, 'info')]


def test_stage_worker_runs_off_ui_and_programmatic_teardown_does_not_cancel(tmp_path):
    w = owner(tmp_path); context = fs.SelectionContext.capture(w.view.page())
    caller, seen = threading.get_ident(), []
    class WorkerStore:
        def stage(self, batch, *, cancel, progress):
            seen.append(threading.get_ident()); progress(12, 12)
            assert not cancel()
            return ('sealed',)
    assert fs._stage(context, WorkerStore(), Batch()) == ('sealed',)
    assert seen and seen[0] != caller


def test_stage_cooperates_with_real_progress_cancel_and_preserves_failure_kind(tmp_path, monkeypatch):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QProgressDialog
    from desktop.windows_file_selection import SelectionCanceled
    w = owner(tmp_path); context = fs.SelectionContext.capture(w.view.page())
    class CancelProgress(QProgressDialog):
        def show(self):
            super().show()
            QTimer.singleShot(0, self.cancel)
            QTimer.singleShot(0, self.canceled.emit)
    class WorkerStore:
        def stage(self, batch, *, cancel, progress):
            while not cancel(): threading.Event().wait(.005)
            raise SelectionCanceled('Canceled while staging')
    monkeypatch.setattr(fs, 'QProgressDialog', CancelProgress)
    with pytest.raises(SelectionCanceled): fs._stage(context, WorkerStore(), Batch())
    class FailedStore:
        def stage(self, *args, **kwargs): raise OSError('Synthetic disk write failure')
    # Worker failure remains a failure even if programmatic teardown emits a
    # dialog cancellation signal; the exception is the worker's exact result.
    with pytest.raises(OSError, match='Synthetic disk write failure'):
        fs._stage(context, FailedStore(), Batch())


def test_protected_roots_and_local_only_exceptions(tmp_path, monkeypatch):
    w = owner(tmp_path)
    monkeypatch.setattr(fs, '_known_private_roots', lambda: (tmp_path / 'AppData',))
    roots, exceptions = fs.protected_roots(w)
    assert fs.AREA in roots and fs.PROJECT / '.gate1' in roots and not exceptions
    w.mode = 'local'
    assert fs.protected_roots(w)[1] == (w.paths['tmp'], w.paths['downloads'])


def test_protected_roots_refuse_late_or_missing_metadata(tmp_path, monkeypatch):
    w = owner(tmp_path); w.selection_private_roots = None
    monkeypatch.setattr(fs, '_known_private_roots', lambda: pytest.fail('Never expand owner roots after isolation'))
    with pytest.raises(RuntimeError, match='before application isolation'): fs.protected_roots(w)


def test_long_new_snapshot_rejects_whole_batch_without_releasing_earlier_files_or_quota(tmp_path_factory, monkeypatch):
    from desktop import windows_file_selection as native
    from tests.webview2.test_browser_paths import private_parent, units
    base = tmp_path_factory.mktemp('selection-bounds')
    ordinary = base / 'ordinary'; ordinary.mkdir(mode=0o700)
    root = private_parent(base, 150)
    previous_source = ordinary / 'previous.txt'; previous_source.write_bytes(b'Previous immutable bytes\n')
    good_source = ordinary / 'new.txt'; good_source.write_bytes(b'New synthetic bytes\n')
    long_source = ordinary / ('y' * 30 + '.txt'); long_source.write_bytes(b'Overbound synthetic bytes\n')
    store = native.SnapshotStore(root)
    previous_batch = native.capture([previous_source])
    try: previous = store.stage(previous_batch)
    finally: previous_batch.close()
    baseline_bytes = native._launcher_bytes
    w = owner(base); w.view._selection_store = store
    w.file_selection_for_test = [str(good_source), str(long_source)]
    staged = []
    monkeypatch.setattr(fs, 'protected_roots', lambda owner: ((), ()))
    monkeypatch.setattr(fs, '_consent', lambda *args: True)
    def stage(context, value, batch):
        result = value.stage(batch); staged.extend(result); return result
    monkeypatch.setattr(fs, '_stage', stage)
    monkeypatch.setattr(fs, '_warning', lambda context, ticket, message: fs._feedback(context, ticket, message, 'error'))
    try:
        assert choose(w) == []
        assert len(staged) == 2 and units(staged[0].path) <= 239 < units(staged[1].path)
        assert store.snapshots == list(previous) and native._launcher_bytes == baseline_bytes
        assert all(not item.path.exists() for item in staged)
        assert previous[0].path.read_bytes() == b'Previous immutable bytes\n'
        with pytest.raises(OSError): previous[0].path.write_bytes(b'Forbidden mutation')
        assert w.view._pending_file_selections == {} and not store.closed
        assert w.messages[-1][1] == 'error' and 'shorter --data-root or filename' in w.messages[-1][0]
    finally:
        assert store.close() == () and native._launcher_bytes == baseline_bytes - previous[0].size


def test_final_handback_rechecks_all_snapshot_path_bounds(selection):
    w, batch, store, snapshots, calls = selection
    paths = choose(w)
    snapshots[1].path = Path('C:/') / ('x' * 234 + '😀.txt')
    assert fs.prepare_handback(w.view, 9, paths) == []
    assert store.discarded == [snapshots] and not w.view._pending_file_selections and not store.closed
    assert w.messages[-1][1] == 'error' and 'shorter --data-root or filename' in w.messages[-1][0]

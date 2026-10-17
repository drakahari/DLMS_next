"""Windows export publication/controller checks; no owner folders or input."""
from concurrent.futures import Future
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtWidgets import QApplication, QMainWindow

if os.name != 'nt':
    pytest.skip('Windows-only export destinations', allow_module_level=True)

from desktop import webview2_exports as exports
from desktop.webview2_browser import Download


@pytest.fixture(scope='module', autouse=True)
def application():
    app = QApplication.instance() or QApplication([])
    yield app


def directory(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


@pytest.mark.parametrize('name', ['quiz.txt', 'Library Reference 日本語.txt', 'quiz.zip', 'quiz.csv', 'quiz.apkg'])
def test_safe_names_preserve_exact_names(name):
    assert exports.safe_name(name) == name


@pytest.mark.parametrize('name', ['', '.', '..', '../quiz.txt', 'C:/quiz.txt', 'quiz:stream.txt', 'CON.txt', 'quiz .', 'nul', 'a\x00.txt', 'x' * 256])
def test_unsafe_names_are_refused(name):
    with pytest.raises(ValueError):
        exports.safe_name(name)


def test_preference_first_downloads_success_reopen_and_unavailable_fallback(tmp_path):
    root, documents, downloads, other = [directory(tmp_path / name) for name in ('profile', 'Documents', 'Downloads 日本語', 'Other')]
    forbidden = (root,)
    assert exports.initial_directory(root, (documents, downloads), forbidden=forbidden) == (downloads, '')
    exports.remember_directory(root, other, forbidden=forbidden)
    assert exports.initial_directory(root, (documents, downloads), forbidden=forbidden) == (other, '')
    # A separate call reads the private JSON again; no process-global cache.
    other.rmdir()
    initial, warning = exports.initial_directory(root, (documents, downloads), forbidden=forbidden)
    assert initial == downloads and 'unavailable' in warning


@pytest.mark.parametrize('payload', [b'x' * 4097, b'{bad', b'{}', b'{"version":true,"directory":"C:/"}', b'{"version":2,"directory":"C:/"}'])
def test_corrupt_or_unbounded_preferences_fall_back_without_rewrite(tmp_path, payload):
    root, docs, down = [directory(tmp_path / n) for n in ('profile', 'docs', 'downloads')]
    preference = root / exports.PREFERENCE
    preference.write_bytes(payload)
    assert exports.initial_directory(root, (docs, down), forbidden=(root,))[0] == down
    assert preference.read_bytes() == payload


def test_local_server_preferences_are_independent(tmp_path):
    local, server, docs, downloads, other = [directory(tmp_path / n) for n in ('local', 'server', 'docs', 'downloads', 'other')]
    exports.remember_directory(local, other, forbidden=(local, server))
    assert exports.initial_directory(server, (docs, downloads), forbidden=(local, server)) == (downloads, '')
    assert not (server / exports.PREFERENCE).exists()


def test_server_preference_is_bound_to_exact_server_identity_and_origin(tmp_path):
    root, docs, down, other = [directory(tmp_path / n) for n in ('server', 'docs', 'downloads', 'other')]
    exports.remember_directory(root, other, forbidden=(root,), scope='server:id:https://first.invalid:443')
    assert exports.initial_directory(root, (docs, down), forbidden=(root,), scope='server:id:https://first.invalid:443') == (other, '')
    fallback, warning = exports.initial_directory(root, (docs, down), forbidden=(root,), scope='server:id:https://second.invalid:443')
    assert fallback == down and warning


def test_destination_refuses_collision_managed_alias_and_reparse(tmp_path):
    target = directory(tmp_path / 'ordinary') / 'quiz.txt'
    selected = exports.select_destination(target, forbidden=(tmp_path / 'private',))
    assert selected['path'] == str(target) and selected['parent_identity']
    target.write_text('old')
    with pytest.raises(FileExistsError):
        exports.select_destination(target, forbidden=())
    with pytest.raises(ValueError, match='outside managed'):
        exports.select_destination(target, forbidden=(target.parent,))
    with pytest.raises(ValueError):
        exports.select_destination(target.parent / 'quiz.txt:stream', forbidden=())
    assert target.read_text() == 'old'


def test_frozen_output_protection_covers_whole_payload_not_only_internal(tmp_path, monkeypatch):
    from desktop import isolation
    payload = tmp_path / 'payload'
    monkeypatch.setattr(isolation, 'FROZEN', True)
    monkeypatch.setattr(isolation, 'PROJECT', payload / '_internal')
    monkeypatch.setattr('sys.executable', str(payload / 'DLMS-Desktop-WebView2.exe'))
    roots = exports.forbidden_roots(SimpleNamespace(selection_private_roots=(tmp_path / 'protected',)))
    assert payload in roots and payload / '_internal' in roots and tmp_path not in roots
    with pytest.raises(ValueError, match='outside managed'):
        exports.select_destination(payload / 'quiz.txt', forbidden=roots)


def test_generic_publication_exact_bytes_hash_and_late_collision(tmp_path):
    import hashlib
    from desktop.windows_backup_output import publish
    private, ordinary = [directory(tmp_path / n) for n in ('private', 'ordinary')]
    source, target = private / 'reference.txt', ordinary / 'reference.txt'
    content = b'Q: Synthetic?\r\nA: Alpha\r\nB: Beta\r\n'
    source.write_bytes(content)
    selection = exports.select_destination(target, forbidden=(private,))
    result = publish(source, selection)
    assert target.read_bytes() == content and result['sha256'] == hashlib.sha256(content).hexdigest()
    second = ordinary / 'second.txt'
    selection = exports.select_destination(second, forbidden=(private,))
    second.write_bytes(b'newer existing bytes')
    with pytest.raises(OSError):
        publish(source, selection)
    assert second.read_bytes() == b'newer existing bytes'
    assert not list(ordinary.glob('.dlms-backup-*.part'))


def test_generic_publication_refuses_replaced_parent_identity(tmp_path):
    from desktop.windows_backup_output import publish
    private, ordinary = [directory(tmp_path / n) for n in ('private', 'ordinary')]
    source, target = private / 'quiz.csv', ordinary / 'quiz.csv'
    source.write_bytes(b'Question,Choice\nSynthetic,First\n')
    selection = exports.select_destination(target, forbidden=(private,))
    ordinary.rename(tmp_path / 'retired-ordinary')
    directory(ordinary)
    with pytest.raises(ValueError, match='folder changed'):
        publish(source, selection)
    assert not target.exists()


class Request(QObject):
    isFinishedChanged = Signal()
    stateChanged = Signal(object)
    DownloadState = Download.DownloadState
    def __init__(self, page, name='reference.txt'):
        super().__init__()
        self._page, self.name, self.current = page, name, self.DownloadState.DownloadRequested
    def page(self): return self._page
    def downloadFileName(self): return self.name
    def setDownloadFileName(self, name): self.name = name
    def setDownloadDirectory(self, directory): self.directory = directory
    def state(self): return self.current
    def accept(self): self.current = self.DownloadState.DownloadInProgress
    def cancel(self): self.current = self.DownloadState.DownloadCancelled
    def interruptReasonString(self): return 'Synthetic transfer interrupted'
    def complete(self, content=b'Q: Synthetic?\nA: First\nB: Second\n'):
        (Path(self.directory) / self.name).write_bytes(content)
        self.current = self.DownloadState.DownloadCompleted
        self.stateChanged.emit(self.current)
        self.isFinishedChanged.emit()


class Executor:
    def submit(self, function, *args):
        future = Future()
        try: future.set_result(function(*args))
        except BaseException as exc: future.set_exception(exc)
        return future


def window(tmp_path, monkeypatch, mode='local'):
    root, server, docs, downloads, ordinary = [directory(tmp_path / n) for n in ('local', 'server', 'docs', 'downloads', 'ordinary')]
    w = QMainWindow()
    page = object()
    view = SimpleNamespace(page=lambda: page, _active_generation=5, _active_navigation=6,
                           url=lambda: QUrl('http://127.0.0.1:44444/library' if mode == 'local' else 'https://synthetic.invalid/library'),
                           setFocus=lambda *_: None)
    identity = {'uuid': 'uuid', 'epoch': 'epoch'}
    w.__dict__.update(mode=mode, view=view, manifest=identity, profile_name='synthetic', port=44444,
        backend=SimpleNamespace(poll=lambda: None), _browser_generation=3, _server_navigation_serial=7,
        _closing=False, _retiring_browser=None, _browser_dialog_depth=0, _browser_operation_depth=0,
        _close_after_dialog=False, download_results=[], downloaded_files=[],
        paths={'root': root, 'downloads': directory(root / 'downloads')},
        server_paths={'root': server, 'downloads': directory(server / 'downloads')},
        mode_config={'server': {'id': 'synthetic-server', 'origin': 'https://synthetic.invalid'}},
        selection_private_roots=(root, server), backup_chooser_folders=(docs, downloads),
        backup_selection_executor=Executor(), messages=[], serial=0)
    def begin(action):
        w.serial += 1
        return w.serial
    w._begin_feedback = begin
    w._feedback = lambda ticket, text, severity='info': w.messages.append((ticket, text, severity)) if ticket == w.serial else False
    monkeypatch.setattr('desktop.profile_state.read_manifest', lambda *a: identity.copy())
    return w, Request(page), ordinary


@pytest.mark.parametrize('mode', ['local', 'server'])
def test_success_uses_native_selected_destination_exact_bytes_remembers_and_no_path_to_renderer(tmp_path, monkeypatch, mode):
    w, request, ordinary = window(tmp_path, monkeypatch, mode)
    destination = ordinary / 'Export 日本語.txt'
    observed = []
    def chooser(owner, name, folders, **kwargs):
        observed.append((name, kwargs, owner._browser_dialog_depth, owner._browser_operation_depth))
        return str(destination), ''
    operation = exports.begin_export(w, request, local=mode == 'local', chooser=chooser)
    content = b'Q: Synthetic?\r\nA: First\r\nB: Second\r\n'
    request.complete(content)
    QApplication.processEvents()
    operation.poll()
    assert destination.read_bytes() == content
    assert w.download_results[0]['state'] == 'completed'
    assert w.download_results[0]['phase'] == 'publishing'
    assert Path(request.directory).is_relative_to((w.paths if mode == 'local' else w.server_paths)['downloads'])
    assert observed[0][1]['initial'] == w.backup_chooser_folders[1]
    assert observed[0][2:] == (1, 1)
    assert ('synthetic.invalid' in observed[0][1]['title']) == (mode == 'server')
    own = w.paths if mode == 'local' else w.server_paths
    other = w.server_paths if mode == 'local' else w.paths
    assert json.loads((own['root'] / exports.PREFERENCE).read_text())['directory'] == str(ordinary)
    assert not (other['root'] / exports.PREFERENCE).exists()
    assert 'completed:' in w.messages[-1][1]


@pytest.mark.parametrize('choice', ['cancel', 'exists', 'stale'])
def test_cancel_collision_or_stale_consent_does_not_publish_or_remember(tmp_path, monkeypatch, choice):
    w, request, ordinary = window(tmp_path, monkeypatch)
    target = ordinary / 'quiz.txt'
    if choice == 'exists': target.write_text('existing')
    def chooser(*args, **kwargs):
        if choice == 'stale': w.view._active_navigation += 1
        return ('' if choice == 'cancel' else str(target)), ''
    operation = exports.begin_export(w, request, local=True, chooser=chooser)
    request.complete(); QApplication.processEvents()
    assert operation.future is None
    assert w.download_results[0]['state'] == ('cancelled' if choice == 'cancel' else 'failed')
    assert not (w.paths['root'] / exports.PREFERENCE).exists()
    assert not target.exists() if choice != 'exists' else target.read_text() == 'existing'
    assert w._browser_dialog_depth == w._browser_operation_depth == 0


def test_interrupted_transfer_terminal_without_chooser_or_stale_feedback(tmp_path, monkeypatch):
    w, request, ordinary = window(tmp_path, monkeypatch)
    operation = exports.begin_export(w, request, local=True, chooser=lambda *a, **k: pytest.fail('chooser opened'))
    w.serial += 1
    before = list(w.messages)
    request.current = request.DownloadState.DownloadInterrupted
    request.stateChanged.emit(request.current)
    assert operation.record['state'] == 'failed' and operation.record['reason'] == 'Synthetic transfer interrupted'
    assert w.messages == before
    request.complete(); QApplication.processEvents()
    assert operation.record['state'] == 'failed' and not list(ordinary.iterdir())


def test_pending_dialog_refuses_nested_export_without_staging(tmp_path, monkeypatch):
    w, request, ordinary = window(tmp_path, monkeypatch)
    w._browser_dialog_depth = 1
    assert exports.begin_export(w, request, local=True) is None
    assert request.current == request.DownloadState.DownloadCancelled and not w.download_results


def test_completed_publication_after_context_change_records_outcome_without_remember_or_feedback(tmp_path, monkeypatch):
    w, request, ordinary = window(tmp_path, monkeypatch)
    pending = Future()
    w.backup_selection_executor = SimpleNamespace(submit=lambda *args: pending)
    target = ordinary / 'quiz.txt'
    operation = exports.begin_export(w, request, local=True, chooser=lambda *a, **k: (str(target), ''))
    request.complete(); QApplication.processEvents()
    assert operation.record['phase'] == 'publishing' and operation.record['state'] == 'in_progress'
    w.view._active_navigation += 1
    w.serial += 1
    previous = list(w.messages)
    pending.set_result({'path': str(target), 'bytes': 1, 'sha256': 'synthetic'})
    operation.poll()
    assert operation.record['state'] == 'completed'
    assert not (w.paths['root'] / exports.PREFERENCE).exists()
    assert w.messages == previous

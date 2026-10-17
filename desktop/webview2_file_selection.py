"""Explicit ordinary Windows selection for the private WebView2 host.

Only native main-frame picker tickets reach this module. Selected source handles
are captured before consent, and only sealed, page-owned private copies are sent
back over the owning process pipe. No directory is granted to page content.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import os
from pathlib import Path
import threading

from PySide6.QtCore import QEventLoop, QTimer, QUrl, Qt
from PySide6.QtWidgets import QFileDialog, QMessageBox, QProgressDialog
from PySide6.QtWebEngineCore import QWebEnginePage
from shiboken6 import isValid

from .browser_lifetime import browser_dialog
from .isolation import AREA, PROJECT
from .profile_state import MANIFEST, read_manifest
from .server_browser import exact_server_origin
from .webview2_paths import require_browser_path

SUCCESS = ('Selected private copies are ready for this form. Submit/review to save; '
           'choosing files alone does not save application data.')
CANCELED = 'File selection canceled. No new files were selected or submitted.'
SERVER_CANCELED = 'Server file access canceled. No new files were selected or submitted.'
CONSENT_TITLE = 'Allow selected files for this Server?'
CONSENT_WARNING = ('These selected copies become readable by this Server session, including its page content. '
                   'It may upload them immediately. Local data and recovery files remain private. '
                   'Continue only if you trust this exact destination.')


def _primitive():
    # Windows APIs are never imported into a Linux/Qt application path.
    from . import windows_file_selection
    return windows_file_selection


def _identity(owner):
    cached = getattr(owner, 'manifest', None)
    cached_id = (cached.get('uuid'), cached.get('epoch')) if cached else None
    # A fresh Server profile has no Local root/manifest. Reading its absence
    # must neither create Local directories nor start/adopt a Local backend.
    path = owner.paths['root'] / MANIFEST
    disk = read_manifest(owner.paths, owner.profile_name) if path.exists() else None
    disk_id = (disk.get('uuid'), disk.get('epoch')) if disk else None
    return cached_id, disk_id


def _state_allows_selection(owner):
    flags = ('_closing', '_close_active', '_close_after_dialog', '_mode_switch_busy', '_browser_operation_depth', '_settings_transition_refused',
             'import_in_progress', 'maintenance_transition', '_settings_action_busy', '_backup_creating')
    if any(getattr(owner, key, False) for key in flags): return False
    if (getattr(owner, '_retiring_browser', None) is not None or getattr(owner, 'failed_reason', None) is not None
            or any(getattr(owner, key, None) is not None for key in
                   ('import_worker', 'maintenance_worker', 'removal_worker', 'backup_output_future', '_import_reopen_status'))):
        return False
    if owner.mode == 'local':
        return owner.backend is not None and owner.backend.poll() is None
    return owner.mode == 'server'


@dataclass(frozen=True)
class SelectionContext:
    owner: object
    view: object
    page: object
    mode: str
    href: bytes
    origin: str
    server_id: str | None
    profile: str
    identity: tuple
    browser_generation: int
    navigation_generation: int
    navigation_id: int
    server_navigation: int

    @classmethod
    def capture(cls, page):
        owner = page.owner
        view = owner.view
        if view is None or view.page() is not page or not _state_allows_selection(owner):
            raise RuntimeError('The selected page is changing or unavailable. Reopen its chooser after the transition finishes.')
        url = page.url()
        if page.isLoading(): raise RuntimeError('Wait for this page to finish loading before selecting files.')
        if owner.mode == 'server':
            configured = owner.mode_config.get('server')
            if not configured or not exact_server_origin(url, configured['origin']):
                raise RuntimeError('The configured Server origin is not the current page.')
            origin, server_id = configured['origin'], configured['id']
        else:
            from .shell import allowed_internal
            if not allowed_internal(url, owner.port): raise RuntimeError('The owned Local page is unavailable.')
            origin, server_id = f'http://127.0.0.1:{owner.port}', None
        identity = _identity(owner)
        if owner.mode == 'local' and (identity[0] is None or identity[0] != identity[1]):
            raise RuntimeError('Local profile identity changed; reopen this profile before selecting files.')
        return cls(owner, view, page, owner.mode, bytes(url.toEncoded()), origin, server_id,
                   owner.profile_name, identity, owner._browser_generation,
                   view._active_generation, view._active_navigation,
                   getattr(owner, '_server_navigation_serial', 0))

    def valid(self):
        try:
            if not isValid(self.view) or not isValid(self.page): return False
            return SelectionContext.capture(self.page) == self
        except (RuntimeError, ValueError, OSError, AttributeError):
            return False


def _known_private_roots():
    """Known Folder metadata only; never enumerate/read personal directories."""
    import ctypes
    from ctypes import wintypes
    import uuid
    from .windows_processes import api
    get = api(ctypes.WinDLL('shell32'), 'SHGetKnownFolderPath', ctypes.c_long,
              wintypes.LPVOID, wintypes.DWORD, wintypes.HANDLE, ctypes.POINTER(wintypes.LPWSTR))
    release = api(ctypes.WinDLL('ole32'), 'CoTaskMemFree', None, wintypes.LPVOID)
    values = []
    for raw in ('f1b32785-6fba-4fcf-9d55-7b8e7f157091',  # LocalAppData
                '3eb685db-65f9-4cf6-a03a-e3ef65729f3d',  # RoamingAppData
                '5e6c858f-0e22-4760-9afe-ea3317b67173'):  # Profile
        folder = (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(raw).bytes_le)
        output = wintypes.LPWSTR()
        result = get(folder, 0, None, ctypes.byref(output))
        if result != 0:
            raise RuntimeError(f'Windows private-folder metadata is unavailable ({raw}, HRESULT 0x{result & 0xffffffff:08x}); file selection was refused.')
        try: values.append(Path(output.value))
        finally: release(output)
    local, roaming, home = values
    return (local, roaming, *(home / name for name in ('.codex', '.agents', '.aws', '.ssh', '.gnupg', '.config')))


def protected_roots(owner):
    captured = getattr(owner, 'selection_private_roots', None)
    if not isinstance(captured, tuple) or not captured or any(not isinstance(p, Path) or not p.is_absolute() for p in captured):
        raise RuntimeError('Windows private-folder protection metadata was not captured before application isolation. Close and reopen the application before choosing files.')
    roots = (AREA, PROJECT / '.gate1', *(PROJECT / name for name in ('.git', '.codex', '.agents', '.aws')),
             *captured)
    exceptions = () if owner.mode == 'server' else (owner.paths['tmp'], owner.paths['downloads'])
    return roots, exceptions


def _feedback(context, ticket, message, severity='info'):
    if context.valid(): return context.owner._feedback(ticket, message, severity)
    return False


def _warning(context, ticket, message):
    if not _feedback(context, ticket, message, 'error'): return
    box = QMessageBox(context.owner)
    box.setWindowTitle('File selection unavailable')
    box.setTextFormat(Qt.TextFormat.PlainText)
    box.setText(str(message))
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    with browser_dialog(context.owner):
        box.exec()


def consent_body(origin, names):
    return origin + '\n\n' + '\n'.join(names) + '\n\n' + CONSENT_WARNING


def _consent(context, batch):
    box = QMessageBox(context.owner)
    box.setWindowTitle(CONSENT_TITLE)
    box.setTextFormat(Qt.TextFormat.PlainText)
    box.setText(consent_body(context.origin, (item.name for item in batch.files)))
    box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(QMessageBox.StandardButton.Cancel)
    box.setEscapeButton(QMessageBox.StandardButton.Cancel)
    return box.exec() == QMessageBox.StandardButton.Yes


def _store(view, context):
    existing = getattr(view, '_selection_store', None)
    if existing is not None: return existing
    from .windows_files import assert_path, owned, pinned_parents
    parent = context.owner.paths['root'] if context.mode == 'local' else context.owner.server_paths['root']
    root = parent / 'selected'
    with pinned_parents(root):
        owned(parent, private=True)
        assert_path(root)
        root.mkdir(mode=0o700, exist_ok=True)
        owned(root, private=True)
        store = _primitive().SnapshotStore(root)
    view._selection_store = store
    return store


def _stage(context, store, batch):
    """Keep the dialog stack owned while a bounded/cancelable worker copies."""
    cancel, user_cancel = threading.Event(), threading.Event()
    progress = QProgressDialog('Preparing selected private copies…', 'Cancel', 0, 0, context.owner)
    progress.setWindowTitle('Preparing selected files')
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(0)
    progress.setAutoClose(False); progress.setAutoReset(False)
    loop, timer = QEventLoop(), QTimer(progress)
    timer.setInterval(40)
    state, lock = {'copied': 0, 'total': batch.total_bytes}, threading.Lock()
    def copied(current, total):
        with lock: state.update(copied=current, total=total)
    def canceled():
        user_cancel.set(); cancel.set()
    progress.canceled.connect(canceled)
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix='dlms-selected-input') as executor:
        future = executor.submit(store.stage, batch, cancel=cancel.is_set, progress=copied)
        def poll():
            if not context.valid(): cancel.set()
            if future.done(): loop.quit(); return
            if user_cancel.is_set():
                progress.setLabelText('Canceling private selection; waiting for cleanup…')
                progress.setCancelButton(None)
                progress.show()
            else:
                with lock: amount = state['copied']
                progress.setLabelText(f'Preparing private copies and checking selected bytes…\n{amount:,} bytes copied. No application data has been saved.')
        timer.timeout.connect(poll)
        progress.show(); timer.start(); poll()
        if not future.done(): loop.exec()
        timer.stop()
        # QProgressDialog.close/reset can emit canceled: only user cancellation
        # may classify the result. Disconnect solely for programmatic teardown.
        try: progress.canceled.disconnect(canceled)
        except RuntimeError: pass
        progress.close(); progress.deleteLater()
        return future.result()


@dataclass
class PendingSelection:
    context: SelectionContext
    ticket: int
    snapshots: tuple
    attempted: bool = False


def choose_files(page, mode, old_files, accepted_mime_types, *, ticket, requested_url=None):
    """One explicit main-frame chooser; MIME accept hints never grant access."""
    if os.name != 'nt': return []
    try: context = SelectionContext.capture(page)
    except (RuntimeError, ValueError, OSError): return []
    if not ticket or (requested_url is not None and bytes(QUrl(requested_url).toEncoded()) != context.href):
        return []
    if mode not in (QWebEnginePage.FileSelectionMode.FileSelectOpen, QWebEnginePage.FileSelectionMode.FileSelectOpenMultiple):
        return []
    if context.owner._browser_dialog_depth:
        return []
    feedback_ticket = context.owner._begin_feedback('file_selection')
    batch, snapshots, store = None, (), None
    primitive = _primitive()
    with browser_dialog(context.owner):
        try:
            blocked, exceptions = protected_roots(context.owner)
            selected = context.owner.file_selection_for_test
            if selected is not None:
                context.owner.file_selection_for_test = None
                paths = list(selected) if isinstance(selected, (list, tuple)) else [selected]
            elif mode == QWebEnginePage.FileSelectionMode.FileSelectOpenMultiple:
                paths, _ = QFileDialog.getOpenFileNames(context.owner, 'Choose files', str(context.owner.documents_folder))
            else:
                path, _ = QFileDialog.getOpenFileName(context.owner, 'Choose a file', str(context.owner.documents_folder))
                paths = [path] if path else []
            if not paths:
                _feedback(context, feedback_ticket, SERVER_CANCELED if context.mode == 'server' else CANCELED)
                return []
            # No context probes, consent loop or source reads intervene between
            # chooser return and initial identity/handle capture.
            batch = primitive.capture(paths, blocked_roots=blocked, allowed_private_roots=exceptions)
            if not context.valid(): return []
            if context.mode == 'server':
                accepted = _consent(context, batch)
                if not context.valid(): return []
                if not accepted:
                    _feedback(context, feedback_ticket, SERVER_CANCELED)
                    return []
            store = _store(context.view, context)
            snapshots = _stage(context, store, batch)
            if not context.valid():
                store.discard(snapshots)
                return []
            for item in snapshots:
                require_browser_path(item.path, 'Selected private copy')
            pending = getattr(context.view, '_pending_file_selections', None)
            if pending is None: pending = context.view._pending_file_selections = {}
            pending[ticket] = PendingSelection(context, feedback_ticket, snapshots)
            return [str(item.path) for item in snapshots]
        except primitive.SelectionCanceled:
            _feedback(context, feedback_ticket, SERVER_CANCELED if context.mode == 'server' else CANCELED)
            return []
        except (ValueError, OSError, RuntimeError) as exc:
            if snapshots and store is not None: store.discard(snapshots)
            _warning(context, feedback_ticket, str(exc))
            return []
        finally:
            if batch is not None: batch.close()


def prepare_handback(view, ticket, paths):
    pending = getattr(view, '_pending_file_selections', {}).get(ticket)
    if pending is None: return []
    if not pending.context.valid():
        view._selection_store.discard(pending.snapshots)
        view._pending_file_selections.pop(ticket, None)
        return []
    try:
        for item in pending.snapshots:
            require_browser_path(item.path, 'Selected private copy')
    except ValueError as exc:
        view._selection_store.discard(pending.snapshots)
        view._pending_file_selections.pop(ticket, None)
        _warning(pending.context, pending.ticket, str(exc))
        return []
    pending.attempted = True
    return paths


def handback_complete(view, ticket, *, success, result=None):
    pending = getattr(view, '_pending_file_selections', {}).pop(ticket, None)
    if pending is None: return
    if success and isinstance(result, dict) and result.get('files_applied') is True:
        _feedback(pending.context, pending.ticket, SUCCESS)
        return  # Browser-readable Files retain their sealed handles until retirement.
    exposed = result.get('files_exposed') if isinstance(result, dict) else None
    if not pending.attempted or exposed is False or (isinstance(result, dict) and result.get('files_applied') is False):
        view._selection_store.discard(pending.snapshots)
    # An unknown/partially applied native failure may already have exposed Files.
    # Retain those seals conservatively until browser retirement, never publish
    # an application-save claim or invalidate earlier FileLists.
    _warning(pending.context, pending.ticket, 'The page changed or refused the selected files. No application save was confirmed. Reopen the chooser on the current form.')


def retire(view):
    store = getattr(view, '_selection_store', None)
    if store is None: return ()
    errors = store.close()
    view._pending_file_selections = {}
    view._selection_store = None
    return errors

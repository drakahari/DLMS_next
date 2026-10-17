"""Windows-only explicit export destinations; pages see private staging only.

Native download retirement precedes the Save As dialog. The selected destination
is never returned to WebView2, and publication preserves the exact staged bytes.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import secrets

from PySide6.QtCore import QObject, QTimer, Qt

PREFERENCE = 'export-destination.json'
PREFERENCE_LIMIT = 4096


def safe_name(value):
    from .windows_files import lexical
    if not isinstance(value, str) or not value or Path(value).name != value or len(value.encode('utf-16-le')) > 510:
        raise ValueError('Export filename is unsafe or too long')
    lexical(Path('C:/') / value)
    return value


def forbidden_roots(owner):
    from .isolation import AREA, PROJECT, FROZEN
    import sys
    captured = getattr(owner, 'selection_private_roots', None)
    if not isinstance(captured, tuple) or not captured or any(not isinstance(p, Path) or not p.is_absolute() for p in captured):
        raise ValueError('Private-folder protection metadata is unavailable; close and reopen Desktop')
    return (AREA, PROJECT if FROZEN else PROJECT / 'desktop',
            *((Path(sys.executable).parent,) if FROZEN else ()),
            *(PROJECT / name for name in ('.git', '.codex', '.agents', '.aws')), *captured)


def _allowed(path, forbidden):
    from .windows_files import lexical
    path = lexical(path)
    if any(path.is_relative_to(root) for root in forbidden):
        raise ValueError('Choose a destination outside managed application and private storage')
    return path


def select_destination(path, *, forbidden):
    """Capture the chosen directory identity, refusing every existing leaf."""
    from .windows_files import pinned_parents, owned, identity
    path = _allowed(Path(path), forbidden)
    safe_name(path.name)
    with pinned_parents(path) as parent:
        owned(path.parent)
        if path.exists() or path.is_symlink():
            raise FileExistsError('That filename already exists; choose a different name. No file was replaced')
        return {'path': str(path), 'parent_identity': identity(parent), 'operation': secrets.token_hex(16)}


def _usable_directory(directory, forbidden):
    from .windows_files import pinned_parents, owned
    directory = _allowed(Path(directory), forbidden)
    with pinned_parents(directory / '.dlms-export-folder-check'):
        owned(directory)
    return directory


def initial_directory(root, folders, *, forbidden, scope=None):
    """Read only this Local or Server profile's bounded private preference."""
    from .windows_files import pinned_parents, owned, open_read
    root = Path(root)
    preference = root / PREFERENCE
    warning = ''
    try:
        with pinned_parents(preference):
            owned(root, private=True)
            try:
                fd = open_read(preference)
            except FileNotFoundError:
                fd = None
            if fd is not None:
                import msvcrt
                from .windows_files import owned_handle
                with os.fdopen(fd, 'rb') as stream:
                    owned_handle(msvcrt.get_osfhandle(stream.fileno()), private=True)
                    value = stream.read(PREFERENCE_LIMIT + 1)
                if len(value) > PREFERENCE_LIMIT:
                    raise ValueError('Saved export location is too large')
                record = json.loads(value)
                if (not isinstance(record, dict) or set(record) != {'version', 'directory', 'scope'}
                        or type(record['version']) is not int or record['version'] != 1
                        or not isinstance(record['directory'], str) or record['scope'] != scope):
                    raise ValueError('Saved export location is invalid')
                return _usable_directory(record['directory'], forbidden), ''
    except (OSError, ValueError, TypeError):
        warning = 'The last export folder is unavailable or unsafe. Choose another destination.'
    # The caller passes real pre-isolation Documents, Downloads in that order.
    candidates = tuple(folders[1:2]) + tuple(folders[:1])
    for directory in candidates:
        try:
            return _usable_directory(directory, forbidden), warning
        except (OSError, ValueError):
            continue
    raise ValueError('Configured Downloads and Documents are unavailable; choose a working Windows folder after reopening Desktop')


def remember_directory(root, directory, *, forbidden, scope=None):
    from .windows_files import pinned_parents, owned
    from .profile_state import atomic_json
    directory = _usable_directory(directory, forbidden)
    root = Path(root)
    with pinned_parents(root / PREFERENCE):
        owned(root, private=True)
        record = {'version': 1, 'directory': str(directory), 'scope': scope}
        if len(json.dumps(record).encode('utf-8')) + 1 > PREFERENCE_LIMIT:
            raise ValueError('The selected directory is too long to remember')
        atomic_json(root / PREFERENCE, record)


@dataclass(frozen=True)
class Context:
    owner: object
    view: object
    page: object
    mode: str
    generation: int
    navigation: int
    native_generation: object
    native_navigation: object
    href: bytes
    identity: tuple
    root: Path
    origin: str

    @property
    def preference_scope(self):
        return ('local:' + self.owner.profile_name if self.mode == 'local' else
                'server:' + self.identity[0] + ':' + self.origin)

    @classmethod
    def capture(cls, owner, request):
        view = owner.view
        if view is None or request.page() is not view.page():
            raise ValueError('The export page is no longer current')
        if owner.mode == 'local':
            from .shell import allowed_internal
            if owner.backend is None or owner.backend.poll() is not None or not allowed_internal(view.url(), owner.port):
                raise ValueError('The owned Local backend/page is unavailable')
            from .profile_state import read_manifest
            saved = owner.manifest
            disk = read_manifest(owner.paths, owner.profile_name)
            if not saved or not disk or (saved['uuid'], saved['epoch']) != (disk['uuid'], disk['epoch']):
                raise ValueError('Local profile identity changed; close and reopen Desktop')
            identity = (saved['uuid'], saved['epoch'])
            root, origin = owner.paths['root'], f'http://127.0.0.1:{owner.port}'
        elif owner.mode == 'server':
            from .server_browser import exact_server_origin
            server = owner.mode_config['server']
            if not exact_server_origin(view.url(), server['origin']):
                raise ValueError('The configured Server is not the current page')
            identity, root, origin = (server['id'], server['origin']), owner.server_paths['root'], server['origin']
        else:
            raise ValueError('The export mode is unavailable')
        return cls(owner, view, request.page(), owner.mode, owner._browser_generation,
                   getattr(owner, '_server_navigation_serial', 0), getattr(view, '_active_generation', None),
                   getattr(view, '_active_navigation', None), bytes(view.url().toEncoded()), identity, root, origin)

def _context_valid(context):
    # Avoid a page field/method collision while comparing the complete context.
    from types import SimpleNamespace
    owner = context.owner
    if (owner._closing or owner._retiring_browser is not None or getattr(owner, '_close_active', False)
            or getattr(owner, '_close_after_dialog', False) or getattr(owner, '_mode_switch_busy', False)
            or getattr(owner, 'failed_reason', None) is not None
            or any(getattr(owner, key, False) for key in ('import_in_progress', 'maintenance_transition',
                '_settings_transition_refused', '_settings_action_busy', '_backup_creating'))
            or any(getattr(owner, key, None) is not None for key in ('import_worker', 'maintenance_worker',
                'removal_worker', '_import_reopen_status'))):
        return False
    try:
        return Context.capture(owner, SimpleNamespace(page=lambda: context.page)) == context
    except (OSError, ValueError, RuntimeError, AttributeError, KeyError):
        return False


class Export(QObject):
    """One native download and one final publication; all outcomes terminal."""
    def __init__(self, owner, request, local, chooser):
        super().__init__(owner)
        self.owner, self.request, self.chooser = owner, request, chooser
        self.context = Context.capture(owner, request)
        self.label = 'Download' if local else 'Server download'
        self.ticket = owner._begin_feedback('download' if local else 'server_download')
        self.record = {'path': '', 'state': 'in_progress', 'feedback_ticket': self.ticket}
        owner.download_results.append(self.record)
        self.future = None
        self.selecting = False
        self.timer = QTimer(self)
        self.timer.setInterval(30)
        self.timer.timeout.connect(self.poll)

    def feedback(self, message, severity='info'):
        if _context_valid(self.context):
            self.owner._feedback(self.ticket, message, severity)

    def terminal(self, state, message, severity='info', reason=None):
        if self.record['state'] != 'in_progress':
            return
        self.record['state'] = state
        if reason is not None:
            self.record['reason'] = reason
        self.timer.stop()
        self.feedback(message, severity)
        self.deleteLater()

    def start(self):
        request = self.request
        from .windows_files import owned
        name = safe_name(request.downloadFileName())
        paths = self.owner.paths if self.context.mode == 'local' else self.owner.server_paths
        job = paths['downloads'] / ('download-' + secrets.token_hex(12))
        owned(paths['downloads'], private=True)
        job.mkdir(mode=0o700)
        owned(job, private=True)
        self.source = job / name
        self.record['staging_path'] = str(self.source)
        request.setDownloadDirectory(str(job))
        request.setDownloadFileName(name)
        request.isFinishedChanged.connect(self.finished)
        request.stateChanged.connect(self.finished)
        self.feedback(self.label + ' in progress; a native Save As chooser follows completion')
        request.accept()

    def finished(self, *_):
        if self.record['state'] != 'in_progress' or self.future is not None or self.selecting:
            return
        state, states = self.request.state(), self.request.DownloadState
        if state == states.DownloadCompleted:
            self.selecting = True
            # Return through the native event reader before entering COM's
            # modal loop; chooser callbacks must not reenter frame dispatch.
            QTimer.singleShot(0, self.choose)
        elif state == states.DownloadCancelled:
            self.terminal('cancelled', self.label + ' cancelled; no selected file was published')
        elif state == states.DownloadInterrupted:
            reason = self.request.interruptReasonString()
            self.terminal('failed', self.label + ' failed: ' + reason, 'error', reason)

    def choose(self):
        from .browser_lifetime import browser_dialog
        from .windows_backup_output import publish
        owner, context = self.owner, self.context
        try:
            if not _context_valid(context):
                raise ValueError('Export page changed before destination consent; no selected file was published')
            if getattr(owner, '_browser_dialog_depth', 0) or getattr(owner, '_browser_operation_depth', 0):
                raise ValueError('Finish the open dialog and retry the export')
            forbidden = forbidden_roots(owner)
            initial, warning = initial_directory(context.root, owner.backup_chooser_folders,
                                                 forbidden=forbidden, scope=context.preference_scope)
            if warning:
                self.feedback(warning, 'warning')
            owner._browser_operation_depth += 1
            try:
                with browser_dialog(owner):
                    title = ('Save quiz export as' if context.mode == 'local' else
                             'Save export from ' + context.origin)
                    result = self.chooser(owner, self.source.name, owner.backup_chooser_folders,
                                          initial=initial, title=title, notice=warning)
                if not _context_valid(context):
                    raise ValueError('Export page changed during destination selection; no selected file was published')
                selected = result[0] if isinstance(result, tuple) else result
                if not selected:
                    self.terminal('cancelled', self.label + ' save canceled; no selected file was published')
                    return
                selection = select_destination(Path(selected), forbidden=forbidden)
            finally:
                owner._browser_operation_depth -= 1
                if _context_valid(context) and owner.isActiveWindow():
                    context.view.setFocus(Qt.FocusReason.OtherFocusReason)
            self.record['path'] = selection['path']
            self.record['phase'] = 'publishing'
            self.forbidden, self.selection = forbidden, selection
            self.future = owner.backup_selection_executor.submit(publish, self.source, selection)
            self.feedback(self.label + ' publishing to the selected destination…')
            self.timer.start()
        except (OSError, ValueError, RuntimeError) as exc:
            self.terminal('failed', self.label + ' destination refused: ' + str(exc), 'error', str(exc))

    def poll(self):
        if self.future is None or not self.future.done():
            return
        try:
            result = self.future.result()
        except (OSError, ValueError, RuntimeError) as exc:
            self.terminal('failed', self.label + ' publication failed: ' + str(exc), 'error', str(exc))
            return
        self.record.update(result)
        if self.context.mode == 'local':
            self.owner.downloaded_files.append(Path(result['path']))
        warning = ''
        try:
            if _context_valid(self.context):
                remember_directory(self.context.root, Path(result['path']).parent, forbidden=self.forbidden,
                                   scope=self.context.preference_scope)
        except (OSError, ValueError, RuntimeError):
            warning = ' The file was saved, but this folder could not be remembered.'
        self.terminal('completed', f"{self.label} completed: {result['path']}" + warning, 'warning' if warning else 'success')


def begin_export(owner, request, *, local, chooser=None):
    """Called only after the shell has validated the download's exact origin."""
    if chooser is None:
        from .windows_backup_chooser import choose_export
        chooser = choose_export
    if (getattr(owner, '_browser_dialog_depth', 0) or getattr(owner, '_browser_operation_depth', 0)
            or owner._closing or owner._retiring_browser is not None):
        request.cancel()
        return None
    operation = None
    try:
        operation = Export(owner, request, local, chooser)
        if (operation.context.mode == 'local') != local:
            raise ValueError('The export mode changed before acceptance')
        if not _context_valid(operation.context):
            raise ValueError('The export context is changing; try again after navigation completes')
        operation.start()
        return operation
    except (OSError, ValueError, RuntimeError) as exc:
        request.cancel()
        if operation is not None:
            operation.terminal('failed', 'Download refused: ' + str(exc), 'error', str(exc))
        else:
            ticket = owner._begin_feedback('download' if local else 'server_download')
            owner._feedback(ticket, 'Download refused: ' + str(exc), 'error')
        return None

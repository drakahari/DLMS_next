"""Windows browser adapter; the browser lives in a private C# child process.

Only Qt Core/Widgets provide Desktop chrome. Importing WebEngine enums does
not create a Chromium profile or renderer. Browser commands travel over owned
anonymous pipes, never through a page-visible web-message/native-object API.
"""
from __future__ import annotations

from enum import IntEnum
from collections import deque
from contextlib import ExitStack
import json
import math
import os
from pathlib import Path
import secrets
import time

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, QUrl, Qt, Signal, QEvent
from PySide6.QtGui import QWindow
from PySide6.QtWidgets import QWidget, QVBoxLayout, QMessageBox, QInputDialog, QDialog, QLabel
from PySide6.QtWebEngineCore import QWebEngineLoadingInfo, QWebEnginePage

from .isolation import PROJECT, FROZEN
from .webview2_paths import BrowserPathError, require_browser_path


def physical_viewport(width: int, height: int, scale: float) -> dict:
    """Describe Qt's native pixel extent and its logical content scale."""
    if (not isinstance(width, int) or isinstance(width, bool) or width < 1
            or not isinstance(height, int) or isinstance(height, bool) or height < 1
            or not isinstance(scale, (float, int)) or isinstance(scale, bool)
            or not math.isfinite(scale) or not .25 <= scale <= 8):
        raise ValueError('Unsupported native viewport size or Qt device-pixel ratio')
    # Positive qRound semantics match Qt's native geometry conversion.
    physical_width = max(1, math.floor(width * scale + .5))
    physical_height = max(1, math.floor(height * scale + .5))
    if physical_width > 16384 or physical_height > 16384:
        raise ValueError('Native viewport exceeds the supported physical extent')
    return {'width': physical_width, 'height': physical_height, 'scale': float(scale)}


def host_executable() -> Path:
    """One explicit payload path; never search PATH or another installation."""
    path = ((PROJECT / 'windows_webview2') if FROZEN else
            PROJECT / '.gate1/windows-native/webview2-host-candidate-65/payload') / 'DLMS-WebView2-Host.exe'
    if not path.is_file() or path.is_symlink():
        raise RuntimeError('The pinned Windows WebView2 host payload is missing')
    return path


def private_root(base: str, *, pins: ExitStack) -> Path:
    """Retain one private browser root, recreating only its exact missing leaf."""
    if os.name != 'nt':
        raise RuntimeError('The WebView2 browser adapter is Windows only')
    from .windows_files import assert_path, owned, pinned_parents
    root = Path(base)
    assert_path(root)
    # Restore/maintenance can quarantine the old storage leaf. Recreate only
    # that exact leaf, under its existing checked and rename-pinned parent.
    pins.enter_context(pinned_parents(root))
    owned(root.parent, private=True)
    root.mkdir(mode=0o700, exist_ok=True)
    pins.enter_context(pinned_parents(root / '.dlms-root-anchor'))
    owned(root, private=True)
    return root


def private_storage(base: str, *, pins: ExitStack) -> Path:
    """Keep WebView2 state separate from prior Qt storage and reject aliases."""
    root = private_root(base, pins=pins)
    from .windows_files import assert_path, owned, pinned_parents
    path = root / 'webview2'
    path.mkdir(mode=0o700, exist_ok=True)
    pins.enter_context(pinned_parents(path / '.dlms-storage-anchor'))
    assert_path(path)
    owned(path, private=True)
    return path


class Settings:
    def __init__(self):
        self.attributes = {}

    def setAttribute(self, key, value):
        # Host enforces its own restrictive browser settings. This records the
        # controller's declarative policy, rather than configuring Qt Chromium.
        self.attributes[key] = bool(value)


class Profile(QObject):
    downloadRequested = Signal(object)

    class PersistentCookiesPolicy(IntEnum):
        ForcePersistentCookies = 2

    def __init__(self, name, parent=None):
        super().__init__(parent)
        self.name, self.storage, self.cache = name, None, None
        self.interceptor = None
        self._settings = Settings()

    def setPersistentStoragePath(self, value): self.storage = value
    def setCachePath(self, value): self.cache = value
    def setPersistentCookiesPolicy(self, value): self.cookies_policy = value
    def setUrlRequestInterceptor(self, value): self.interceptor = value
    def settings(self): return self._settings


class LoadingInfo:
    def __init__(self, url, *, ok=False, download=False, started=False, error=0):
        self._url, self._download, self._error = QUrl(url), bool(download), error
        statuses = QWebEngineLoadingInfo.LoadStatus
        self._status = (statuses.LoadStartedStatus if started else statuses.LoadStoppedStatus
                        if download else statuses.LoadSucceededStatus if ok else statuses.LoadFailedStatus)

    def status(self): return self._status
    def url(self): return QUrl(self._url)
    def isDownload(self): return self._download
    def isErrorPage(self): return False
    def errorCode(self): return self._error if isinstance(self._error, int) else -1
    def errorDomain(self): return QWebEngineLoadingInfo.ErrorDomain.InternalErrorDomain


class _LifecycleState(IntEnum):
    Unknown = -1


class Page(QObject):
    FileSelectionMode = QWebEnginePage.FileSelectionMode
    loadStarted = Signal()
    loadFinished = Signal(bool)
    urlChanged = Signal(QUrl)
    loadingChanged = Signal(object)
    printRequested = Signal()
    pdfPrintingFinished = Signal(str, bool)
    renderProcessPidChanged = Signal(int)
    renderProcessTerminated = Signal(object, int)

    def __init__(self, profile, owner, parent=None):
        super().__init__(parent if parent is not None else owner)
        self.profile, self.owner = profile, owner
        self._url, self._loading = QUrl(), False
        self.last_http_status = 0
        self._title = ''

    def url(self): return QUrl(self._url)
    def requestedUrl(self): return QUrl(getattr(self, '_requested_url', self._url))
    def isLoading(self): return self._loading
    def title(self): return self._title
    def renderProcessPid(self): return 0  # The host/browser PID is not a renderer identity.
    def lifecycleState(self): return _LifecycleState.Unknown  # Qt lifecycle state is unavailable.

    def runJavaScript(self, script, *args):
        world, callback = 0, None
        if len(args) == 1:
            if callable(args[0]): callback = args[0]
            else: world = int(getattr(args[0], 'value', args[0]))
        elif len(args) == 2:
            world, callback = int(getattr(args[0], 'value', args[0])), args[1]
        if not isinstance(self.parent(), View):
            if callback: QTimer.singleShot(0, lambda: callback(None))
            return
        self.parent().command('eval', callback=callback, script=script, world=1 if world else 0)

    def setBackgroundColor(self, value):
        if isinstance(self.parent(), View):
            self.parent().command('background', value=value.name())


class LocalPage(Page):
    def chooseFiles(self, *args, ticket=None, requested_url=None):
        from .webview2_file_selection import choose_files
        return choose_files(self, *args, ticket=ticket, requested_url=requested_url)


class ServerPage(Page):
    def __init__(self, profile, owner, origin, parent=None):
        super().__init__(profile, owner, parent)
        self.origin = origin

    def chooseFiles(self, *args, ticket=None, requested_url=None):
        from .webview2_file_selection import choose_files
        return choose_files(self, *args, ticket=ticket, requested_url=requested_url)


class Download(QObject):
    """One terminal transition; late native notifications cannot rewrite it."""
    isFinishedChanged = Signal()
    stateChanged = Signal(object)

    class DownloadState(IntEnum):
        DownloadRequested = 0
        DownloadInProgress = 1
        DownloadCompleted = 2
        DownloadCancelled = 3
        DownloadInterrupted = 4

    def __init__(self, view, event):
        super().__init__(view)
        self.view, self.identifier = view, event['download_id']
        self._page, self._url, self._name = view.page(), QUrl(event['url']), event.get('name', '')
        self._blob_download = event.get('blob') is True
        self._download_context = (event.get('generation'), event.get('nav_id'),
                                  QUrl(event.get('document_url') or '').toString())
        self.directory, self._reason = None, ''
        self._pins, self._target, self._partial = None, None, None
        self._native_pending = False
        self._state = self.DownloadState.DownloadRequested
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(120000)
        self.timer.timeout.connect(self._timeout)

    def page(self): return self._page
    def url(self): return QUrl(self._url)
    def downloadFileName(self): return self._name
    def setDownloadFileName(self, value): self._name = value
    def setDownloadDirectory(self, value): self.directory = value
    def state(self): return self._state
    def isFinished(self): return self._state in (self.DownloadState.DownloadCompleted, self.DownloadState.DownloadCancelled, self.DownloadState.DownloadInterrupted)
    def interruptReasonString(self): return self._reason

    def accept(self):
        if self._state != self.DownloadState.DownloadRequested: return
        try:
            from .windows_files import assert_path, owned, pinned_parents
            if not self.directory or Path(self._name).name != self._name or self._name in ('', '.', '..'):
                raise ValueError('Unsafe download filename')
            path = Path(self.directory) / self._name
            assert_path(path, leaf=True)
            owned(path.parent, private=True)
            if path.exists(): raise ValueError('Download destination already exists')
            self._pins = pinned_parents(path)
            self._pins.__enter__()
            # Verify the actual directory again after pinning all ancestors.
            owned(path.parent, private=True)
            self._target = path
            self._partial = path.parent / ('.wv-' + secrets.token_hex(16) + '.part')
            require_browser_path(self._partial, 'Download staging')
            assert_path(self._partial, leaf=True)
            if self._partial.exists(): raise ValueError('Private staging collision')
        except (ValueError, OSError) as exc:
            self.view.command('download', download_id=self.identifier, action='cancel')
            self.finish('interrupted', str(exc), native_done=False)
            return
        self._state = self.DownloadState.DownloadInProgress
        self._native_pending = True
        self.stateChanged.emit(self._state)
        self.timer.start()
        self.view.command('download', on_error=lambda error: self.finish('interrupted',
                          'Native download acceptance failed: ' + str(error.get('message', 'request refused')), native_done=False),
                          download_id=self.identifier, action='accept', path=str(self._partial))

    def cancel(self):
        if self.isFinished(): return
        self.view.command('download', download_id=self.identifier, action='cancel')
        self.finish('cancelled', native_done=False)

    def _timeout(self):
        self.view.command('download', download_id=self.identifier, action='cancel')
        self.finish('interrupted', 'Download made no progress for 120 seconds; no completed file was reported', native_done=False)

    def finish(self, state, reason='', *, native_done=True):
        states = {'completed': self.DownloadState.DownloadCompleted, 'cancelled': self.DownloadState.DownloadCancelled,
                  'interrupted': self.DownloadState.DownloadInterrupted}
        if state not in states: return
        if native_done: self._native_pending = False
        if self.isFinished():
            self._release_pins_if_retired()
            return
        if state == 'completed' and not native_done:
            state, reason = 'interrupted', 'Native download writer retirement was not acknowledged'
        if state == 'completed':
            try:
                if self._target is None or self._partial is None or self._pins is None:
                    raise ValueError('Completion has no accepted private destination')
                from .windows_files import assert_path, publication_handle, rename_by_handle
                # Native completion is not publication: verify the actual file
                # and atomically rename its retained identity without replacing.
                with publication_handle(self._partial) as handle:
                    assert_path(self._target, leaf=True)
                    if self._target.exists(): raise ValueError('The final destination now exists; no file was replaced')
                    rename_by_handle(handle, self._target)
            except (OSError, ValueError) as exc:
                state, reason = 'interrupted', f'Download publication failed: {exc}'
        self.timer.stop()
        self._state, self._reason = states[state], str(reason)
        self._release_pins_if_retired()
        self.stateChanged.emit(self._state)
        self.isFinishedChanged.emit()

    def _release_pins_if_retired(self):
        if not self._native_pending and self._pins is not None:
            self._pins.__exit__(None, None, None)
            self._pins = None


class PrintPublication:
    """Native printing writes a private partial; only its exact handle publishes."""
    def __init__(self, target):
        from .windows_files import assert_path, owned, pinned_parents
        self.target = Path(target)
        self.pins, self.terminal, self.reason = ExitStack(), False, ''
        self.native_done = False
        try:
            assert_path(self.target, leaf=True)
            self.pins.enter_context(pinned_parents(self.target))
            owned(self.target.parent, private=True)
            if self.target.exists(): raise ValueError('PDF destination already exists')
            job = self.target.parent / ('.p-' + secrets.token_hex(16))
            self.partial = job / 'p.pdf'
            require_browser_path(self.partial, 'PDF staging')
            assert_path(job)
            job.mkdir(mode=0o700)
            owned(job, private=True)
            self.pins.enter_context(pinned_parents(self.partial))
            assert_path(self.partial, leaf=True)
            if self.partial.exists(): raise ValueError('Private PDF staging collision')
        except BaseException:
            self.pins.close()
            raise

    def finish(self, success, *, native_done=True):
        if native_done: self.native_done = True
        if self.terminal:
            if self.native_done: self.pins.close()
            return False
        self.terminal = True
        try:
            if not success:
                self.reason = 'Native PDF generation did not complete'
                return False
            if not self.native_done:
                raise ValueError('Native PDF writer retirement was not acknowledged')
            from .windows_files import publication_handle, rename_by_handle, info
            with publication_handle(self.partial) as handle:
                value = info(handle)
                if not value.size_hi and not value.size_lo:
                    raise ValueError('Native PDF output is empty')
                rename_by_handle(handle, self.target)
            return True
        except (OSError, ValueError) as exc:
            self.reason = 'PDF publication failed: ' + str(exc)
            return False
        finally:
            if self.native_done: self.pins.close()


class View(QWidget):
    loadStarted = Signal()
    loadFinished = Signal(bool)
    urlChanged = Signal(QUrl)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._page, self.process, self.container, self.native_window = None, None, None, None
        self._ready, self._retiring, self._serial = False, False, 0
        self._active_generation, self._active_navigation = 0, None
        self._storage_pins = ExitStack()
        self._host_started, self._browser_exit_pid, self._retired_pid = False, None, None
        self._retirement_error = None
        self._policy = None
        self._queue, self._callbacks, self._downloads, self._prints = [], {}, {}, {}
        self._selection_store, self._pending_file_selections, self._selection_cleanup_errors = None, {}, []
        self._position_ancestors = []
        self._buffer, self._stderr = bytearray(), bytearray()
        self.protocol_events = deque(maxlen=128)
        self.startup_stage = 'not-started'
        self._startup_deadline, self._startup_failed = None, False
        self.layout_box = QVBoxLayout(self)
        self.layout_box.setContentsMargins(0, 0, 0, 0)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._deadline = QTimer(self)
        self._deadline.setInterval(1000)
        self._deadline.timeout.connect(self._expire_callbacks)

    def setPage(self, page):
        if self._page is not None: raise RuntimeError('A browser view owns exactly one page')
        if page.parent() is not self: page.setParent(self)
        self._page = page

    def page(self): return self._page
    def url(self): return self.page().url()
    def title(self): return self.page().title()

    def _start(self):
        if self.process is not None: return
        owner, profile = self.page().owner, self.page().profile
        if owner.mode not in ('local', 'server') or not profile.storage or not profile.cache:
            raise ValueError('Browser mode and private storage/cache roots are required')
        try:
            storage = private_storage(profile.storage, pins=self._storage_pins)
            # Backup adoption quarantines both managed roots. WebView2 keeps
            # its actual cache under storage, but later fresh-reset ownership
            # still binds both roots: restore their strict startup invariant.
            private_root(profile.cache, pins=self._storage_pins)
            executable = host_executable()
        except BaseException:
            self._storage_pins.close()
            raise
        config = {'mode': owner.mode, 'storage': str(storage), 'parent_hwnd': int(self.winId())}
        if owner.mode == 'local':
            config.update(origin=f'http://127.0.0.1:{owner.port}', token=owner.nonce)
        else:
            config.update(origin=owner.mode_config['server']['origin'])
        process = self.process = QProcess(self)
        self.startup_stage = 'process-created'
        self._startup_deadline = time.monotonic() + 45
        process.setProgram(str(executable))
        process.setWorkingDirectory(str(executable.parent))
        env = QProcessEnvironment.systemEnvironment()
        for key in env.keys():
            if key.startswith(('WEBVIEW2_', 'QTWEBENGINE_', 'DLMS_', 'QUIZAPP_')) or key in ('PYTHONHOME', 'PYTHONPATH'):
                env.remove(key)
        process.setProcessEnvironment(env)
        process.readyReadStandardOutput.connect(self._read)
        process.readyReadStandardError.connect(self._read_error)
        process.finished.connect(self._exited)
        process.errorOccurred.connect(self._process_error)
        def configure():
            self._host_started = True
            self.startup_stage = 'configuration-written'
            process.write((json.dumps(config, ensure_ascii=True) + '\n').encode('utf-8'))
        process.started.connect(configure)
        process.start()
        self._deadline.start()

    def command(self, op, callback=None, on_error=None, **values):
        if self._retiring and op not in ('close', 'dialog'):
            if callback: QTimer.singleShot(0, lambda: callback(None))
            return
        self._serial += 1
        item = dict(id=self._serial, op=op, **values)
        if callback is not None or on_error is not None:
            self._callbacks[self._serial] = (time.monotonic()+15, callback, on_error)
        if not self._ready:
            if len(self._queue) >= 256: raise RuntimeError('WebView2 startup command queue exceeded its bound')
            self._queue.append(item)
        else:
            self._write(item)

    def _write(self, item):
        if self.process is not None and self.process.state() != QProcess.ProcessState.NotRunning:
            interceptor = self.page().profile.interceptor
            blocked = tuple(sorted(getattr(interceptor, 'blocked_internal_paths', ())))
            if item['op'] != 'policy' and blocked != self._policy:
                self._policy = blocked
                self._serial += 1
                self._write(dict(id=self._serial, op='policy', blocked_paths=list(blocked)))
            data = (json.dumps(item, ensure_ascii=True, separators=(',', ':')) + '\n').encode('utf-8')
            if len(data) > 2*1024*1024: raise ValueError('Browser command exceeds the protocol bound')
            self.process.write(data)

    def setUrl(self, url):
        self._start()
        self.command('navigate', url=QUrl(url).toString())

    def _send_physical_resize(self):
        if not getattr(self, '_ready', False):
            return
        try:
            metrics = physical_viewport(max(1, self.width()), max(1, self.height()), self.devicePixelRatioF())
        except ValueError as exc:
            self._failure(str(exc))
            return
        self.command('resize', **metrics, on_error=lambda error:
                     self._failure('WebView2 geometry could not be applied: ' + str(error.get('message', 'request refused'))))

    def _refresh_scale_event(self, event):
        if event.type() in (QEvent.Type.DevicePixelRatioChange, QEvent.Type.ScreenChangeInternal):
            self._send_physical_resize()

    def stop(self): self.command('stop')
    def setServerCover(self, shown, text, browser_visible):
        owner = self.page().owner
        if owner.mode != 'server' or owner.view is not self or self._retiring or owner._closing:
            return
        self.command('cover', shown=bool(shown), text=str(text)[:4096], browser_visible=bool(browser_visible))

    def printToPdf(self, path):
        target = str(path)
        if self._retiring:
            self.page().pdfPrintingFinished.emit(target, False)
            return
        try:
            output = PrintPublication(target)
        except (OSError, ValueError) as exc:
            self.page().pdfPrintingFinished.emit(target, False)
            if isinstance(exc, BrowserPathError): self._command_notice(str(exc))
            return
        partial = str(output.partial)
        self._prints[partial] = output
        try:
            self.command('print', path=partial, on_error=lambda error: self._finish_print(partial, False, native_done=False))
        except (OSError, ValueError, RuntimeError):
            self._finish_print(partial, False, native_done=False)

    def _finish_print(self, partial, success, *, native_done=True):
        output = self._prints.get(str(partial))
        if output is None: return
        was_terminal = output.terminal
        ok = output.finish(bool(success), native_done=native_done)
        if native_done: self._prints.pop(str(partial), None)
        if not was_terminal: self.page().pdfPrintingFinished.emit(str(output.target), ok)

    def _cancel_prints(self):
        for partial in list(getattr(self, '_prints', {})):
            self._finish_print(partial, False, native_done=False)

    def _read_error(self):
        chunk = bytes(self.process.readAllStandardError())
        if len(self._stderr) < 65536: self._stderr.extend(chunk[:65536-len(self._stderr)])

    def _read(self):
        self._buffer.extend(bytes(self.process.readAllStandardOutput()))
        if len(self._buffer) > 4*1024*1024:
            self._failure('WebView2 protocol output exceeded its bound')
            self._buffer.clear()
            return
        while b'\n' in self._buffer:
            line, _, rest = self._buffer.partition(b'\n')
            self._buffer = bytearray(rest)
            try:
                event = json.loads(line)
                if not isinstance(event, dict): raise ValueError('Invalid browser event')
                self._event(event)
            except (ValueError, TypeError, KeyError) as exc:
                self._failure(f'Invalid WebView2 protocol event: {exc}')

    def _event(self, event):
        kind = event.get('event')
        if hasattr(self, 'protocol_events'):
            self.protocol_events.append((round(time.monotonic(), 3), str(kind)))
        if kind in ('attachment-declined', 'file-picker', 'file-picker-failed', 'download-blocked', 'focus-boundary') and 'generation' not in event:
            return
        if kind in ('load-start', 'url', 'load-finish', 'attachment-declined', 'file-picker', 'file-picker-failed', 'download-blocked', 'focus-boundary') and 'generation' in event:
            generation, navigation = event['generation'], event.get('nav_id')
            if (not isinstance(generation, int) or isinstance(generation, bool) or generation < 0
                    or not isinstance(navigation, int) or isinstance(navigation, bool) or navigation < 0):
                raise ValueError('Invalid navigation identity')
            current = getattr(self, '_active_generation', 0)
            if kind == 'load-start' and generation > current:
                self._active_generation, self._active_navigation = generation, navigation
            elif generation != current or navigation != getattr(self, '_active_navigation', None):
                return
        if kind == 'reply':
            item = self._callbacks.pop(event.get('id'), None)
            if item:
                if event.get('ok'):
                    if item[1]: item[1](event.get('value'))
                else:
                    error = event.get('value')
                    if len(item) > 2 and item[2]: item[2](error if isinstance(error, dict) else {'message': 'Request refused'})
                    if item[1]: item[1](None)
        elif kind == 'ready':
            if self._ready or self._retiring: return
            self.startup_stage = 'ready-event'
            hwnd = int(event['hwnd'])
            import ctypes
            from ctypes import wintypes
            native_pid = wintypes.DWORD()
            ctypes.windll.user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(native_pid))
            if native_pid.value != self.process.processId():
                raise ValueError('WebView2 child window does not belong to the owned renderer process')
            self.startup_stage = 'window-verified'
            self.native_window = QWindow.fromWinId(hwnd)
            if self.native_window is None: raise ValueError('WebView2 child window could not be embedded')
            self.startup_stage = 'window-wrapped'
            self.container = QWidget.createWindowContainer(self.native_window, self)
            # View owns one Qt tab stop; the foreign HWND owns its DOM order.
            self.container.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.startup_stage = 'container-created'
            self.layout_box.addWidget(self.container)
            self.startup_stage = 'ready'
            self._ready = True
            self._refresh_position_filters()
            self.runtime_version = event.get('version', '')
            for item in self._queue: self._write(item)
            self._queue.clear()
            self.command('visible', value=self.isVisible())
            self.command('enabled', value=self.isEnabled())
            self._send_physical_resize()
        elif kind == 'load-start':
            self.page()._requested_url = QUrl(event['url'])
            self.page()._loading = True
            self.page().last_http_status = 0
            self.page().loadStarted.emit(); self.loadStarted.emit()
            self.page().loadingChanged.emit(LoadingInfo(event['url'], started=True))
        elif kind == 'url':
            self.page()._url = QUrl(event['url'])
            self.page().urlChanged.emit(self.url()); self.urlChanged.emit(self.url())
        elif kind == 'load-finish':
            self.page()._loading = False
            self.page().last_http_status = int(event.get('http_status', 0))
            ok = bool(event.get('ok'))
            self.page().loadingChanged.emit(LoadingInfo(event['url'], ok=ok, download=event.get('download', False), error=event.get('error', 0)))
            self.page().loadFinished.emit(ok); self.loadFinished.emit(ok)
        elif kind == 'download':
            identifier = event['download_id']
            if identifier in self._downloads: raise ValueError('Duplicate download identifier')
            request = Download(self, event)
            self._downloads[identifier] = request
            self.page().profile.downloadRequested.emit(request)
        elif kind == 'download-state':
            request = self._downloads.get(event['download_id'])
            if request: request.finish(event.get('state'), event.get('reason', ''))
        elif kind == 'download-progress':
            request = self._downloads.get(event['download_id'])
            if request and not request.isFinished(): request.timer.start()
        elif kind == 'download-blocked':
            self._command_notice('The download was refused by this session\'s origin/document safeguards. No file was saved. Retry an explicit export on the current page.')
        elif kind == 'file-picker':
            generation, navigation = event.get('generation'), event.get('nav_id')
            if (generation is not None and (generation != self._active_generation or navigation != self._active_navigation)):
                self.command('files', ticket=event['ticket'], paths=[])
                return
            from .webview2_file_selection import prepare_handback, handback_complete
            mode = QWebEnginePage.FileSelectionMode.FileSelectOpenMultiple if event.get('multiple') else QWebEnginePage.FileSelectionMode.FileSelectOpen
            ticket = event['ticket']
            paths = self.page().chooseFiles(mode, [], [], ticket=ticket, requested_url=event.get('url'))
            paths = prepare_handback(self, ticket, paths)
            self.command('files', ticket=event['ticket'], paths=paths,
                         callback=lambda value: handback_complete(self, ticket, success=True, result=value),
                         on_error=lambda error: handback_complete(self, ticket, success=False, result=error))
        elif kind == 'script-dialog':
            accepted, text = self._script_dialog(event)
            self.command('dialog', ticket=event['ticket'], accepted=accepted, text=text)
        elif kind == 'focus-boundary':
            direction = event.get('direction')
            if direction not in ('next', 'previous'): raise ValueError('Invalid native focus direction')
            self._leave_browser_focus(direction)
        elif kind == 'print': self.page().printRequested.emit()
        elif kind == 'print-finished': self._finish_print(event['path'], bool(event.get('ok')))
        elif kind == 'attachment-declined':
            status = event.get('http_status')
            if (isinstance(status, int) and not isinstance(status, bool) and 200 <= status < 300
                    and event.get('reason') in ('automatic-downloads-denied', 'browser-declined')):
                owner=self.page().owner
                handler=getattr(owner,'_attachment_declined',None)
                if (not self._retiring and not owner._closing and owner.view is self
                        and handler is not None and handler(self,QUrl(event.get('url','')))):
                    return
                self._command_notice('The browser declined this attachment; no new file was saved for this request. Use an explicit export action or your regular browser.')
        elif kind in ('external-request', 'external-refused'):
            from .webview2_external import request
            request(self, event)
        elif kind in ('blocked', 'navigation-blocked', 'popup-blocked'):
            # Generic policy denials carry no authority to launch another app.
            self.page().owner.note_blocked(QUrl(event.get('url', '')))
        elif kind in ('certificate-error', 'certificate-refused'):
            self.page().owner.statusBar().showMessage('Server certificate validation failed. The certificate was not bypassed.')
        elif kind in ('process-failed', 'fatal'):
            value = event.get('value')
            self._failure(event.get('error', event.get('message', value.get('message') if isinstance(value, dict) else 'WebView2 browser process failed')))
        elif kind == 'close-requested':
            self.page().owner.close()
        elif kind == 'runtime':
            self.runtime_info = dict(event)
        elif kind == 'scale-state':
            self.scale_state = dict(event)
        elif kind == 'cover-state':
            owner = self.page().owner
            if owner.mode != 'server' or owner.view is not self or self._retiring or owner._closing:
                return
            import ctypes
            from ctypes import wintypes
            hwnd = event.get('hwnd')
            if not isinstance(hwnd, int) or isinstance(hwnd, bool) or hwnd <= 0:
                raise ValueError('Invalid native cover window identity')
            pid = wintypes.DWORD()
            ctypes.windll.user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
            if pid.value != self.process.processId():
                raise ValueError('Native cover window is outside the owned renderer process')
            self.server_cover_state = dict(event)
        elif kind == 'browser-exited':
            self._browser_exit_pid = event.get('pid')
        elif kind == 'retired':
            if event.get('browser_exited') is True:
                self._retired_pid = event.get('pid')
        elif kind == 'initialization':
            self.startup_stage = 'host-' + str(event.get('value', 'unknown'))[:64]
        elif kind in ('file-picker-failed', 'print-request-failed'):
            owner = self.page().owner
            if not self._retiring and not owner._closing and owner.view is self:
                owner.statusBar().showMessage(
                    'File selection could not be completed; no new file was selected. Retry the chooser.'
                    if kind == 'file-picker-failed' else
                    'The print request could not be completed; no PDF was reported. Retry from the current page.')

    def _expire_callbacks(self):
        now = time.monotonic()
        if (not self._ready and not self._retiring and self._startup_deadline is not None
                and now >= self._startup_deadline and not self._startup_failed):
            self._startup_failed = True
            self._failure(f'The packaged WebView2 host did not become ready within 45 seconds ({self.startup_stage})')
        for identifier, item in list(self._callbacks.items()):
            if now >= item[0]:
                del self._callbacks[identifier]
                if len(item) > 2 and item[2]: item[2]({'message': 'Browser command timed out'})
                if item[1]: item[1](None)

    def _command_notice(self, message):
        owner = self.page().owner
        if not self._retiring and not owner._closing and owner.view is self:
            owner.statusBar().showMessage(message)

    def _script_dialog(self, event):
        """Ordinary page dialogs retain the same native stack close guard."""
        from .browser_lifetime import browser_dialog, OwnedPage
        owner = self.page().owner
        message = str(event.get('message', ''))
        if (self._retiring or owner.view is not self or
                OwnedPage._closing_notice(self.page(), message)):
            return False, ''
        kind = event.get('kind')
        title = 'DLMS page dialog — ' + QUrl(event.get('url', '')).host()
        with browser_dialog(owner):
            if kind == 'Prompt':
                dialog = QInputDialog(owner)
                dialog.setWindowTitle(title)
                dialog.setInputMode(QInputDialog.InputMode.TextInput)
                dialog.setLabelText(message)
                dialog.setTextValue(str(event.get('default', '')))
                for label in dialog.findChildren(QLabel): label.setTextFormat(Qt.TextFormat.PlainText)
                accepted = dialog.exec() == QDialog.DialogCode.Accepted
                return bool(accepted), dialog.textValue() if accepted else ''
            if kind not in ('Alert', 'Confirm', 'Beforeunload', 'BeforeUnload'):
                return False, ''
            dialog = QMessageBox(owner)
            dialog.setWindowTitle(title)
            dialog.setTextFormat(Qt.TextFormat.PlainText)
            dialog.setText(message)
            if kind == 'Alert':
                dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
                dialog.exec()
                return True, ''
            dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            dialog.setDefaultButton(QMessageBox.StandardButton.No)
            dialog.setEscapeButton(QMessageBox.StandardButton.No)
            return dialog.exec() == QMessageBox.StandardButton.Yes, ''

    def _process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self._failure('The packaged WebView2 host could not start')
            if not self._host_started:
                self._release_retired_resources()
                if self._retiring: QWidget.deleteLater(self)

    def _failure(self, message):
        self._cancel_prints()
        for request in self._downloads.values(): request.finish('interrupted', str(message), native_done=False)
        callbacks = list(self._callbacks.values())
        self._callbacks.clear()
        for item in callbacks:
            if item[1]: item[1](None)
        owner = self.page().owner
        if not self._retiring and not owner._closing:
            owner._fail(str(message))

    def _exited(self, code, status):
        # Drain the final proof records before interpreting QProcess.finished.
        self._read()
        self._read_error()
        self._ready = False
        self._deadline.stop()
        if not self._host_started or self._retirement_confirmed():
            self._release_retired_resources()
            if self._retiring:
                QWidget.deleteLater(self)
            else:
                self._failure(f'WebView2 host stopped unexpectedly ({code}); reopen the profile for recovery')
            return
        self._retirement_error = f'WebView2 host exited ({code}) without confirmed browser retirement; storage and staging pins remain held'
        self._failure(self._retirement_error)

    def _retirement_confirmed(self):
        pid = getattr(self, '_browser_exit_pid', None)
        expected = getattr(self, 'runtime_info', {}).get('pid')
        return (isinstance(pid, int) and not isinstance(pid, bool) and pid > 0
                and pid == getattr(self, '_retired_pid', None) and (expected is None or expected == pid))

    def _release_retired_resources(self):
        for request in getattr(self, '_downloads', {}).values():
            request.finish('interrupted', 'The owned native writer retired before completion', native_done=True)
        for partial in list(getattr(self, '_prints', {})):
            self._finish_print(partial, False, native_done=True)
        try:
            if getattr(self, '_selection_store', None) is not None:
                from .webview2_file_selection import retire
                errors = retire(self)
                self._selection_cleanup_errors.extend(errors or ())
        except Exception as exc:
            self._selection_cleanup_errors.append(str(exc))
        finally:
            pins = getattr(self, '_storage_pins', None)
            if pins is not None: pins.close()

    def deleteLater(self):
        if self._retiring: return
        View._cancel_prints(self)
        self._retiring = True
        self._detach_position_filters()
        if self.process is None or (self.process.state() == QProcess.ProcessState.NotRunning
                                    and (not getattr(self, '_host_started', False) or self._retirement_confirmed())):
            View._release_retired_resources(self)
            QWidget.deleteLater(self)
            return
        if self.process.state() == QProcess.ProcessState.NotRunning:
            self._retirement_error = 'The native host is gone without browser retirement proof; storage remains pinned'
            return
        # Do not delete QProcess or the page while the native child still owns
        # storage/handles. A stuck host leaves retirement incomplete, fail closed.
        self._queue.clear()
        self._serial += 1
        self._write(dict(id=self._serial, op='close'))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._send_physical_resize()

    def event(self, event):
        result = super().event(event)
        self._refresh_scale_event(event)
        if event.type() in (QEvent.Type.ParentChange, QEvent.Type.WinIdChange):
            self._refresh_position_filters()
        if event.type() in self._position_events():
            self._notify_parent_position()
        return result

    @staticmethod
    def _position_events():
        return (QEvent.Type.Move, QEvent.Type.Resize, QEvent.Type.ParentChange, QEvent.Type.WinIdChange,
                QEvent.Type.ScreenChangeInternal, QEvent.Type.DevicePixelRatioChange)

    def _detach_position_filters(self):
        for ancestor in getattr(self, '_position_ancestors', ()):
            try: ancestor.removeEventFilter(self)
            except RuntimeError: pass  # An ancestor may already be destroyed.
        self._position_ancestors = []

    def _refresh_position_filters(self):
        self._detach_position_filters()
        if not getattr(self, '_ready', False) or getattr(self, '_retiring', False): return
        ancestor = self.parentWidget()
        while ancestor is not None:
            ancestor.installEventFilter(self)
            self._position_ancestors.append(ancestor)
            ancestor = ancestor.parentWidget()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.ParentChange:
            self._refresh_position_filters()
        if event.type() in self._position_events():
            self._notify_parent_position()
        return super().eventFilter(watched, event)

    def _notify_parent_position(self):
        if not getattr(self, '_ready', False) or getattr(self, '_retiring', False) or self.native_window is None:
            return
        owner = self.page().owner
        if owner.view is self and not owner._closing and getattr(owner, '_retiring_browser', None) is None:
            # The C# host calls the supported Controller notification API.
            # HWND parent movement may not change the child's relative coords.
            self.command('position')

    def setZoomFactor(self, value):
        self.command('zoom', value=float(value))

    def showEvent(self, event):
        super().showEvent(event)
        if self._ready: self.command('visible', value=True)

    def hideEvent(self, event):
        super().hideEvent(event)
        if self._ready: self.command('visible', value=False)

    def setEnabled(self, value):
        super().setEnabled(value)
        if self._ready: self.command('enabled', value=bool(value))

    def focusInEvent(self, event):
        super().focusInEvent(event)
        if self._ready and not self._retiring:
            reason = {Qt.FocusReason.TabFocusReason: 'next', Qt.FocusReason.BacktabFocusReason: 'previous'}.get(event.reason(), 'programmatic')
            self.command('focus', reason=reason)

    def _leave_browser_focus(self, direction):
        """Leave the HWND only for a visible, enabled native Qt tab stop."""
        owner = self.page().owner
        if (self._retiring or not self._ready or owner.view is not self or owner._closing
                or any(getattr(owner, flag, False) for flag in ('_browser_dialog_depth', '_close_active',
                    '_close_after_dialog', '_mode_switch_busy', '_browser_operation_depth'))
                or getattr(owner, '_retiring_browser', None) is not None):
            return
        forward = direction == 'next'
        reason = Qt.FocusReason.TabFocusReason if forward else Qt.FocusReason.BacktabFocusReason
        candidate = self.nextInFocusChain() if forward else self.previousInFocusChain()
        visited = {self}
        while candidate not in visited:
            visited.add(candidate)
            if (not self.isAncestorOf(candidate) and candidate.window() is self.window()
                    and candidate.isVisible() and candidate.isEnabled()
                    and candidate.focusPolicy() & Qt.FocusPolicy.TabFocus):
                candidate.setFocus(reason)
                return
            candidate = candidate.nextInFocusChain() if forward else candidate.previousInFocusChain()

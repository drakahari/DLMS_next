"""A bounded Qt WebEngine window owning one disposable local DLMS backend."""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
import http.client
import ipaddress
import json
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import time

from PySide6.QtCore import QEventLoop, QLockFile, QStandardPaths, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QIcon, QColor
from PySide6.QtNetwork import QLocalServer, QLocalSocket, QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QMainWindow,
                               QMenu, QMessageBox, QProgressBar, QPushButton, QSizePolicy, QToolButton,
                               QStackedLayout, QVBoxLayout, QWidget)
from PySide6.QtWebEngineCore import (
    QWebEnginePage, QWebEngineProfile, QWebEngineSettings, QWebEngineScript,
    QWebEngineUrlRequestInterceptor, QWebEngineLoadingInfo,
)
from PySide6.QtWebEngineWidgets import QWebEngineView

from .isolation import AREA, PROJECT, FROZEN, assert_safe_leaf, isolated_environment
from .frozen_runtime import (abstract_instance_socket, child_command,
                             instance_socket_name, source_environment, spawn_process)
from .processes import reap_owned_group
from .profile_state import atomic_json, new_manifest, publish_manifest, read_manifest
from .settings_surface import LocalSettingsSurface, DEFAULT_THEME, THEME_REGISTRY, _solid
from .server_surface import NEUTRAL_SERVER_PALETTE, connection_text
from .server_readiness import READINESS_SCRIPT, document_identity, ready_new_document
from .server_mode import configured_server, read_config, server_root, shell_root, write_config
from .server_browser import ServerOnlyInterceptor, ServerPage, exact_server_origin
from .browser_lifetime import (browser_dialog, OwnedPage, BrowserRetirement, browser_operation,
                               browser_file_dialog)

READY_PATH = "/_desktop/ready"
# Safety allowlist for links read from the captured canonical sidebar. This
# does not define labels, order, active state or visibility; the verified DOM
# remains their source. A new source navigation route needs explicit review.
SETTINGS_NAV_DESTINATIONS = frozenset({
    "/", "/library", "/upload", "/study-packs", "/it", "/law", "/medical",
    "/study-packs?domain_group=other", "/certifications", "/history", "/dashboard",
    "/learning-intelligence", "/marked-questions", "/anki", "/settings", "/content-packs",
    "/admin/image-editor", "/help", "/settings/backup", "/settings/reset-remove",
    "/settings/appearance", "/settings/layout",
})


def dispatch_external(url: QUrl):
    """No private Desktop descriptor may follow a URL into an external app."""
    from .package_entry import _seal_private_descriptors
    _seal_private_descriptors()
    if sys.platform == 'darwin' and url.scheme() in {'http', 'https'}:
        from .macos_browser import dispatch
        return dispatch(url)
    if sys.platform.startswith("linux") and url.scheme() in {"http", "https"}:
        from .external_browser import dispatch
        return dispatch(url)
    if os.name == 'nt' and url.scheme() in ('http', 'https'):
        from .webview2_runtime import active as webview2_active
        if webview2_active():
            from .windows_browser_handoff import dispatch
            return dispatch(url)
    return QDesktopServices.openUrl(url)


def handoff_external(owner, url: QUrl, *, ai=False):
    """Report async portal outcomes without changing action authorization.

    Authorization remains at the owned AI input or generic confirmation call
    site. A new handoff/page/mode/status retires this UI callback, not the actual
    session request. Clipboard contents and prompt generation are untouched.
    """
    # QtDBus is Linux-only; shared AI/link call sites must keep working on the
    # other platform's existing browser adapter without importing this module.
    if sys.platform.startswith('linux'):
        from .external_browser import PortalRequest
    else:
        PortalRequest = ()
    serial = getattr(owner, '_external_handoff_serial', 0) + 1
    owner._external_handoff_serial = serial
    context = (getattr(owner, 'mode', None), getattr(owner, '_browser_generation', None),
               getattr(owner, 'view', None))
    pending = ('Requesting opening in your default browser…' if sys.platform == 'darwin'
               else 'Requesting browser opening through the session portal…')
    bar = owner.statusBar()
    bar.showMessage(pending)
    def completed(outcome, message):
        from PySide6.QtCore import QObject
        from shiboken6 import isValid
        if isinstance(owner, QObject) and not isValid(owner):
            return
        if (getattr(owner, '_closing', False) or getattr(owner, '_retiring_browser', None) is not None
                or owner._external_handoff_serial != serial
                or context != (getattr(owner, 'mode', None), getattr(owner, '_browser_generation', None),
                               getattr(owner, 'view', None)) or bar.currentMessage() != pending):
            return
        if ai and outcome == 'accepted':
            message += ' Paste manually; nothing was submitted.'
        bar.showMessage(message)
        bar.setToolTip(message)
        bar.setAccessibleDescription(message)
        if outcome in {'unavailable', 'unconfirmed'}:
            with browser_dialog(owner):
                QMessageBox.warning(owner, 'Browser handoff unconfirmed', message)
    try:
        request = dispatch_external(url)
        if isinstance(request, PortalRequest):
            request.finished.connect(completed)
        elif request:
            completed('accepted', 'Browser handoff requested.')  # Other platforms retain their own adapter.
        else:
            completed('unconfirmed', 'The browser could not confirm handoff. Check your browser before retrying.')
    except (OSError, ValueError) as exc:
        completed('unavailable', str(exc))


def allowed_internal(url: QUrl, port: int) -> bool:
    return (url.scheme() == "http" and url.host() == "127.0.0.1"
            and url.port() == port and not url.userName() and not url.password())


def allowed_external(url: QUrl) -> bool:
    host = url.host().lower().rstrip(".")
    if url.scheme() not in {"http", "https"} or not host or url.userName() or url.password():
        return False
    if host == "localhost" or host.endswith(".localhost"):
        return False
    try:
        if ipaddress.ip_address(host).is_loopback:
            return False
    except ValueError:
        pass
    return True


def managed_settings_page(url: QUrl, port: int) -> str | None:
    """Recognize only the recorded origin and exact supported Settings documents."""
    if not allowed_internal(url, port):
        return None
    encoded = bytes(url.toEncoded()).decode("ascii")
    origin = f"http://127.0.0.1:{port}"
    if encoded in {origin + "/settings/backup",
                   origin + "/settings/backup?storage=1",
                   origin + "/settings/backup?storage=1#storage-health"}:
        return "backup"
    if encoded == origin + "/settings/reset-remove":
        return "reset-remove"
    return None


def safe_native_navigation(path: str) -> bool:
    """Restrict mirrored sidebar controls to ordinary local GET page routes."""
    return isinstance(path, str) and path in SETTINGS_NAV_DESTINATIONS


class LocalOnlyInterceptor(QWebEngineUrlRequestInterceptor):
    def __init__(self, token: str, port: int, parent=None):
        super().__init__(parent)
        self.token = token.encode("ascii")
        self.port = port
        self.blocked_internal_paths: set[str] = set()
        self.denied_initiators: list[tuple[str, str]] = []

    def interceptRequest(self, info):  # noqa: N802 - Qt API
        url = info.requestUrl()
        initiator = info.initiator()
        first_party = allowed_internal(initiator, self.port)
        top_bootstrap = (info.resourceType() == info.ResourceType.ResourceTypeMainFrame
                         and (initiator.isEmpty() or first_party))
        if (not allowed_internal(url, self.port) and url.scheme() not in {"data", "blob", "about"}) or (allowed_internal(url, self.port) and url.path() in self.blocked_internal_paths):
            info.block(True)
        elif allowed_internal(url, self.port):
            if first_party or top_bootstrap:
                info.setHttpHeader(b"X-DLMS-Desktop-Token", self.token)
                if first_party and info.requestMethod() == b"POST":
                    # Qt emits Origin:null for ordinary form navigations.
                    # This initiator is the exact owned application origin.
                    info.setHttpHeader(b"Origin", f"http://127.0.0.1:{self.port}".encode("ascii"))
            else:
                self.denied_initiators.append((url.path(), initiator.toString()))
                info.block(True)


class LocalPage(OwnedPage):
    def __init__(self, profile, owner, parent=None):
        super().__init__(profile, parent if parent is not None else owner)
        self.owner = owner
        self.newWindowRequested.connect(self._new_window)
        from .marked_exports import install
        install(self)
        from .ai_actions import AIHandoff
        self.ai_handoff = AIHandoff(self, owner)
        if sys.platform == 'darwin':
            from .macos_file_selection import install_selection_guard
            install_selection_guard(self)

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):  # noqa: N802 - Qt API
        if self.owner.view is None:
            return False
        if not is_main_frame:
            return allowed_internal(url, self.owner.port) or url.scheme() in {"data", "blob", "about"}
        if allowed_internal(url, self.owner.port) or url.toString() == "about:blank":
            return True
        if nav_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked:
            self.ai_handoff.handle(url, True, generic=lambda: self.owner.open_external(url))
        else:
            self.owner.note_blocked(url)
        return False

    def _new_window(self, request):
        if (self.owner.view is None or self.owner._closing
                or self.owner._retiring_browser is not None or self.owner.view.page() is not self):
            return
        url = request.requestedUrl()
        if not request.isUserInitiated():
            self.owner.note_blocked(url)
        elif allowed_internal(url, self.owner.port):
            request.openIn(self)  # Preserve POST/body; setUrl would manufacture GET.
        else:
            self.ai_handoff.handle(url, request.isUserInitiated(), generic=lambda: self.owner.open_external(url))

    @browser_file_dialog
    def chooseFiles(self, mode, old_files, accepted_mime_types):  # noqa: N802 - Qt API
        # Linux receives immutable, explicitly selected private snapshots.
        # Other platforms retain their current adapter pending native work.
        import sys
        if sys.platform == 'darwin':
            from .macos_file_selection import choose_files
            return choose_files(self, mode, server=False)
        if sys.platform.startswith("linux"):
            from .file_selection import choose_files
            return choose_files(self, mode, server=False)
        """Use a native picker rooted in disposable data, rejecting outside paths."""
        events=getattr(self.owner,'window_events',None)
        if events is not None:events.emit('file-dialog-open',kind='upload')
        selected = self.owner.file_selection_for_test
        if selected is not None:
            self.owner.file_selection_for_test = None
            choices = [str(selected)]
        elif mode == QWebEnginePage.FileSelectionMode.FileSelectOpenMultiple:
            choices, _ = QFileDialog.getOpenFileNames(self.owner, "Choose synthetic files", str(upload_start_directory()))
        elif mode == QWebEnginePage.FileSelectionMode.FileSelectOpen:
            choice, _ = QFileDialog.getOpenFileName(self.owner, "Choose a synthetic file", str(upload_start_directory()))
            choices = [choice] if choice else []
        else:
            return []
        approved = []
        for choice in choices:
            path = Path(choice).resolve()
            if path.is_file() and (path.is_relative_to(AREA.resolve()) or path.is_relative_to((PROJECT / "fixtures").resolve())):
                approved.append(str(path))
            else:
                self.owner.note_blocked(QUrl.fromLocalFile(str(path)))
                self.owner.statusBar().showMessage(
                    "File selection was refused. Choose a synthetic file inside this candidate's data root or its bundled fixtures."
                    if os.name=='nt' and FROZEN else
                    "File selection was refused. Choose a synthetic file inside this project's disposable area or fixtures.")
        if events is not None:events.emit('file-dialog-result',accepted=len(approved),refused=len(choices)-len(approved))
        return approved


def upload_start_directory():
    # Frozen private candidates ship the same synthetic inputs allowed by the
    # existing PROJECT/fixtures boundary. No repository/personal path exception.
    fixtures=PROJECT/'fixtures'
    return fixtures if os.name=='nt' and FROZEN and fixtures.is_dir() else AREA


class DesktopWindow(QMainWindow):
    def __init__(self, paths: dict[str, Path], profile_name: str, *, documents_folder: Path | None = None):
        super().__init__()
        self.paths = paths
        self.profile_name = profile_name
        self.documents_folder = documents_folder or Path(
            QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
            or QStandardPaths.writableLocation(QStandardPaths.StandardLocation.HomeLocation))
        self.mode_config = read_config(profile_name)
        self.mode = self.mode_config["mode"]
        self.owner_root = shell_root(profile_name)
        self.local_lock: QLockFile | None = None
        self.server_paths: dict[str, Path] | None = None
        self.server_interceptor = None
        self.server_unreachable = False
        self.server_loaded_once = False
        self._local_loaded_url = None
        self._server_loaded_url = None
        self._mode_switch_busy = False
        self._mode_theme = DEFAULT_THEME
        self.manifest = read_manifest(paths, profile_name) if self.mode == "local" else None
        self.port = self.manifest["port"] if self.manifest else None
        self.nonce = secrets.token_hex(32)
        # Qt helpers created after this point inherit an exact, random owner
        # marker; cleanup never targets a process by executable name.
        os.environ["DLMS_DESKTOP_NONCE"] = self.nonce
        self.reserved_socket: socket.socket | None = None
        self.parent_pipe_write: int | None = None
        self.backend: subprocess.Popen | None = None
        self.backend_log = None
        self.started_at = time.monotonic()
        self.ready_ms: int | None = None
        self.failed_reason: str | None = None
        self.blocked_urls: list[str] = []
        self.downloaded_files: list[Path] = []
        self.download_results: list[dict] = []
        self.pdf_files: list[Path] = []
        self.pdf_results: list[dict] = []
        self.file_selection_for_test: Path | None = None
        self.view: QWebEngineView | None = None
        self.profile: QWebEngineProfile | None = None
        self.settings_panel: LocalSettingsSurface | None = None
        self.settings_fallback: QLabel | None = None
        self.settings_buttons: dict[str, QPushButton] = {}
        self.settings_network = QNetworkAccessManager(self)
        self._settings_action_busy = False
        self._backup_creating = False
        from .operation_feedback import OperationFeedback
        self.operation_feedback = OperationFeedback()
        self._feedback_mode = "local"
        self._feedback_writing = False
        self.statusBar().messageChanged.connect(self._status_message_changed)
        self._backup_feedback_ticket = 0
        self._import_feedback_ticket = 0
        self._settings_transition_refused = False
        self._settings_generation = 0
        self._settings_kind: str | None = None
        self._settings_verified_url: bytes | None = None
        self._closing = False
        self._close_active = False
        self._close_complete = False
        self._browser_dialog_depth = 0
        self._close_after_dialog = False
        self._browser_generation = 0
        self._browser_operation_depth = 0
        self.close_browser_notices = []
        self._retiring_browser = None
        self._retirement_wait_active = False
        self.browser_retirements = []
        self.setWindowTitle("DLMS Desktop")
        icon_path = PROJECT / "desktop_assets/dlms-icon-master.png"
        icon = QIcon(str(icon_path))
        if icon.isNull():
            raise RuntimeError(f"The owner-selected Desktop icon is unavailable: {icon_path}")
        self.setWindowIcon(icon)
        QApplication.instance().setWindowIcon(icon)
        self.resize(1280, 850)
        self._create_mode_toolbar()
        self.setCentralWidget(QLabel("Starting the disposable DLMS backend…"))
        self.import_worker: subprocess.Popen | None = None
        self.import_output = None
        self.import_parent_pipe: int | None = None
        self.import_started: float | None = None
        self.import_in_progress = False
        self._import_status_serial = 0
        self._import_worker_status_serial: int | None = None
        self._import_reopen_status: tuple[int, str] | None = None
        self.backup_selection_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dlms-backup-selection")
        self.backup_selection_future = None
        self.backup_selection_context = None
        self.backup_output_selection = None
        self.backup_output_operation = None
        self.backup_output_future = None
        self.backup_output_record = None
        self.backup_output_timer = QTimer(self)
        self.backup_output_timer.setInterval(100)
        self.backup_output_timer.timeout.connect(self._poll_backup_output)
        self.open_backup_folder = QPushButton("Open containing folder", self)
        self.open_backup_folder.setAccessibleName("Open folder containing the saved Local backup")
        self.open_backup_folder.hide()
        self.open_backup_folder.clicked.connect(self._open_backup_folder)
        self.statusBar().addPermanentWidget(self.open_backup_folder)
        self.last_backup_output = None
        self.backup_selection_timer = QTimer(self)
        self.backup_selection_timer.setInterval(100)
        self.backup_selection_timer.timeout.connect(self._poll_backup_selection)
        self.import_stage = None
        self.import_timer = QTimer(self)
        self.import_timer.setInterval(150)
        self.import_timer.timeout.connect(self._poll_import)
        self.maintenance_worker: subprocess.Popen | None = None
        self.maintenance_output = None
        self.maintenance_pipe: int | None = None
        self.maintenance_started: float | None = None
        self.maintenance_stage = None
        self.maintenance_transition = False
        self.maintenance_timer = QTimer(self)
        self.maintenance_timer.setInterval(150)
        self.maintenance_timer.timeout.connect(self._poll_maintenance)
        self.removal_worker: subprocess.Popen | None = None
        self.removal_output = None
        self.removal_pipe: int | None = None
        self.removal_handoff = False
        self.removal_timer = QTimer(self)
        self.removal_timer.setInterval(150)
        self.removal_timer.timeout.connect(self._poll_removal)
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self._focus_request)
        self.socket_path = instance_socket_name(self.owner_root)
        # The launcher holds the shell lock. Local separately holds its
        # original profile lock so existing worker ownership checks remain.
        if self.mode == "local":
            self._acquire_local_ownership()
        if abstract_instance_socket():
            self.server.setSocketOptions(QLocalServer.SocketOption.AbstractNamespaceOption)
        else:
            QLocalServer.removeServer(self.socket_path)
        if not self.server.listen(self.socket_path):
            raise RuntimeError(f"Cannot listen for duplicate-launch requests: {self.server.errorString()}")
        self.instance_secret = secrets.token_hex(32)
        self.instance_descriptor = self.owner_root / "instance-owner.json"
        from .ownership import process_start_ticks
        descriptor = {"pid": os.getpid(), "start_ticks": process_start_ticks(os.getpid()),
                      "name": profile_name, "secret": self.instance_secret}
        atomic_json(self.instance_descriptor, descriptor)
        if self.mode == "local":
            atomic_json(self.paths["root"] / "instance-owner.json", descriptor)
        self.poll = QTimer(self)
        self.poll.setInterval(120)
        self.poll.timeout.connect(self._poll_backend)
        self.monitor = QTimer(self)
        self.monitor.setInterval(500)
        self.monitor.timeout.connect(self._monitor_backend)
        self.mode_theme_poll = QTimer(self)
        self.mode_theme_poll.setInterval(1200)
        self.mode_theme_poll.timeout.connect(self._poll_mode_theme)
        self.mode_theme_poll.start()
        self.server_readiness_timer = QTimer(self)
        self.server_readiness_timer.setInterval(50)
        self.server_readiness_timer.timeout.connect(self._probe_server_readiness)

    def _acquire_local_ownership(self):
        if self.local_lock is not None:
            return
        root = self.paths["root"]
        if not root.is_dir() or root.is_symlink():
            raise RuntimeError("The existing Local profile root is unavailable; no Local dataset was created")
        lock_path = root / "instance.lock"
        assert_safe_leaf(lock_path)
        lock = QLockFile(str(lock_path))
        lock.setStaleLockTime(0)
        if not lock.tryLock(0):
            raise RuntimeError("Local profile has another owner; no second writer was started")
        self.local_lock = lock
        if hasattr(self, "instance_secret"):
            try:
                from .ownership import process_start_ticks
                atomic_json(root / "instance-owner.json", {
                    "pid": os.getpid(), "start_ticks": process_start_ticks(os.getpid()),
                    "name": self.profile_name, "secret": self.instance_secret})
            except Exception:
                lock.unlock()
                self.local_lock = None
                raise

    def _release_local_ownership(self):
        if self.local_lock is None:
            return
        descriptor = self.paths["root"] / "instance-owner.json"
        try:
            data = json.loads(descriptor.read_text())
            if data.get("secret") == self.instance_secret:
                descriptor.unlink()
        except (OSError, ValueError):
            pass
        self.local_lock.unlock()
        self.local_lock = None

    def _create_mode_toolbar(self):
        # This Qt-owned control exists even when the web page is unavailable.
        # Remote documents receive no command channel to these actions.
        self.mode_identity = QToolButton(self)
        self.mode_identity.setObjectName("desktopModeControl")
        self.mode_identity.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.mode_identity.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.mode_menu = QMenu(self.mode_identity)
        self.mode_identity.setMenu(self.mode_menu)
        group = QActionGroup(self.mode_menu)
        group.setExclusive(True)
        self.local_mode_action = QAction("Local", group)
        self.local_mode_action.setCheckable(True)
        self.local_mode_action.triggered.connect(self.switch_to_local)
        self.server_mode_action = QAction("Server", group)
        self.server_mode_action.setCheckable(True)
        self.server_mode_action.triggered.connect(self.switch_to_server)
        self.mode_menu.addAction(self.local_mode_action)
        self.mode_menu.addAction(self.server_mode_action)
        self.mode_menu.addSeparator()
        self.configure_server_action = self.mode_menu.addAction("Configure Server…", self._configure_server_dialog)
        self.retry_server_action = self.mode_menu.addAction("Retry connection", self._retry_server)
        self.mode_menu.addSeparator()
        self.mix_diagnostics = None
        self.mix_diagnostic_action = None
        if os.environ.get("DLMS_DESKTOP_DEBUG_MIX_TIMING") == "1":
            self.mix_diagnostic_action = self.mode_menu.addAction("Capture Mix timing (60 seconds)…", self._capture_mix_diagnostics)
        self.about_action = self.mode_menu.addAction("About DLMS Desktop…", self._show_about)
        self.statusBar().addPermanentWidget(self.mode_identity)
        self._style_mode_control(DEFAULT_THEME)
        self._update_mode_toolbar()

    @browser_operation
    def _capture_mix_diagnostics(self):
        # Native opt-in only. Nothing on a remote page can call this method.
        if self.mix_diagnostic_action is None:
            return
        current=getattr(self,'mix_diagnostics',None)
        if current is not None and not current.stopped:
            current.stop("Capture stopped by owner")
            return
        if (self.mode != "server" or self.view is None or self._closing
                or self._retiring_browser is not None or not self._server_page_exposed
                or self.view.page().isLoading()
                or not exact_server_origin(self.view.url(),self.mode_config['server']['origin'])
                or self.view.url().path() != "/quiz-composer"):
            QMessageBox.information(self,"Mix timing unavailable","Open the loaded Server Mix Questions page first. Local data and other pages are not captured.")
            return
        context=(self.view.page(),self._browser_generation,self._server_navigation_serial,self._server_document_identity,self.mode_config['server']['origin'])
        answer=QMessageBox.question(self,"Capture Mix timing counts",
            "For 60 seconds, record filter/selection event timings and numeric counts only. "
            "No question text, selected IDs, server URL, cookies, credentials or request bodies are recorded. "
            "This adds small measurement overhead and does not save or change your selection. "
            "The private log stays in this Desktop profile’s shell evidence. Start capture?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if answer != QMessageBox.StandardButton.Yes:return
        if (self._closing or self._retiring_browser is not None or self.mode!='server'
                or self.view is None or not self._server_page_exposed or self.view.page().isLoading()
                or context!=(self.view.page(),self._browser_generation,self._server_navigation_serial,self._server_document_identity,self.mode_config['server']['origin'])):
            return
        from .mix_diagnostics import MixDiagnostics
        try:
            collector=MixDiagnostics(self);self.mix_diagnostics=collector
            self.mix_diagnostic_action.setText("Stop Mix timing capture")
            def finished(path,reason):
                self.mix_diagnostic_action.setText("Capture Mix timing (60 seconds)…")
                if not self._closing and collector.valid():
                    QMessageBox.information(self,"Mix timing evidence",reason+"\nPrivate counts log: "+path)
                elif not self._closing:
                    self.statusBar().showMessage(reason+"; private counts evidence retained.",10000)
            collector.finished.connect(finished)
        except (OSError,ValueError):
            QMessageBox.warning(self,"Mix timing unavailable","The private diagnostic destination is unavailable; capture was not started.")

    def _about_text(self):
        from .build_info import about_text
        saved=self.manifest or read_manifest(self.paths,self.profile_name)
        origin=f"http://127.0.0.1:{saved['port']}" if saved else None
        return about_text(mode=self.mode,profile=self.profile_name,local_origin=origin,
                          server=self.mode_config.get('server'))

    def _show_about(self):
        dialog=QDialog(self)
        dialog.setWindowTitle("About DLMS Desktop")
        dialog.setAccessibleName("DLMS Desktop build and active dataset")
        layout=QVBoxLayout(dialog)
        label=QLabel(self._about_text(),dialog)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByKeyboard | Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setAccessibleName("Build, support, mode and dataset information")
        label.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        layout.addWidget(label)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Close,dialog)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        theme=THEME_REGISTRY.get(getattr(self,'_mode_theme',DEFAULT_THEME),THEME_REGISTRY[DEFAULT_THEME])
        colors=theme['colors'];base=colors['body_base']
        dialog.setStyleSheet(f"QDialog {{background:{_solid(colors['panel1'],base)};color:{colors['page']};}} "
            f"QLabel {{color:{colors['page']};font-size:14px;padding:8px;}} "
            f"QPushButton {{background:{_solid(colors['surface2'],base)};color:{colors['page']};padding:8px 16px;}} "
            f"QPushButton:focus {{border:2px solid {colors['accent_text']};}}")
        dialog.resize(min(600,max(300,self.width()-40)),460)
        buttons.button(QDialogButtonBox.StandardButton.Close).setFocus()
        dialog.exec()
        self.activateWindow()
        self.mode_identity.setFocus()

    def _update_mode_toolbar(self):
        if hasattr(self, "open_backup_folder"):
            self.open_backup_folder.setVisible(self.mode == "local" and self.last_backup_output is not None)
        server = self.mode_config.get("server")
        if self.mode == "server" and server:
            state = " — connection unavailable" if self.server_unreachable else ""
            label = f"Server: {server['label']}"
            detail = f"{label} · {server['origin']}{state}"
        else:
            label = "Local"
            detail = f"Local · profile {self.profile_name} · private Desktop data"
        self._mode_label = label
        self.mode_identity.setText(self.mode_identity.fontMetrics().elidedText(
            label + "  ▾", Qt.TextElideMode.ElideRight, min(280, max(120, self.width() // 3))))
        self.mode_identity.setToolTip(detail)
        self.mode_identity.setAccessibleName(f"Desktop mode: {detail}. Open mode menu")
        self.setWindowTitle(f"DLMS Desktop — {detail}")
        self.local_mode_action.setChecked(self.mode == "local")
        self.server_mode_action.setChecked(self.mode == "server")
        self.server_mode_action.setText(f"Server: {server['label']}" if server else "Server (not configured)")
        self.local_mode_action.setEnabled(not self._mode_switch_busy and self.mode != "local")
        self.server_mode_action.setEnabled(not self._mode_switch_busy and self.mode == "local" and server is not None)
        self.configure_server_action.setEnabled(not self._mode_switch_busy and self.mode == "local")
        self.retry_server_action.setVisible(self.mode == "server" and self.server_unreachable)
        self.retry_server_action.setEnabled(not self._mode_switch_busy)
        self.mode_identity.setEnabled(not self._mode_switch_busy)

    def resizeEvent(self, event):  # noqa: N802 - Qt API
        super().resizeEvent(event)
        if hasattr(self, "mode_identity"):
            self._update_mode_toolbar()

    def _style_mode_control(self, theme: str):
        if theme not in THEME_REGISTRY:
            theme = "" if self.mode == "server" else DEFAULT_THEME
        if theme == self._mode_theme and self.mode_identity.styleSheet():
            return
        self._mode_theme = theme
        entry = THEME_REGISTRY.get(theme)
        p = entry["colors"] if entry else NEUTRAL_SERVER_PALETTE
        extra = entry["extra_tokens"] if entry else {}
        base = p["body_base"]
        panel = _solid(p["panel1"], base)
        hover = _solid(p["surface2"], base)
        border = _solid(p["border"], base)
        focus = extra.get("--theme-focus-ring", p["accent_text"])
        self.statusBar().setStyleSheet(f"QStatusBar {{ background: {panel}; color: {p['page']}; }}")
        self.mode_identity.setStyleSheet(f"""
            QToolButton#desktopModeControl {{ background: {hover}; color: {p['page']};
                border: 1px solid {border}; border-radius: 8px; padding: 4px 10px; font-weight: 600; }}
            QToolButton#desktopModeControl:hover {{ border-color: {p['accent']}; }}
            QToolButton#desktopModeControl:focus {{ border: 2px solid {focus}; padding: 3px 9px; }}
            QToolButton#desktopModeControl:disabled {{ color: {p['muted']}; }}
        """)
        self.mode_menu.setStyleSheet(f"""
            QMenu {{ background: {panel}; color: {p['page']}; border: 1px solid {border}; padding: 5px; }}
            QMenu::item {{ padding: 7px 18px; }}
            QMenu::item:selected {{ background: {hover}; color: {p['heading']}; }}
            QMenu::item:disabled {{ color: {p['muted']}; }}
        """)

    def _poll_mode_theme(self):
        if (self._closing or self._retiring_browser is not None or self.view is None
                or not self.view.isVisible() or self.view.page().isLoading()
                or (self.mode == "server" and not self._server_page_exposed)):
            return
        page, mode = self.view.page(), self.mode
        generation = self._browser_generation
        serial = getattr(self, "_server_navigation_serial", 0)
        url = page.url().toString()
        origin = self.mode_config["server"]["origin"] if mode == "server" else None
        def received(value):
            # Only the current top document may select an allowlisted palette.
            # This callback has no command, file, token or transaction capability.
            if (self._closing or self._retiring_browser is not None or self.view is None
                    or self.view.page() is not page or self.mode != mode
                    or self._browser_generation != generation or page.isLoading()
                    or page.url().toString() != url or not self.view.isVisible()
                    or (mode == "server" and not self._server_page_exposed)
                    or getattr(self, "_server_navigation_serial", 0) != serial):
                return
            if mode == "server":
                if (self.server_unreachable or self.mode_config["server"]["origin"] != origin
                        or not exact_server_origin(page.url(), origin)):
                    return
                if isinstance(value, str) and value in THEME_REGISTRY:
                    self._server_theme = value
                    self._style_server_surface()
            elif isinstance(value, str) and value in THEME_REGISTRY:
                self._style_mode_control(value)
        page.runJavaScript("document.querySelector('.dashboard-sidebar')?.dataset.theme || ''", received)

    def _style_server_surface(self):
        theme = self._server_theme
        p = THEME_REGISTRY[theme]["colors"] if theme in THEME_REGISTRY else NEUTRAL_SERVER_PALETTE
        base, text = p["body_base"], p["page"]
        self.server_shell.setStyleSheet(f"QWidget#serverSurface {{ background: {base}; }}")
        self.server_status.setStyleSheet(f"QLabel {{ background: {base}; color: {text}; padding: 24px; font-size: 16px; }}")
        self.view.page().setBackgroundColor(QColor(base))
        self._style_mode_control(theme)

    def _configure_server_dialog(self):
        if (self._mode_switch_busy or self.mode != "local" or self.import_in_progress
                or self.maintenance_worker is not None):
            return
        prior = self.mode_config.get("server") or {}
        raw, accepted = QInputDialog.getText(self, "Configure Server origin",
            "Exact root URL (HTTPS recommended; no path, credentials or redirects):",
            text=prior.get("origin", "https://"))
        if not accepted:
            return
        label, accepted = QInputDialog.getText(self, "Name Server deployment",
            "Visible name for this separate server dataset:", text=prior.get("label", "DLMS Server"))
        if not accepted:
            return
        private_http = raw.lower().startswith("http://")
        if private_http and QMessageBox.warning(self, "Private HTTP has no transport encryption",
                f"Allow only this exact origin?\n\n{raw}\n\n"
                "HTTP does not encrypt the LAN hop, including a subnet-router-to-server hop. "
                "A private IP does not establish trust or application authentication. "
                "Use this advanced option only on a network you control.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        try:
            value = configured_server(self.mode_config, raw, label, private_http_opt_in=private_http)
        except ValueError as exc:
            QMessageBox.warning(self, "Server endpoint refused", str(exc))
            return
        try:
            if value["origin"] == f"http://127.0.0.1:{self.port}":
                raise ValueError("The current Local backend cannot be configured as a Server deployment")
            updated = dict(self.mode_config, server=value)
            write_config(self.profile_name, updated)
            self.mode_config = updated
            self._update_mode_toolbar()
            self.statusBar().showMessage("Server endpoint saved. Selecting Server will leave Local only after pending-work checks.")
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Server endpoint refused", str(exc))

    def _switch_refusal(self, reason: str) -> bool:
        self.statusBar().showMessage(reason)
        if os.environ.get("DLMS_DESKTOP_AUTOMATED") != "1":
            QMessageBox.warning(self, "Mode switch refused", reason)
        return False

    def _local_switch_preflight(self) -> None:
        if (self.mode != "local" or self.view is None or self.backend is None or self.backend.poll() is not None
                or self._closing or self.maintenance_transition or self.import_in_progress
                or self.maintenance_worker is not None or self.removal_worker is not None
                or self._backup_creating or self._active_outputs()):
            raise RuntimeError("Finish Local startup, import, backup, maintenance and downloads before switching")
        from .maintenance import _browser_pending, _ensure_no_pending
        from .maintenance import read_marker
        from .transition import read_transition
        from .removal import read_tombstone
        if read_marker(self.profile_name) is not None or read_transition(self.paths) is not None or read_tombstone(self.profile_name) is not None:
            raise RuntimeError("A Local data transition must be reconciled before switching modes")
        _ensure_no_pending(self.paths)
        for label in (".restore_operations", ".quiz_publications"):
            folder = self.paths["backend"] / label
            if folder.is_symlink() or (folder.exists() and not folder.is_dir()):
                raise RuntimeError(f"Local publication evidence is unsafe: {label}")
            if folder.exists() and any(folder.iterdir()):
                raise RuntimeError(f"Local publication or restore is unresolved: {label}")
        reason = _browser_pending(self._browser_storage_snapshot())
        if reason:
            raise RuntimeError(f"Local browser has pending work: {reason}. Resolve it before switching")

    @browser_operation
    def switch_to_server(self) -> bool:
        if getattr(self, '_browser_dialog_depth', 0):
            return self._switch_refusal('Finish or cancel the open file/browser dialog before switching modes')
        if self._mode_switch_busy:
            return False
        self._mode_switch_busy = True
        self._update_mode_toolbar()
        try:
            return self._switch_to_server_impl()
        finally:
            if not self._settings_transition_refused and self.failed_reason is None:
                self._mode_switch_busy = False
            self._update_mode_toolbar()

    def _switch_to_server_impl(self) -> bool:
        if self.mode == "server":
            return True
        if self.mode_config.get("server") is None:
            return self._switch_refusal("Configure a Server endpoint before selecting Server")
        if self.mode_config["server"]["origin"] == f"http://127.0.0.1:{self.port}":
            return self._switch_refusal("The Local backend cannot be selected as a Server deployment")
        try:
            self._local_switch_preflight()
        except (OSError, ValueError, RuntimeError) as exc:
            return self._switch_refusal(str(exc))
        if not self._quiesce_browser() or not self._drain_backend():
            self._show_transition_refusal("Local save outcome is uncertain. Reopen this profile to recover before switching modes")
            return False
        try:
            # The post-drain check is decisive: the first preflight alone may
            # race an in-flight save completing while the page is quiesced.
            self._local_switch_preflight()
            if read_config(self.profile_name) != self.mode_config:
                raise RuntimeError("Server selection changed while Local was draining")
            if not self._checkpoint_browser():
                raise RuntimeError("Independent browser recovery checkpoint could not be retained")
        except (OSError, ValueError, RuntimeError) as exc:
            self._show_transition_refusal(f"Local recovery evidence needs inspection after drain: {exc}. Reopen this profile")
            return False
        self.monitor.stop()
        self._dispose_webview()
        self._stop_backend()
        self._release_local_ownership()
        updated = dict(self.mode_config, mode="server")
        try:
            write_config(self.profile_name, updated)
        except (OSError, ValueError) as exc:
            self._fail(f"Local stopped, but Server selection could not be retained: {exc}. Reopen this profile to recover")
            return False
        self.mode_config = updated
        self.mode = "server"
        self._begin_feedback("")
        try:
            self._show_server()
        except (OSError, ValueError, RuntimeError) as exc:
            self._fail(f"Server mode was retained, but its browser could not open: {exc}. Reopen this profile to inspect")
            return False
        return True

    @browser_operation
    def switch_to_local(self) -> bool:
        if getattr(self, '_browser_dialog_depth', 0):
            return self._switch_refusal('Finish or cancel the open file/browser dialog before switching modes')
        if self._mode_switch_busy:
            return False
        self._mode_switch_busy = True
        self._update_mode_toolbar()
        try:
            return self._switch_to_local_impl()
        finally:
            self._mode_switch_busy = False
            self._update_mode_toolbar()

    def _switch_to_local_impl(self) -> bool:
        if self.mode == "local":
            return True
        if self._active_outputs():
            return self._switch_refusal("Wait for the Server download to finish before switching")
        if os.environ.get("DLMS_DESKTOP_AUTOMATED") != "1":
            if QMessageBox.question(self, "Leave Server session?",
                    "The remote deployment may have unsaved Study or Exam work. Desktop cannot verify its save state. "
                    "Finish or inspect Server History before leaving. Return to the same Local profile now?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return False
        try:
            from .removal import read_tombstone
            from .transition import read_transition
            from .maintenance import read_marker
            if (read_tombstone(self.profile_name) is not None or read_transition(self.paths) is not None
                    or read_marker(self.profile_name) is not None):
                raise RuntimeError("Local has a data transition or removal to reconcile. Close and reopen this profile in Local mode after inspection")
            self.manifest = read_manifest(self.paths, self.profile_name)
            if self.manifest is None:
                raise RuntimeError("The selected Local profile identity is missing; no new Local dataset was created")
            self.port = self.manifest["port"]
            self._acquire_local_ownership()
        except (OSError, ValueError, RuntimeError) as exc:
            return self._switch_refusal(str(exc))
        self._dispose_webview()
        updated = dict(self.mode_config, mode="local")
        try:
            write_config(self.profile_name, updated)
        except (OSError, ValueError) as exc:
            self._release_local_ownership()
            self._fail(f"Local selection could not be retained: {exc}. Restart and inspect mode state")
            return False
        self.mode_config = updated
        self.mode = "local"
        self._begin_feedback("")
        self.server_unreachable = False
        self._update_mode_toolbar()
        self.started_at = time.monotonic()
        self.ready_ms = None
        self.start()
        return True

    def _show_server(self):
        server = self.mode_config["server"]
        if server is None:
            self._fail("Server mode has no exact configured origin")
            return
        self.server_paths = server_root(server["id"])
        self.mode = "server"
        self.server_unreachable = False
        self._update_mode_toolbar()
        self.profile = QWebEngineProfile(f"dlms-server-{server['id']}", self)
        self.profile.setPersistentStoragePath(str(self.server_paths["storage"]))
        self.profile.setCachePath(str(self.server_paths["cache"]))
        self.profile.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, False)
        self.profile.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        self.profile.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, False)
        self.profile.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanPaste, False)
        self.profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
        self.server_interceptor = ServerOnlyInterceptor(server["origin"], self.profile)
        self.profile.setUrlRequestInterceptor(self.server_interceptor)
        self.profile.downloadRequested.connect(self._server_download)
        self.view = QWebEngineView(self)
        self.view.setPage(ServerPage(self.profile, self, server["origin"], parent=self.view))
        # WebEngine's outer view can default to NoFocus while its internal
        # focus proxy accepts keys. Save an explicit interactive policy before
        # the loading cover propagates NoFocus to that proxy.
        self.view.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._server_loaded_url = None
        self._server_theme = ""
        self._server_has_document = False
        self._server_connection_attempt = True
        self._server_navigation_serial = 0
        self._server_document_identity = None
        self._server_previous_document = None
        self._server_probe_pending = False
        self._server_probe_deadline = 0
        self._server_probe_ticket = 0
        self._server_early_revealed = False
        self._server_page_exposed = False
        self._server_view_focus_policy = self.view.focusPolicy()
        self.server_readiness_timer.stop()
        shell = QWidget(self)
        self.server_shell = shell
        shell.setObjectName("serverSurface")
        layout = QStackedLayout(shell)
        layout.setStackingMode(QStackedLayout.StackingMode.StackAll)
        layout.setContentsMargins(0, 0, 0, 0)
        self._server_surface_stack = layout
        self.server_status = QLabel(shell)
        self.server_status.setTextFormat(Qt.TextFormat.PlainText)
        self.server_status.setWordWrap(True)
        self.server_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.server_status.setAccessibleName("Server connection state")
        layout.addWidget(self.view)
        layout.addWidget(self.server_status)
        layout.setCurrentWidget(self.server_status)
        self.setCentralWidget(shell)
        self._style_server_surface()
        self._set_server_page_exposed(False, loading=True)
        self.view.loadStarted.connect(self._server_load_started)
        self.view.page().loadingChanged.connect(
            lambda info, view=self.view: self._page_loading_changed(info, view, "server"))
        if getattr(self,'window_events',None) is not None:self.window_events.bind(self.view)
        self._retry_server()

    def _set_server_page_exposed(self, exposed: bool, *, loading: bool = False):
        """Cover pixels/input without hiding a loading Server renderer.

        Hiding the WebEngine widget makes Chromium treat it as a background
        document; large Mix Questions pages then stall before load/readiness.
        The opaque native label covers the full viewport, owns input, and keeps
        the actual render view active underneath. No earlier success/save ack.
        A terminal failure may hide the renderer again; Local is unchanged.
        """
        self._server_page_exposed = exposed
        if exposed:
            self.view.setFocusPolicy(self._server_view_focus_policy)
            self.view.setEnabled(True)
            self.view.show()
            self._server_surface_stack.setCurrentWidget(self.view)
            self.server_status.hide()
        else:
            self.server_status.show()
            self._server_surface_stack.setCurrentWidget(self.server_status)
            self.view.clearFocus()
            self.view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.view.setEnabled(False)
            self.view.setVisible(loading)
            self.server_status.raise_()

    def _server_load_started(self):
        if self.mode != "server" or self.view is None or self._closing or self._retiring_browser is not None:
            return
        self._server_navigation_serial += 1
        self._server_previous_document = self._server_document_identity
        self._server_document_identity = None
        self._server_probe_ticket += 1
        self._server_probe_pending = False
        self._server_early_revealed = False
        self._server_probe_deadline = time.monotonic() + 5
        self.server_readiness_timer.stop()
        if self._server_has_document and not self._server_connection_attempt and self._server_previous_document is not None:
            self.server_readiness_timer.start()
        self._set_server_page_exposed(False, loading=True)
        self.server_status.setText(connection_text(
            self.mode_config["server"]["origin"], self.profile_name,
            initial=self._server_connection_attempt or not self._server_has_document))
        self.statusBar().showMessage("Loading Server page; awaiting the configured origin")
        self.server_status.show()

    def _server_load_finished(self, ok: bool):
        if self.mode != "server" or self.view is None or self._closing or self._retiring_browser is not None:
            return
        # Qt can finish a superseded request while a newer top-level load is
        # active. Its bool alone must not publish a result for that newer load.
        if self.view.page().isLoading():
            return
        self.server_readiness_timer.stop()
        self._server_probe_ticket += 1
        self._server_probe_pending = False
        server = self.mode_config["server"]
        valid = ok and exact_server_origin(self.view.url(), server["origin"])
        self.server_unreachable = not valid
        self._update_mode_toolbar()
        if valid:
            self._server_loaded_url = bytes(self.view.url().toEncoded())
            self.server_loaded_once = True
            self._server_has_document = True
            self._server_connection_attempt = False
            self._set_server_page_exposed(True)
            self._probe_server_readiness(completed=True)
            self._poll_mode_theme()
            self.statusBar().showMessage(f"Server mode: {server['label']} at {server['origin']}. Server Settings affect remote data")
        else:
            self._server_document_identity = None
            self._set_server_page_exposed(False)
            self.server_status.setText(f"Cannot connect to {server['label']} at {server['origin']}.\n"
                "Server mode remains selected; Local data was not opened. Retry, or explicitly return to Local. "
                "Certificate errors and redirects outside the exact origin are blocked.")
            self.server_status.show()
            self.statusBar().showMessage("Server unavailable; no Local fallback")

    def _server_load_information(self, info, page, generation):
        if (self.mode != "server" or self._closing or self._retiring_browser is not None
                or self.view is None or self.view.page() is not page
                or self._browser_generation != generation):
            return
        status = info.status()
        if status == QWebEngineLoadingInfo.LoadStatus.LoadStartedStatus:
            return
        if page.isLoading():
            return  # A superseded terminal signal cannot publish this load.
        if (status == QWebEngineLoadingInfo.LoadStatus.LoadStoppedStatus
                and info.isDownload() and not info.isErrorPage()
                and exact_server_origin(info.url(), self.mode_config["server"]["origin"])):
            self._restore_server_attachment_document(page, generation)
        else:
            self._server_load_finished(status == QWebEngineLoadingInfo.LoadStatus.LoadSucceededStatus)

    def _restore_server_attachment_document(self, page, generation):
        """Retain a verified old document only for a Qt-confirmed attachment.

        This is presentation recovery, never a transfer/save success acknowledgment.
        No URL suffix, error code, filename or page-supplied flag is authority.
        """
        self.server_readiness_timer.stop()
        self._server_probe_ticket += 1
        self._server_probe_pending = False
        previous = self._server_previous_document
        if previous is None or not self._server_has_document or self._server_connection_attempt:
            self._server_load_finished(False)
            return
        serial, ticket = self._server_navigation_serial, self._server_probe_ticket
        origin = self.mode_config["server"]["origin"]
        def received(raw):
            if (self.mode != "server" or self._closing or self._retiring_browser is not None
                    or self.view is None or self.view.page() is not page
                    or generation != self._browser_generation or serial != self._server_navigation_serial
                    or ticket != self._server_probe_ticket or origin != self.mode_config["server"]["origin"]
                    or page.isLoading()):
                return
            try:
                value = json.loads(raw) if isinstance(raw, str) else None
            except (TypeError, ValueError):
                value = None
            if (not exact_server_origin(page.url(), origin) or page.url().toString() != previous[0]
                    or document_identity(value) != previous or value.get("ready") != "complete"):
                self._server_load_finished(False)
                return
            self._server_document_identity = previous
            self.server_unreachable = False
            self._update_mode_toolbar()
            self._set_server_page_exposed(True)
        page.runJavaScript(READINESS_SCRIPT, QWebEngineScript.ScriptWorldId.ApplicationWorld, received)

    def _probe_server_readiness(self, completed=False):
        if (self.mode != "server" or self._closing or self._retiring_browser is not None
                or self.view is None):
            self.server_readiness_timer.stop()
            return
        # Bound presentational polling even if a renderer never answers. This
        # is not a connection/save timeout: normal load/error handling continues.
        if not completed and time.monotonic() >= self._server_probe_deadline:
            self.server_readiness_timer.stop()
            return
        if self._server_probe_pending:
            return
        page = self.view.page()
        if not completed and (not page.isLoading() or not self.server_readiness_timer.isActive()):
            self.server_readiness_timer.stop()
            return
        serial, generation = self._server_navigation_serial, self._browser_generation
        origin = self.mode_config["server"]["origin"]
        self._server_probe_pending = True
        self._server_probe_ticket += 1
        ticket = self._server_probe_ticket
        def received(raw):
            if (self.mode != "server" or self._closing or self._retiring_browser is not None
                    or self.view is None or self.view.page() is not page
                    or serial != self._server_navigation_serial or generation != self._browser_generation
                    or ticket != self._server_probe_ticket
                    or origin != self.mode_config["server"]["origin"]):
                return
            self._server_probe_pending = False
            if not exact_server_origin(page.url(), origin):
                return
            try:
                value = json.loads(raw) if isinstance(raw, str) else None
            except (TypeError, ValueError):
                return
            current = page.url().toString()
            if completed:
                if (page.isLoading() or not self.view.isVisible() or not self._server_page_exposed
                        or self.server_unreachable):
                    return
                identity = document_identity(value)
                if identity is not None and identity[0] == current:
                    self._server_document_identity = identity
                return
            if (not page.isLoading() or not self.server_readiness_timer.isActive()
                    or not ready_new_document(value, self._server_previous_document, current)):
                return
            # New main document is ready, but resources/load can still fail.
            # Do not publish load success or any save-state acknowledgment here.
            self._server_document_identity = document_identity(value)
            self._server_early_revealed = True
            theme = value.get("theme")
            if isinstance(theme, str) and theme in THEME_REGISTRY:
                self._server_theme = theme
                self._style_server_surface()
            self._set_server_page_exposed(True)
            self.server_readiness_timer.stop()
            self.statusBar().showMessage("Server page visible; still loading resources…")
        page.runJavaScript(READINESS_SCRIPT, QWebEngineScript.ScriptWorldId.ApplicationWorld, received)

    def _retry_server(self):
        if self.mode == "server" and self.view is not None:
            self._server_connection_attempt = True
            self.view.setUrl(QUrl(self.mode_config["server"]["origin"] + "/"))

    def _server_download(self, request):
        from .marked_exports import allowed_blob
        marked_blob = allowed_blob(self, request)
        if (self.mode != "server" or self._closing or self._retiring_browser is not None
                or self.view is None or request.page() is not self.view.page()
                or not (exact_server_origin(request.url(), self.mode_config["server"]["origin"]) or marked_blob)):
            request.cancel()
            return
        name = Path(request.downloadFileName()).name
        if name in {"", ".", ".."} or "\x00" in name:
            request.cancel()
            self.statusBar().showMessage("Server download filename was unsafe; no file was published")
            return
        try:
            job = self.server_paths["downloads"] / f"download-{secrets.token_hex(12)}"
            job.mkdir(mode=0o700)
            target = job / name
            assert_safe_leaf(target)
        except (OSError, ValueError):
            request.cancel()
            self.statusBar().showMessage("Server download destination is unavailable; no existing file was replaced")
            return
        request.setDownloadDirectory(str(job))
        request.setDownloadFileName(name)
        ticket = self._begin_feedback("server_download")
        download_profile = self.profile
        from .exports import context, current
        export_context = context(self)
        record = {"path": str(target), "state": "in_progress", "feedback_ticket": ticket}
        self.download_results.append(record)
        if marked_blob:
            record["marked_blob_url"] = request.url().toString()
        page, generation = request.page(), self._browser_generation
        def finished(*_):
            if record["state"] != "in_progress" or record.get("native_export"):
                return
            state = request.state()
            if state not in (request.DownloadState.DownloadCompleted, request.DownloadState.DownloadCancelled,
                             request.DownloadState.DownloadInterrupted):
                return
            if state == request.DownloadState.DownloadCompleted:
                if not current(self, export_context):
                    record['state']='completed_private';return
                from .exports import begin
                begin(self, record, captured=export_context)
                return
            elif state == request.DownloadState.DownloadCancelled:
                record["state"] = "cancelled"
                message = "Server download cancelled; no completed file was reported."
            else:
                record["state"] = "interrupted"
                record["reason"] = request.interruptReasonString()
                message = f"Server download failed: {record['reason']}"
            if self.mode == "server" and self.profile is download_profile and not self._closing:
                self._feedback(ticket, message, "success" if record["state"] == "completed" else
                               "error" if record["state"] == "interrupted" else "info")
                if marked_blob:
                    from .marked_exports import report
                    report(self, record, export_context,
                           'cancelled' if record['state'] == 'cancelled' else 'refused')
        request.isFinishedChanged.connect(finished)
        request.stateChanged.connect(finished)
        self._feedback(ticket, f"Receiving Server download in its separate private folder: {target}")
        request.accept()

    def start(self):
        if self.mode == "server":
            try:
                self._show_server()
            except (OSError, ValueError, RuntimeError) as exc:
                self._fail(f"Could not open the private Server browser profile: {exc}")
            return
        try:
            from .maintenance import read_marker, reconcile, clear_completed_marker
            marker = read_marker(self.profile_name)
            if marker is not None:
                marker = reconcile(self.profile_name)
                if marker["scope"] == "fresh" and marker["phase"] == "committed":
                    from .maintenance import quarantine_fresh_browser
                    marker = quarantine_fresh_browser(self.profile_name, owner=self)
                if marker["phase"] in {"rolled_back", "browser_done"}:
                    clear_completed_marker(self.profile_name)
                elif marker["phase"] not in {"committed", "browser_check_pending"}:
                    raise RuntimeError(f"Maintenance {marker['scope']} is {marker['phase']}; normal application use is blocked")
            self._start_reserved()
        except (OSError, ValueError, RuntimeError) as exc:
            self._fail(f"Could not start the disposable Desktop backend: {exc}")

    def _start_reserved(self):
        self.reserved_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Immediate relaunch must survive TIME_WAIT from our prior backend;
        # this does not permit sharing a live exact listener (SO_REUSEPORT is off).
        self.reserved_socket.setsockopt(socket.SOL_SOCKET,
                                       socket.SO_EXCLUSIVEADDRUSE if os.name == "nt" else socket.SO_REUSEADDR, 1)
        deadline = time.monotonic() + (3 if self.manifest else 0)
        while True:
            try:
                self.reserved_socket.bind(("127.0.0.1", self.port or 0))
                break
            except OSError as exc:
                if self.manifest and time.monotonic() < deadline:
                    time.sleep(0.1)  # old exact owner may still be closing after a crash
                    continue
                self.reserved_socket.close()
                self.reserved_socket = None
                if self.port:
                    raise RuntimeError(f"Saved origin 127.0.0.1:{self.port} is occupied; close its owner or reopen later. Browser recovery was preserved") from exc
                raise
        self.port = self.reserved_socket.getsockname()[1]
        # Listening before handoff makes the reservation exclusive even with
        # SO_REUSEADDR; Waitress may call listen() again on the same socket.
        self.reserved_socket.listen(128)
        if self.manifest is None:
            self.manifest = new_manifest(self.profile_name, self.port)
        shutdown_marker = self.paths["root"] / "shutdown.request"
        assert_safe_leaf(shutdown_marker)
        shutdown_marker.unlink(missing_ok=True)
        env = isolated_environment(self.paths)
        env.update({
            "DLMS_DESKTOP_PROFILE_NAME": self.profile_name,
            "DLMS_DESKTOP_PARENT_PID": str(os.getpid()),
            "DLMS_DESKTOP_PARENT_GROUP": str(os.getpid() if os.name == "nt" else os.getpgrp()),
            "DLMS_DESKTOP_NONCE": self.nonce,
            "DLMS_DESKTOP_PORT": str(self.port),
            "PYTHONNOUSERSITE": "1",
        })
        source_environment(env)
        if os.environ.get("DLMS_DESKTOP_TEST_CHILD") == "1":
            env["DLMS_DESKTOP_TEST_CHILD"] = "1"
        if os.environ.get("DLMS_DESKTOP_TEST_FAIL_BACKEND") == "1":
            env["DLMS_DESKTOP_TEST_FAIL_BACKEND"] = "1"
        if os.environ.get("DLMS_DESKTOP_AUTOMATED") == "1":
            env["DLMS_DESKTOP_AUTOMATED"] = "1"
            if os.environ.get("DLMS_DESKTOP_TEST_PAUSE_AT"):
                env["DLMS_DESKTOP_TEST_PAUSE_AT"] = os.environ["DLMS_DESKTOP_TEST_PAUSE_AT"]
            for key in ("DLMS_DESKTOP_TEST_PAUSE_PHASE", "DLMS_DESKTOP_TEST_FAIL_ACTION_CLEANUP",
                        "DLMS_DESKTOP_TEST_FAIL_ACTION_ACCEPT", "DLMS_DESKTOP_TEST_DROP_CLEANED_EXAM_REPLY",
                        "DLMS_DESKTOP_TEST_ABORT_REQUEST", "DLMS_DESKTOP_TEST_FAIL_REQUEST_CLEANUP",
                        "DLMS_DESKTOP_TEST_PAUSE_BACKUP_ITERATION",
                        "DLMS_DESKTOP_TEST_PAUSE_PUBLICATION",
                        "DLMS_DESKTOP_TEST_PAUSE_SETTINGS_WRITE",
                        "DLMS_DESKTOP_TEST_ABORT_IMPORT_AT",
                        "DLMS_DESKTOP_TEST_FAIL_IMPORT_RECEIPT",
                        "DLMS_DESKTOP_TEST_FAIL_IMPORT_CLEANUP"):
                if key in os.environ:
                    env[key] = os.environ[key]
        log_path = self.paths["logs"] / "backend.log"
        assert_safe_leaf(log_path)
        self.backend_log = open(log_path, "ab", buffering=0)
        read_fd, write_fd = os.pipe()
        self.parent_pipe_write = write_fd
        env["DLMS_DESKTOP_PARENT_PIPE"] = str(read_fd)
        env["DLMS_DESKTOP_SOCKET_FD"] = str(self.reserved_socket.fileno())
        try:
            self.backend = spawn_process(
                child_command("backend"),
                bound=self.reserved_socket,
                cwd=PROJECT,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=self.backend_log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
                pass_fds=(read_fd, self.reserved_socket.fileno()),
            )
        finally:
            os.close(read_fd)
        self.poll.start()

    def _poll_backend(self):
        if self.backend is None:
            return
        if self.backend.poll() is not None:
            self._fail(f"Backend exited during startup (code {self.backend.returncode}). See {self.paths['logs'] / 'backend.log'}")
            return
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=0.15)
        try:
            connection.request("GET", READY_PATH, headers={
                "Host": f"127.0.0.1:{self.port}",
                "X-DLMS-Desktop-Nonce": self.nonce,
                "X-DLMS-Desktop-Token": self.nonce,
            })
            response = connection.getresponse()
            ready = response.status == 200 and response.read(64) == b"DLMS Desktop Block A ready"
        except OSError:
            ready = False
        finally:
            connection.close()
        if ready:
            self.poll.stop()
            self.ready_ms = round((time.monotonic() - self.started_at) * 1000)
            try:
                if not (self.paths["root"] / "desktop-profile.json").exists():
                    publish_manifest(self.paths, self.manifest)
                published = read_manifest(self.paths, self.profile_name)
                if published["port"] != self.port or published["uuid"] != self.manifest["uuid"]:
                    raise RuntimeError("Desktop origin or profile identity changed during startup")
                self.manifest = published
            except (OSError, ValueError, RuntimeError) as exc:
                self._fail(f"Backend recovered, but the Desktop origin could not be saved: {exc}. The page was not opened")
                return
            self.reserved_socket.close()
            self.reserved_socket = None
            self._show_webview()
            self.monitor.start()
        elif time.monotonic() - self.started_at > 25:
            self._fail(f"Backend did not become ready on saved origin 127.0.0.1:{self.port}. See {self.paths['logs'] / 'backend.log'}")

    def _monitor_backend(self):
        if self._closing or self._close_active:
            return
        request = self.paths["root"] / "shutdown.request"
        assert_safe_leaf(request)
        if request.exists() and request.read_text() == self.nonce:
            request.unlink(missing_ok=True)
            self.close()
            return
        if not self._closing and self.backend is not None and self.backend.poll() is not None:
            self.monitor.stop()
            reap_owned_group(self.backend.pid, self.nonce)
            self._fail(f"The task-owned backend stopped unexpectedly (code {self.backend.returncode}). Reopen the same disposable profile to recover. See {self.paths['logs'] / 'backend.log'}")

    def _show_webview(self):
        self._local_loaded_url = None
        self.mode = "local"
        self._update_mode_toolbar()
        from .maintenance import read_marker
        marker = read_marker(self.profile_name)
        self.maintenance_transition = marker is not None
        self.profile = QWebEngineProfile("dlms-block-a", self)
        self.profile.setPersistentStoragePath(str(self.paths["web_storage"]))
        self.profile.setCachePath(str(self.paths["web_cache"]))
        self.profile.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
        # DLMS's Study copy button needs sanitized clipboard writes after a
        # user gesture. Clipboard reading/paste remains disabled.
        self.profile.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, True)
        self.profile.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanPaste, False)
        self.profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
        self.interceptor = LocalOnlyInterceptor(self.nonce, self.port, self.profile)
        self.profile.setUrlRequestInterceptor(self.interceptor)
        self.profile.downloadRequested.connect(self._download)
        self.view = QWebEngineView(self)
        page = LocalPage(self.profile, self, parent=self.view)
        page.printRequested.connect(self._print_pdf)
        page.pdfPrintingFinished.connect(self._pdf_finished)
        self.view.setPage(page)
        shell = QWidget(self)
        layout = QVBoxLayout(shell)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.view, 1)
        self.settings_panel = LocalSettingsSurface(
            self.profile_name, str(self.paths["root"]),
            self._activate_settings_action, self._navigate_settings, shell)
        self.settings_buttons = self.settings_panel.buttons
        self.settings_panel.hide()
        layout.addWidget(self.settings_panel, 1)
        self.settings_fallback = QLabel(shell)
        self.settings_fallback.setWordWrap(True)
        self.settings_fallback.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.settings_fallback.setMinimumHeight(240)
        self.settings_fallback.setStyleSheet(
            "background: #172239; color: #f1efff; font-size: 16px; padding: 32px;")
        self.settings_fallback.setAccessibleName("Desktop page recovery guidance")
        self.settings_fallback.hide()
        layout.addWidget(self.settings_fallback, 1)
        self.setCentralWidget(shell)
        self._local_document_identity = None
        self._local_previous_document = None
        self.view.loadStarted.connect(self._local_load_started)
        self.view.urlChanged.connect(self._settings_url_changed)
        self.view.page().loadingChanged.connect(
            lambda info, view=self.view: self._page_loading_changed(info, view, "local"))
        if getattr(self,'window_events',None) is not None:self.window_events.bind(self.view)
        close_delay = int(os.environ.get("DLMS_DESKTOP_CLOSE_AFTER_READY_MS", "0"))
        if close_delay > 0:
            self.view.loadFinished.connect(lambda ok: QTimer.singleShot(close_delay, self.close) if ok else None)
        if self.maintenance_transition:
            self.view.loadFinished.connect(self._maintenance_page_loaded)
        route = "/_desktop/maintenance" if self.maintenance_transition else "/"
        self.view.setUrl(QUrl(f"http://127.0.0.1:{self.port}{route}"))

    def _page_loading_changed(self, info, view, mode):
        # loadFinished(false) also means "continued as an attachment". Qt6.9+
        # exposes that distinction explicitly; neither ERR_ABORTED nor a filename
        # is proof of a download. Do not hide actual HTTP/network/cert failures.
        if (view is not self.view or self.mode != mode or self._closing
                or self._retiring_browser is not None):
            return
        if mode == "local" and (self.failed_reason is not None or self._settings_transition_refused
                or self.maintenance_transition or self.import_in_progress
                or self.backend is None or self.backend.poll() is not None):
            return  # Recovery/transition guidance must remain fail-closed.
        status = info.status()
        if status == QWebEngineLoadingInfo.LoadStatus.LoadStartedStatus:
            return
        if view.page().isLoading():
            return  # A superseded terminal signal cannot uncover a newer load.
        if info.isDownload():
            current = bytes(view.url().toEncoded())
            if mode == "local":
                if (allowed_internal(info.url(), self.port) and allowed_internal(view.url(), self.port)
                        and current == self._local_loaded_url):
                    # The old document is still displayed. Settings must pass its
                    # ordinary top-document marker check again before actions show.
                    self._settings_page_loaded(True, view)
            elif (exact_server_origin(info.url(), self.mode_config["server"]["origin"])
                  and exact_server_origin(view.url(), self.mode_config["server"]["origin"])
                  and current == self._server_loaded_url):
                self.server_readiness_timer.stop()
                self._server_probe_ticket += 1
                self._server_probe_pending = False
                self._server_document_identity = self._server_previous_document
                self.server_unreachable = False
                self._set_server_page_exposed(True)
                self._update_mode_toolbar()
                self.statusBar().showMessage("Server attachment requested; current page retained. Await the download outcome.")
            else:
                self.server_status.setText("The server returned a download, not an application page. Retry connection or return to Local.")
            return
        if (status == QWebEngineLoadingInfo.LoadStatus.LoadFailedStatus
                and info.errorDomain() == QWebEngineLoadingInfo.ErrorDomain.HttpStatusCodeDomain
                and 400 <= info.errorCode() <= 599 and not info.isErrorPage()
                and bytes(info.url().toEncoded()) == bytes(view.url().toEncoded())
                and (allowed_internal(view.url(), self.port) if mode == "local" else
                     exact_server_origin(view.url(), self.mode_config["server"]["origin"]))):
            # A server-supplied validation/error document is useful feedback, not
            # a failed connection. Show it as a refusal, never as save success or
            # authorization for native Settings actions. Qt's own error pages,
            # network/certificate failures and foreign origins take the fallback.
            if mode == "local":
                self._settings_page_loaded(False, view)
                self._settings_navigation_started()
                self.settings_fallback.hide()
                view.show()
            else:
                self.server_readiness_timer.stop()
                self._server_probe_ticket += 1
                self._server_probe_pending = False
                self._server_document_identity = None
                self._server_loaded_url = bytes(view.url().toEncoded())
                self.server_unreachable = False
                self.server_loaded_once = True
                self._server_has_document = True
                self._server_connection_attempt = False
                self._set_server_page_exposed(True)
                self._update_mode_toolbar()
                self._poll_mode_theme()
            self.statusBar().showMessage(
                f"{mode.title()} request returned HTTP {info.errorCode()}. Read the page for details; no successful save is implied.")
            return
        ok = status == QWebEngineLoadingInfo.LoadStatus.LoadSucceededStatus
        if mode == "server":
            self._server_load_finished(ok)
        else:
            self._settings_page_loaded(ok, view)

    def _local_load_started(self):
        self._local_previous_document = self._local_document_identity
        self._local_document_identity = None
        self._settings_navigation_started()

    def _local_load_information(self, info, page, generation):
        if (self.mode != "local" or self._closing or self._retiring_browser is not None
                or self.view is None or self.view.page() is not page
                or self._browser_generation != generation or page.isLoading()):
            return
        status = info.status()
        if status == QWebEngineLoadingInfo.LoadStatus.LoadStartedStatus:
            return
        attachment = (status == QWebEngineLoadingInfo.LoadStatus.LoadStoppedStatus
                      and info.isDownload() and not info.isErrorPage()
                      and allowed_internal(info.url(), self.port))
        ok = status == QWebEngineLoadingInfo.LoadStatus.LoadSucceededStatus
        if not attachment:
            self._settings_page_loaded(ok, self.view)
            if not ok:
                return
        previous = self._local_previous_document
        if attachment and previous is None:
            self._settings_page_loaded(False, self.view)
            return
        settings_generation = self._settings_generation
        def received(raw):
            if (self.mode != "local" or self._closing or self._retiring_browser is not None
                    or self.view is None or self.view.page() is not page
                    or generation != self._browser_generation or settings_generation != self._settings_generation
                    or page.isLoading() or self.maintenance_transition or self.import_in_progress
                    or self._settings_transition_refused or self.failed_reason is not None
                    or self.backend is None or self.backend.poll() is not None):
                return
            try:
                value = json.loads(raw) if isinstance(raw, str) else None
            except (TypeError, ValueError):
                value = None
            identity = document_identity(value)
            verified = (identity is not None and allowed_internal(page.url(), self.port)
                        and page.url().toString() == identity[0] and value.get("ready") == "complete")
            if attachment:
                verified = verified and identity == previous
            if not verified:
                if attachment:
                    self._settings_page_loaded(False, self.view)
                return
            self._local_document_identity = identity
            if attachment:
                # Existing Settings marker/origin checks retain sole authority
                # over native controls; this does not acknowledge a saved file.
                self._settings_page_loaded(True, self.view)
        page.runJavaScript(READINESS_SCRIPT, QWebEngineScript.ScriptWorldId.ApplicationWorld, received)

    def _settings_navigation_started(self):
        self._settings_generation += 1
        self._settings_kind = None
        self._settings_verified_url = None
        self._settings_action_busy = False
        if self._settings_transition_refused:
            return  # A drained window remains on recovery guidance until close.
        if self.settings_panel is not None:
            self.settings_panel.hide()
        if self.settings_fallback is not None:
            self.settings_fallback.hide()
        if self.view is not None and not self._settings_transition_refused:
            self.view.show()

    def _settings_url_changed(self, _url):
        self._settings_navigation_started()

    def _settings_ready(self, kind: str | None = None) -> bool:
        if (self.mode != "local" or self.view is None or self.view.page() is None or self.settings_panel is None
                or not self.settings_panel.isVisible() or not self.view.isEnabled()
                or self.failed_reason is not None or self.backend is None
                or self.backend.poll() is not None or self._closing or self.maintenance_transition
                or self.import_in_progress or self.maintenance_worker is not None
                or self.removal_worker is not None):
            return False
        actual_kind = managed_settings_page(self.view.url(), self.port)
        return (actual_kind is not None and (kind is None or kind == actual_kind)
                and self._settings_kind == actual_kind
                and self._settings_verified_url == bytes(self.view.url().toEncoded()))

    def _settings_page_loaded(self, ok: bool, loaded_view=None):
        if loaded_view is not None and loaded_view is not self.view:
            return  # A disposed page cannot complete a newer import's status.
        if self.view is None or self.settings_panel is None or self.maintenance_transition:
            return
        page = self.view.page()
        url = bytes(self.view.url().toEncoded())
        kind = managed_settings_page(self.view.url(), self.port)
        generation = self._settings_generation
        pending = self._import_reopen_status
        local_page = (self.mode == "local" and self.view.url().scheme() == "http"
                      and self.view.url().host() == "127.0.0.1"
                      and self.view.url().port() == self.port)
        if pending is not None and local_page:
            serial, expected = pending
            self._import_reopen_status = None
            if (serial == self._import_status_serial and self.failed_reason is None
                    and self.statusBar().currentMessage() == expected):
                if ok and self.backend is not None and self.backend.poll() is None:
                    self._import_feedback(
                        f"Backup committed to profile {self.profile_name}; Local page loaded. Check Library and History.", "success")
                else:
                    self._import_feedback(
                        f"Backup committed, but the application page did not load. Reopen profile {self.profile_name} to inspect it.", "error")
        if (local_page and self.view.url().path() == "/settings/backup/create" and self._backup_creating
                and self.view.url().query() == "desktop_output=" + str(self.backup_output_operation)
                and not self._active_outputs()):
            # Qt can report HTTP 409 as loadFinished(false). This is the exact
            # native request's non-download response, not a saved destination.
            self._backup_creating = False
            self.backup_output_selection = None
            self._settings_navigation_started()
            self.view.show()
            self._feedback(self._backup_feedback_ticket,
                "Backup did not start a download; no selected file was published. Read the Local response before retrying.", "error")
            return
        if ok and local_page:
            self._local_loaded_url = url
        if not ok:
            self._local_loaded_url = None
            self._settings_navigation_started()
            self._show_settings_fallback("The application page did not load")
            return
        if kind is None or self.backend is None or self.backend.poll() is not None:
            return
        self._read_settings_document(page, url, kind, generation, 0)

    def _read_settings_document(self, page, url: bytes, kind: str, generation: int, attempt: int):
        if (self.view is None or self._closing or self.view.page() is not page
                or generation != self._settings_generation):
            return
        # Read only the top document's canonical, already normalized sidebar.
        # Its async portal config controls certifications and Study Area visibility.
        # No script or page-origin command is passed to Qt.
        script = """JSON.stringify((() => {
          const aside = document.querySelector('.dashboard-sidebar');
          const ready = aside && aside.querySelector('.dashboard-nav-normalized') &&
            aside.querySelector('.dashboard-theme-quick')?.hidden === false &&
            aside.querySelector('#dlmsQuickTheme')?.disabled === false;
          const nodes = ready ? [...aside.querySelectorAll(
            '.dashboard-nav-section-label, .dashboard-nav-normalized .dashboard-nav-item')] : [];
          return {kind:document.documentElement.getAttribute('data-dlms-desktop-settings'),
            theme:aside?.dataset.theme || '', ready:!!ready,
            nav:nodes.filter(el => !el.closest('[hidden]')).map(el => ({
              type:el.matches('a') ? 'link' : 'section',
              label:(el.querySelector('span')?.textContent || el.textContent || '').trim(),
              path:el.matches('a') ? el.getAttribute('href') : null,
              icon:el.matches('a') ? el.querySelector('use')?.getAttribute('href') : null,
              iconColor:el.matches('a') && el.querySelector('.dashboard-nav-icon') ?
                getComputedStyle(el.querySelector('.dashboard-nav-icon')).color : null,
              active:el.classList.contains('active')}))};
        })())"""
        page.runJavaScript(script, lambda value: self._settings_marker_checked(
            page, url, kind, generation, value, attempt))

    def _show_settings_fallback(self, reason: str):
        if self.settings_panel is not None:
            self.settings_panel.hide()
        if self.settings_fallback is not None:
            self.settings_fallback.setText(
                f"{reason} for disposable profile {self.profile_name}. No maintenance action is available here. "
                f"Close and reopen this profile; diagnostics: {self.paths['logs'] / 'backend.log'}")
            if self.view is not None:
                self.view.hide()
            self.settings_fallback.show()

    def _show_transition_refusal(self, reason: str):
        """A drain may already be in force; never present this window as writable."""
        self._settings_transition_refused = True
        self._show_settings_fallback(reason + ". Close and reopen to reconcile saved work")
        self.statusBar().showMessage(reason + ". Close and reopen this profile before trying again.")

    def _settings_marker_checked(self, page, url: bytes, kind: str, generation: int, value, attempt: int = 0):
        try:
            marker = json.loads(value) if isinstance(value, str) else None
        except ValueError:
            marker = None
        if (generation != self._settings_generation or self.view is None
                or self.view.page() is not page or bytes(self.view.url().toEncoded()) != url
                or managed_settings_page(self.view.url(), self.port) != kind
                or not self.view.isEnabled() or self.failed_reason is not None
                or self.backend is None or self.backend.poll() is not None
                or self.maintenance_transition or self._closing or self.import_in_progress
                or self.maintenance_worker is not None or self.removal_worker is not None):
            return
        if not isinstance(marker, dict) or marker.get("kind") != kind:
            self._settings_kind = None
            self._settings_verified_url = None
            self._show_settings_fallback("The intended Settings document could not be verified")
            return
        if not marker.get("ready"):
            if attempt < 20:
                QTimer.singleShot(100, lambda: self._read_settings_document(
                    page, url, kind, generation, attempt + 1))
            else:
                self._show_settings_fallback("The Settings navigation and appearance preferences could not be loaded")
            return
        navigation = []
        for entry in marker.get("nav", []):
            if not isinstance(entry, dict) or entry.get("type") not in {"link", "section"}:
                continue
            label = entry.get("label")
            if not isinstance(label, str) or not label or len(label) > 100:
                continue
            if entry["type"] == "section":
                navigation.append({"type": "section", "label": label})
                continue
            path = entry.get("path")
            if not safe_native_navigation(path):
                continue
            icon = entry.get("icon")
            if not isinstance(icon, str) or not re.fullmatch(r"/static/icons\.svg#[a-z][a-z-]*", icon):
                icon = None
            css_color = entry.get("iconColor")
            color_match = re.fullmatch(r"rgb\(\s*(\d{1,3}),\s*(\d{1,3}),\s*(\d{1,3})\s*\)", css_color) if isinstance(css_color, str) else None
            icon_color = None
            if color_match:
                parts = [int(value) for value in color_match.groups()]
                if all(value <= 255 for value in parts):
                    icon_color = "#" + "".join(f"{value:02x}" for value in parts)
            navigation.append({"type": "link", "label": label, "icon": icon.rsplit("#", 1)[-1] if icon else None,
                               "icon_color": icon_color,
                               "path": path, "active": entry.get("active") is True})
        if not any(item.get("path") == "/settings" for item in navigation):
            self._show_settings_fallback("The Settings navigation is incomplete")
            return
        if self.settings_fallback is not None:
            self.settings_fallback.hide()
        self._settings_kind = kind
        self._settings_verified_url = url
        self.settings_panel.set_navigation(navigation)
        self.settings_panel.set_theme(marker.get("theme"))
        self._style_mode_control(marker.get("theme"))
        self.settings_panel.show_kind(kind)
        self.view.hide()
        self.settings_panel.show()
        for button in self.settings_buttons.values():
            button.setEnabled(not self._backup_creating)
        self._render_backup_feedback()
        if kind == "backup":
            self._refresh_settings_summary()

    def _navigate_settings(self, path: str):
        if (safe_native_navigation(path) and self._settings_ready()
                and not self._settings_action_busy and not self._backup_creating):
            self.view.setUrl(QUrl(f"http://127.0.0.1:{self.port}{path}"))

    def _refresh_settings_summary(self):
        if not self._settings_ready("backup"):
            return
        generation = self._settings_generation
        request = QNetworkRequest(QUrl(f"http://127.0.0.1:{self.port}/_desktop/settings/summary"))
        # Never forward native-only headers through a redirect.
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        request.setRawHeader(b"X-DLMS-Desktop-Token", self.nonce.encode("ascii"))
        request.setRawHeader(b"X-DLMS-Desktop-Nonce", self.nonce.encode("ascii"))
        reply = self.settings_network.get(request)

        def complete():
            try:
                if not self._settings_ready("backup") or generation != self._settings_generation:
                    return
                status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
                if reply.error() != QNetworkReply.NetworkError.NoError or status != 200:
                    raise ValueError(f"authenticated storage check did not complete (HTTP {status}; {reply.errorString()})")
                data = json.loads(bytes(reply.readAll()))
                storage = data["storage"]
                if not self.settings_panel.storage_composition.set_snapshot(storage):
                    raise ValueError("inconsistent storage categories; no chart was drawn")
                self.settings_panel.storage_space_label.setText(
                    f"Available disk space: {storage['free']} · space status: {storage['status']}. "
                    "Free space is separate from the DLMS data chart.")
                lines = [f"DLMS data size: {storage['size']}; available disk space: {storage['free']}."]
                if storage.get("partial"):
                    lines.append("This bounded scan is incomplete; reported sizes are lower bounds.")
                lines.append(f"Space status: {storage['status']}.")
                lines.extend(f"{item['label']}: {item['size']}" for item in storage["groups"])
                self.settings_panel.storage_label.setText("\n".join(lines))
                recent = data["recent_backups"]
                self.settings_panel.inventory_label.setText(
                    "\n".join(f"{item['label']} · {item['size']} · {item['created']}\n{item['name']}" for item in recent)
                    if recent else "No safety backups are currently stored in this profile.")
                self.settings_panel.action_status["refresh_storage"].setText("Storage check completed.")
            except (ValueError, KeyError, TypeError) as exc:
                self.settings_panel.storage_composition.clear()
                self.settings_panel.storage_composition.note.setText("Storage composition is unavailable.")
                self.settings_panel.storage_space_label.setText("Available disk space could not be confirmed.")
                self.settings_panel.storage_label.setText("Earlier storage figures are no longer confirmed; refresh to check again.")
                self.settings_panel.inventory_label.setText("Earlier backup inventory is no longer confirmed; refresh to check again.")
                self.settings_panel.action_status["refresh_storage"].setText(f"Storage check unavailable: {exc}.")
            finally:
                reply.deleteLater()

        reply.finished.connect(complete)

    def _status_message_changed(self, message: str):
        # Native status also has non-output callers (mode/recovery/busy guards).
        # Keep accessibility and tooltip text truthful for all of them.
        self.statusBar().setToolTip(message)
        self.statusBar().setAccessibleDescription(message)
        if not self._feedback_writing:
            state = self.operation_feedback
            if state.message and state.severity in {"success", "warning", "error"}:
                state.begin("")
            if self.settings_panel is not None:
                self.settings_panel.clear_backup_feedback()

    def _begin_feedback(self, action: str) -> int:
        ticket = self.operation_feedback.begin(action)
        self._feedback_mode = self.mode
        if self.settings_panel is not None:
            self.settings_panel.clear_backup_feedback()
        self.statusBar().clearMessage()
        self.statusBar().setToolTip("")
        self.statusBar().setAccessibleDescription("")
        return ticket

    def _feedback(self, ticket: int, message: str, severity: str = "info") -> bool:
        # UI tickets do not replace publication IDs, receipts or recovery state.
        # Old callbacks still process their real outcomes, but cannot announce
        # an obsolete outcome over a newer action or a stopped/remote page.
        if (self.failed_reason is not None or self._settings_transition_refused
                or self.mode != self._feedback_mode):
            return False
        if not self.operation_feedback.update(ticket, message, severity):
            return False
        self._feedback_writing = True
        try:
            self.statusBar().showMessage(message)
        finally:
            self._feedback_writing = False
        self.statusBar().setToolTip(message)
        self.statusBar().setAccessibleDescription(message)
        self._render_backup_feedback(reveal=severity in {"warning", "error"})
        return True

    def _render_backup_feedback(self, *, reveal=False):
        state = self.operation_feedback
        if self.settings_panel is not None and self.mode == "local":
            self.settings_panel.clear_backup_feedback()
            if (state.action in {"create_backup", "backup"} and state.message
                    and state.message == self.statusBar().currentMessage()):
                self.settings_panel.set_backup_feedback(state.action, state.message, state.severity,
                    reveal=reveal and self._settings_ready("backup"))

    def _import_feedback(self, message: str, severity: str = "info"):
        return self._feedback(self._import_feedback_ticket, message, severity)

    def _create_settings_backup(self):
        if self._backup_creating or self._active_outputs() or not self._settings_ready("backup"):
            return
        self._backup_creating = True
        ticket = self._backup_feedback_ticket = self._begin_feedback("create_backup")
        generation = self._settings_generation
        self.open_backup_folder.hide()
        try:
            selected, _ = self._choose_backup_destination()
            if not self._settings_ready("backup") or generation != self._settings_generation:
                self._backup_creating = False
                return
            if not selected:
                self._backup_creating = False
                self._feedback(ticket, "Backup save canceled; no backup requested.")
                return
            from .backup_output import select
            self.backup_output_selection = select(Path(selected), forbidden=(
                AREA if FROZEN else AREA / "profiles", PROJECT if FROZEN else PROJECT / "desktop"))
        except (OSError, ValueError) as exc:
            self._backup_creating = False
            self._feedback(ticket, f"Backup destination refused: {exc}", "error")
            return
        finally:
            if self._settings_ready("backup"):
                self.settings_buttons["create_backup"].setFocus(Qt.FocusReason.OtherFocusReason)
        self.backup_output_operation = self.backup_output_selection["operation"]
        operation = self.backup_output_operation
        self.settings_buttons["create_backup"].setEnabled(False)
        self._feedback(ticket, "Creating the portable backup; wait for its download outcome.")
        page = self.view.page()
        generation = self._settings_generation
        # This is native -> owned browser form submission, never a web -> native
        # command. The existing form, CSRF cookie, token interceptor, backend
        # pending-work gate and download handler retain their usual authority.
        script = """(()=>{const f=document.querySelector('form[action="/settings/backup/create"]');
          if(!f || f.method.toUpperCase()!=='POST' || new URL(f.action).origin!==location.origin ||
             location.pathname!=='/settings/backup') return false;
          const original=f.getAttribute('action');
          f.setAttribute('action', original+'?desktop_output='+OPERATION);
          try { f.requestSubmit(); } finally { f.setAttribute('action', original); }
          return true;})()""".replace("OPERATION", json.dumps(operation))

        def submitted(ok):
            if (self.view is None or self._closing or page is not self.view.page() or generation != self._settings_generation
                    or operation != self.backup_output_operation):
                return
            if ok is not True:
                self._backup_creating = False
                self.settings_buttons["create_backup"].setEnabled(True)
                self._feedback(ticket,
                    "Backup form was unavailable; no result is confirmed. Reopen Backup & Restore.", "error")

        page.runJavaScript(script, submitted)

    def _choose_backup_destination(self):
        return QFileDialog.getSaveFileName(
            self, "Save Local DLMS backup", str(self._documents_folder() /
                time.strftime("DLMS-backup-%Y%m%d-%H%M%S.zip")), "DLMS backups (*.zip)",
            options=QFileDialog.Option.DontConfirmOverwrite)

    def _activate_settings_action(self, action: str):
        # A queued native click must be checked again after navigation or worker start.
        kind = "backup" if action in {"backup", "create_backup", "refresh_storage"} else "reset-remove"
        if not self._settings_ready(kind) or self._settings_action_busy or self._backup_creating:
            return
        if action == "refresh_storage":
            self._refresh_settings_summary()
            return
        if action == "create_backup":
            self._create_settings_backup()
            return
        self._settings_action_busy = True
        generation = self._settings_generation
        valid = lambda: self._settings_ready(kind) and self._settings_generation == generation
        for button in self.settings_buttons.values():
            button.setEnabled(False)
        try:
            if action == "backup" and kind == "backup":
                self._choose_backup(still_authorized=valid)
            elif action == "remove" and kind == "reset-remove":
                self.begin_removal(still_authorized=valid)
            elif kind == "reset-remove":
                from .maintenance import SCOPES
                if action in SCOPES:
                    self.begin_maintenance(action, still_authorized=valid)
        finally:
            self._settings_action_busy = False
            if valid():
                for button in self.settings_buttons.values():
                    button.setEnabled(True)
                # A canceled chooser/confirmation returns focus to its source.
                self.settings_buttons[action].setFocus(Qt.FocusReason.OtherFocusReason)

    def _download(self, request):
        from .marked_exports import allowed_blob
        marked_blob = allowed_blob(self, request)
        if (self.mode != "local" or self._closing or self._retiring_browser is not None
                or self.view is None or request.page() is not self.view.page()
                or not (allowed_internal(request.url(), self.port) or marked_blob)):
            request.cancel()
            self.statusBar().showMessage("A download outside the local application was blocked.")
            return
        native_selection = None
        if request.url().path() == "/settings/backup/create":
            candidate = self.backup_output_selection
            if (candidate is not None and self._backup_creating and self.mode == "local"
                    and request.page() is self.view.page()
                    and request.url().query() == "desktop_output=" + candidate["operation"]
                    and candidate["operation"] == self.backup_output_operation):
                native_selection = dict(candidate)
                self.backup_output_selection = None  # claim exactly once at acceptance
            elif self._backup_creating or request.url().hasQuery():
                request.cancel()
                return  # No older/duplicate callback can claim the new destination.
        ticket = (self._backup_feedback_ticket if native_selection is not None
                  else self._begin_feedback("download"))
        name = Path(request.downloadFileName()).name or "download"
        # A private, newly created directory per request prevents a repeated
        # export or a later file from replacing a prior download. Qt still
        # controls the final file write inside this disposable directory.
        job_dir = self.paths["downloads"] / f"download-{secrets.token_hex(12)}"
        destination = job_dir / name
        try:
            if name in {".", ".."} or "\x00" in name:
                raise ValueError("unsafe download name")
            job_dir.mkdir(mode=0o700)
            assert_safe_leaf(destination)
        except (OSError, ValueError):
            request.cancel()
            if native_selection and native_selection["operation"] == self.backup_output_operation:
                self._backup_creating = False
            self._feedback(ticket, "Download destination was unsafe or unavailable; no file was replaced.", "error")
            return
        request.setDownloadDirectory(str(job_dir))
        request.setDownloadFileName(name)
        record = {"path": str(destination), "state": "in_progress", "feedback_ticket": ticket}
        if marked_blob:
            record["marked_blob_url"] = request.url().toString()
        self.download_results.append(record)
        from .exports import context, current
        # A native backup already carries its claimed destination/operation.
        # Only ordinary Qt exports use the page's document-generation context.
        export_context = context(self) if native_selection is None else None

        def finished(*_):
            if record["state"] != "in_progress" or record.get("native_export"):
                return
            if native_selection and native_selection["operation"] != self.backup_output_operation:
                record["state"] = "unconfirmed_old_operation"
                return
            state = request.state()
            if state not in (request.DownloadState.DownloadCompleted, request.DownloadState.DownloadCancelled,
                             request.DownloadState.DownloadInterrupted):
                return
            if (state == request.DownloadState.DownloadCompleted
                    and native_selection is not None and self._backup_creating):
                if self.backup_output_future is not None:
                    return
                from .backup_output import publish
                record["operation"] = native_selection["operation"]
                self.backup_output_record = record
                self.backup_output_future = self.backup_selection_executor.submit(
                    publish, destination, native_selection)
                self.backup_output_timer.start()
                self._feedback(ticket, "Publishing the completed backup to the selected folder…")
                return
            if state == request.DownloadState.DownloadCompleted:
                if native_selection is not None:
                    # A retired/canceled native operation cannot become an
                    # ordinary export or claim a different destination.
                    record['state'] = 'completed_private'
                    return
                if not current(self, export_context):
                    record['state']='completed_private';return
                from .exports import begin
                begin(self, record, captured=export_context)
                return
            elif state == request.DownloadState.DownloadCancelled:
                record["state"] = "cancelled"
                self._feedback(ticket, "Download cancelled; no completed file was reported.")
            elif state == request.DownloadState.DownloadInterrupted:
                record["state"] = "interrupted"
                record["reason"] = request.interruptReasonString()
                self._feedback(ticket, f"Download failed: {record['reason']}", "error")
            if marked_blob:
                from .marked_exports import report
                report(self, record, export_context,
                       'cancelled' if record['state'] == 'cancelled' else 'refused')
            if native_selection and native_selection["operation"] == self.backup_output_operation and self._backup_creating:
                self._backup_creating = False
                self._feedback(ticket, "Backup download did not complete; no selected file was published. "
                               "Inspect the outcome before retrying.", "error")
                if self._settings_ready():
                    for button in self.settings_buttons.values():
                        button.setEnabled(True)
                    if self._settings_ready("backup"):
                        self.settings_buttons["create_backup"].setFocus(Qt.FocusReason.OtherFocusReason)
                        self._refresh_settings_summary()
                elif self.view is not None and managed_settings_page(self.view.url(), self.port) == "backup":
                    self._settings_page_loaded(True)

        request.isFinishedChanged.connect(finished)
        request.stateChanged.connect(finished)
        self._feedback(ticket, f"Downloading to private staging: {destination}")
        request.accept()

    def _print_pdf(self):
        if self.view is None:
            return
        destination = self.paths["downloads"] / f"print-{secrets.token_hex(12)}.pdf"
        assert_safe_leaf(destination)
        ticket = self._begin_feedback("pdf")
        self.pdf_results.append({"path": str(destination), "state": "in_progress", "feedback_ticket": ticket})
        self._feedback(ticket, "Generating a PDF in the disposable downloads area…")
        self.view.printToPdf(str(destination))

    def _pdf_finished(self, file_path: str, success: bool):
        matching = next((item for item in self.pdf_results if item["path"] == file_path), None)
        if matching is None or matching["state"] != "in_progress":
            return
        destination = Path(file_path)
        if success and destination.is_file() and destination.stat().st_size > 0:
            matching["state"] = "completed"
            self.pdf_files.append(destination)
            self._feedback(matching["feedback_ticket"], f"PDF saved: {destination}", "success")
        else:
            matching["state"] = "failed"
            self._feedback(matching["feedback_ticket"], "PDF generation failed; no completed PDF was reported.", "error")

    def open_external(self, url: QUrl):
        if not allowed_external(url):
            self.note_blocked(url)
            return
        # Qt's LinkClicked classification can include a scripted anchor.click().
        # A separate human confirmation is required before leaving the app.
        with browser_dialog(self):
            if QMessageBox.question(
                self, "Open external link?", f"Open this address in your default browser?\n\n{url.toString()}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            ) != QMessageBox.StandardButton.Yes:
                self.note_blocked(url)
                return
            handoff_external(self, url)

    def note_blocked(self, url: QUrl):
        self.blocked_urls.append(url.toString())

    def _focus_request(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            if socket.waitForReadyRead(300) and socket.readAll().data().strip() == self.instance_secret.encode():
                self.showNormal()
                self.raise_()
                self.activateWindow()
            socket.disconnectFromServer()
            socket.deleteLater()

    def _fail(self, reason: str):
        self.poll.stop()
        self.failed_reason = reason
        self._settings_navigation_started()
        if self.view is not None:
            self.view.setEnabled(False)
        elif self.import_stage is not None:
            self.import_stage.setText(reason)
        self.statusBar().showMessage(reason)
        print(f"[DLMS Desktop] {reason}", file=sys.stderr, flush=True)
        if os.environ.get("DLMS_DESKTOP_AUTOMATED") == "1":
            QTimer.singleShot(0, QApplication.instance().quit)
        else:
            QMessageBox.critical(self, "DLMS Desktop startup failed", reason)
            QApplication.instance().quit()

    def _evaluate_browser(self, script: str, timeout_ms: int) -> dict:
        """Bound callbacks to this live page and wait; retire stale callbacks.

        Qt may deliver JavaScript callbacks while a page is being destroyed.
        Such callbacks must not touch a retired page or an expired wait loop.
        """
        from shiboken6 import isValid
        view = self.view
        if view is None or not isValid(view):
            return {"done": False, "value": None}
        page = view.page()
        if page is None or not isValid(page):
            return {"done": False, "value": None}
        generation = self._browser_generation
        loop = QEventLoop()
        timer = QTimer(loop)
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        result = {"done": False, "value": None}
        active = True

        def completed(value):
            if (not active or generation != self._browser_generation
                    or self.view is not view or not isValid(view) or not isValid(page)):
                return
            result.update(done=True, value=value)
            loop.quit()

        page.runJavaScript(script, completed)
        timer.start(timeout_ms)
        loop.exec()
        active = False
        timer.stop()
        return result

    def _checkpoint_browser(self):
        """Capture normal-close browser evidence; not a crash durability boundary."""
        if self.view is None or self.view.page() is None:
            return False
        script = """(()=>{try {
          if (typeof checkpointQuizRecovery === 'function') checkpointQuizRecovery();
          const records = {};
          for (let i=0;i<localStorage.length;i++) {
            const key=localStorage.key(i);
            if (key.startsWith('dlms.quiz-progress.v1:') || key==='dlms-study-mistakes-request')
              records[key]=localStorage.getItem(key);
          }
          return JSON.stringify({ok:true,records});
        } catch(e) { return JSON.stringify({ok:false,error:String(e)}); }})()"""

        result = self._evaluate_browser(script, 2000)
        try:
            value = json.loads(result["value"]) if result["done"] else None
        except (TypeError, ValueError):
            value = None
        if not result["done"] or not isinstance(value, dict) or not value.get("ok"):
            print("[DLMS Desktop] Browser checkpoint could not be confirmed; recovery state was not cleared", file=sys.stderr)
            return False
        try:
            atomic_json(self.paths["root"] / "recovery-evidence.json", {
                "profile_uuid": self.manifest["uuid"], "epoch": self.manifest["epoch"],
                "origin": f"http://127.0.0.1:{self.port}", "records": value["records"],
            })
            return True
        except (OSError, ValueError) as exc:
            print(f"[DLMS Desktop] Could not retain a separate browser evidence copy: {exc}", file=sys.stderr)
            return False

    def _quiesce_browser(self) -> bool:
        """Stop new quiz actions and wait for the page's known save promises."""
        if self.view is None or self.view.page() is None:
            return True
        self.view.setEnabled(False)
        self.view.page().runJavaScript("""(()=>{
          window.__dlmsDesktopCloseState='pending';
          Promise.resolve(typeof dlmsDesktopBeforeClose==='function' ? dlmsDesktopBeforeClose() : null)
            .then(()=>{window.__dlmsDesktopCloseState='settled'})
            .catch(()=>{window.__dlmsDesktopCloseState='failed'});
          return true;
        })()""")
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            state = self._evaluate_browser("window.__dlmsDesktopCloseState", 150)
            if state["value"] == "settled":
                return True
            if state["value"] == "failed":
                break
        print("[DLMS Desktop] Browser saves did not settle before close; inspect durable recovery on reopen.", file=sys.stderr)
        return False

    def _drain_backend(self) -> bool:
        if self.backend is None or self.backend.poll() is not None:
            return False
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            connection.request("POST", "/_desktop/drain", headers={
                "Host": f"127.0.0.1:{self.port}",
                "X-DLMS-Desktop-Nonce": self.nonce,
                "X-DLMS-Desktop-Token": self.nonce,
            })
            response = connection.getresponse()
            response.read(32)
            if response.status != 200:
                raise RuntimeError("backend still has an in-flight request")
            return True
        except (OSError, RuntimeError) as exc:
            message = f"Some saves have no confirmed result: {exc}. Reopen this profile and review its recovery state."
            print(f"[DLMS Desktop] {message}", file=sys.stderr)
            if os.environ.get("DLMS_DESKTOP_AUTOMATED") != "1":
                QMessageBox.warning(self, "Save result uncertain", message)
            return False
        finally:
            connection.close()

    def _stop_backend(self):
        if self.backend is None:
            if self.reserved_socket is not None:
                self.reserved_socket.close()
                self.reserved_socket = None
            if self.parent_pipe_write is not None:
                os.close(self.parent_pipe_write)
                self.parent_pipe_write = None
            if self.backend_log is not None:
                self.backend_log.close()
                self.backend_log = None
            return
        proc = self.backend
        if proc.poll() is None:
            reap_owned_group(proc.pid, self.nonce)
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()  # exact Popen child only
                proc.wait(timeout=3)
        reap_owned_group(proc.pid, self.nonce)
        if self.parent_pipe_write is not None:
            os.close(self.parent_pipe_write)
            self.parent_pipe_write = None
        if self.reserved_socket is not None:
            self.reserved_socket.close()
            self.reserved_socket = None
        if self.backend_log is not None:
            self.backend_log.close()
            self.backend_log = None
        self.backend = None

    def _documents_folder(self) -> Path:
        return self.documents_folder

    def _open_backup_folder(self):
        if self.mode == "local" and self.last_backup_output is not None:
            try:
                opened = dispatch_external(QUrl.fromLocalFile(str(self.last_backup_output.parent)))
            except ValueError as exc:
                ticket = self._begin_feedback("create_backup")
                self._feedback(ticket, f"Backup remains saved at {self.last_backup_output}. {exc}", "warning")
                return
            if not opened:
                ticket = self._begin_feedback("create_backup")
                self._feedback(ticket, f"Backup remains saved at {self.last_backup_output}. "
                    "The containing folder could not be opened; use your file manager.", "warning")

    def _poll_backup_output(self):
        future = self.backup_output_future
        if future is None or not future.done():
            return
        self.backup_output_timer.stop()
        self.backup_output_future = None
        record = self.backup_output_record
        self.backup_output_record = None
        if record["operation"] != self.backup_output_operation:
            record["state"] = "unconfirmed_old_operation"
            return
        try:
            result = future.result()
            record.update(state="completed", published=result)
            self.last_backup_output = Path(result["path"])
            self.downloaded_files.append(self.last_backup_output)
            message = f"Backup saved: {result['path']} (SHA-256 {result['sha256']})"
            self.open_backup_folder.setVisible(self.mode == "local")
        except Exception as exc:
            record.update(state="publication_failed", reason=str(exc))
            message = f"Backup publication was not confirmed: {exc}. The private download is retained at {record['path']}."
        self.backup_output_selection = None
        self._backup_creating = False
        self._feedback(record["feedback_ticket"], message, "success" if record["state"] == "completed" else "error")
        if self._settings_ready():
            for button in self.settings_buttons.values():
                button.setEnabled(True)
            if self._settings_ready("backup"):
                self.settings_buttons["create_backup"].setFocus(Qt.FocusReason.OtherFocusReason)
                self._refresh_settings_summary()
        elif self.view is not None and managed_settings_page(self.view.url(), self.port) == "backup":
            # A form download may emit loadFinished(false) while leaving the
            # original Settings document loaded. Re-verify that exact document
            # before restoring its native controls; never trust the download URL.
            self._settings_page_loaded(True, self.view)

    @staticmethod
    def _eligible_backup_path(archive: Path) -> Path | None:
        try:
            from .backup_selection import _source_path
            return _source_path(archive)[0]
        except (OSError, ValueError, RuntimeError):
            return None

    def _warn_backup_path(self):
        self._import_feedback("Backup path is not eligible; no import started. Choose an owned local ZIP, without symbolic links.", "error")
        QMessageBox.warning(self, "Backup not selected",
            "Choose a local ZIP file owned by you. Symbolic links, special files and ambiguous paths are not supported.")

    def _backup_selection_identity(self, archive: Path) -> tuple | None:
        """Cheap picker change check; the worker still validates its staged bytes."""
        resolved = self._eligible_backup_path(archive)
        if resolved is None:
            return None
        try:
            selected = archive.stat(follow_symlinks=False)
            return (resolved, selected.st_dev, selected.st_ino, selected.st_size,
                    selected.st_mtime_ns, selected.st_ctime_ns)
        except OSError:
            return None

    def _choose_backup(self, *, still_authorized=None):
        if self.import_in_progress:
            return
        self._import_feedback_ticket = self._begin_feedback("backup")
        self._import_status_serial += 1
        self._import_reopen_status = None
        selected, _ = self._choose_backup_source()
        if still_authorized is not None and not still_authorized():
            return
        if selected:
            archive = Path(selected)
            selected_identity = self._backup_selection_identity(archive)
            if selected_identity is None:
                self._warn_backup_path()
                self._restore_backup_focus(still_authorized)
                return
            from .backup_selection import prepare
            self.import_in_progress = True
            self._import_feedback("Copying and validating a private backup snapshot before confirmation…")
            self.backup_selection_context = (archive, selected_identity, still_authorized, self._import_status_serial)
            self.backup_selection_future = self.backup_selection_executor.submit(
                prepare, self.paths, self.profile_name, archive)
            self.backup_selection_timer.start()
        else:
            self._import_feedback("Backup file selection canceled; no import started.")
            self._restore_backup_focus(still_authorized)

    def _choose_backup_source(self):
        return QFileDialog.getOpenFileName(
            self, "Select a Local DLMS backup", str(self._documents_folder()), "DLMS backups (*.zip)")

    def _poll_backup_selection(self):
        future = self.backup_selection_future
        if future is None or not future.done():
            return
        self.backup_selection_timer.stop()
        self.backup_selection_future = None
        archive, selected_identity, still_authorized, status_serial = self.backup_selection_context
        self.backup_selection_context = None
        self.import_in_progress = False
        try:
            selection = future.result()
        except Exception as exc:
            message = f"Backup selection was not staged or confirmed: {type(exc).__name__}: {exc}"
            if status_serial == self._import_status_serial:
                self._import_feedback(message, "error")
            if os.environ.get("DLMS_DESKTOP_AUTOMATED") != "1":
                QMessageBox.warning(self, "Backup not ready", message)
            self._restore_backup_focus(still_authorized)
            return
        from .backup_selection import advance, cancel, read
        try:
            if still_authorized is not None and not still_authorized():
                cancel(self.paths, self.profile_name, selection["token"])
                if status_serial == self._import_status_serial:
                    self._import_feedback("Backup selection canceled after leaving Settings; no import started.")
                self._restore_backup_focus(still_authorized)
                return
            summary = selection.get("summary") or {}
            details = ", ".join(f"{key}: {value}" for key, value in sorted(summary.items())
                                if isinstance(value, int) and not isinstance(value, bool))
            answer = QMessageBox.question(
                self, "Import validated backup into this disposable profile?",
                f"Import the private snapshot of {archive.name} into profile {self.profile_name}?\n\n"
                f"Archive size: {selection['size']:,} bytes; {selection['file_count']} data files.\n"
                f"SHA-256: {selection['sha256']}\n"
                f"{details}\n\n"
                "Archive structure and CRC were checked. Full dataset checks run before any live change. "
                "Desktop will retain this input and make a safety backup. The dataset and recovery epoch may change. "
                "Reopen this profile if import is interrupted.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes or (still_authorized is not None and not still_authorized()):
                cancel(self.paths, self.profile_name, selection["token"])
                if status_serial == self._import_status_serial:
                    self._import_feedback("Backup selection canceled; no import started.")
                self._restore_backup_focus(still_authorized)
                return
            if self._backup_selection_identity(archive) != selected_identity:
                cancel(self.paths, self.profile_name, selection["token"])
                if status_serial == self._import_status_serial:
                    self._import_feedback("Backup source changed; the private snapshot was not imported.", "error")
                QMessageBox.warning(self, "Backup changed after selection",
                    "The source backup changed. The validated private snapshot was not imported. Select it again.")
                self._restore_backup_focus(still_authorized)
                return
            advance(self.paths, self.profile_name, selection["token"], "ready", "confirmed")
            if not self.adopt_backup(selection):
                current = read(self.paths, self.profile_name, selection["token"])
                if current["state"] == "confirmed":
                    advance(self.paths, self.profile_name, selection["token"], "confirmed", "refused")
                self._restore_backup_focus(still_authorized)
        except Exception as exc:
            message = f"Backup confirmation could not be used safely: {type(exc).__name__}: {exc}"
            if (status_serial == self._import_status_serial
                    or (self._import_worker_status_serial == status_serial + 1
                        and self.import_worker is None)):
                self._import_feedback(message, "error")
            if os.environ.get("DLMS_DESKTOP_AUTOMATED") != "1":
                QMessageBox.warning(self, "Backup not started", message)
            self._restore_backup_focus(still_authorized)

    def _restore_backup_focus(self, still_authorized):
        if still_authorized is None or still_authorized():
            for button in self.settings_buttons.values():
                button.setEnabled(True)
            button = self.settings_buttons.get("backup")
            if button is not None:
                button.setFocus(Qt.FocusReason.OtherFocusReason)

    def _dispose_webview(self):
        if self._browser_dialog_depth:
            raise RuntimeError('Browser retirement cannot run inside a browser dialog')
        if self.view is None and self._retiring_browser is None:
            return
        if self._retiring_browser is None:
            retirement = BrowserRetirement(self.view, self.profile, self)
            self._retiring_browser = retirement
            self._browser_generation += 1
            self._settings_navigation_started()
            # Invalidate ownership before stop/destruction can invoke callbacks.
            self.view = None
            self.profile = None
            self.settings_panel = None
            self.settings_fallback = None
            self.settings_buttons = {}
        retirement = self._retiring_browser
        if not retirement.done:
            loop = QEventLoop()
            timeout = QTimer(loop)
            timeout.setSingleShot(True)
            timeout.timeout.connect(loop.quit)
            retirement.finished.connect(loop.quit)
            timeout.start(5000)
            if not retirement._profile_queued:
                retirement.start()
            self._retirement_wait_active = True
            try:
                loop.exec()
            finally:
                self._retirement_wait_active = False
                timeout.stop()
                retirement.finished.disconnect(loop.quit)
        if not retirement.done:
            raise RuntimeError('Browser retirement was not confirmed; transition must remain closed')
        self.browser_retirements.append(list(retirement.events))
        self._retiring_browser = None
        retirement.deleteLater()

    def _active_outputs(self) -> list[dict]:
        return [item for item in (*self.download_results, *self.pdf_results)
                if item["state"] == "in_progress"]

    @browser_operation
    def adopt_backup(self, archive: Path | dict) -> bool:
        """Closed-browser import; never point the backend at an outside root."""
        if self.import_in_progress:
            return False
        if self._backup_creating or self._active_outputs():
            message = "Wait for the current download or PDF to finish before importing a backup. No data transition was started."
            self._import_feedback(message, "error")
            if os.environ.get("DLMS_DESKTOP_AUTOMATED") != "1":
                QMessageBox.warning(self, "Output still in progress", message)
            return False
        if self.backend is None or self.backend.poll() is not None or self.view is None:
            QMessageBox.warning(self, "Desktop not ready", "Reopen this disposable profile before importing a backup.")
            return False
        from .backup_selection import advance, prepare, read
        if not isinstance(archive, dict):
            self._import_feedback_ticket = self._begin_feedback("backup")
        if isinstance(archive, dict):
            selection = read(self.paths, self.profile_name, archive["token"], state="confirmed")
        else:
            # Direct calls are confined to synthetic acceptance drivers. The
            # normal UI always stages before explicit owner confirmation.
            if os.environ.get("DLMS_DESKTOP_AUTOMATED") != "1":
                raise RuntimeError("Use the Backup & Restore chooser to confirm a private snapshot")
            if self._eligible_backup_path(archive) is None:
                self._warn_backup_path()
                return False
            try:
                selection = prepare(self.paths, self.profile_name, archive)
            except (OSError, ValueError) as exc:
                self._import_feedback(f"Synthetic backup was rejected before confirmation: {exc}", "error")
                return False
            advance(self.paths, self.profile_name, selection["token"], "ready", "confirmed")
        self._import_status_serial += 1
        self._import_worker_status_serial = self._import_status_serial
        self._import_reopen_status = None
        self.import_in_progress = True
        self._import_feedback("Importing the confirmed private backup; application use is paused…")
        if self.settings_panel is not None:
            self.settings_panel.hide()
        if not self._quiesce_browser() or not self._drain_backend():
            self.import_in_progress = False
            self._import_worker_status_serial = None
            advance(self.paths, self.profile_name, selection["token"], "confirmed", "refused")
            self._show_transition_refusal("Backup import did not start because a save could not be confirmed")
            QMessageBox.warning(self, "Import not started", "A save could not be confirmed. Close and reopen this profile to resolve it before importing.")
            return False
        self._checkpoint_browser()
        self.monitor.stop()
        self._dispose_webview()
        progress_view = QWidget(self)
        layout = QVBoxLayout(progress_view)
        layout.setContentsMargins(40, 24, 40, 24)
        progress_view.setStyleSheet("background: #111827; color: #f5f3ff;")
        layout.addStretch(1)
        self.import_stage = QLabel("Preparing the isolated restore worker…", progress_view)
        self.import_stage.setWordWrap(True)
        self.import_stage.setAccessibleName("Backup import stage")
        self.import_stage.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.import_stage.setMinimumHeight(100)
        self.import_stage.setStyleSheet("font-size: 17px; font-weight: 600; padding: 12px;")
        indicator = QProgressBar(progress_view)
        indicator.setRange(0, 0)  # no false percentage for validation or restore
        indicator.setAccessibleName("Backup import in progress")
        indicator.setMinimumHeight(24)
        layout.addWidget(self.import_stage)
        layout.addWidget(indicator)
        layout.addStretch(1)
        self.setCentralWidget(progress_view)
        QApplication.processEvents()
        self._stop_backend()
        env = isolated_environment(self.paths)
        env.update(PYTHONNOUSERSITE="1",
                   DLMS_DESKTOP_ADOPT_OWNER_SECRET=self.instance_secret,
                   DLMS_DESKTOP_NONCE=self.nonce,
                   DLMS_DESKTOP_ADOPT_PARENT_PID=str(os.getpid()))
        source_environment(env, include_app=False)
        if os.environ.get("DLMS_DESKTOP_AUTOMATED") == "1":
            env["DLMS_DESKTOP_AUTOMATED"] = "1"
            if os.environ.get("DLMS_DESKTOP_TEST_PAUSE_AT"):
                env["DLMS_DESKTOP_TEST_PAUSE_AT"] = os.environ["DLMS_DESKTOP_TEST_PAUSE_AT"]
            if os.environ.get("DLMS_DESKTOP_TEST_ABORT_AT"):
                env["DLMS_DESKTOP_TEST_ABORT_AT"] = os.environ["DLMS_DESKTOP_TEST_ABORT_AT"]
        log_path = self.paths["logs"] / "desktop-adoption.log"
        assert_safe_leaf(log_path)
        progress_path = self.paths["root"] / "import-progress.json"
        assert_safe_leaf(progress_path)
        progress_path.unlink(missing_ok=True)
        self.import_output = open(log_path, "ab", buffering=0)
        read_fd, write_fd = os.pipe()
        env["DLMS_DESKTOP_ADOPT_PARENT_PIPE"] = str(read_fd)
        try:
            self.import_worker = spawn_process(
                child_command("adopt", "--profile", self.profile_name,
                              "--selection", selection["token"]), cwd=PROJECT, env=env,
                stdin=subprocess.DEVNULL, stdout=self.import_output, stderr=subprocess.STDOUT,
                start_new_session=True, close_fds=True, pass_fds=(read_fd,),
            )
        except OSError as exc:
            print(f"[DLMS Desktop] Restore worker did not start: {exc}", file=sys.stderr)
            os.close(read_fd)
            os.close(write_fd)
            self.import_output.close()
            self.import_output = None
            self.import_in_progress = False
            self._import_worker_status_serial = None
            self._import_feedback("Backup import worker did not start; no import was committed.", "error")
            advance(self.paths, self.profile_name, selection["token"], "confirmed", "refused")
            self.manifest = read_manifest(self.paths, self.profile_name)
            try:
                self._start_reserved()
            except (OSError, ValueError, RuntimeError) as restart_error:
                self._fail(f"Import worker did not start and the local backend could not reopen: {restart_error}. See {log_path}")
            return False
        os.close(read_fd)
        self.import_parent_pipe = write_fd
        self.import_started = time.monotonic()
        self.import_timer.start()
        return True

    def _poll_import(self):
        worker = self.import_worker
        if worker is None:
            return
        progress_path = self.paths["root"] / "import-progress.json"
        try:
            status = json.loads(progress_path.read_text())
            if status.get("worker_pid") == worker.pid and isinstance(status.get("stage"), str):
                self.import_stage.setText(status["stage"])
        except (OSError, ValueError, TypeError):
            pass
        if worker.poll() is None:
            if time.monotonic() - self.import_started > 180:
                self.import_timer.stop()
                # This is a forced interruption, never a successful cancel.
                reap_owned_group(worker.pid, self.nonce)
                worker.kill()  # exact task-owned worker
                worker.wait(timeout=5)
                self._finish_import(timed_out=True)
            return
        self._finish_import()

    def _finish_import(self, *, timed_out=False):
        self.import_timer.stop()
        worker = self.import_worker
        self.import_worker = None
        status_serial = self._import_worker_status_serial
        self._import_worker_status_serial = None
        reap_owned_group(worker.pid, self.nonce)
        if self.import_parent_pipe is not None:
            os.close(self.import_parent_pipe)
            self.import_parent_pipe = None
        if self.import_output is not None:
            self.import_output.close()
            self.import_output = None
        self.import_started = None
        self.import_in_progress = False
        log_path = self.paths["logs"] / "desktop-adoption.log"
        if timed_out or worker.returncode != 0:
            from .transition import read_transition
            if read_transition(self.paths) is not None:
                self._fail(f"Backup outcome needs recovery. Keep this profile closed and inspect {log_path}")
                return
            message = ("Backup was not adopted. The application's previous data was verified after a failed restore; "
                       "a rollback may have advanced the Desktop epoch. Review the preserved input and safety copy. "
                       f"See {log_path}") if worker.returncode == 3 else (
                       f"Backup was rejected or interrupted; no success is claimed. See {log_path}")
            if os.environ.get("DLMS_DESKTOP_AUTOMATED") == "1":
                print(f"[DLMS Desktop] {message}", file=sys.stderr)
            else:
                QMessageBox.warning(self, "Backup not adopted", message)
            self._import_feedback(message, "error")
        elif status_serial == self._import_status_serial:
            message = "Backup committed; reopening the Local application…"
            self._import_feedback(message, "success")
            self._import_reopen_status = (status_serial, message)
        self.manifest = read_manifest(self.paths, self.profile_name)
        self.port = self.manifest["port"]
        self.started_at = time.monotonic()
        self.ready_ms = None
        try:
            self._start_reserved()
        except (OSError, ValueError, RuntimeError) as exc:
            self._fail(f"Import finished, but the local backend could not reopen: {exc}. See {log_path}")

    def _browser_storage_snapshot(self) -> dict:
        if self.view is None or self.view.page() is None:
            raise RuntimeError("The owned browser page is unavailable")
        script = """(()=>{try {
          const read=store=>{const out={};for(let i=0;i<store.length;i++){
            const key=store.key(i);out[key]=store.getItem(key);
          }return out};
          return JSON.stringify({ok:true,origin:location.origin,local:read(localStorage),session:read(sessionStorage)});
        }catch(error){return JSON.stringify({ok:false,error:String(error)})}})()"""
        result = self._evaluate_browser(script, 3000)
        if not result["done"] or not isinstance(result["value"], str):
            raise RuntimeError("Browser storage did not answer")
        value = json.loads(result["value"])
        if not value.get("ok") or value.get("origin") != f"http://127.0.0.1:{self.port}":
            raise RuntimeError(f"Browser storage cannot be inspected at the saved origin: {value.get('error', 'origin mismatch')}")
        return {"local": value["local"], "session": value["session"]}

    def _maintenance_page_loaded(self, ok: bool):
        if not ok:
            self._fail("The authenticated maintenance recovery page could not open; application use remains blocked")
            return
        self.view.loadFinished.disconnect(self._maintenance_page_loaded)
        QTimer.singleShot(0, self._finish_maintenance_browser)

    @browser_operation
    def _finish_maintenance_browser(self):
        from .maintenance import (browser_transition_plan, complete_browser_transition,
                                  clear_completed_marker)
        try:
            before = self._browser_storage_snapshot()
            plan = browser_transition_plan(self.profile_name, before)
            removed_now = any(key in before["local"] for key in plan["remove"])
            script = """(()=>{try{
              const expected=JSON.parse(%s);
              for(const [key,raw] of Object.entries(expected)){
                const actual=localStorage.getItem(key);
                if(actual!==null && actual!==raw) throw new Error('Browser record changed: '+key);
                if(actual!==null) localStorage.removeItem(key);
              }
              return JSON.stringify({ok:true});
            }catch(error){return JSON.stringify({ok:false,error:String(error)})}})()""" % json.dumps(json.dumps(plan["expected"]))
            result = self._evaluate_browser(script, 3000)
            if not result["done"] or not json.loads(result["value"] or "{}").get("ok"):
                raise RuntimeError("Browser key cleanup did not confirm; quarantined evidence and marker remain")
            after = self._browser_storage_snapshot()
            record = complete_browser_transition(self.profile_name, after, removed_now=removed_now)
            self._dispose_webview()
            self._stop_backend()
            self.maintenance_transition = False
            if record["phase"] == "browser_check_pending":
                self.statusBar().showMessage("Maintenance data committed; reopen this same disposable profile once to verify saved browser state before normal use")
                print("[DLMS Desktop] Maintenance browser cleanup recorded. Reopen the same disposable profile for separate-process verification.", file=sys.stderr)
                QTimer.singleShot(0, self.close)
                return
            clear_completed_marker(self.profile_name)
            self.started_at = time.monotonic()
            self.ready_ms = None
            self._start_reserved()
        except Exception as exc:
            self._fail(f"Maintenance browser recovery needs inspection: {type(exc).__name__}: {exc}. No normal application page was opened")

    @browser_operation
    def begin_maintenance(self, scope: str, *, confirmed: bool = False, still_authorized=None) -> bool:
        """Begin one synthetic, closed-browser scope; never call a legacy POST."""
        from .maintenance import SCOPES, SCOPE_EFFECTS, browser_preflight, read_marker
        if scope not in SCOPES:
            QMessageBox.warning(self, "Maintenance unavailable", "This scope is not enabled until its browser-storage transition is verified.")
            return False
        if not confirmed:
            if scope == "study":
                from PySide6.QtWidgets import QInputDialog
                phrase, accepted = QInputDialog.getText(
                    self, "Delete Study History",
                    f"Type DELETE STUDY HISTORY to delete Study history in disposable profile {self.profile_name}.")
                if not accepted or phrase.strip() != "DELETE STUDY HISTORY":
                    return False
            answer = QMessageBox.question(self, "Confirm Desktop maintenance",
                f"{SCOPES[scope]} in disposable profile {self.profile_name}?\n\n"
                f"{SCOPE_EFFECTS[scope]}\n\n"
                "The Desktop will keep a private full recovery copy and the source safety backup where applicable. "
                "Reopen this profile once after browser cleanup to verify the result before normal use.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return False
        elif os.environ.get("DLMS_DESKTOP_AUTOMATED") != "1":
            raise RuntimeError("Automated confirmation is unavailable outside disposable test mode")
        if still_authorized is not None and not still_authorized():
            return False
        if (self.maintenance_worker is not None or self.import_in_progress or self._backup_creating or read_marker(self.profile_name)
                or self.backend is None or self.backend.poll() is not None or self.view is None or self._active_outputs()):
            QMessageBox.warning(self, "Maintenance unavailable", "Finish the current work and resolve any transition before trying again.")
            return False
        from .import_operations import unresolved_count as pending_bundle_imports
        from .pack_operations import unresolved_count as pending_pack_installs
        from .profile_state import read_manifest
        try:
            identity = read_manifest(self.paths, self.profile_name)
            pending_import = bool(identity and (
                pending_bundle_imports(self.paths["root"], identity["epoch"])
                or pending_pack_installs(self.paths["root"], identity["epoch"])))
        except Exception as exc:
            QMessageBox.warning(self, "Maintenance unavailable",
                                f"Import recovery evidence needs inspection before maintenance: {exc}")
            return False
        if pending_import:
            QMessageBox.warning(self, "Maintenance unavailable",
                                "A portable import has accepted work. Resume or inspect it before maintenance.")
            return False
        self.view.setEnabled(False)
        self._settings_navigation_started()
        if not self._quiesce_browser() or not self._drain_backend():
            self._show_transition_refusal("Maintenance did not start because a save could not be confirmed")
            return False
        try:
            self._checkpoint_browser()
            snapshot = self._browser_storage_snapshot()
            operation_id = secrets.token_hex(16)
            browser_preflight(self.profile_name, operation_id, snapshot)
        except Exception as exc:
            self._show_transition_refusal("Maintenance did not start because saved browser work needs inspection")
            QMessageBox.warning(self, "Maintenance not started", f"Saved browser work needs inspection: {exc}")
            return False
        self.monitor.stop()
        windows_retirement = None
        from .webview2_runtime import active as webview2_active
        if scope == "fresh" and os.name == "nt" and webview2_active():
            try:
                from .windows_browser_quarantine import capture
                windows_retirement = capture(self)
            except (OSError, ValueError, RuntimeError) as exc:
                self._fail(f"Fresh-state browser ownership could not be captured: {exc}")
                return False
        self._dispose_webview()
        if windows_retirement is not None:
            try:
                from .maintenance import record_windows_browser_retirement
                record_windows_browser_retirement(self.profile_name, operation_id, windows_retirement)
            except (OSError, ValueError, RuntimeError) as exc:
                self._fail(f"Fresh-state browser retirement could not be confirmed: {exc}")
                return False
        progress_view = QWidget(self)
        layout = QVBoxLayout(progress_view)
        layout.setContentsMargins(40, 24, 40, 24)
        layout.addStretch(1)
        self.maintenance_stage = QLabel(f"Preparing {SCOPES[scope]} for {self.profile_name}…", progress_view)
        self.maintenance_stage.setWordWrap(True)
        self.maintenance_stage.setAccessibleName("Maintenance stage")
        layout.addWidget(self.maintenance_stage)
        indicator = QProgressBar(progress_view)
        indicator.setRange(0, 0)
        layout.addWidget(indicator)
        layout.addStretch(1)
        self.setCentralWidget(progress_view)
        QApplication.processEvents()
        self._stop_backend()
        env = isolated_environment(self.paths)
        env.update(PYTHONNOUSERSITE="1",
                   DLMS_DESKTOP_MAINT_OWNER_SECRET=self.instance_secret,
                   DLMS_DESKTOP_MAINT_PARENT_PID=str(os.getpid()),
                   DLMS_DESKTOP_NONCE=self.nonce)
        source_environment(env, include_app=False)
        if os.environ.get("DLMS_DESKTOP_AUTOMATED") == "1":
            env["DLMS_DESKTOP_AUTOMATED"] = "1"
            if os.environ.get("DLMS_DESKTOP_TEST_MAINTENANCE_ABORT"):
                env["DLMS_DESKTOP_TEST_MAINTENANCE_ABORT"] = os.environ["DLMS_DESKTOP_TEST_MAINTENANCE_ABORT"]
        log_path = self.paths["logs"] / "desktop-maintenance.log"
        assert_safe_leaf(log_path)
        self.maintenance_output = open(log_path, "ab", buffering=0)
        read_fd, write_fd = os.pipe()
        env["DLMS_DESKTOP_MAINT_PARENT_PIPE"] = str(read_fd)
        try:
            self.maintenance_worker = spawn_process(
                child_command("maintenance", "--profile", self.profile_name,
                              "--scope", scope, "--operation-id", operation_id), cwd=PROJECT, env=env,
                stdin=subprocess.DEVNULL, stdout=self.maintenance_output, stderr=subprocess.STDOUT,
                start_new_session=True, close_fds=True, pass_fds=(read_fd,))
        except OSError as exc:
            os.close(read_fd)
            os.close(write_fd)
            self.maintenance_output.close()
            self.maintenance_output = None
            self._fail(f"Maintenance worker did not start: {exc}. The browser preflight was retained")
            return False
        os.close(read_fd)
        self.maintenance_pipe = write_fd
        self.maintenance_started = time.monotonic()
        self.maintenance_timer.start()
        return True

    def _poll_maintenance(self):
        worker = self.maintenance_worker
        if worker is None:
            return
        if worker.poll() is None:
            if time.monotonic() - self.maintenance_started > 180:
                reap_owned_group(worker.pid, self.nonce)
                worker.kill()
                worker.wait(timeout=5)
                self._finish_maintenance_worker()
            return
        self._finish_maintenance_worker()

    def _finish_maintenance_worker(self):
        from .maintenance import read_marker
        self.maintenance_timer.stop()
        worker = self.maintenance_worker
        self.maintenance_worker = None
        reap_owned_group(worker.pid, self.nonce)
        if self.maintenance_pipe is not None:
            os.close(self.maintenance_pipe)
            self.maintenance_pipe = None
        if self.maintenance_output is not None:
            self.maintenance_output.close()
            self.maintenance_output = None
        self.maintenance_started = None
        marker = read_marker(self.profile_name)
        if worker.returncode != 0 or marker is None or marker["phase"] != "committed":
            self._fail("Maintenance did not reach a verified commit. The profile remains closed until restart reconciliation; see desktop-maintenance.log")
            return
        if marker["scope"] == "fresh":
            from .maintenance import quarantine_fresh_browser
            try:
                if os.name != "nt":
                    reap_owned_group(os.getpgrp(), self.nonce, exclude={os.getpid()})
                quarantine_fresh_browser(self.profile_name, owner=self)
            except Exception as exc:
                self._fail(f"Fresh-state browser quarantine needs inspection: {exc}")
                return
            self.statusBar().showMessage("Fresh-state data is committed; old Chromium storage is quarantined. Reopen this disposable profile to verify the empty state")
            QTimer.singleShot(0, self.close)
            return
        self.manifest = read_manifest(self.paths, self.profile_name)
        self.started_at = time.monotonic()
        self.ready_ms = None
        self._start_reserved()

    @browser_operation
    def begin_removal(self, *, confirmed: bool = False, still_authorized=None) -> bool:
        """Intentional removal of this exact synthetic profile after owner handoff."""
        from .maintenance import _browser_pending, read_marker
        from .removal import read_tombstone
        if not confirmed:
            from PySide6.QtWidgets import QInputDialog
            phrase, accepted = QInputDialog.getText(self, "Remove disposable profile",
                f"Type REMOVE DLMS DATA to remove active profile {self.profile_name} and all its local data. "
                "A private synthetic recovery copy will be retained outside the target for this acceptance phase.")
            if not accepted or phrase.strip() != "REMOVE DLMS DATA":
                return False
            if QMessageBox.question(self, "Confirm exact profile removal",
                f"Remove only {self.paths['root']}? The next launch will not recreate this name. "
                "Use a new disposable profile name to start fresh.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return False
        elif os.environ.get("DLMS_DESKTOP_AUTOMATED") != "1":
            raise RuntimeError("Automated confirmation is unavailable outside disposable test mode")
        if still_authorized is not None and not still_authorized():
            return False
        if (self.removal_worker is not None or self.maintenance_worker is not None or self.import_in_progress or self._backup_creating
                or read_marker(self.profile_name) or read_tombstone(self.profile_name)
                or self.backend is None or self.backend.poll() is not None or self.view is None or self._active_outputs()):
            QMessageBox.warning(self, "Removal unavailable", "Resolve current work or transition before removing this disposable profile.")
            return False
        self.view.setEnabled(False)
        self._settings_navigation_started()
        if not self._quiesce_browser() or not self._drain_backend():
            self._show_transition_refusal("Removal did not start because a save could not be confirmed")
            return False
        try:
            self._checkpoint_browser()
            reason = _browser_pending(self._browser_storage_snapshot())
            if reason:
                raise RuntimeError(reason)
            from .maintenance import _close_checkpoint
            _close_checkpoint(self.paths, self.manifest)
        except Exception as exc:
            self._show_transition_refusal("Removal did not start because saved browser work needs inspection")
            QMessageBox.warning(self, "Removal not started", str(exc))
            return False
        self.monitor.stop()
        self._dispose_webview()
        self.setCentralWidget(QLabel("Preparing the exact disposable profile removal. The window will close only after the external intent is recorded."))
        QApplication.processEvents()
        self._stop_backend()
        external_logs = AREA / "removal-logs"
        if external_logs.is_symlink() or (external_logs.exists() and not external_logs.is_dir()):
            self._fail("External removal log path is unsafe")
            return False
        external_logs.mkdir(mode=0o700, exist_ok=True)
        log_path = external_logs / f"{self.profile_name}.log"
        assert_safe_leaf(log_path)
        self.removal_output = open(log_path, "ab", buffering=0)
        read_fd, write_fd = os.pipe()
        env = isolated_environment(self.paths)
        env.update(PYTHONNOUSERSITE="1",
                   DLMS_DESKTOP_REMOVE_OWNER_SECRET=self.instance_secret,
                   DLMS_DESKTOP_REMOVE_PARENT_PID=str(os.getpid()),
                   DLMS_DESKTOP_REMOVE_PARENT_PIPE=str(read_fd), DLMS_DESKTOP_NONCE=self.nonce)
        source_environment(env, include_app=False)
        if os.environ.get("DLMS_DESKTOP_AUTOMATED") == "1":
            env["DLMS_DESKTOP_AUTOMATED"] = "1"
        operation_id = secrets.token_hex(16)
        try:
            self.removal_worker = spawn_process(
                child_command("removal", "--profile", self.profile_name,
                              "--operation-id", operation_id), cwd=PROJECT, env=env,
                stdin=subprocess.DEVNULL, stdout=self.removal_output, stderr=subprocess.STDOUT,
                start_new_session=True, close_fds=True, pass_fds=(read_fd,))
        except OSError as exc:
            os.close(read_fd)
            os.close(write_fd)
            self.removal_output.close()
            self.removal_output = None
            self._fail(f"Removal worker did not start: {exc}")
            return False
        os.close(read_fd)
        self.removal_pipe = write_fd
        self.removal_timer.start()
        return True

    def _poll_removal(self):
        from .removal import read_tombstone
        worker = self.removal_worker
        if worker is None:
            return
        ready = AREA / "removed" / f"{self.profile_name}.ready.json"
        if ready.exists():
            try:
                record = json.loads(ready.read_text())
                marker = read_tombstone(self.profile_name)
                if marker and record.get("operation_id") == marker["operation_id"] and worker.poll() is None:
                    self.removal_timer.stop()
                    self.removal_handoff = True
                    self.statusBar().showMessage("Removal intent retained. Closing this window so the exact profile can be removed")
                    self.close()
                    return
            except (OSError, ValueError):
                pass
        if worker.poll() is not None:
            self.removal_timer.stop()
            self._fail("Removal did not reach owner handoff. The external tombstone, if present, requires reconciliation; see the external removal log")

    def _confirm_server_close(self) -> bool:
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Close DLMS Desktop?")
        dialog.setIcon(QMessageBox.Icon.Question)
        dialog.setText(
            "The remote deployment may have unsaved Study or Exam work. DLMS Desktop cannot verify its save state. "
            "Closing DLMS Desktop does not delete results already saved on the server. "
            "Finish the work or inspect Server History before closing.")
        keep = dialog.addButton("Keep open", QMessageBox.ButtonRole.RejectRole)
        close = dialog.addButton("Close DLMS Desktop", QMessageBox.ButtonRole.AcceptRole)
        dialog.setDefaultButton(keep)
        dialog.setEscapeButton(keep)
        dialog.exec()
        return dialog.clickedButton() is close

    def closeEvent(self, event):  # noqa: N802 - Qt API
        if self._close_complete:
            event.accept()
            return
        if self._close_active:
            event.ignore()
            return
        if (getattr(self, '_browser_operation_depth', 0)
                or getattr(self, '_settings_action_busy', False)
                or getattr(self, '_retirement_wait_active', False)):
            self.statusBar().showMessage('A Desktop transition is still finishing. Keep this window open; close again after its outcome is reported.')
            event.ignore()
            return
        if self._browser_dialog_depth:
            self._close_after_dialog = True
            self.statusBar().showMessage('Close requested; dismiss the browser dialog. Saves will be checked afterward.')
            event.ignore()
            return
        exports = getattr(self, '_native_exports', None)
        if exports is not None and (exports.active is not None or exports.queue):
            self.statusBar().showMessage('Finish or cancel the export before closing; publication is not yet confirmed.')
            event.ignore(); return
        self._close_active = True
        try:
            self._close_event_impl(event)
        except (RuntimeError, OSError, ValueError) as exc:
            # Keep evidence and ownership if resource retirement cannot be
            # established. Do not claim a successful close/data transition.
            self._closing = False
            event.ignore()
            message = f"Close did not complete safely: {exc}. Recovery evidence is retained; no save success is claimed."
            self.statusBar().showMessage(message)
            print(f"[DLMS Desktop] {message}", file=sys.stderr, flush=True)
        finally:
            self._close_active = False

    def _close_event_impl(self, event):
        if self.backup_output_future is not None:
            self.statusBar().showMessage("Backup publication is still running. Keep this window open until its outcome is reported.")
            event.ignore()
            return
        if self.mode == "server":
            if self._active_outputs() and os.environ.get("DLMS_DESKTOP_AUTOMATED") != "1":
                QMessageBox.information(self, "Server download active", "Finish the Server download before closing this window.")
                event.ignore()
                return
            if self.server_loaded_once and os.environ.get("DLMS_DESKTOP_AUTOMATED") != "1":
                if not self._confirm_server_close():
                    event.ignore()
                    return
            for item in self._active_outputs():
                item["state"] = "interrupted_by_close"
            self._closing = True
            self._dispose_webview()
            self.server.close()
            if os.name != "nt":
                reap_owned_group(os.getpgrp(), self.nonce, exclude={os.getpid()})
            # Windows Qt helpers inherit the launcher's kill-on-close job.
            # Its noninherited handle closes at process exit, after Qt retires.
            self._release_local_ownership()
            try:
                data = json.loads(self.instance_descriptor.read_text())
                if data.get("secret") == self.instance_secret:
                    self.instance_descriptor.unlink()
            except (OSError, ValueError):
                pass
            self._close_complete = True
            return super().closeEvent(event)
        if self.removal_worker is not None and not self.removal_handoff:
            event.ignore()
            return
        if self.maintenance_worker is not None:
            if os.environ.get("DLMS_DESKTOP_AUTOMATED") != "1":
                QMessageBox.information(self, "Maintenance in progress",
                    "Keep this window open. An interruption will be reconciled from its retained private recovery copy on the next launch.")
            event.ignore()
            return
        if self.import_in_progress:
            # The worker is owned by this window. An abrupt process death is
            # handled by its parent pipe and the transition journal on restart.
            if os.environ.get("DLMS_DESKTOP_AUTOMATED") != "1":
                QMessageBox.information(self, "Import in progress",
                    "The backup import is still running. Keep this window open. If the process stops unexpectedly, reopen this profile to reconcile the recorded outcome.")
            event.ignore()
            return
        if self._backup_creating and not self._active_outputs():
            message = ("A backup request has no confirmed download outcome yet. Closing may leave a retained backup "
                       "in this disposable profile. Reopen and inspect Recent safety backups before retrying.")
            if (os.environ.get("DLMS_DESKTOP_AUTOMATED") != "1"
                    and QMessageBox.question(self, "Backup outcome pending", message,
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes):
                event.ignore()
                return
            print(f"[DLMS Desktop] {message}", file=sys.stderr, flush=True)
        active_outputs = self._active_outputs()
        if active_outputs:
            message = ("A download or PDF is still in progress. Closing may leave an incomplete file in this "
                       "profile's disposable downloads area. Wait for completion, or close and inspect the output later.")
            if (os.environ.get("DLMS_DESKTOP_AUTOMATED") != "1"
                    and QMessageBox.question(self, "Output not finished", message,
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes):
                event.ignore()
                return
            for item in active_outputs:
                item["state"] = "interrupted_by_close"
            print(f"[DLMS Desktop] {message}", file=sys.stderr, flush=True)
        self._closing = True
        self.poll.stop()
        self.monitor.stop()
        if self.view is not None and self.maintenance_transition:
            self._dispose_webview()
        elif self.view is not None:
            quiesced = self._quiesce_browser()
            drained = self._drain_backend()
            checkpoint = self._checkpoint_browser()
            self.close_result = {"quiesced": quiesced, "drained": drained, "checkpoint": checkpoint}
            if not (quiesced and drained and checkpoint):
                print("[DLMS Desktop] Close completed with unconfirmed browser/backend saves; recovery evidence was retained.", file=sys.stderr)
            self._dispose_webview()
        elif self._retiring_browser is not None:
            self._dispose_webview()
        self._stop_backend()
        self.server.close()
        if os.name != "nt":
            reap_owned_group(os.getpgrp(), self.nonce, exclude={os.getpid()})
        self._release_local_ownership()
        try:
            data = json.loads(self.instance_descriptor.read_text())
            if data.get("secret") == self.instance_secret:
                self.instance_descriptor.unlink()
        except (OSError, ValueError):
            pass
        if self.removal_pipe is not None:
            os.close(self.removal_pipe)
            self.removal_pipe = None
        if os.name == "nt" and self.removal_handoff and self.removal_worker is not None:
            # The worker needs EOF and the exact Local lock release above to
            # finish. Keep the owning job alive until verified completion; a
            # bounded failure leaves the external tombstone for reconciliation.
            from .removal import read_tombstone
            try:
                self.removal_worker.wait(timeout=180)
                marker = read_tombstone(self.profile_name)
                if self.removal_worker.returncode != 0 or marker is None or marker["phase"] != "removed":
                    raise RuntimeError("Removal worker has no verified completed outcome")
            except (subprocess.TimeoutExpired, OSError, ValueError, RuntimeError) as exc:
                message = f"Profile removal is unresolved: {exc}. Its external tombstone and recovery copy are retained; reopen to reconcile."
                print(f"[DLMS Desktop] {message}", file=sys.stderr, flush=True)
                if os.environ.get("DLMS_DESKTOP_AUTOMATED") != "1":
                    QMessageBox.warning(self, "Removal needs inspection", message)
                reap_owned_group(self.removal_worker.pid, self.nonce)
        if self.removal_output is not None:
            self.removal_output.close()
            self.removal_output = None
        event.accept()
        self._close_complete = True


def send_focus(socket_path: str, secret: str) -> bool:
    socket = QLocalSocket()
    if abstract_instance_socket():
        socket.setSocketOptions(QLocalSocket.SocketOption.AbstractNamespaceOption)
    socket.connectToServer(socket_path)
    if not socket.waitForConnected(700):
        print(f"[DLMS Desktop] Could not contact existing window: {socket.errorString()}", file=sys.stderr)
        return False
    socket.write(secret.encode() + b"\n")
    socket.flush()
    sent = socket.bytesToWrite() == 0 or socket.waitForBytesWritten(700)
    if not sent:
        print(f"[DLMS Desktop] Could not send focus request: {socket.errorString()}", file=sys.stderr)
    socket.disconnectFromServer()
    return sent

"""Windows native controls with an independently owned C# WebView2 surface.

The native Settings and transaction controller are retained. The Qt browser
fallback and Linux renderer are not modified or instantiated by this subclass.
"""
import os
from pathlib import Path
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QStackedLayout, QMessageBox
from PySide6.QtWebEngineCore import QWebEngineSettings, QWebEngineScript, QWebEngineLoadingInfo
from .shell import (DesktopWindow as QtDesktopWindow, LocalOnlyInterceptor,
                    allowed_internal, managed_settings_page, assert_safe_leaf)
from .server_browser import ServerOnlyInterceptor, exact_server_origin
from .server_mode import server_root
from .settings_surface import LocalSettingsSurface
from .webview2_browser import Profile, View, LocalPage, ServerPage
from .browser_lifetime import browser_operation


class DesktopWindow(QtDesktopWindow):
    """Preserve native save/recovery/backup authority; change browser factory only."""

    def __init__(self,*args,**kwargs):
        # Captured before application HOME/APPDATA isolation. Late Known Folder
        # expansion can resolve the synthetic environment instead of owner roots.
        roots = kwargs.pop('selection_private_roots', None)
        self.selection_private_roots = tuple(roots) if roots is not None else None
        self.backup_chooser_folders = tuple(kwargs.pop('backup_chooser_folders', ()) or ())
        self._wv_status_serial = 0
        self._wv_feedback_context = {}
        # Runtime availability is a prerequisite, not permission to fall back
        # to Qt or download/install software. Resolve before starting a backend.
        from .webview2_browser import host_executable
        import subprocess
        environment={k:v for k,v in os.environ.items() if not k.startswith('WEBVIEW2_')}
        probe=subprocess.run([str(host_executable()),'--runtime-version'],capture_output=True,
            text=True,timeout=15,env=environment,creationflags=subprocess.CREATE_NO_WINDOW)
        from .webview2_runtime import compatible_runtime, MIN_RUNTIME_VERSION
        if probe.returncode or not compatible_runtime(probe.stdout.strip()):
            raise RuntimeError(f'Microsoft Edge WebView2 Evergreen Runtime {MIN_RUNTIME_VERSION} or newer is required. Install or update the official Runtime with owner approval, then retry. No renderer fallback was selected.')
        self.webview2_runtime_version=probe.stdout.strip()
        super().__init__(*args,**kwargs)

    def _selection_switch_refused(self):
        if (getattr(self,'_browser_dialog_depth',0)
                or getattr(self,'_browser_operation_depth',0)):
            self._switch_refusal('Finish or cancel the open browser/file operation before switching Local/Server modes')
            return True
        return False

    def _choose_backup_destination(self):
        import time
        from .browser_lifetime import browser_dialog
        from .windows_backup_chooser import choose
        with browser_dialog(self):
            result = choose(self, time.strftime('DLMS-backup-%Y%m%d-%H%M%S.zip'),
                            self.backup_chooser_folders)
        if result[0]:
            import sys
            if (getattr(sys, 'frozen', False)
                    and Path(result[0]).is_relative_to(Path(sys.executable).parent)):
                raise ValueError('Choose a ZIP outside the application payload')
        return result

    class _RestoreChooserFailure(Exception):
        """Native setup failed before the base restore transaction began."""

    @browser_operation
    def _choose_backup(self, *, still_authorized=None):
        context = (self.mode, self.view, self._browser_generation,
                   getattr(self, '_settings_generation', None))
        expected_serial = self._import_status_serial + 1
        def current():
            return (not self._closing and self._retiring_browser is None
                    and context == (self.mode, self.view, self._browser_generation,
                                    getattr(self, '_settings_generation', None))
                    and self._import_status_serial == expected_serial
                    and (still_authorized is None or still_authorized()))
        try:
            return super()._choose_backup(still_authorized=still_authorized)
        except self._RestoreChooserFailure as exc:
            if not current():
                return
            message = ('Backup chooser could not open; no import started. '
                       'Reconnect the configured Documents or Downloads folder and retry. '
                       'If it remains unavailable, close and reopen Desktop.\n\n' + str(exc)[:1000])
            if not self._import_feedback(message, 'error'):
                return  # A newer notice owns feedback and focus.
            feedback_context = (self._import_feedback_ticket, self._wv_status_serial)
            if os.environ.get('DLMS_DESKTOP_AUTOMATED') != '1':
                from .browser_lifetime import browser_dialog
                dialog = QMessageBox(self)
                dialog.setWindowTitle('Backup chooser unavailable')
                dialog.setIcon(QMessageBox.Icon.Warning)
                dialog.setTextFormat(Qt.TextFormat.PlainText)
                dialog.setText(message)
                dialog.setStandardButtons(QMessageBox.StandardButton.Close)
                dialog.setDefaultButton(QMessageBox.StandardButton.Close)
                dialog.setEscapeButton(QMessageBox.StandardButton.Close)
                try:
                    with browser_dialog(self):
                        dialog.exec()
                finally:
                    dialog.deleteLater()
            focused_context = lambda: (current() and feedback_context == (
                self._import_feedback_ticket, self._wv_status_serial))
            if focused_context():
                self._restore_backup_focus(focused_context)

    def _choose_backup_source(self):
        from .browser_lifetime import browser_dialog
        from .windows_backup_chooser import choose_open
        try:
            with browser_dialog(self):
                return choose_open(self, self.backup_chooser_folders)
        except Exception as exc:
            raise self._RestoreChooserFailure(f'{type(exc).__name__}: {exc}') from exc

    def _close_event_impl(self, event):
        if any(item.get('state') == 'in_progress' and item.get('phase') == 'publishing'
               for item in self.download_results):
            self.statusBar().showMessage('Export publication is still running. Keep this window open until its outcome is reported.')
            event.ignore()
            return
        return super()._close_event_impl(event)

    def switch_to_server(self):
        # A chooser or staging loop owns the page before any drain/retirement.
        if self._selection_switch_refused():return False
        return super().switch_to_server()

    def switch_to_local(self):
        if self._selection_switch_refused():return False
        return super().switch_to_local()

    def _status_message_changed(self, message):
        if not self._feedback_writing:
            self._wv_status_serial = getattr(self, '_wv_status_serial', 0) + 1
        super()._status_message_changed(message)

    def _begin_feedback(self, action):
        ticket = super()._begin_feedback(action)
        # clearMessage() above can synchronously emit messageChanged. Capture
        # the context afterward, otherwise the new operation invalidates itself.
        self._wv_feedback_context = {ticket: (
            self.mode, self._browser_generation, getattr(self, '_wv_status_serial', 0))}
        return ticket

    def _feedback(self, ticket, message, severity='info'):
        context = getattr(self, '_wv_feedback_context', {}).get(ticket)
        if context != (self.mode, self._browser_generation, getattr(self, '_wv_status_serial', 0)):
            return False
        return super()._feedback(ticket, message, severity)

    def _blob_download_current(self, request, origin):
        from .webview2_runtime import canonical_blob_download
        view = self.view
        return (view is not None and not self._closing and self._retiring_browser is None
                and request.page() is view.page() and not view.page().isLoading()
                and getattr(request, '_blob_download', False) is True
                and getattr(request, '_download_context', None) == (
                    view._active_generation, view._active_navigation, view.url().toString())
                and canonical_blob_download(request.url().toString(), origin))

    def _download(self, request):
        if request.url().scheme() != 'blob':
            if (self.mode != 'local' or self.view is None or request.page() is not self.view.page()
                    or self._closing or self._retiring_browser is not None
                    or not allowed_internal(request.url(), self.port)):
                request.cancel()
                return
            # Managed backup output retains its byte-bound native transaction.
            if request.url().path() == '/settings/backup/create':
                candidate = self.backup_output_selection
                if (candidate is None or not self._backup_creating
                        or candidate['operation'] != self.backup_output_operation
                        or request.url().query() != 'desktop_output=' + candidate['operation']):
                    request.cancel()
                    return
                return super()._download(request)
            return self._ordinary_download(request, local=True)
        origin = f'http://127.0.0.1:{self.port}'
        if (self.mode != 'local' or self.view is None or self.backend is None or self.backend.poll() is not None
                or not allowed_internal(self.view.url(), self.port)
                or not self._blob_download_current(request, origin)):
            request.cancel()
            return
        # Browser-created exports never claim a native backup selection, token
        # or transaction. They use only ordinary private download publication.
        self._ordinary_download(request, local=True)

    def _server_download(self, request):
        if (self.mode != 'server' or self._closing or self._retiring_browser is not None
                or self.view is None or request.page() is not self.view.page()
                or not (exact_server_origin(request.url(), self.mode_config['server']['origin'])
                        or (exact_server_origin(self.view.url(), self.mode_config['server']['origin'])
                            and self._blob_download_current(request, self.mode_config['server']['origin'])))):
            request.cancel()
            return
        self._ordinary_download(request, local=False)

    def _ordinary_download(self, request, *, local):
        from .webview2_exports import begin_export
        view = self.view
        offer = getattr(request, '_download_context', None)
        if (view is None or request.page() is not view.page()
                or not isinstance(offer, tuple) or len(offer) != 3
                or any(type(value) is not int or value < 0 for value in offer[:2])
                or offer[:2] != (getattr(view, '_active_generation', None),
                                 getattr(view, '_active_navigation', None))):
            request.cancel()
            return
        return begin_export(self, request, local=local)

    def _set_server_page_exposed(self, exposed, *, loading=False):
        super()._set_server_page_exposed(exposed, loading=loading)
        if self.mode=='server' and self.view is not None:
            # Foreign HWNDs remain above Qt siblings. Keep the containing form
            # visible; its own native cover controls pixels/input. Only its
            # browser control may hide on a terminal error, never while loading.
            self.view.show()
            self._wv_cover_loading=loading
            QTimer.singleShot(0,self._sync_server_cover)

    def _sync_server_cover(self):
        if (self.mode!='server' or self.view is None or self._closing
                or self._retiring_browser is not None):return
        cover=getattr(self.view,'setServerCover',None)
        if cover is not None:
            exposed=self._server_page_exposed
            cover(not exposed,self.server_status.text(),
                  browser_visible=exposed or getattr(self,'_wv_cover_loading',False))

    def _style_server_surface(self):
        super()._style_server_surface()
        QTimer.singleShot(0,self._sync_server_cover)

    @staticmethod
    def _prepare_server_cover(label):
        label.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        label.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)

    def _create_mode_toolbar(self):
        super()._create_mode_toolbar()
        # Diagnostics are opt-in CLI evidence, never an ordinary product menu.
        if self.mix_diagnostic_action is not None:
            self.mode_menu.removeAction(self.mix_diagnostic_action)
            self.mix_diagnostic_action.setVisible(False)
        self.local_mode_action.setText('&Local')
        self.configure_server_action.setText('&Configure Server…')
        self.retry_server_action.setText('&Retry connection')
        self.retry_server_action.triggered.disconnect()
        self.retry_server_action.triggered.connect(self._retry_server_from_menu)
        self.about_action.setText('&About DLMS Desktop…')
        # Windows-only mnemonic access when the native selector has focus.
        # The browser retains ordinary typing and web shortcuts.

    def _update_mode_toolbar(self):
        super()._update_mode_toolbar()
        server = self.mode_config.get('server')
        self.server_mode_action.setText('&Server: ' + server['label'].replace('&', '&&')
            if server else '&Server (not configured)')
        self.mode_identity.setToolTip(self.mode_identity.toolTip() + '\nPress Space to open the native menu; use arrows or the underlined letter.')

    def _native_menu_context(self):
        return (self.mode, self.view, self._browser_generation)

    def _native_menu_available(self):
        return not (self._closing or self._retiring_browser is not None
                    or self._close_active or self._mode_switch_busy
                    or self._browser_dialog_depth or self._browser_operation_depth)

    def _native_menu_focus(self, context):
        # Do not steal foreground activation after another application was
        # selected while a modal loop was running, nor focus a retired page.
        if (not self._closing and self._retiring_browser is None
                and context == self._native_menu_context() and self.isActiveWindow()):
            self.mode_identity.setFocus(Qt.FocusReason.OtherFocusReason)

    def _about_text(self):
        from .webview2_about import about_text
        runtime = getattr(self.view, 'runtime_version', None) or self.webview2_runtime_version
        return about_text(mode=self.mode, runtime_version=runtime)

    def _show_about(self):
        if not self._native_menu_available():
            return
        return self._show_webview2_about()

    @browser_operation
    def _show_webview2_about(self):
        context = self._native_menu_context()
        dialog = QMessageBox(self)
        dialog.setObjectName('desktopAboutDialog')
        dialog.setWindowTitle('About DLMS Desktop')
        dialog.setAccessibleName('DLMS Desktop build, backend and runtime identity')
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByKeyboard
                                       | Qt.TextInteractionFlag.TextSelectableByMouse)
        try:
            dialog.setText(self._about_text())
        except (OSError, ValueError, TypeError):
            dialog.setText('DLMS Desktop build information is unavailable or invalid. '
                           'Keep the entire executable folder together and use the matching candidate package. '
                           'No data or settings were changed.')
        dialog.setStandardButtons(QMessageBox.StandardButton.Close)
        dialog.setDefaultButton(QMessageBox.StandardButton.Close)
        dialog.setEscapeButton(QMessageBox.StandardButton.Close)
        dialog.exec()
        self._native_menu_focus(context)
        dialog.deleteLater()

    def _configure_server_dialog(self):
        if not self._native_menu_available():
            return
        return self._configure_webview2_server_dialog()

    @browser_operation
    def _configure_webview2_server_dialog(self):
        context = self._native_menu_context()
        try:
            return super()._configure_server_dialog()
        finally:
            self._native_menu_focus(context)

    def _retry_server_from_menu(self):
        if not self._native_menu_available():
            return
        result = super()._retry_server()
        if self.view is not None and self.isActiveWindow():
            self.view.setFocus(Qt.FocusReason.OtherFocusReason)
        return result

    def _settings_page_loaded(self,ok,loaded_view=None):
        view=self.view
        if (view is not None and (loaded_view is None or loaded_view is view)
                and not self._closing and self._retiring_browser is None and self.mode=='local'
                and not self._close_active and not self._mode_switch_busy
                and not self._browser_operation_depth and self._import_reopen_status is None
                and not self._settings_transition_refused and not self.import_in_progress
                and not self.maintenance_transition and self.failed_reason is None
                and self.backend is not None and self.backend.poll() is None
                and self.import_worker is None and self.maintenance_worker is None
                and self.removal_worker is None
                and allowed_internal(view.url(),self.port)
                and (view.url().path()=='/certifications' or view.url().path().startswith('/certifications/'))
                and managed_settings_page(view.url(),self.port) is None
                and getattr(view.page(),'last_http_status',0) in (400,422)):
            # Source validation responses (including Certification forms) are
            # actionable documents. They grant no native Settings authority.
            self._settings_navigation_started()
            if self.settings_panel is not None:self.settings_panel.hide()
            if self.settings_fallback is not None:self.settings_fallback.hide()
            view.show()
            self.statusBar().showMessage('The application reported a validation error. Review the visible response; no native Settings action was enabled.')
            return
        return super()._settings_page_loaded(ok,loaded_view)

    def _attachment_declined(self, view, url):
        """A declined native backup has no Download object to release its intent."""
        if (self.mode!='local' or self.view is not view or self._closing
                or self._retiring_browser is not None or self.failed_reason is not None
                or self._close_active or self._mode_switch_busy or self._browser_operation_depth
                or self._settings_transition_refused or self._import_reopen_status is not None
                or self.import_in_progress or self.maintenance_transition
                or self.import_worker is not None or self.maintenance_worker is not None
                or self.removal_worker is not None
                or self.backend is None or self.backend.poll() is not None
                or not self._backup_creating or self._active_outputs()
                or not allowed_internal(url,self.port)
                or url.path()!='/settings/backup/create'
                or url.query()!='desktop_output='+str(self.backup_output_operation)):
            return False
        self._backup_creating=False
        self.backup_output_selection=None
        self._feedback(self._backup_feedback_ticket,
            'The browser declined the backup attachment; no selected destination was published. Retry an explicit backup action.', 'error')
        # The exact prior Settings document was retained by the native host;
        # verify its normal marker again before enabling native controls.
        if managed_settings_page(view.url(),self.port)=='backup':
            self._settings_page_loaded(True,view)
        return True

    def _server_load_information(self,info,page,generation):
        if (self.mode=='server' and self.view is not None and self.view.page() is page
                and self._browser_generation==generation and not self._closing
                and self._retiring_browser is None and not page.isLoading()
                and not info.isDownload() and 400<=getattr(page,'last_http_status',0)<500
                and exact_server_origin(page.url(),self.mode_config['server']['origin'])):
            # A real same-origin application validation response differs from
            # a transport/certificate/outage failure. No Local token or native
            # Settings surface exists in Server mode.
            self._server_load_finished(True)
            return
        return super()._server_load_information(info,page,generation)
    def _show_webview(self):
        self.mode = "local"
        self._update_mode_toolbar()
        from .maintenance import read_marker
        marker = read_marker(self.profile_name)
        self.maintenance_transition = marker is not None
        self.profile = Profile("dlms-block-a", self)
        self.profile.setPersistentStoragePath(str(self.paths["web_storage"]))
        self.profile.setCachePath(str(self.paths["web_cache"]))
        self.profile.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
        # DLMS's Study copy button needs sanitized clipboard writes after a
        # user gesture. Clipboard reading/paste remains disabled.
        self.profile.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, True)
        self.profile.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanPaste, False)
        self.profile.setPersistentCookiesPolicy(Profile.PersistentCookiesPolicy.ForcePersistentCookies)
        self.interceptor = LocalOnlyInterceptor(self.nonce, self.port, self.profile)
        self.profile.setUrlRequestInterceptor(self.interceptor)
        self.profile.downloadRequested.connect(self._download)
        self.view = View(self)
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
        generation = self._browser_generation
        page.loadingChanged.connect(lambda info: self._local_load_information(info, page, generation))
        if getattr(self,'window_events',None) is not None:self.window_events.bind(self.view)
        close_delay = int(os.environ.get("DLMS_DESKTOP_CLOSE_AFTER_READY_MS", "0"))
        if close_delay > 0:
            self.view.loadFinished.connect(lambda ok: QTimer.singleShot(close_delay, self.close) if ok else None)
        if self.maintenance_transition:
            self.view.loadFinished.connect(self._maintenance_page_loaded)
        route = "/_desktop/maintenance" if self.maintenance_transition else "/"
        self.view.setUrl(QUrl(f"http://127.0.0.1:{self.port}{route}"))

    def _show_server(self):
        server = self.mode_config["server"]
        if server is None:
            self._fail("Server mode has no exact configured origin")
            return
        self.server_paths = server_root(server["id"])
        self.mode = "server"
        self.server_unreachable = False
        self._update_mode_toolbar()
        self.profile = Profile(f"dlms-server-{server['id']}", self)
        self.profile.setPersistentStoragePath(str(self.server_paths["storage"]))
        self.profile.setCachePath(str(self.server_paths["cache"]))
        self.profile.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, False)
        self.profile.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        self.profile.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, False)
        self.profile.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanPaste, False)
        self.profile.setPersistentCookiesPolicy(Profile.PersistentCookiesPolicy.ForcePersistentCookies)
        self.server_interceptor = ServerOnlyInterceptor(server["origin"], self.profile)
        self.profile.setUrlRequestInterceptor(self.server_interceptor)
        self.profile.downloadRequested.connect(self._server_download)
        self.view = View(self)
        self.view.setPage(ServerPage(self.profile, self, server["origin"], parent=self.view))
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
        self._prepare_server_cover(self.server_status)
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
        page, generation = self.view.page(), self._browser_generation
        # loadFinished(false) also means a navigation became an attachment.
        # Qt's loading information distinguishes that from a failed page load.
        page.loadingChanged.connect(lambda info: self._server_load_information(info, page, generation))
        if getattr(self,'window_events',None) is not None:self.window_events.bind(self.view)
        self._retry_server()

"""Unprivileged, exact-origin WebEngine boundary for a configured server.

No Local Desktop token, page adapter, recovery API, or native command is
reachable from these classes. Cross-origin login flows are intentionally
unsupported in the first Server block.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl, qVersion
from PySide6.QtWidgets import QFileDialog
from PySide6.QtWebEngineCore import (QWebEnginePage, QWebEngineUrlRequestInterceptor,
                                        qWebEngineVersion, qWebEngineChromiumVersion)

from .server_console import ServerPolicyDiagnostics
from .isolation import AREA, PROJECT
from .browser_lifetime import OwnedPage, browser_file_dialog


def exact_server_origin(url: QUrl, origin: str) -> bool:
    if not url.isValid() or url.userName() or url.password():
        return False
    expected = QUrl(origin)
    return (url.scheme() == expected.scheme() and url.host() == expected.host()
            and url.port(443 if url.scheme() == "https" else 80) == expected.port(443 if expected.scheme() == "https" else 80))


class ServerOnlyInterceptor(QWebEngineUrlRequestInterceptor):
    def __init__(self, origin: str, parent=None):
        super().__init__(parent)
        self.origin = origin
        self.blocked: list[str] = []

    def interceptRequest(self, info):  # noqa: N802 - Qt API
        target, initiator = info.requestUrl(), info.initiator()
        main = info.resourceType() == info.ResourceType.ResourceTypeMainFrame
        allowed = exact_server_origin(target, self.origin) and (
            exact_server_origin(initiator, self.origin) or (main and initiator.isEmpty()))
        if target.scheme() in {"data", "blob"} and exact_server_origin(initiator, self.origin):
            allowed = True
        if not allowed:
            self.blocked.append(target.toString())
            info.block(True)


class ServerPage(OwnedPage):
    def __init__(self, profile, owner, origin: str, parent=None):
        super().__init__(profile, parent if parent is not None else owner)
        self.owner, self.origin = owner, origin
        self.policy_diagnostics = ServerPolicyDiagnostics((qVersion(), qWebEngineVersion(), qWebEngineChromiumVersion()))
        self.newWindowRequested.connect(self._new_window)
        from .ai_actions import AIHandoff
        self.ai_handoff = AIHandoff(self, owner)
        if __import__('sys').platform == 'darwin':
            from .macos_file_selection import install_selection_guard
            install_selection_guard(self)

    def javaScriptConsoleMessage(self, level, message, line_number, source_id):  # noqa: N802
        # First occurrence remains visible. Only exact harmless parser warnings
        # verified for this pinned engine are deduplicated for this page lifetime.
        # Other warnings, all errors and unknown engine builds retain Qt reporting.
        if self.policy_diagnostics.repeated(message, warning=(
                level == QWebEnginePage.JavaScriptConsoleMessageLevel.WarningMessageLevel)):
            return
        super().javaScriptConsoleMessage(level, message, line_number, source_id)

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):  # noqa: N802 - Qt API
        if self.owner.view is None:
            return False
        if exact_server_origin(url, self.origin):
            return True
        if not is_main_frame and url.scheme() in {"data", "blob"}:
            return True
        if is_main_frame and nav_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked:
            from .shell import allowed_external
            if allowed_external(url):
                self.ai_handoff.handle(url, True, generic=lambda: self.owner.open_external(url))
                return False
        self.owner.note_blocked(url)
        self.owner.statusBar().showMessage("Server navigation outside the configured origin was blocked. Cross-origin login is unsupported.")
        return False

    def _new_window(self, request):
        if self.owner.view is None or self.owner._closing:
            return
        # A popup must not inherit this authenticated profile or leak a URL
        # through the system browser without a separately approved flow.
        # Qt deletes the request after this signal. Async validation retains
        # only value copies, never the ephemeral C++ request wrapper.
        url, user = QUrl(request.requestedUrl()), request.isUserInitiated()
        self.ai_handoff.handle(url, user, generic=lambda: self.owner.open_external(url))

    def certificateError(self, error):  # noqa: N802 - Qt API
        self.owner.statusBar().showMessage("Server certificate validation failed. The certificate was not bypassed.")
        return False

    @browser_file_dialog
    def chooseFiles(self, mode, old_files, accepted_mime_types):  # noqa: N802 - Qt API
        # Linux receives immutable, explicitly selected private snapshots.
        # Other platforms retain their current adapter pending native work.
        import sys
        if sys.platform == 'darwin':
            from .macos_file_selection import choose_files
            return choose_files(self, mode, server=True)
        if sys.platform.startswith("linux"):
            from .file_selection import choose_files
            return choose_files(self, mode, server=True)
        # No other Desktop profile is an upload source. The fixture directory
        # is captured, non-personal test material; AREA/server-uploads is an
        # explicit synthetic staging location for a later owner workflow.
        selected = self.owner.file_selection_for_test
        if selected is not None:
            self.owner.file_selection_for_test = None
            choices = [str(selected)]
        elif mode == QWebEnginePage.FileSelectionMode.FileSelectOpenMultiple:
            choices, _ = QFileDialog.getOpenFileNames(self.owner, "Choose synthetic Server upload", str(AREA / "server-uploads"))
        elif mode == QWebEnginePage.FileSelectionMode.FileSelectOpen:
            choice, _ = QFileDialog.getOpenFileName(self.owner, "Choose synthetic Server upload", str(AREA / "server-uploads"))
            choices = [choice] if choice else []
        else:
            return []
        permitted = (AREA / "server-uploads").resolve(), (PROJECT / "fixtures").resolve()
        approved = []
        for choice in choices:
            path = Path(choice)
            resolved = path.resolve()
            if not path.is_symlink() and resolved.is_file() and any(resolved.is_relative_to(root) for root in permitted):
                approved.append(str(resolved))
            else:
                self.owner.note_blocked(QUrl.fromLocalFile(str(path)))
        return approved

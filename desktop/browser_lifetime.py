"""Ordered WebEngine retirement and browser-dialog stack ownership."""
from contextlib import contextmanager
from functools import wraps
import sys
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWebEngineCore import QWebEnginePage


@contextmanager
def browser_dialog(owner):
    owner._browser_dialog_depth += 1
    try:
        yield
    finally:
        owner._browser_dialog_depth -= 1
        if owner._browser_dialog_depth == 0 and owner._close_after_dialog:
            owner._close_after_dialog = False
            # Run only after the JS-dialog virtual and its native stack return.
            QTimer.singleShot(0, owner.close)


def browser_operation(method):
    """Keep window ownership across a whole operation's nested event loops."""
    @wraps(method)
    def guarded(owner, *args, **kwargs):
        owner._browser_operation_depth = getattr(owner, '_browser_operation_depth', 0) + 1
        try:
            return method(owner, *args, **kwargs)
        finally:
            owner._browser_operation_depth -= 1
    return guarded


def browser_file_dialog(method):
    @wraps(method)
    def guarded(page, *args, **kwargs):
        if page.owner._closing or getattr(page.owner, '_retiring_browser', None) is not None:
            return []
        with browser_dialog(page.owner):
            return method(page, *args, **kwargs)
    return guarded


class OwnedPage(QWebEnginePage):
    """Preserve native dialogs; never destroy their page on their modal stack."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.document_generation = 0
        self.loadStarted.connect(self._document_started)

    def _document_started(self):
        self.document_generation += 1

    def _closing_notice(self, message):
        if not (self.owner._closing or getattr(self.owner, '_retiring_browser', None) is not None):
            return False
        # An alert arriving during the save wait must not open another modal
        # loop on a page being retired. Preserve its text and fail closed for
        # confirmations/prompts; this does not acknowledge any pending save.
        notice = 'Browser notice during retirement/close (no save success implied): ' + str(message)
        self.owner.statusBar().showMessage(notice)
        self.owner.close_browser_notices.append(notice)
        print('[DLMS Desktop] ' + notice, file=sys.stderr, flush=True)
        return True

    def javaScriptAlert(self, origin, message):  # noqa: N802
        if self._closing_notice(message):
            return
        with browser_dialog(self.owner):
            return super().javaScriptAlert(origin, message)

    def javaScriptConfirm(self, origin, message):  # noqa: N802
        if self._closing_notice(message):
            return False
        with browser_dialog(self.owner):
            return super().javaScriptConfirm(origin, message)

    def javaScriptPrompt(self, origin, message, default):  # noqa: N802
        if self._closing_notice(message):
            return False, ""
        with browser_dialog(self.owner):
            return super().javaScriptPrompt(origin, message, default)


class BrowserRetirement(QObject):
    """One deletion owner: view owns page; profile outlives both destructors.

    No setPage(None), explicit page deletion or global sendPostedEvents. Signal
    callbacks record destruction only; profile retirement is posted on the next
    event-loop turn after *both* view and page destruction signals occurred.
    """
    finished = Signal()

    def __init__(self, view, profile, parent):
        super().__init__(parent)
        self.view, self.page, self.profile = view, view.page(), profile
        if self.page.parent() is not view:
            raise RuntimeError('Browser page has an unexpected deletion owner')
        self.events = []
        self.done = False
        self.started = False
        self._profile_queued = False
        self.view.destroyed.connect(lambda *_: self._object_destroyed('view'))
        self.page.destroyed.connect(lambda *_: self._object_destroyed('page'))
        self.profile.destroyed.connect(self._profile_destroyed)

    def start(self):
        if self.started:
            return
        self.started = True
        self.view.hide()
        self.view.setEnabled(False)
        self.view.stop()
        # The scoped wait loop receives the timer, then Qt handles deleteLater
        # at its ordinary event boundary. Parent close handling remains guarded.
        QTimer.singleShot(0, self.view.deleteLater)

    def _object_destroyed(self, kind):
        self.events.append(kind)
        if {'view', 'page'}.issubset(self.events) and not self._profile_queued:
            self._profile_queued = True
            QTimer.singleShot(0, self.profile.deleteLater)

    def _profile_destroyed(self, *_):
        self.events.append('profile')
        self.done = True
        self.finished.emit()

"""Host-owned AI website actions. No renderer message can activate this menu.

Server documents cannot attest their own AI controls. These native actions use
fixed, content-free destinations and leave the existing page/clipboard alone.
"""
from contextlib import contextmanager

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMenu, QToolButton

from .webview2_file_selection import SelectionContext
from . import webview2_external as external


DESTINATIONS = (
    ('chatgpt', 'Chat&GPT', 'https://chatgpt.com/', 'g'),
    ('claude', '&Claude', 'https://claude.ai/', 'c'),
    ('gemini', 'G&emini', 'https://gemini.google.com/', 'e'),
)


def capture(owner):
    if (getattr(owner, '_external_handoff_pending', False)
            or getattr(owner, '_browser_dialog_depth', 0)
            or getattr(owner, '_browser_operation_depth', 0)
            or (owner.mode == 'server' and not owner._server_page_exposed)):
        return None
    try:
        return SelectionContext.capture(owner.view.page())
    except (RuntimeError, ValueError, OSError, AttributeError):
        return None


class AIWebsiteMenu(QMenu):
    def __init__(self, owner, parent):
        super().__init__(parent)
        self.owner = owner
        self._context = self._press = self._lease = None
        self._targets = {}
        self._mnemonics = {}
        for provider, label, url, mnemonic in DESTINATIONS:
            action = self.addAction(label)
            action.setObjectName('desktopAI_' + provider)
            action.setToolTip('Open ' + url + ' in your normal default browser. Clipboard unchanged; paste yourself.')
            self._targets[action] = url
            self._mnemonics[mnemonic] = action
            action.triggered.connect(lambda checked=False, a=action: self._activate(a))
        self.aboutToShow.connect(self._opening)
        self.aboutToHide.connect(self._hidden)

    def _opening(self):
        self._context = capture(self.owner)
        self._press = self._lease = None
        for action in self._targets:
            action.setEnabled(self._context is not None)

    def _hidden(self):
        self._press = None
        # QAction.triggered runs while QMenu is closing. Only the dispatch-scoped
        # lease below survives hide, never a reusable permission or menu grant.
        self._context = None

    def _current(self, action):
        context = self._context
        return (self.isVisible() and action in self._targets and action.isEnabled()
                and context is not None and context.valid()
                and capture(self.owner) == context)

    @contextmanager
    def _dispatch(self, action):
        self._lease = (action, self._context) if self._current(action) else None
        try:
            yield
        finally:
            self._lease = None

    def _activate(self, action):
        lease, self._lease = self._lease, None  # Consume before queued handoff.
        if lease is None or lease[0] is not action:
            return
        context = lease[1]
        if context.valid() and capture(self.owner) == context:
            external.open_native_ai(self.owner, context, self._targets[action])

    def mousePressEvent(self, event):
        action = self.actionAt(event.position().toPoint())
        self._press = (action if event.spontaneous() and event.button() == Qt.MouseButton.LeftButton
                       and self._current(action) else None)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        action = self.actionAt(event.position().toPoint())
        pressed, self._press = self._press, None
        if (event.spontaneous() and event.button() == Qt.MouseButton.LeftButton
                and pressed is not None and pressed is action):
            with self._dispatch(action):
                super().mouseReleaseEvent(event)
        else:
            super().mouseReleaseEvent(event)  # Any triggered signal has no lease.

    def keyPressEvent(self, event):
        action = None
        if event.spontaneous() and not event.isAutoRepeat():
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
                action = self.activeAction()
            elif event.modifiers() in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.AltModifier):
                action = self._mnemonics.get(event.text().lower())
        if action is not None and self._current(action):
            with self._dispatch(action):
                action.trigger()
                self.close()
            event.accept()
        else:
            super().keyPressEvent(event)


def install(owner):
    button = QToolButton(owner)
    button.setObjectName('desktopAIWebsites')
    button.setText('AI websites ▾')
    button.setAccessibleName('Open AI website in default browser; clipboard unchanged')
    button.setToolTip('Copy a prompt with the page controls, then open an AI website here. '
                      'Nothing is pasted or submitted automatically.')
    button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    menu = AIWebsiteMenu(owner, button)
    button.setMenu(menu)
    owner.statusBar().addPermanentWidget(button)
    owner.ai_website_button, owner.ai_website_menu = button, menu

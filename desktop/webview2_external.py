"""Explicit Windows browser handoff, never a page-visible native API.

Only an owned host's current, user-initiated main-document event may request
HTTP(S) consent. No clipboard text, cookie, authentication header or form data
is forwarded by this adapter. Qt/Linux keeps its own browser mechanism.
"""
from __future__ import annotations

from PySide6.QtCore import QTimer, QUrl, Qt
from PySide6.QtWidgets import QMessageBox

from .browser_lifetime import browser_dialog
from .shell import allowed_external, dispatch_external
from .webview2_file_selection import SelectionContext
from .windows_browser_handoff import HandoffUnconfirmed

AI_ACTIONS = frozenset(('study-review', 'review-single', 'review-selected',
    'study-pack', 'law-prompt', 'cert-combined', 'cert-manual'))


def _direct_ai(event, context):
    # Owned-host evidence only: Local producer/observer or Server native user
    # signal plus consumed private activation. Labels/URLs/messages alone fail.
    attested = (event.get('kind') == 'ai-action' and event.get('verified_ai') is True
                and event.get('ai_action') in AI_ACTIONS)
    return attested and (context.mode == 'local' or (context.mode == 'server'
        and event.get('native_user') is True and approved_server_ai(event.get('url', ''))))


def approved_server_ai(value):
    url = QUrl(value, QUrl.ParsingMode.StrictMode)
    return url.isValid() and bytes(url.toEncoded()) in (
        b'https://chatgpt.com/', b'https://claude.ai/', b'https://gemini.google.com/')


def confirm(owner, url, mode, origin):
    dialog = QMessageBox(owner)
    dialog.setWindowTitle('Open external link?')
    dialog.setTextFormat(Qt.TextFormat.PlainText)
    source = ('Server session: ' + origin + '\n\n') if mode == 'server' else ''
    dialog.setText(source + 'Open this address in your default browser?\n\n'
                   + url.toString() + '\n\n'
                   'Desktop will open only this address. It will not submit or paste your prompt. '
                   'If the action copied a prompt, paste it yourself when ready.')
    dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    dialog.setDefaultButton(QMessageBox.StandardButton.No)
    dialog.setEscapeButton(QMessageBox.StandardButton.No)
    try:
        return dialog.exec() == QMessageBox.StandardButton.Yes
    finally:
        dialog.deleteLater()


def _matches(view, event, context):
    return (event.get('user') is True and event.get('mode') == context.mode
            and (event.get('kind') in ('navigation', 'popup') or _direct_ai(event, context))
            and type(event.get('generation')) is int
            and type(event.get('nav_id')) is int
            and (event['generation'], event['nav_id']) ==
                (context.navigation_generation, context.navigation_id)
            and isinstance(event.get('source'), str)
            and bytes(QUrl(event['source']).toEncoded()) == context.href
            and context.view is view)


def request(view, event):
    owner = view.page().owner
    if (getattr(owner, '_external_handoff_pending', False)
            or getattr(owner, '_browser_dialog_depth', 0)
            or getattr(owner, '_browser_operation_depth', 0)):
        return  # No nested prompts/replayed clicks while native consent owns input.
    try:
        context = SelectionContext.capture(view.page())
        url = QUrl(event.get('url', ''))
        if (not _matches(view, event, context)
                or (context.mode == 'server' and not owner._server_page_exposed)):
            return
        if event.get('event') == 'external-refused':
            if event.get('refusal') == 'frame-attribution':
                ticket = owner._begin_feedback('external_link')
                owner._feedback(ticket, 'External link refused: its requesting frame cannot be verified safely. '
                                'Reopen this window and retry the AI link from the main page.', 'error')
            elif event.get('refusal') == 'ai-activation':
                ticket = owner._begin_feedback('external_link')
                owner._feedback(ticket, 'AI opening refused. Activate the AI button again and use ChatGPT, Claude or Gemini '
                                'over HTTPS. A repeated, expired or unsupported request cannot open a browser.', 'error')
            return
        if not url.isValid() or len(bytes(url.toEncoded())) > 8192 or not allowed_external(url):
            ticket = owner._begin_feedback('external_link')
            owner._feedback(ticket, 'External link refused. Choose a credential-free HTTP(S) AI website '
                            'outside localhost; executable, file and custom-scheme links are not allowed.', 'error')
            return
    except (RuntimeError, ValueError, OSError, AttributeError, TypeError):
        return
    owner._external_handoff_pending = True
    # Leave the native event reader before entering a nested dialog loop.
    direct = _direct_ai(event, context)
    QTimer.singleShot(0, lambda: _open(owner, context, url, direct=direct))


def _open(owner, context, url, *, direct=False):
    try:
        if not context.valid():
            return
        ticket = owner._begin_feedback('external_link')
        accepted = direct
        if not direct:
            with browser_dialog(owner):
                accepted = confirm(owner, url, context.mode, context.origin)
        if not context.valid():
            return
        if not accepted:
            shown = owner._feedback(ticket, 'External browser opening canceled. The page remains available.')
            if shown and context.valid() and owner.isActiveWindow():
                context.view.setFocus(Qt.FocusReason.OtherFocusReason)
            return
        try:
            with browser_dialog(owner):
                if not dispatch_external(url):
                    raise OSError('Windows did not accept the default-browser request')
        except HandoffUnconfirmed:
            if not context.valid():
                return
            shown = owner._feedback(ticket, 'Browser opening was not confirmed. Check your browser before retrying; '
                            'it may already have opened. Your copied prompt and DLMS page remain available.', 'error')
            if shown and context.valid() and owner.isActiveWindow():
                context.view.setFocus(Qt.FocusReason.OtherFocusReason)
            return
        except (OSError, ValueError, RuntimeError):
            if not context.valid():
                return
            # Do not log URLs, copied prompts or native exception details.
            shown = owner._feedback(ticket, 'External link could not open. Check your Windows default browser, '
                            'then retry the AI link. Your copied prompt and DLMS page remain available.', 'error')
            if shown and context.valid() and owner.isActiveWindow():
                context.view.setFocus(Qt.FocusReason.OtherFocusReason)
            return
        if not context.valid():
            return
        owner._feedback(ticket, 'Default-browser opening requested. Paste your copied prompt yourself when ready.')
        # A successful handoff deliberately leaves browser activation alone.
    finally:
        owner._external_handoff_pending = False


def open_native_ai(owner, context, target):
    """Called only after consuming the native menu's scoped activation lease.

    Separate from request(): even a forged Server ai-action event cannot enter
    this path. Validate the closed host mapping again at the handoff boundary.
    """
    from .webview2_native_ai import DESTINATIONS, capture
    if (target not in {item[2] for item in DESTINATIONS}
            or not context.valid() or capture(owner) != context):
        return
    url = QUrl(target)
    if not allowed_external(url):
        return
    ticket = object()
    owner._native_ai_pending_ticket = ticket
    owner._external_handoff_pending = True
    def launch():
        if getattr(owner, '_native_ai_pending_ticket', None) is not ticket:
            return
        try:
            if (not owner._external_handoff_pending
                    or getattr(owner, '_browser_dialog_depth', 0)
                    or getattr(owner, '_browser_operation_depth', 0)
                    or (context.mode == 'server' and not owner._server_page_exposed)
                    or not context.valid()):
                return
            _open(owner, context, url, direct=True)
        finally:
            if getattr(owner, '_native_ai_pending_ticket', None) is ticket:
                owner._native_ai_pending_ticket = None
                owner._external_handoff_pending = False
    QTimer.singleShot(0, launch)

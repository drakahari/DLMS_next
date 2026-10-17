"""Linux OpenURI client: never infer session browser settings from scoped HOME.

No browser subprocess, profile copying, settings changes or xdg-open fallback.
"""
from __future__ import annotations
import uuid
from PySide6.QtCore import QObject, QCoreApplication, QTimer, Signal, Slot, SLOT
from PySide6.QtDBus import (QDBusConnection, QDBusMessage, QDBusObjectPath,
                           QDBusPendingCallWatcher, QDBusServiceWatcher)

SERVICE = 'org.freedesktop.portal.Desktop'
PATH = '/org/freedesktop/portal/desktop'
REQUEST = 'org.freedesktop.portal.Request'
SLOT_RESPONSE = SLOT('response(QDBusMessage)')
_active = set()


class PortalRequest(QObject):
    """One async handoff. Portal acceptance is not proof of page display."""
    finished = Signal(str, str)

    def __init__(self, address, *, connection=None, timeout_ms=120000):
        super().__init__(QCoreApplication.instance())
        self.bus = connection or QDBusConnection.sessionBus()
        self.address = address
        self.token = 'dlms_browser_' + uuid.uuid4().hex
        sender = self.bus.baseService().lstrip(':').replace('.', '_')
        self.expected = f'{PATH}/request/{sender}/{self.token}'
        self.handle = None
        self.portal_owner = None
        self.early = {}
        self.done = False
        self.watchers = set()
        self.owner_watch = None
        self.subscribed = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._timeout)
        self.timer.start(timeout_ms)
        QCoreApplication.instance().aboutToQuit.connect(self.cancel)
        _active.add(self)
        QTimer.singleShot(0, self._start)

    def _call(self, service, path, interface, method, args, callback):
        message = QDBusMessage.createMethodCall(service, path, interface, method)
        message.setArguments(args)
        watcher = QDBusPendingCallWatcher(self.bus.asyncCall(message, 10000), self)
        self.watchers.add(watcher)
        def received(w):
            self.watchers.discard(w)
            reply = w.reply()
            w.deleteLater()
            if not self.done:
                callback(reply)
        watcher.finished.connect(received)

    def _start(self):
        if self.done:
            return
        if not self.bus.isConnected():
            self._finish('unavailable', 'The graphical session bus is unavailable. No browser fallback was used.')
            return
        # Standard property lookup activates the service without synchronous UI
        # waits. Only v1 OpenURI/Request features are required.
        self._call(SERVICE, PATH, 'org.freedesktop.DBus.Properties',
                   'Get', ['org.freedesktop.portal.OpenURI', 'version'], self._activated)

    def _activated(self, reply):
        if reply.type() == QDBusMessage.MessageType.ErrorMessage:
            self._finish('unavailable', 'The session OpenURI portal is unavailable. No browser fallback was used.')
            return
        self._call('org.freedesktop.DBus', '/org/freedesktop/DBus',
                   'org.freedesktop.DBus', 'GetNameOwner', [SERVICE], self._owner)

    def _owner(self, reply):
        args = reply.arguments()
        if (reply.type() == QDBusMessage.MessageType.ErrorMessage or len(args) != 1
                or not isinstance(args[0], str) or not args[0].startswith(':')):
            self._finish('unavailable', 'The session portal owner could not be verified. No browser fallback was used.')
            return
        self.portal_owner = args[0]
        self.owner_watch = QDBusServiceWatcher(SERVICE, self.bus,
            QDBusServiceWatcher.WatchModeFlag.WatchForOwnerChange, self)
        self.owner_watch.serviceOwnerChanged.connect(self._owner_changed)
        # Subscribe before OpenURI. Buffer even legacy early responses, but only
        # the pinned sender and eventual exact returned handle can finish us.
        self.subscribed = self.bus.connect(self.portal_owner, '', REQUEST,
                                           'Response', self, SLOT_RESPONSE)
        if not self.subscribed:
            self._finish('unavailable', 'Could not listen for the session portal response. No browser fallback was used.')
            return
        # Empty parent is supported: never fabricate a Wayland handle from winId.
        # No ask option: do not require another chooser; session policy decides.
        self._call(self.portal_owner, PATH, 'org.freedesktop.portal.OpenURI',
                   'OpenURI', ['', self.address, {'handle_token': self.token}], self._opened)

    def _opened(self, reply):
        args = reply.arguments()
        if reply.type() == QDBusMessage.MessageType.ErrorMessage:
            self._finish('unconfirmed', 'The session portal could not confirm browser handoff. Check your browser before retrying.')
            return
        if len(args) != 1 or not isinstance(args[0], QDBusObjectPath):
            self._finish('unconfirmed', 'The session portal returned an invalid request. Check your browser before retrying.')
            return
        handle = args[0].path()
        prefix = self.expected.rsplit('/', 1)[0] + '/'
        if not handle.startswith(prefix) or '/' in handle[len(prefix):] or not handle[len(prefix):]:
            self._finish('unconfirmed', 'The session portal returned an unexpected request identity. Check your browser before retrying.')
            return
        self.handle = handle
        early = self.early.pop(handle, None)
        self.early.clear()
        if early is not None:
            self._response_code(early)

    @Slot(QDBusMessage)
    def response(self, message):
        if self.done or message.service() != self.portal_owner:
            return
        args = message.arguments()
        if len(args) != 2 or type(args[0]) is not int:
            return
        if self.handle is None:
            if (message.path().startswith(self.expected.rsplit('/', 1)[0] + '/')
                    and len(self.early) < 8):
                self.early[message.path()] = args[0]
        elif message.path() == self.handle:
            self._response_code(args[0])

    def _response_code(self, code):
        if code == 0:
            self._finish('accepted', 'The session portal accepted the browser handoff. Browser/page selection is controlled by your session.')
        elif code == 1:
            self._finish('cancelled', 'Browser opening cancelled by the session portal.')
        else:
            self._finish('unconfirmed', 'The session portal did not confirm browser opening. Check your browser before retrying.')

    def _owner_changed(self, name, old, new):
        if self.portal_owner and new != self.portal_owner:
            self._finish('unconfirmed', 'The session portal disconnected. Check your browser before retrying.')

    def _close_request(self):
        if self.portal_owner and self.subscribed:
            message = QDBusMessage.createMethodCall(self.portal_owner, self.handle or self.expected, REQUEST, 'Close')
            self.bus.asyncCall(message, 1000)

    def _timeout(self):
        self._close_request()
        self._finish('unconfirmed', 'Browser handoff timed out; cancellation was requested. Check your browser before retrying.')

    @Slot()
    def cancel(self):
        if not self.done:
            self._close_request()
            self._finish('cancelled', 'Browser handoff cancelled as DLMS Desktop closed.')

    def _finish(self, outcome, message):
        if self.done:
            return
        self.done = True
        self.timer.stop()
        if self.subscribed:
            self.bus.disconnect(self.portal_owner, '', REQUEST, 'Response', self, SLOT_RESPONSE)
        if self.owner_watch is not None:
            self.owner_watch.setWatchedServices([])
        self.early.clear()
        _active.discard(self)
        self.finished.emit(outcome, message)
        self.deleteLater()


def dispatch(url):
    from .shell import allowed_external
    if not allowed_external(url):
        raise ValueError('External web address is not permitted')
    address = bytes(url.toEncoded()).decode('ascii')
    if len(address) > 8192 or any(ord(c) < 32 for c in address):
        raise ValueError('External address is too long or invalid')
    if QCoreApplication.instance() is None:
        raise OSError('Browser handoff requires the DLMS Desktop event loop')
    if len(_active) >= 8:
        raise OSError('Browser handoffs are still pending. Check your browser before retrying.')
    return PortalRequest(address)

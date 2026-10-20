"""Deliberate Avery printing through the standard printer/PDF dialog."""
from __future__ import annotations

import json
import hashlib
import os
import secrets
import sys
import weakref
from PySide6.QtCore import QObject, QTimer, QMarginsF
from PySide6.QtGui import QPageLayout, QPageSize
from PySide6.QtWebEngineCore import QWebEngineScript
from PySide6.QtPrintSupport import QPrinter, QPrintDialog
from PySide6.QtWidgets import QApplication, QDialog
from shiboken6 import isValid

from . import exports
from .isolation import assert_safe_leaf
from .browser_lifetime import browser_dialog

# Qt borrows the QPrinter pointer until printFinished, even if its page dies.
# Keep jobs independent of the page-owned adapter; never drop them on a timeout.
_JOBS = set()


def avery_layout():
    return QPageLayout(QPageSize(QPageSize.PageSizeId.Letter),
                       QPageLayout.Orientation.Portrait, QMarginsF(0, 0, 0, 0))


def restore_view(owner, view, enabled):
    if (isValid(view) and owner.view is view and not owner._closing
            and owner._retiring_browser is None):
        ready = owner.mode != 'server' or (owner._server_page_exposed and not owner.server_unreachable)
        view.setEnabled(enabled and ready)


class PrinterJob(QObject):
    def __init__(self, controller, printer):
        super().__init__(QApplication.instance())
        self.printer = printer
        self.owner = controller.owner
        self.view = controller.owner.view
        self.controller = weakref.ref(controller)
        self.operation = controller.operation
        controller.native_busy = True
        self.enabled = self.view.isEnabled()
        self.guard = browser_dialog(controller.owner)
        self.guard.__enter__()
        self.view.setEnabled(False)
        self.view.printFinished.connect(self.finished)
        _JOBS.add(self)

    def start(self):
        try:
            self.view.print(self.printer)
        except (RuntimeError, TypeError, ValueError):
            self.finished(False)

    def finished(self, success):
        if self not in _JOBS:
            return
        if isValid(self.view):
            self.view.printFinished.disconnect(self.finished)
            restore_view(self.owner, self.view, self.enabled)
        controller = self.controller()
        if (controller is not None and isValid(controller)
                and controller.operation == self.operation):
            controller.native_busy = False
            controller.message('Print/PDF operation completed. Physical paper output is not confirmed.'
                               if success else 'Print/PDF operation failed or was canceled. Check the selected destination or printer queue.',
                               'success' if success else 'error')
            controller.retire()
        self.guard.__exit__(None, None, None)
        _JOBS.remove(self)
        self.deleteLater()


WORLD = QWebEngineScript.ScriptWorldId.ApplicationWorld
LAYOUT_SCRIPT = "[...document.querySelectorAll('style,link[rel=stylesheet],.avery-sheet')].map(e=>e.outerHTML).join('\\n')"
SCRIPT = r'''(()=>{
 if(self!==top)return;
 let grant=null,repeating=false;
 const button=e=>e instanceof HTMLButtonElement&&e.isConnected&&!e.disabled&&
   (!e.id||e.id==='printCards')&&e.matches('.print-toolbar .print-actions > button[type="button"]')&&
   e.ownerDocument===document&&e.textContent.trim()==='Print Cards'&&
   (e.getAttribute('onclick')||'').replace(/\s/g,'')==='window.print()';
 document.addEventListener('keydown',e=>{if(e.isTrusted&&(e.key==='Enter'||e.key===' '))repeating=e.repeat;},true);
 document.addEventListener('keyup',e=>{if(e.isTrusted)repeating=false;},true);
 document.addEventListener('click',e=>{
  grant=null;
  if(e.isTrusted&&!e.defaultPrevented&&!repeating&&!e.ctrlKey&&!e.altKey&&!e.metaKey&&!e.shiftKey&&
     location.pathname==='/anki/printable'&&!location.search&&!location.hash){
   const el=e.target instanceof Element?e.target.closest('button'):null;
   if(button(el))grant={el,href:location.href,time:performance.now()};
  }
 },true);
 window.addEventListener('pagehide',()=>{grant=null;});
 Object.defineProperty(globalThis,'__dlmsTakeAveryPrint',{value:()=>{
  const g=grant;grant=null;
  return !!(g&&g.href===location.href&&performance.now()-g.time<5000&&button(g.el));
 },writable:false});
})()'''


def allowed(owner, page):
    from .shell import allowed_internal
    from .server_browser import exact_server_origin
    if (owner._closing or owner._retiring_browser is not None or owner.view is None
            or owner.view.page() is not page or page.isLoading()):
        return False
    url = page.url()
    if url.path() != '/anki/printable' or url.hasQuery() or url.hasFragment():
        return False
    if owner.mode == 'local':
        return allowed_internal(url, owner.port)
    if owner.mode == 'server':
        server = owner.mode_config.get('server') or {}
        return (owner._server_page_exposed and not owner.server_unreachable
                and exact_server_origin(url, server.get('origin', '')))
    return False


def install(page, owner):
    controller = AveryPrint(page, owner)
    page.avery_print = controller  # Retain the Python adapter for this owned page.
    return controller


class AveryPrint(QObject):
    def __init__(self, page, owner):
        super().__init__(page)
        self.page, self.owner = page, owner
        self.record = None
        self.captured = None
        self.operation = 0
        self.native_busy = False
        self.deadline = QTimer(self)
        self.deadline.setSingleShot(True)
        self.deadline.timeout.connect(lambda: self.failed('PDF generation timed out. No destination was changed.'))
        script = QWebEngineScript()
        script.setName('dlms-owned-avery-print')
        script.setWorldId(WORLD)
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setRunsOnSubFrames(False)
        script.setSourceCode(SCRIPT)
        page.scripts().insert(script)
        page.printRequested.connect(self.request)
        page.printRequestedByFrame.connect(lambda *_: self.refused('Print Cards is available only from the main Avery layout.'))
        page.loadStarted.connect(self.retire)

    def retire(self):
        if self.record is not None and self.record['state'] in ('authorizing', 'generating'):
            self.record['state'] = 'retired'
            owner = self.owner
            ticket = self.record['feedback_ticket']
            if (not owner._closing and owner._retiring_browser is None
                    and owner.operation_feedback.serial == ticket):
                owner._feedback(ticket, 'PDF operation canceled because the page changed. No destination was changed.', 'warning')
        self.operation += 1
        self.native_busy = False
        self.deadline.stop()
        self.record = None
        self.captured = None

    def valid(self):
        return (isValid(self) and self.captured is not None
                and exports.current(self.owner, self.captured) and allowed(self.owner, self.page))

    def message(self, text, severity='info', *, page=True):
        owner = self.owner
        if (owner._closing or owner._retiring_browser is not None or owner.view is None
                or owner.view.page() is not self.page):
            return
        ticket = self.record['feedback_ticket'] if self.record else owner._begin_feedback('pdf')
        owner._feedback(ticket, text, severity)
        if (page and allowed(owner, self.page) and owner.operation_feedback.serial == ticket):
            # Constant outcome text only; never expose native paths to a server page.
            self.page.runJavaScript('(()=>{const s=document.getElementById("printCardsStatus");'
                                    'if(s)s.textContent=' + json.dumps(text) + ';})()', WORLD)

    def refused(self, text):
        self.message('Print Cards refused: ' + text, 'warning')

    def request(self):
        if self.record is not None:
            self.page.runJavaScript('globalThis.__dlmsTakeAveryPrint?.()', WORLD)
            self.refused('Finish or cancel the current print or PDF operation first.')
            return
        if not allowed(self.owner, self.page):
            self.refused('Use the completed Avery layout in the active Local or configured Server page.')
            return
        self.captured = exports.context(self.owner)
        self.operation += 1
        operation = self.operation
        # Claim before async permission lookup: duplicate signals cannot reuse it.
        self.record = {'state': 'authorizing', 'feedback_ticket': self.owner._begin_feedback('pdf')}
        def authorized(ok):
            if not isValid(self) or operation != self.operation:
                return
            if not self.valid():
                self.retire()
                return
            try:
                details = json.loads(ok) if isinstance(ok, str) else None
            except (ValueError, TypeError):
                details = None
            if (not isinstance(details, dict) or details.get('duplex') not in ('short', 'long')
                    or not isinstance(details.get('layout'), str) or not details['layout']):
                self.failed('Print Cards refused: use this page’s Print Cards button directly.')
                return
            self.record['layout_digest'] = hashlib.sha256(details['layout'].encode()).hexdigest()
            if sys.platform == 'darwin':
                self.record['native_duplex'] = details['duplex']
                self.generate(operation)
            else:
                self.print_dialog(details['duplex'])
        self.page.runJavaScript('(()=>{if(globalThis.__dlmsTakeAveryPrint?.()!==true)return null;'
            'return JSON.stringify({duplex:document.querySelector("input[name=duplex_flip]")?.value==="short"?"short":"long",'
            'layout:'+LAYOUT_SCRIPT+'});})()', WORLD, authorized)

    def print_dialog(self, duplex):
        if not self.valid():
            self.retire()
            return
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.NativeFormat)
        printer.setDocName('DLMS Avery cards')
        printer.setPageLayout(avery_layout())
        printer.setFullPage(True)
        printer.setResolution(600)
        printer.setDuplex(QPrinter.DuplexMode.DuplexShortSide if duplex == 'short'
                          else QPrinter.DuplexMode.DuplexLongSide)
        self.record['state'] = 'dialog'
        self.message('Choose a printer or PDF destination in the print dialog. Confirm only when ready.')
        self.native_busy = True
        try:
            with browser_dialog(self.owner):
                dialog = QPrintDialog(printer, self.owner)
                result = dialog.exec()
            if not self.valid():
                self.native_busy = False
                self.retire()
                return
            if result != QDialog.DialogCode.Accepted:
                self.native_busy = False
                self.message('Print canceled. No job was sent. Your selected cards remain unchanged.')
                self.retire()
                return
            if not printer.isValid():
                self.native_busy = False
                self.failed('The selected printer or PDF destination is unavailable. Printing did not start.')
                return
            operation = self.operation
            def checked(layout):
                if not isValid(self) or operation != self.operation:
                    return
                self.native_busy = False
                if (not self.valid() or not isinstance(layout, str)
                        or hashlib.sha256(layout.encode()).hexdigest() != self.record['layout_digest']):
                    self.failed('The Avery document changed during the print dialog. Printing did not start; reopen the layout and retry.')
                    return
                self.record['state'] = 'printing'
                self.message('Completing the selected print/PDF operation…')
                PrinterJob(self, printer).start()
            self.page.runJavaScript(LAYOUT_SCRIPT, WORLD, checked)
        except (RuntimeError, TypeError, ValueError, OSError):
            self.native_busy = False
            self.failed('The native print dialog could not complete. Printing did not start.')

    def generate(self, operation):
        if not self.valid():
            self.retire()
            return
        owner = self.owner
        try:
            folder = owner.paths['downloads'] if owner.mode == 'local' else owner.server_paths['downloads']
            destination = folder / ('avery-' + secrets.token_hex(12) + '.pdf')
            assert_safe_leaf(destination)
        except (KeyError, OSError, ValueError):
            self.failed('PDF staging is unavailable. No destination was changed.')
            return
        self.record.update(path=str(destination), state='generating')
        owner.pdf_results.append(self.record)
        self.message('Generating Avery PDF…')
        self.deadline.start(30000)
        layout = avery_layout()
        def generated(data):
            if not isValid(self) or operation != self.operation:
                return
            self.deadline.stop()
            if not self.valid():
                self.retire()
                return
            native_started = False
            try:
                content = bytes(data)
                if not content.startswith(b'%PDF-') or not content:
                    raise ValueError('Qt did not produce a PDF')
                fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                with os.fdopen(fd, 'wb') as output:
                    output.write(content)
                    output.flush()
                    os.fsync(output.fileno())
                self.record['state'] = 'staged'
                from .macos_printing import print_avery
                self.message('Choose a printer or Save as PDF in the system print dialog. Avery uses US Letter, 100% scale and the selected flip by default.')
                view = owner.view
                enabled = view.isEnabled()
                self.native_busy = True
                view.setEnabled(False)
                try:
                    with browser_dialog(owner):
                        native_started = True
                        result = print_avery(content, self.record['native_duplex'], self.valid, owner)
                finally:
                    self.native_busy = False
                    restore_view(owner, view, enabled)
                if not self.valid():
                    self.retire()
                    return
                self.record['state'] = result['kind']
                self.message(result['message'], 'warning' if result['kind'] == 'not_completed' else 'info')
                self.retire()
            except (OSError, TypeError, ValueError, RuntimeError):
                self.failed('Print/PDF completion could not be confirmed. Check the selected destination or printer queue.'
                            if native_started else 'PDF could not be prepared. No destination was changed.')
        try:
            self.page.printToPdf(generated, layout)
        except (RuntimeError, TypeError, ValueError):
            self.failed('PDF generation could not start. No destination was changed.')

    def failed(self, text):
        self.deadline.stop()
        if self.record is not None:
            self.record['state'] = 'failed'
        self.message(text, 'error')
        self.retire()

"""Owned Qt Avery PDF output; no browser-to-native filesystem command API."""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
from PySide6.QtCore import QObject, QTimer, QMarginsF
from PySide6.QtGui import QPageLayout, QPageSize
from PySide6.QtWebEngineCore import QWebEngineScript
from shiboken6 import isValid

from . import exports
from .isolation import assert_safe_leaf

WORLD = QWebEngineScript.ScriptWorldId.ApplicationWorld
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
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self.poll)
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
        self.timer.stop()
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
            self.refused('Finish or cancel the current PDF operation first.')
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
            if ok is not True:
                self.failed('Print Cards refused: use this page’s Print Cards button directly.')
                return
            self.generate(operation)
        self.page.runJavaScript('globalThis.__dlmsTakeAveryPrint?.() === true', WORLD, authorized)

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
        layout = QPageLayout(QPageSize(QPageSize.PageSizeId.Letter),
                             QPageLayout.Orientation.Portrait, QMarginsF(0, 0, 0, 0))
        def generated(data):
            if not isValid(self) or operation != self.operation:
                return
            self.deadline.stop()
            if not self.valid():
                self.retire()
                return
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
                exports.begin(owner, self.record, captured=self.captured)
                self.timer.start()
            except (OSError, TypeError, ValueError, RuntimeError):
                self.failed('PDF could not be prepared. No destination was changed.')
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

    def poll(self):
        if not self.valid():
            self.retire()
            return
        state = self.record['state']
        text = {'completed': 'Avery PDF saved to the selected folder. Open it to print at actual size (100%).',
                'cancelled': 'PDF Save As canceled. No destination file was changed. Your selected cards remain unchanged.',
                'failed': 'PDF not saved. Check the native message; no existing destination was replaced.',
                'refused': 'PDF not saved: the print action was refused. Your selected cards remain unchanged.'}.get(state)
        if text:
            # Keep the native queue's complete destination feedback on success.
            if state == 'completed':
                if self.owner.operation_feedback.serial == self.record['feedback_ticket']:
                    self.page.runJavaScript('(()=>{const s=document.getElementById("printCardsStatus");'
                                            'if(s)s.textContent=' + json.dumps(text) + ';})()', WORLD)
                if self.owner.mode == 'local':
                    self.owner.pdf_files.append(Path(self.record['published_path']))
            else:
                self.message(text, 'error' if state in ('failed', 'refused') else 'info')
            self.retire()

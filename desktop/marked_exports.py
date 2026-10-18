"""Download-only consent for the marked-question and attempt-review APKG workflows.

The isolated-world observer exposes no native command or filesystem API. A
private transfer is not permission to publish: native Save As still requires
one trusted top-document action and the unchanged page/dataset context.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
from PySide6.QtCore import QUrl
from PySide6.QtWebEngineCore import QWebEngineScript

WORLD = QWebEngineScript.ScriptWorldId.ApplicationWorld
SCRIPT = r'''(()=>{
 if(self!==top)return;
 let intent=null,download=null;
 const attempt=()=>/^\?attempt=[A-Za-z0-9_-]{1,128}$/.test(location.search)?new URLSearchParams(location.search).get('attempt'):null;
 const workflow=()=>location.pathname==='/marked-questions'?'marked':location.pathname==='/review'&&attempt()?'attempt':null;
 const link=e=>e instanceof HTMLAnchorElement&&e.isConnected&&(workflow()==='marked'
  ?e.matches('#markExportResult a[download="dlms_marked_questions.apkg"]')
  :workflow()==='attempt'&&e.matches('#attemptExportResult a[download]')&&e.dataset.attempt===attempt()&&/^[A-Za-z0-9_-][A-Za-z0-9_.-]{0,255}\.apkg$/.test(e.download));
 const originBlob=url=>url.startsWith('blob:'+location.origin+'/');
 document.addEventListener('click',e=>{
  const kind=workflow();if(!kind)return;
  const el=e.target instanceof Element?e.target.closest('button,a'):null;
  if(e.isTrusted&&el?.id===(kind==='marked'?'exportMarks':'exportAttemptMissed')&&!el.disabled){
   intent={href:location.href,time:performance.now()};download=null;return;
  }
  if(!link(el)||!originBlob(el.href)){if(e.isTrusted){intent=null;download=null;}return;}
  if(e.isTrusted||(intent&&intent.href===location.href&&performance.now()-intent.time<120000)){
   download={url:el.href,name:el.download,href:location.href,time:performance.now()};intent=null;
  }
 },true);
 window.addEventListener('pagehide',()=>{intent=null;download=null;});
 Object.defineProperty(globalThis,'__dlmsTakeMarkedExport',{value:(url,name)=>{
  const d=download;download=null;
  return !!(d&&d.url===url&&d.name===name&&d.href===location.href&&performance.now()-d.time<120000&&
    [...document.querySelectorAll('#markExportResult a,#attemptExportResult a')].some(e=>link(e)&&e.href===url&&e.download===name));
 },writable:false});
})()'''


def install(page):
    script = QWebEngineScript()
    script.setName('dlms-marked-export-consent')
    script.setWorldId(WORLD)
    script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
    script.setRunsOnSubFrames(False)
    script.setSourceCode(SCRIPT)
    page.scripts().insert(script)


def allowed_blob(owner, request):
    """Narrow exception for this workflow; never a navigation permission."""
    from .shell import allowed_internal
    from .server_browser import exact_server_origin
    if (owner.view is None or request.page() is not owner.view.page()
            or owner._closing or owner._retiring_browser is not None):
        return False
    url = request.url()
    if url.scheme() != 'blob':
        return False
    document = request.page().url()
    if document.path() == '/marked-questions':
        if request.downloadFileName() != 'dlms_marked_questions.apkg':
            return False
    elif document.path() == '/review':
        # This exact attempt document only; no duplicate/extra/encoded query.
        if (document.hasFragment() or not re.fullmatch(r'attempt=[A-Za-z0-9_-]{1,128}', document.query(QUrl.ComponentFormattingOption.FullyEncoded))
                or not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_.-]{0,255}\.apkg', request.downloadFileName())):
            return False
    else:
        return False
    # No encoded alternate spelling, credentials, query, fragment or opaque
    # origin. Chromium creates canonical UUID URLs for these object blobs.
    value = bytes(url.toEncoded()).decode('ascii')
    if not re.fullmatch(r'blob:https?://[^/?#]+/[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', value):
        return False
    inner = QUrl(value[5:])
    if owner.mode == 'local':
        return allowed_internal(document, owner.port) and allowed_internal(inner, owner.port)
    if owner.mode == 'server':
        origin = owner.mode_config['server']['origin']
        return exact_server_origin(document, origin) and exact_server_origin(inner, origin)
    return False


def authorize(owner, record, captured, completed):
    """Consume one read-only top-document permission before showing Save As."""
    from .exports import current
    if not current(owner, captured):
        completed(False)
        return
    def checked(ok):
        completed(ok is True and current(owner, captured))
    captured[0].runJavaScript(
        'globalThis.__dlmsTakeMarkedExport?.(' + json.dumps(record['marked_blob_url']) + ',' + json.dumps(Path(record['path']).name) + ') === true',
        WORLD, checked)


def outcome_message(outcome, *, attempt=False):
    """Keep Exam-result reassurance distinct from saved question marks."""
    messages = {
        'completed': 'Anki package saved to the selected folder. Your marks remain saved.',
        'cancelled': 'Anki Save As canceled. No destination file was changed. Your marks remain saved.',
        'refused': 'Anki package not saved. Check the native message before retrying; your marks remain saved.',
        'unconfirmed': 'Anki save outcome is unconfirmed. Inspect the selected folder before retrying; your marks remain saved.',
    }
    message = messages[outcome]
    return re.sub(r'your marks remain saved\.',
                  'Your saved Exam result and history are unchanged.', message,
                  flags=re.IGNORECASE) if attempt else message


def report(owner, record, captured, outcome):
    """Present only a fixed outcome, never native paths or private error text."""
    from .exports import current
    if (not record.get('marked_blob_url') or not current(owner, captured)
            or owner.operation_feedback.serial != record['feedback_ticket']):
        return
    # The token and document checks stop old callbacks replacing a newer
    # export's result. Server content receives no selected filename or path.
    captured[0].runJavaScript('''(()=>{const attempt=location.pathname==='/review';
        const a=document.querySelector(attempt?'#attemptExportResult a':'#markExportResult a');
        if((attempt||location.pathname==='/marked-questions')&&a?.href===''' + json.dumps(record['marked_blob_url']) + '''){
            const s=document.getElementById(attempt?'attemptExportStatus':'markActionStatus');
            if(s)s.textContent=attempt?''' + json.dumps(outcome_message(outcome, attempt=True)) + ''' : ''' + json.dumps(outcome_message(outcome)) + ''';
        }})()''', WORLD)

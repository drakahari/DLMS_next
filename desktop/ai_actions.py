"""One-use, native-input-bound website handoff; no web-to-native command API."""
from __future__ import annotations
import json
import math
import time
from PySide6.QtCore import QObject,QEvent,Qt,QTimer,QUrl
from PySide6.QtWebEngineCore import QWebEngineScript

PROVIDERS=frozenset({'https://chatgpt.com/','https://claude.ai/','https://gemini.google.com/'})
WORLD=QWebEngineScript.ScriptWorldId.ApplicationWorld
# Adapted from reviewed Windows AiScripts.cs40d7063. Only private bookkeeping,
# read by the native host; page MainWorld has no launch function or message API.
SCRIPT=r'''(()=>{
 if(self!==top)return;
 let epoch=0,active=null,repeating=false,seq=0;
 const clean=e=>e.textContent.replace(/\s+/g,' ').trim();
 function eligible(e){
  if(!e||!e.isConnected||e.disabled||e.ownerDocument!==document)return null;
  const p=location.pathname,h=e.getAttribute('onclick')||'',t=clean(e);
  if(e.tagName==='BUTTON'){
   if(/^\/quizzes\/[^/]+\.html$/.test(p)&&e.id==='studyAiBtn'&&h.replace(/\s/g,'')==='reviewCurrentQuestionWithAI()'&&['Review with AI','✨ Review with AI'].includes(t))return h;
   if(p==='/review'||p==='/review.html'){
    if(/^openAIExplain\(\s*\d+\s*,\s*this\s*\)$/.test(h)&&e.closest('.review-question-actions')&&['Explain with AI','Prompt Copied'].includes(t))return h;
    if(h.replace(/\s/g,'')==='explainSelectedWithAI()'&&t==='Explain Selected with AI')return h;
   }
   if((p==='/law/create'||p==='/study-packs/ai-builder')&&t==='Copy Prompt & Open AI'){
    const f=p==='/law/create'?'copyPromptAndOpenAi':'copyAndOpen';
    if(h.startsWith(f+'(')&&h.endsWith(')')&&document.querySelector(p==='/law/create'?'#lawPromptBox':'#studyPrompt')){
     try{if(typeof JSON.parse(h.slice(f.length+1,-1))==='string')return h;}catch(_){}
    }
   }
   if((p==='/certifications/matches'||/^\/certifications\/[0-9a-f]{32}\/ai$/.test(p))&&e.hasAttribute('data-cert-launch')&&t==='Copy & open AI'&&document.querySelector('#certPrompt')&&document.querySelector('#certProviderLink'))return 'cert-launch';
  }
  if(e.tagName==='A'&&(p==='/certifications/matches'||/^\/certifications\/[0-9a-f]{32}\/ai$/.test(p))&&e.id==='certProviderLink'&&t==='Open AI manually'&&e.target==='_blank'&&e.relList.contains('noopener')&&e.relList.contains('noreferrer'))return 'cert-manual';
  return null;
 }
 Object.defineProperty(globalThis,'__dlmsAIInput',{value:n=>{epoch=n;active=null;},writable:false});
 document.addEventListener('keydown',e=>{if(e.isTrusted&&(e.key==='Enter'||e.key===' '))repeating=e.repeat;},true);
 document.addEventListener('keyup',e=>{if(e.isTrusted)repeating=false;},true);
 window.addEventListener('blur',()=>{active=null;});
 document.addEventListener('visibilitychange',()=>{active=null;});
 document.addEventListener('click',e=>{
  active=null;
  if(!e.isTrusted||e.defaultPrevented||!epoch||repeating||e.ctrlKey||e.altKey||e.metaKey||e.shiftKey)return;
  const el=e.target instanceof Element?e.target.closest('button,a'):null,h=eligible(el);
  if(h)active={el,h,epoch,created:performance.now(),used:false,id:++seq,href:location.href,timeOrigin:performance.timeOrigin};
 },true);
 Object.defineProperty(globalThis,'__dlmsAITake',{value:n=>{
  const a=active;if(!a)return {state:'generic'};
  if(a.used||a.epoch!==n||performance.now()-a.created>5000)return {state:'refused'};
  a.used=true;
  if(eligible(a.el)!==a.h||a.href!==location.href)return {state:'refused'};
  return {state:'ai',id:a.id,epoch:a.epoch,href:a.href,timeOrigin:a.timeOrigin};
 },writable:false});
 Object.defineProperty(globalThis,'__dlmsAIValidate',{value:(n,id,origin)=>{
  const a=active;return !!(a&&a.used&&a.epoch===n&&a.id===id&&a.timeOrigin===origin&&a.href===location.href&&eligible(a.el)===a.h&&performance.now()-a.created<=5000);
 },writable:false});
})()'''


def approved(url):
    # Encoded spelling is intentionally canonical; no credentials/query/fragment,
    # lookalikes, alternate ports or paths become direct-opening authority.
    return bytes(url.toEncoded()).decode('ascii') in PROVIDERS


class AIHandoff(QObject):
    def __init__(self,page,owner):
        super().__init__(page);self.page=page;self.owner=owner;self.epoch=0;self.used=0;self.started=0
        script=QWebEngineScript();script.setName('dlms-private-ai-activation');script.setWorldId(WORLD)
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation);script.setRunsOnSubFrames(False);script.setSourceCode(SCRIPT)
        page.scripts().insert(script)
        self.bound=[]
        QTimer.singleShot(0,self.bind)
        page.loadFinished.connect(lambda *_:self.bind())
        page.loadStarted.connect(self.retire)
    def bind(self):
        from PySide6.QtWidgets import QWidget
        view=self.owner.view
        if view is None or self.owner._closing:return
        for widget in (view,*view.findChildren(QWidget)):
            if widget not in self.bound:
                widget.installEventFilter(self);self.bound.append(widget)
    def retire(self):
        self.epoch+=1;self.started=0
        self.page.runJavaScript(f'globalThis.__dlmsAIInput?.({self.epoch})',WORLD)
    def eventFilter(self,obj,event):
        kind=event.type()
        if kind==QEvent.Type.ChildAdded:
            QTimer.singleShot(0,self.bind);return False
        if kind not in (QEvent.Type.MouseButtonPress,QEvent.Type.KeyPress,QEvent.Type.FocusOut,QEvent.Type.Hide):return False
        view=self.owner.view
        # Never call view.page() here: it lazily creates a page while setPage
        # and WebEngine construction can themselves dispatch Qt events.
        if view is None or self.owner._closing or self.owner._retiring_browser is not None:return False
        target=obj
        while target is not None and target is not view:
            target=target.parent() if hasattr(target,'parent') else None
        if target is not view:return False
        if kind in (QEvent.Type.MouseButtonPress,QEvent.Type.KeyPress):
            self.epoch+=1;self.started=time.monotonic()
            self.page.runJavaScript(f'globalThis.__dlmsAIInput?.({self.epoch})',WORLD)
        elif kind in (QEvent.Type.FocusOut,QEvent.Type.Hide):self.retire()
        return False
    def handle(self,url,user_initiated,*,generic):
        owner=self.owner;page=self.page;epoch=self.epoch
        context=(owner.view,owner.mode,owner._browser_generation,bytes(page.url().toEncoded()),dict(owner.manifest or {}),
                 (owner.mode_config.get('server') or {}).copy())
        def valid():
            from .shell import allowed_internal
            from .server_browser import exact_server_origin
            intended=(allowed_internal(page.url(),owner.port) if owner.mode=='local' else
                      exact_server_origin(page.url(),(owner.mode_config.get('server') or {}).get('origin','')))
            return (intended and not owner._closing and owner._retiring_browser is None and owner.view is context[0]
                and owner.view is not None and owner.view.page() is page and owner.mode==context[1]
                and owner._browser_generation==context[2] and bytes(page.url().toEncoded())==context[3]
                and (owner.manifest or {})==context[4] and (owner.mode_config.get('server') or {})==context[5]
                and self.epoch==epoch)
        if (not user_initiated or not valid() or epoch==self.used or time.monotonic()-self.started>5):
            owner.note_blocked(url);return
        if not approved(url):
            # Generic links retain their existing native confirmation, never a
            # bypass based just on the provider's hostname or native flag.
            generic();return
        # Claim native epoch BEFORE async JS. Stale/new inputs cannot transfer it.
        self.used=epoch
        def taken(value):
            if not valid():return
            try:value=json.loads(value) if isinstance(value,str) else None
            except (ValueError,TypeError):return
            if not isinstance(value,dict) or value.get('state')!='ai':
                if isinstance(value,dict) and value.get('state')=='generic':generic()
                else:owner.note_blocked(url)
                return
            if value.get('epoch')!=epoch or value.get('href')!=page.url().toString():return
            ident=value.get('id');origin=value.get('timeOrigin')
            if type(ident) is not int or ident<=0 or type(origin) not in (int,float) or not math.isfinite(origin) or origin<=0:return
            def verified(ok):
                if ok is True and valid() and self.used==epoch:
                    # Native URL already validated; no prompt data appended.
                    from .shell import handoff_external
                    handoff_external(owner,url,ai=True)
            page.runJavaScript('globalThis.__dlmsAIValidate?.('+json.dumps(epoch)+','+json.dumps(ident)+','+json.dumps(origin)+')',WORLD,verified)
        page.runJavaScript(f'JSON.stringify(globalThis.__dlmsAITake?.({epoch}))',WORLD,taken)

"""Opt-in counts/timing only, top Server composer; no requests or native bridge."""
from __future__ import annotations
import json,math,os,re,secrets,time
from pathlib import Path
from PySide6.QtCore import QObject,QTimer,Signal
from PySide6.QtWebEngineCore import QWebEngineScript
from .isolation import assert_safe_leaf
from .server_browser import exact_server_origin

INSTALL=r"""(() => {
 if(location.href!==EXPECTED_URL||performance.timeOrigin!==EXPECTED_ORIGIN)return false;
 if(location.pathname!=='/quiz-composer'||!document.getElementById('mixedQuizForm')||!document.getElementById('questionList'))return false;
 const key='__dlmsMixTimingCountsV1';if(window[key])window[key].stop();
 const token=CAPTURE_TOKEN;const start=performance.now(),events=[],frames=new Set(),tasks=new Set();let dropped=0,active=true;
 const frame=fn=>{const id=requestAnimationFrame(()=>{frames.delete(id);if(active)fn()});frames.add(id)};
 const counts=()=>{
  const boxes=[...document.querySelectorAll('input[name="question_ids"]')],cards=[...document.querySelectorAll('.mixed-builder-question')];
  const shown=cards.filter(n=>!n.hidden).length,checked=boxes.filter(n=>n.checked),text=document.getElementById('selectedCount')?.textContent||'';
  const match=text.match(/^(\d{1,9}) selected$/);
  return {total:boxes.length,shown,checked:checked.length,hiddenChecked:checked.filter(n=>n.closest('.mixed-builder-question')?.hidden).length,displayed:match?Number(match[1]):null};
 };
 const record=(phase,control,type,trusted,at)=>{
  if(!active)return;if(events.length===64){dropped++;state.stop();return}
  events.push({phase,control,type,trusted,at:at-start,received:performance.now()-start,counts:counts()});
 };
 const handler=e=>{
  if(performance.now()-start>60000){state.stop();return}
  const id=e.target?.id;let control=['folderFilter','sourceFilter','clearSelection','selectVisible','questionSearch'].includes(id)?id:e.target?.name==='question_ids'?'questionToggle':null;
  if(!control)return;const at=performance.now();record('capture',control,e.type,e.isTrusted,at);
  const task=setTimeout(()=>{tasks.delete(task);if(!active)return;record('deferred-after-event',control,e.type,e.isTrusted,at);
   frame(()=>frame(()=>record('frame-opportunity',control,e.type,e.isTrusted,at)));
  },0);tasks.add(task);
 };
 const state=window[key]={token,timeOrigin:performance.timeOrigin,stop(){active=false;for(const type of ['input','change','click'])document.removeEventListener(type,handler,true);clearTimeout(timer);for(const id of frames)cancelAnimationFrame(id);frames.clear();for(const id of tasks)clearTimeout(id);tasks.clear()},read(){return {timeOrigin:performance.timeOrigin,version:1,elapsed:performance.now()-start,counts:counts(),events:events.splice(0),dropped,active}}};
 for(const type of ['input','change','click'])document.addEventListener(type,handler,{capture:true,passive:true});
 const timer=setTimeout(()=>state.stop(),60000);return JSON.stringify({installed:true,timeOrigin:performance.timeOrigin});
})()"""
READ="JSON.stringify(window.__dlmsMixTimingCountsV1?.token===CAPTURE_TOKEN && performance.timeOrigin===EXPECTED_ORIGIN ? window.__dlmsMixTimingCountsV1.read() : null)"
CLEANUP="if(window.__dlmsMixTimingCountsV1?.token===CAPTURE_TOKEN && performance.timeOrigin===EXPECTED_ORIGIN){window.__dlmsMixTimingCountsV1.stop(); delete window.__dlmsMixTimingCountsV1;}"
CONTROLS={'folderFilter','sourceFilter','clearSelection','selectVisible','questionSearch','questionToggle'}

def sanitized(value):
    """Do not persist arbitrary page fields, strings, content, IDs or URLs."""
    if not isinstance(value,dict) or value.get('version')!=1:raise ValueError('Unsupported counts snapshot')
    def number(x):
        if isinstance(x,bool) or not isinstance(x,(float,int)) or not math.isfinite(x) or not 0<=x<=1e9:raise ValueError('Invalid diagnostic number')
        return x
    def counts(x):
        if not isinstance(x,dict):raise ValueError('Invalid counts')
        return {key:(None if x.get(key) is None and key=='displayed' else number(x.get(key))) for key in ['total','shown','checked','hiddenChecked','displayed']}
    events=value.get('events')
    if not isinstance(events,list) or len(events)>64:raise ValueError('Unbounded event snapshot')
    rows=[]
    for event in events:
        if (not isinstance(event,dict) or event.get('phase') not in {'capture','deferred-after-event','frame-opportunity'} or event.get('control') not in CONTROLS or event.get('type') not in {'input','change','click'} or type(event.get('trusted')) is not bool):raise ValueError('Invalid diagnostic event')
        rows.append({key:event[key] for key in ['phase','control','type','trusted']}|{'at':number(event.get('at')),'received':number(event.get('received')),'counts':counts(event.get('counts'))})
    return {'version':1,'elapsed':number(value.get('elapsed')),'counts':counts(value.get('counts')),'events':rows,'dropped':number(value.get('dropped')),'active':value.get('active') is True}

class MixDiagnostics(QObject):
    finished=Signal(str,str)
    def __init__(self,window):
        super().__init__(window);self.window=window;self.page=window.view.page();self.serial=window._server_navigation_serial;self.generation=window._browser_generation;self.origin=window.mode_config['server']['origin'];self.url=self.page.url().toString();self.document=window._server_document_identity
        if self.document is None or self.document[0]!=self.url:raise ValueError('Current document identity unavailable')
        self.token=secrets.token_hex(16)
        self.started=time.monotonic();self.pending=True;self.ready=False;self.stopped=False;self.bytes=0
        root=window.owner_root/'mix-diagnostics'
        if root.is_symlink():raise ValueError('Diagnostic directory is unsafe')
        root.mkdir(mode=0o700,exist_ok=True)
        self.path=root/f'counts-{secrets.token_hex(8)}.jsonl';assert_safe_leaf(self.path)
        if os.name == 'nt':
            from .windows_files import owned,pinned_parents
            with pinned_parents(self.path):
                owned(root,private=True)
                fd=os.open(self.path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_BINARY,0o600)
                try:
                    # An inherit-only grant can be inactive on the directory
                    # but public on its new child. Validate before writing.
                    owned(self.path,private=True)
                    os.set_inheritable(fd,False)
                except BaseException:os.close(fd);raise
        else:
            if root.stat().st_uid!=os.getuid() or root.stat().st_mode&0o077:raise ValueError('Diagnostic directory is not private')
            directory=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            try:
                info=os.fstat(directory)
                if info.st_uid!=os.getuid() or info.st_mode&0o077:raise ValueError('Unsafe diagnostic directory')
                fd=os.open(self.path.name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=directory);os.set_inheritable(fd,False)
            finally:os.close(directory)
        self.resource={'fd':fd};resource=self.resource
        self.destroyed.connect(lambda _: os.close(resource.pop('fd')) if 'fd' in resource else None)
        self.timer=QTimer(self);self.timer.setInterval(500);self.timer.timeout.connect(self.poll);self.timer.start()
        self.page.runJavaScript(self.script(INSTALL),QWebEngineScript.ScriptWorldId.ApplicationWorld,self.installed)
    def script(self,text):
        values={'EXPECTED_URL':self.url,'EXPECTED_ORIGIN':self.document[1],'CAPTURE_TOKEN':self.token}
        return re.sub(r'EXPECTED_URL|EXPECTED_ORIGIN|CAPTURE_TOKEN',lambda match:json.dumps(values[match.group()]),text)
    def valid(self):
        w=self.window
        return (not w._closing and w._retiring_browser is None and w.mode=='server' and w.view is not None and w.view.page() is self.page and w._browser_generation==self.generation and w._server_navigation_serial==self.serial and w._server_page_exposed and w._server_document_identity==self.document and w.mode_config['server']['origin']==self.origin and exact_server_origin(self.page.url(),self.origin) and self.page.url().toString()==self.url and self.page.url().path()=='/quiz-composer')
    def installed(self,ok):
        if self.stopped:return
        if time.monotonic()-self.started>=60:self.stop('60-second counts capture complete');return
        try:value=json.loads(ok) if isinstance(ok,str) else None
        except (TypeError,ValueError):value=None
        if (not self.valid() or not isinstance(value,dict) or value.get('installed') is not True
                or value.get('timeOrigin')!=self.document[1]):self.stop('Capture refused: not the current supported Server Mix page');return
        self.pending=False;self.ready=True;self.poll()
    def poll(self):
        if self.stopped:return
        if not self.valid():self.stop('Capture stopped after navigation, switching or close');return
        if time.monotonic()-self.started>=60:self.stop('60-second counts capture complete');return
        if self.pending or not self.ready:return
        self.pending=True;issued=time.monotonic()
        def received(raw):
            if self.stopped:return
            if time.monotonic()-self.started>=60:self.stop('60-second counts capture complete');return
            self.pending=False
            if not self.valid():self.stop('Capture stopped after context changed');return
            try:
                snapshot=json.loads(raw)
                if not isinstance(snapshot,dict) or snapshot.get('timeOrigin')!=self.document[1]:raise ValueError('Stale document snapshot')
                value=sanitized(snapshot);value['native_query_roundtrip_ms']=1000*(time.monotonic()-issued)
                data=(json.dumps(value,separators=(',',':'))+'\n').encode();self.bytes+=len(data)
                if self.bytes>512000:raise ValueError('Diagnostic size limit reached')
                offset=0
                while offset<len(data):
                    written=os.write(self.resource['fd'],data[offset:])
                    if written<=0:raise OSError('Short diagnostic write')
                    offset+=written
                if value['dropped']>0:self.stop('Capture event limit reached; retained counts may be incomplete')
                elif not value['active']:self.stop('Browser capture completed')
            except (OSError,ValueError,TypeError,KeyError) as exc:self.stop(f'Capture stopped safely: {type(exc).__name__}')
        self.page.runJavaScript(self.script(READ),QWebEngineScript.ScriptWorldId.ApplicationWorld,received)
    def stop(self,reason):
        if self.stopped:return
        self.stopped=True;self.timer.stop()
        from shiboken6 import isValid
        if isValid(self.page):self.page.runJavaScript(self.script(CLEANUP),QWebEngineScript.ScriptWorldId.ApplicationWorld)
        fd=self.resource.pop('fd',None)
        if fd is not None:os.close(fd)
        self.finished.emit(str(self.path),reason)

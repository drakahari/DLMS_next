"""Opt-in bounded lifecycle evidence; no page content, URLs or native bridge."""
import json
import math
import os
import secrets
import time
import weakref
from datetime import datetime,timezone

from PySide6.QtCore import QObject,QEvent,QTimer
from PySide6.QtWebEngineCore import QWebEngineScript
from PySide6.QtWidgets import QWidget
from .content_layers import LAYER_PROBE,valid_layers
from .isolation import assert_safe_leaf
from .platform_files import owned

PROBE="""(() => {const style=node=>{if(!node)return null;const s=getComputedStyle(node);return {
display:['none','block','inline','inline-block','flex','grid','contents'].includes(s.display)?s.display:'other',
visibility:['visible','hidden','collapse'].includes(s.visibility)?s.visibility:'other',opacity:Math.round(Number(s.opacity)*100)}};
return JSON.stringify({epoch:performance.timeOrigin,ready:document.readyState,visibility:document.visibilityState,
navigation:performance.getEntriesByType('navigation')[0]?.type||'unknown',
presentation:{root:style(document.documentElement),body:style(document.body)},layers:LAYER_PROBE})})()""".replace('LAYER_PROBE',LAYER_PROBE)
CAPTURE_SECONDS=1800
LIMIT=8*1024*1024
RECORD_LIMIT=8000
FOOTER_RESERVE=512

def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')

def document_sample(value):
    """Accept only numeric document identity and fixed lifecycle enums."""
    value=json.loads(value) if isinstance(value,str) else None
    fields={'epoch','ready','visibility','navigation'}
    if not isinstance(value,dict) or set(value) not in (fields,fields|{'presentation'},fields|{'presentation','layers'}):return None
    epoch=value['epoch']
    if isinstance(epoch,bool) or not isinstance(epoch,(int,float)) or not math.isfinite(epoch) or not 0<epoch<1e15:return None
    if value['ready'] not in ('loading','interactive','complete'):return None
    if value['visibility'] not in ('hidden','visible','prerender'):return None
    if value['navigation'] not in ('navigate','reload','back_forward','unknown'):return None
    if 'presentation' in value:
        presentation=value['presentation']
        if not isinstance(presentation,dict) or set(presentation)!={'root','body'}:return None
        for style in presentation.values():
            if style is None:continue
            if not isinstance(style,dict) or set(style)!={'display','visibility','opacity'}:return None
            if style['display'] not in ('none','block','inline','inline-block','flex','grid','contents','other'):return None
            if style['visibility'] not in ('visible','hidden','collapse','other'):return None
            if type(style['opacity']) is not int or not 0<=style['opacity']<=100:return None
    if 'layers' in value and not valid_layers(value['layers']):return None
    return value

class WindowEvents(QObject):
    def __init__(self,window):
        super().__init__(window)
        self.window=weakref.ref(window);self.view=None;self.page=None;self.serial=0
        self.started=time.monotonic();self.bytes=0;self.records=0;self.stopped=False
        self.epoch=None;self.document=0;self.pending=None;self.paints=0;self.backend=None
        self.native=None;self.last_sample=self.started
        self.content_children=[];self.child_paints=0;self.child_updates=0
        self.pointer_counts={'enter':0,'leave':0,'move':0}
        directory=window.owner_root/'window-events'
        assert_safe_leaf(directory/'probe')
        if directory.is_symlink():raise ValueError('Window evidence directory is a link')
        directory.mkdir(mode=0o700,exist_ok=True)
        if not owned(directory,private=True):raise ValueError('Window evidence directory is not private')
        self.path=directory/('events-'+secrets.token_hex(8)+'.jsonl')
        flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_BINARY',0)
        fd=os.open(self.path,flags,0o600);os.set_inheritable(fd,False)
        self.resource={'fd':fd};resource=self.resource
        self.destroyed.connect(lambda *_:os.close(resource.pop('fd')) if 'fd' in resource else None)
        self.timer=QTimer(self);self.timer.setInterval(1000);self.timer.timeout.connect(self.sample)
        window.installEventFilter(self)
        self.emit('capture-start',seconds=CAPTURE_SECONDS,byte_limit=LIMIT,record_limit=RECORD_LIMIT)
        self.timer.start()
        self.bind_native()

    def emit(self,event,**fields):
        if self.stopped:return
        if time.monotonic()-self.started>=CAPTURE_SECONDS:self.stop('duration');return
        record={'ms':round((time.monotonic()-self.started)*1000),'utc':utc_now(),'event':event,**fields}
        raw=(json.dumps(record,separators=(',',':'))+'\n').encode('utf-8')
        if self.bytes+len(raw)>LIMIT-FOOTER_RESERVE or self.records>=RECORD_LIMIT-1:self.stop('limit');return
        try:
            if os.write(self.resource['fd'],raw)!=len(raw):raise OSError('Short diagnostic write')
            self.bytes+=len(raw);self.records+=1
        except OSError:self.stop('io-error')

    def bind(self,view):
        if self.stopped:return
        self.serial+=1;serial=self.serial;self.view=weakref.ref(view);self.page=weakref.ref(view.page())
        self.epoch=None;self.pending=None
        self.detach_content_children()
        view.installEventFilter(self)
        page=view.page()
        def event(name,**values):
            if serial==self.serial and not self.stopped:self.emit(name,**values)
        page.loadStarted.connect(lambda:event('load-start'))
        page.loadFinished.connect(lambda ok:event('load-finish',ok=ok))
        page.urlChanged.connect(lambda _:event('url-change'))
        page.renderProcessPidChanged.connect(lambda pid:event('renderer-pid',pid=int(pid)))
        page.renderProcessTerminated.connect(lambda status,code:event('renderer-terminated',status=int(status.value),code=code))
        page.loadingChanged.connect(lambda info:event('loading',status=int(info.status().value),error=info.errorCode(),domain=int(info.errorDomain().value)))
        self.emit('view-bound',generation=serial)

    def detach_content_children(self,keep=()):
        for ref in self.content_children:
            child=ref()
            if child is not None and not any(child is current for current in keep):
                try:child.removeEventFilter(self)
                except RuntimeError:pass
        self.content_children=[ref for ref in self.content_children if any(ref() is child for child in keep)]

    def bind_native(self):
        window=self.window()
        native=window.windowHandle() if window is not None else None
        if native is None or native is self.native:return
        self.native=native;native.installEventFilter(self)
        native.visibilityChanged.connect(lambda state:self.emit('native-visibility',state=int(state.value)))
        native.screenChanged.connect(lambda _:self.emit('screen-change'))
        self.emit('native-window-bound')

    def eventFilter(self,obj,event):
        if not self.stopped:
            kind=event.type()
            content_child=any(ref() is obj for ref in self.content_children)
            if content_child:
                if kind==QEvent.Type.Paint:self.child_paints+=1
                elif kind==QEvent.Type.UpdateRequest:self.child_updates+=1
            if content_child or (self.view is not None and self.view() is obj):
                key={QEvent.Type.Enter:'enter',QEvent.Type.Leave:'leave',QEvent.Type.MouseMove:'move'}.get(kind)
                if key:self.pointer_counts[key]+=1
            if kind in (QEvent.Type.Paint,QEvent.Type.UpdateRequest):self.paints+=1
            elif kind in (QEvent.Type.Show,QEvent.Type.Hide,QEvent.Type.Resize,QEvent.Type.WindowStateChange,
                          QEvent.Type.WindowActivate,QEvent.Type.WindowDeactivate,QEvent.Type.WinIdChange):
                self.emit('widget-event',kind=int(kind),window=obj is self.window(),native=obj is self.native,content_child=content_child)
                if obj is self.window() and kind in (QEvent.Type.Show,QEvent.Type.WinIdChange):self.bind_native()
            elif kind==QEvent.Type.Expose and obj is self.native:
                self.emit('native-expose',exposed=obj.isExposed())
            elif kind==QEvent.Type.PlatformSurface:
                self.emit('native-surface',kind=int(event.surfaceEventType().value) if hasattr(event,'surfaceEventType') else -1)
        return False

    def sample(self):
        if self.stopped:return
        window=self.window()
        if window is None or window._closing:self.stop('closing');return
        now=time.monotonic()
        if now-self.started>=CAPTURE_SECONDS:self.stop('duration');return
        gap=round((now-self.last_sample)*1000);self.last_sample=now
        backend=window.backend
        state=(backend.pid,backend.poll()) if backend is not None else (None,None)
        if state!=self.backend:
            self.backend=state;self.emit('backend',pid=state[0],exit=state[1])
        view=self.view() if self.view else None;page=self.page() if self.page else None
        if view is None or page is None or window.view is not view:return
        try:
            children=view.findChildren(QWidget)
            states=[]
            self.detach_content_children(children[:8])
            previous=self.content_children
            self.content_children=[weakref.ref(child) for child in children[:8]]
            for child in children[:8]:
                if not any(ref() is child for ref in previous):child.installEventFilter(self)
                states.append({'visible':child.isVisible(),'width':child.width(),'height':child.height(),
                               'updates_enabled':child.updatesEnabled()})
            self.emit('sample',renderer=int(page.renderProcessPid()),loading=page.isLoading(),
                      view_visible=view.isVisible(),window_visible=window.isVisible(),paints=self.paints,
                      gap_ms=gap,active=window.isActiveWindow(),width=view.width(),height=view.height(),
                      dpr=view.devicePixelRatioF(),exposed=self.native.isExposed() if self.native is not None else None,
                      lifecycle=int(page.lifecycleState().value),
                      settings=window.settings_panel is not None and window.settings_panel.isVisible(),
                      content_children=states,children_truncated=len(children)>8,
                      child_paints=self.child_paints,child_updates=self.child_updates,pointer=dict(self.pointer_counts))
            self.paints=0
            self.child_paints=0;self.child_updates=0
            self.pointer_counts={'enter':0,'leave':0,'move':0}
            if self.pending is not None:
                if time.monotonic()-self.pending>3:self.emit('document-probe-delayed')
                return
            self.pending=time.monotonic();serial=self.serial
            def received(raw):
                if self.stopped or serial!=self.serial:return
                latency=round((time.monotonic()-self.pending)*1000)
                self.pending=None
                try:value=document_sample(raw)
                except (ValueError,TypeError):value=None
                if value is None:self.emit('document-probe-unavailable');return
                if value['epoch']!=self.epoch:
                    self.document+=1;self.epoch=value['epoch']
                    self.emit('document',number=self.document,navigation=value['navigation'])
                self.emit('document-state',ready=value['ready'],visibility=value['visibility'],probe_ms=latency,
                          presentation=value.get('presentation'),layers=value.get('layers'))
            page.runJavaScript(PROBE,QWebEngineScript.ScriptWorldId.ApplicationWorld,received)
        except RuntimeError:self.emit('view-retiring')

    def stop(self,reason='stopped'):
        if self.stopped:return
        # Bound logging failure must never reload a page or interrupt saves.
        self.stopped=True;self.timer.stop();self.detach_content_children()
        fd=self.resource.pop('fd',None)
        if fd is not None:
            try:
                footer={'ms':round((time.monotonic()-self.started)*1000),'utc':utc_now(),'event':'capture-stop',
                        'reason':reason if reason in ('duration','limit','closing','stopped','io-error') else 'stopped',
                        'sample_gap_ms':round((time.monotonic()-self.last_sample)*1000),
                        'records_before_stop':self.records,'bytes_before_stop':self.bytes}
                raw=(json.dumps(footer,separators=(',',':'))+'\n').encode('utf-8')
                if self.bytes+len(raw)<=LIMIT and self.records<RECORD_LIMIT:os.write(fd,raw)
            except OSError:pass
            finally:
                try:os.close(fd)
                except OSError:pass

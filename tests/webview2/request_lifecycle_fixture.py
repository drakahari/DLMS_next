"""Unprivileged synthetic Server scripts, shared by source and normal-package tests."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import threading
import time
from urllib.parse import urlsplit,parse_qs

CASES=('settled','navigate','abort','abort-navigate','same-url')

class Fixture(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,case,count=16,body_bytes=1024*1024,delay_ms=5,wait_held=False):
        if case not in CASES:raise ValueError('Closed fixture case')
        self.case,self.count,self.body_bytes,self.delay_ms=case,count,body_bytes,delay_ms
        self.armed=threading.Event();self.records=[];self.lock=threading.Lock();self.started=False
        self.wait_held=wait_held;self.held=threading.Event()
        super().__init__(('127.0.0.2',0),Handler)
    def record(self,kind,**fields):
        with self.lock:self.records.append({'at':time.monotonic(),'kind':kind,**fields})
    def snapshot(self):
        with self.lock:return list(self.records)

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*_):pass
    def reply(self,body,media='text/html; charset=utf-8'):
        body=body.encode() if isinstance(body,str) else body
        self.send_response(200);self.send_header('Content-Type',media);self.send_header('Cache-Control','no-store')
        self.send_header('Content-Length',str(len(body)));self.end_headers()
        try:self.wfile.write(body)
        except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
    def observed(self):
        path=urlsplit(self.path).path
        self.server.record('request',method=self.command,path=path,
            local_token=bool(self.headers.get('X-DLMS-Desktop-Token')),
            ai_tag=bool(self.headers.get('X-DLMS-AI-Document')))
        return path
    def do_GET(self):
        path=self.observed();f=self.server
        if path=='/gate':
            f.armed.wait(20);self.reply(json.dumps({'start':f.armed.is_set()}),'application/json');return
        if path=='/held':
            f.held.wait(10);self.reply(b'{}','application/json');return
        if path=='/finish' or (path=='/' and f.started):
            self.reply('<html><body id="finished">Synthetic terminal page<script>fetch("/mark",{method:"POST",body:"finished"})</script></body></html>');return
        if path=='/':
            config=json.dumps({'case':f.case,'count':f.count,'bytes':f.body_bytes,'delay':f.delay_ms,'held':f.wait_held})
            self.reply('''<!doctype html><html><body><h1>Synthetic request lifecycle</h1><input id="typing"><script>
            (async()=>{const c='''+config+''';
            await new Promise(r=>addEventListener('load',r,{once:true}));
            await fetch('/mark',{method:'POST',body:'ready'});
            const gate=await fetch('/gate').then(r=>r.json());if(!gate.start)return;
            await fetch('/mark',{method:'POST',body:'started'});
            const control=new AbortController(),body='x'.repeat(c.bytes),requests=[];
            for(let n=0;n<c.count;n++)requests.push(fetch('/work?n='+n,{method:'POST',body,signal:control.signal}).catch(()=>null));
            if(c.held)await fetch('/held');
            if(c.case==='settled'){await Promise.allSettled(requests);location.href='/finish';}
            else if(c.case==='abort'){setTimeout(()=>control.abort(),c.delay);await Promise.allSettled(requests);await fetch('/mark',{method:'POST',body:'aborted'});location.href='/finish';}
            else if(c.case==='abort-navigate'){setTimeout(()=>{control.abort();location.href='/finish';},c.delay);}
            else setTimeout(()=>location.href=c.case==='same-url'?'/':'/finish',c.delay);
            })().catch(()=>fetch('/mark',{method:'POST',body:'script-error'}));
            </script></body></html>''');return
        self.send_error(404)
    def do_POST(self):
        path=self.observed();size=int(self.headers.get('Content-Length','0'))
        if size>2*1024*1024:self.send_error(413);return
        try:body=self.rfile.read(size)
        except (ConnectionError,OSError):return
        if path=='/mark':
            mark=body.decode('ascii',errors='ignore')
            if mark not in ('ready','started','finished','aborted','script-error'):self.send_error(400);return
            if mark=='started':self.server.started=True
            self.server.record('mark',value=mark);self.reply(b'{}','application/json');return
        if path=='/work':
            self.server.record('work-body',bytes=len(body),complete=len(body)==size)
            time.sleep(.05);self.reply(b'{}','application/json');return
        self.send_error(404)

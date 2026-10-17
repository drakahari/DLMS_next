"""Captured application with a bounded synthetic library and diagnostic tail asset."""
import hashlib,json,os,sys,time
from pathlib import Path
project = Path(__file__).resolve().parents[2]
server_source = Path(os.environ['DLMS_PERF_SOURCE']).resolve() if os.environ.get('DLMS_PERF_SOURCE') else project
if os.environ.get('DLMS_PERF_SOURCE') and not server_source.is_relative_to(project/'.gate1'):
    raise ValueError('Released Server tests require a project-local reference snapshot')
sys.path.insert(0,str(server_source))
os.environ['DLMS_NO_BROWSER']='1'
import app as dlms
from flask import request,Response
from werkzeug.serving import make_server

log=Path(os.environ['DLMS_PERF_LOG'])
def record(event):
    with log.open('a') as f:f.write(json.dumps(event)+'\n')
count=int(os.environ.get("DLMS_PERF_QUIZZES","40"))
questions=int(os.environ.get("DLMS_PERF_QUESTIONS","1"))
for i in range(count):
    dlms._publish_quiz(f'Synthetic Library {i+1:02d}',[({'number':n+1,'type':'matching','question':f'Neutral matching bank {i+1}?','pairs':[{'left':'Alpha','right':'First'},{'left':'Beta','right':'Second'}],'explanation':'Synthetic matching preview.'} if os.environ.get('DLMS_PERF_MATCHING') and n==1 else {'number':n+1,'type':'choice','question':f'Neutral synthetic bank {i+1} question {n+1}?','choices':[{'label':'A','text':'Alpha','is_correct':True},{'label':'C','text':'Gamma','is_correct':False}],'correct':['A'],'explanation':'Synthetic benchmark material.'}) for n in range(questions)],filename_prefix=f'perf_{i}',exam_minutes=5)
registry=dlms.load_registry()
for i,entry in enumerate(registry):entry['folder']=f'Synthetic Folder {i%4+1}'
dlms.save_registry(registry)
cfg=dlms.load_portal_config();cfg['theme']='ethereal';dlms._write_settings_portal_config(cfg)
@dlms.app.before_request
def before():
    request.perf_start=time.monotonic();record({'phase':'request','path':request.full_path,'at':request.perf_start,'local_token_present':bool(request.headers.get('X-DLMS-Desktop-Token'))})
@dlms.app.after_request
def after(response):
    if os.environ.get('DLMS_PERF_VARIANT')=='old-css' and request.path=='/static/style.css':
        response.direct_passthrough=False
        body=response.get_data();old=b'gap:16px;padding:18px;contain:style;}'
        assert body.count(old)==1
        response.set_data(body.replace(old,b'gap:16px;padding:18px;}'))
    if os.environ.get('DLMS_PERF_VARIANT')=='style' and request.path=='/quiz-composer':
        body=response.get_data(as_text=True)
        response.set_data(body.replace('</head>','<style>.mixed-builder-question{contain:style;}</style></head>'))
    if os.environ.get('DLMS_PERF_VARIANT')=='contain' and request.path=='/quiz-composer':
        body=response.get_data(as_text=True)
        response.set_data(body.replace('</head>','<style>.mixed-builder-question{contain:layout style;}</style></head>'))
    if os.environ.get('DLMS_PERF_VARIANT')=='flex' and request.path=='/quiz-composer':
        body=response.get_data(as_text=True)
        response.set_data(body.replace('</head>','<style>.mixed-builder-question-list{display:flex;flex-direction:column;}</style></head>'))
    if os.environ.get('DLMS_PERF_VARIANT') in {'hidden','checked','conditional'} and request.path=='/quiz-composer':
        body=response.get_data(as_text=True)
        old='card.hidden = !visible;'
        assert body.count(old)==1
        if os.environ['DLMS_PERF_VARIANT'] in {'hidden','conditional'}:body=body.replace(old,'if (card.hidden !== !visible) card.hidden = !visible;')
        old='checkboxes.forEach(box => { box.checked = false; });'
        assert body.count(old)==1
        if os.environ['DLMS_PERF_VARIANT'] in {'checked','conditional'}:body=body.replace(old,'checkboxes.forEach(box => { if (box.checked) box.checked = false; });')
        response.set_data(body)
    if os.environ.get('DLMS_PERF_NORMAL_RESULTS') and request.path in ['/', '/library', '/quiz-composer']:
        # Synthetic server scripts drive their own DOM; no native hooks/privileges.
        script='''<script>
window.addEventListener('load',async()=>{
 const path=location.pathname,round=Number(new URLSearchParams(location.search).get('round')||0);
 const nav=performance.getEntriesByType('navigation')[0].toJSON();
 let filters=[];
 if(path==='/quiz-composer'){
  const select=document.getElementById('folderFilter');
  for(const folder of ['synthetic folder 1','','synthetic folder 1']){
   const begin=performance.now();select.value=folder;select.dispatchEvent(new Event('input',{bubbles:true}));
   const processed=performance.now();document.getElementById('questionList').getBoundingClientRect();const laid=performance.now();
   await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
   filters.push({folder,handler_ms:processed-begin,layout_ms:laid-processed,frame_ms:performance.now()-begin,
    shown:[...document.querySelectorAll('.mixed-builder-question')].filter(n=>!n.hidden).length});
  }
 }
 await fetch('/__mix_measure',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path,round,nav,filters,questions:document.querySelectorAll('.mixed-builder-question').length,hidden:document.hidden})});
 if(path==='/' || path==='/library')location.href='/quiz-composer?round='+round;
 else if(round===0)location.href='/library?round=1';
});</script>'''
        if os.environ.get('DLMS_PERF_NORMAL_SEQUENCE') and request.path=='/quiz-composer':
            from tests.server_mode.mix_sequence import OPERATIONS
            script="""<script>window.addEventListener('load',async()=>{
            const folder=document.getElementById('folderFilter'),source=document.getElementById('sourceFilter'),boxes=[...document.querySelectorAll('input[name=question_ids]')];
            const nav=performance.getEntriesByType('navigation')[0].toJSON(),round=Number(new URLSearchParams(location.search).get('round')||0),path=location.pathname,filters=[];
            for(const op of OPS){const begin=performance.now();(new Function('folder','source','boxes',op[1]))(folder,source,boxes);const processed=performance.now();getComputedStyle(document.getElementById('questionList')).color;document.getElementById('questionList').getBoundingClientRect();const laid=performance.now();await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
            const ids=boxes.filter(b=>b.checked).map(b=>b.value),formIds=new FormData(document.getElementById('mixedQuizForm')).getAll('question_ids');
            const shown=document.querySelectorAll('.mixed-builder-question:not([hidden])').length,count=document.getElementById('selectedCount').textContent;
            filters.push({name:op[0],handler_ms:processed-begin,style_layout_ms:laid-processed,frame_ms:performance.now()-begin,shown,selected:ids.length,ids,formIds,count,passed:shown===op[2]&&ids.length===op[3]&&count===op[3]+' selected'&&JSON.stringify(ids)===JSON.stringify(formIds)});}
            await fetch('/__mix_measure',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path,round,nav,filters,questions:boxes.length,hidden:document.hidden})});
            if(round===0)location.href='/library?round=1';
            });</script>""".replace('OPS',json.dumps(OPERATIONS))
        response.set_data(response.get_data().replace(b'</body>',script.encode()+b'</body>'))
    if request.path=='/library':
        extra='<script>console.error("DLMS performance sentinel error"); console.warn("DLMS performance sentinel warning");</script>'
        if request.args.get('perf_case')=='tail':extra+='<img src="/__perf_tail.svg" width="1" height="1" alt="Synthetic diagnostic tail asset">'
        response.set_data(response.get_data().replace(b'</body>',extra.encode()+b'</body>'))
    record({'phase':'response_ready','path':request.full_path,'at':time.monotonic(),'status':response.status_code,'bytes':len(response.get_data()) if not response.direct_passthrough else None,'policy':response.headers.get('Permissions-Policy')})
    return response
@dlms.app.get('/__perf_theme/<theme>')
def fixture_theme(theme):
    from dlms.themes import THEME_REGISTRY
    if theme not in THEME_REGISTRY:return Response(status=400)
    cfg=dlms.load_portal_config();cfg['theme']=theme;dlms._write_settings_portal_config(cfg)
    return Response(status=204)
@dlms.app.get('/__perf_tail.svg')
def tail():
    time.sleep(.9) # Deliberately slow independent resource, not a measured production delay.
    return Response('<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>',mimetype='image/svg+xml',headers={'Cache-Control':'no-store'})
@dlms.app.post('/__mix_measure')
def measure():
    # Test-specific same-origin measurements remain protected by normal CSRF.
    value=request.get_json();destination=Path(os.environ['DLMS_PERF_NORMAL_RESULTS'])
    with destination.open('a') as stream:stream.write(json.dumps(value)+'\n')
    return Response(status=204)
original=dlms.app.wsgi_app
def traced(environ,start_response):
    def ready(status,headers,exc_info=None):
        record({'phase':'headers','path':environ.get('PATH_INFO','')+'?'+environ.get('QUERY_STRING',''),'at':time.monotonic(),'status':status,'policy':next((v for k,v in headers if k.lower()=='permissions-policy'),None)})
        return start_response(status,headers,exc_info)
    result=original(environ,ready)
    def stream():
        digest=hashlib.sha256();complete=False
        try:
            for block in result:digest.update(block);yield block
            complete=True
        finally:
            close=getattr(result,'close',None)
            if close:close()
            record({'phase':'body','path':environ.get('PATH_INFO','')+'?'+environ.get('QUERY_STRING',''),'sha256':digest.hexdigest(),'complete':complete,'variant':os.environ.get('DLMS_PERF_VARIANT','baseline')})
    return stream()
server=make_server('127.0.0.2',0,traced,threaded=True)
Path(os.environ['DLMS_PERF_READY']).write_text(str(server.server_port))
server.serve_forever()

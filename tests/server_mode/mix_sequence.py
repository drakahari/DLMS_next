"""Content-free measurement and exact synthetic selection assertions."""
import json

INSTRUMENT = r"""(() => {
 const audit=window.__mixAudit={registration:{},calls:{},handlerMs:{},observers:[],longtasks:[]};
 const key=(node,type)=>type+':'+(node.id||node.name||node.constructor.name);
 const add=EventTarget.prototype.addEventListener,remove=EventTarget.prototype.removeEventListener;
 const wrappers=new WeakMap();
 EventTarget.prototype.addEventListener=function(type,listener,opts){
  if(!['input','change','click'].includes(type)||typeof listener!=='function')return add.call(this,type,listener,opts);
  let entries=wrappers.get(this);if(!entries){entries=[];wrappers.set(this,entries)}
  const capture=typeof opts==='boolean'?opts:!!opts?.capture;
  let item=entries.find(x=>x.type===type&&x.listener===listener&&x.capture===capture);
  if(!item){const target=this;item={type,listener,capture,wrapped:function(event){
   const name=key(target,type),start=performance.now();audit.calls[name]=(audit.calls[name]||0)+1;
   try{return listener.call(this,event)}finally{audit.handlerMs[name]=(audit.handlerMs[name]||0)+performance.now()-start}
  }};entries.push(item);const name=key(this,type);audit.registration[name]=(audit.registration[name]||0)+1}
  return add.call(this,type,item.wrapped,opts);
 };
 EventTarget.prototype.removeEventListener=function(type,listener,opts){
  const capture=typeof opts==='boolean'?opts:!!opts?.capture;
  const item=wrappers.get(this)?.find(x=>x.type===type&&x.listener===listener&&x.capture===capture);
  return remove.call(this,type,item?.wrapped||listener,opts);
 };
 const OriginalObserver=MutationObserver;
 window.MutationObserver=class extends OriginalObserver {
  constructor(callback){const entry={calls:0,records:0,ms:0};audit.observers.push(entry);super((records,observer)=>{
   const start=performance.now();entry.calls++;entry.records+=records.length;try{return callback(records,observer)}finally{entry.ms+=performance.now()-start}
  })}
 };
 try{new PerformanceObserver(list=>{for(const e of list.getEntries())audit.longtasks.push({start:e.startTime,duration:e.duration})}).observe({type:'longtask',buffered:true})}catch{}
})()"""

# All values/IDs only from the synthetic fixture. No application code is replaced.
OPERATIONS=[
 ('folder_one',"folder.value=folder.options[1].value;folder.dispatchEvent(new Event('input',{bubbles:true}));",1500,0),
 ('quiz_one',"source.value=source.options[1].value;source.dispatchEvent(new Event('input',{bubbles:true}));",250,0),
 ('repeat_quiz_one',"source.dispatchEvent(new Event('input',{bubbles:true}));",250,0),
 ('pick_first_25',"boxes.filter(b=>!b.closest('.mixed-builder-question').hidden).slice(0,25).forEach(b=>b.click());",250,25),
 ('quiz_five',"source.value=source.options[5].value;source.dispatchEvent(new Event('input',{bubbles:true}));",250,25),
 ('pick_next_25',"boxes.filter(b=>!b.closest('.mixed-builder-question').hidden).slice(0,25).forEach(b=>b.click());",250,50),
 ('folder_two',"folder.value=folder.options[2].value;folder.dispatchEvent(new Event('input',{bubbles:true}));",0,50),
 ('folder_two_all_quizzes',"source.value='';source.dispatchEvent(new Event('input',{bubbles:true}));",1500,50),
 ('quiz_two',"source.value=source.options[2].value;source.dispatchEvent(new Event('input',{bubbles:true}));",250,50),
 ('clear_hidden_50',"document.getElementById('clearSelection').focus();document.getElementById('clearSelection').click();",250,0),
 ('all_questions',"folder.value='';source.value='';folder.dispatchEvent(new Event('input',{bubbles:true}));",6000,0),
 ('same_turn_folder_quiz',"for(const n of [1,2,3,4]){folder.value=folder.options[n].value;folder.dispatchEvent(new Event('input',{bubbles:true}))}source.value=source.options[4].value;source.dispatchEvent(new Event('input',{bubbles:true}));",250,0),
 ('select_visible_250',"document.getElementById('selectVisible').click();",250,250),
 ('clear_visible_250',"document.getElementById('clearSelection').click();",250,0),
 ('final_all',"folder.value='';source.value='';folder.dispatchEvent(new Event('input',{bubbles:true}));",6000,0),
]

def operation_script(name,body):
    return r"""(() => {
 const folder=document.getElementById('folderFilter'),source=document.getElementById('sourceFilter');
 const boxes=[...document.querySelectorAll('input[name=question_ids]')];
 const auditBefore=structuredClone(window.__mixAudit);
 const before=performance.now();
 BODY
 const after=performance.now();
 const checked=boxes.filter(b=>b.checked).map(b=>b.value);
 const formIds=new FormData(document.getElementById('mixedQuizForm')).getAll('question_ids');
 const count=document.getElementById('selectedCount').textContent;
 const shown=document.querySelectorAll('.mixed-builder-question:not([hidden])').length;
 const measure=window.__mixMeasure={name:NAME,begin:before,handler_ms:after-before,checked,formIds,count,shown,
  hidden_selected:boxes.filter(b=>b.checked&&b.closest('.mixed-builder-question').hidden).length,
  origin:performance.timeOrigin,queue_probe_ms:null,done:false};
 const styleStart=performance.now();getComputedStyle(document.getElementById('questionList')).color;measure.style_read_ms=performance.now()-styleStart;
 const layoutStart=performance.now();document.getElementById('questionList').getBoundingClientRect();measure.layout_ms=performance.now()-layoutStart;
 setTimeout(()=>measure.queue_probe_ms=performance.now()-before,0);
 requestAnimationFrame(()=>requestAnimationFrame(()=>{measure.frames_ms=performance.now()-before;measure.audit={registration:window.__mixAudit.registration,
 calls:Object.fromEntries(Object.entries(window.__mixAudit.calls).map(([k,v])=>[k,v-(auditBefore.calls[k]||0)])),
 handlerMs:Object.fromEntries(Object.entries(window.__mixAudit.handlerMs).map(([k,v])=>[k,v-(auditBefore.handlerMs[k]||0)])),
 observers:window.__mixAudit.observers.map((v,i)=>({calls:v.calls-(auditBefore.observers[i]?.calls||0),records:v.records-(auditBefore.observers[i]?.records||0),ms:v.ms-(auditBefore.observers[i]?.ms||0)})),
 longtasks:window.__mixAudit.longtasks.filter(e=>e.start>=before)};measure.done=true}));return true;
})()""".replace('BODY',body).replace('NAME',json.dumps(name))

FIDELITY=r"""JSON.stringify([...document.querySelectorAll('.mixed-builder-question')].map(card=>({
 id:card.querySelector('[name=question_ids]').value,sources:card.dataset.sources,folder:card.dataset.folder,
 text:card.querySelector('h3').textContent,choices:card.querySelector('.mixed-builder-preview')?.textContent})))"""


def fixture_fidelity(root):
    """Exact synthetic source semantics and published-file bytes; never owner data."""
    import hashlib, sqlite3
    from pathlib import Path
    root=Path(root)
    with sqlite3.connect(root/'results.db') as db:
        records={table:[list(row) for row in db.execute('SELECT * FROM '+table+' ORDER BY rowid')]
                 for table in ['quizzes','questions','choices','matching_pairs']}
    files={}
    for relative in ['config/quizzes.json','data','quizzes','quiz_assets']:
        p=root/relative
        for file in ([p] if p.is_file() else sorted(p.rglob('*'))):
            if file.is_file():files[str(file.relative_to(root))]=hashlib.sha256(file.read_bytes()).hexdigest()
    canonical=json.dumps(records,sort_keys=True,separators=(',',':')).encode()
    return {'records_sha256':hashlib.sha256(canonical).hexdigest(),
            'row_counts':{k:len(v) for k,v in records.items()},'files':files}

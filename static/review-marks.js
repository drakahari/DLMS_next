(() => {
  'use strict';
  const root = document.getElementById('markedQuestions');
  if (!root) return;
  const status = document.getElementById('markActionStatus');
  const retry = document.getElementById('retryMarkAction');
  const key = `dlms.markSelection.${root.dataset.generation}.${root.dataset.scope}.${root.dataset.revision}`;
  let selected;
  try { selected = new Set(JSON.parse(sessionStorage.getItem(key) || '[]')); } catch (_) { selected = new Set(); }
  const boxes = [...root.querySelectorAll('[data-mark-id]')];
  const count = document.getElementById('markSelectionCount');
  const eligibility = document.getElementById('markEligibility');
  const retryPreview = document.getElementById('retryMarkPreview');
  let preview = null, previewIds = '', previewSequence = 0;
  function requestId() {
    if (typeof window.crypto?.randomUUID === 'function') return window.crypto.randomUUID();
    // Ordinary HTTP on a LAN does not expose randomUUID. getRandomValues is
    // available there without changing the browser's secure-context rules.
    if (typeof window.crypto?.getRandomValues === 'function') {
      const bytes = window.crypto.getRandomValues(new Uint8Array(16));
      return 'mark-' + [...bytes].map(value => value.toString(16).padStart(2, '0')).join('');
    }
    throw new Error('This browser cannot create a safe request ID. Use a browser with cryptographic random-number support.');
  }
  async function checkSelection() {
    const sequence=++previewSequence, ids=[...selected];
    preview=null; retryPreview.hidden=true;
    document.getElementById('practiceMarks').disabled=true;
    document.getElementById('exportMarks').disabled=true;
    eligibility.textContent=ids.length?'Checking selected questions…':'Practice: 0 included · 0 excluded. Anki: 0 included · 0 excluded.';
    if (!ids.length) return;
    try {
      const response=await fetch('/api/review-marks/preview',{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':document.querySelector('[name=csrf-token]').content},body:JSON.stringify({generation:root.dataset.generation,revision:Number(root.dataset.revision),ids})});
      const result=await response.json();
      if (sequence!==previewSequence) return;
      if (!response.ok) throw new Error(result.error || 'Could not check the selected questions.');
      preview=result; previewIds=JSON.stringify(ids); eligibility.replaceChildren();
      for (const [action,label,button] of [['practice','Practice','practiceMarks'],['anki','Anki','exportMarks']]) {
        const row=result[action], line=document.createElement('p');
        line.textContent=`${label}: ${row.included} included · ${row.excluded} excluded.`; eligibility.append(line);
        if (row.reasons.length) {
          const detail=document.createElement('details'), summary=document.createElement('summary'), list=document.createElement('ul');
          summary.textContent=`Why ${label.toLowerCase()} excludes ${row.excluded}`;
          for (const item of row.reasons) {const li=document.createElement('li');li.textContent=`${item.count}: ${item.reason}`;list.append(li);}
          detail.append(summary,list);eligibility.append(detail);
        }
        document.getElementById(button).disabled=row.excluded>0 || row.included===0;
      }
      if (result.practice.excluded || result.anki.excluded) {const note=document.createElement('p');note.textContent='Deselect excluded questions before that action. Nothing will be skipped automatically.';eligibility.append(note);}
    } catch (error) {
      if (sequence!==previewSequence) return;
      eligibility.textContent=error.message+' Your selection and marks are retained.';retryPreview.hidden=false;
    }
  }
  retryPreview.onclick=checkSelection;
  function render() {
    boxes.forEach(box => { box.checked = selected.has(box.dataset.markId); });
    const onPage = boxes.filter(box => box.checked).length;
    count.textContent = `${selected.size} ${selected.size === 1 ? 'question' : 'questions'} selected across pages · ${onPage} on this page.`;
    if (selected.size && status.textContent === 'Select at least one question.') status.textContent = '';
    try { sessionStorage.setItem(key, JSON.stringify([...selected])); } catch (_) { status.textContent = 'This browser cannot retain selections across pages. Keep this page open while using the selected questions.'; }
    checkSelection();
  }
  boxes.forEach(box => box.addEventListener('change', () => { if (box.checked) selected.add(box.dataset.markId); else selected.delete(box.dataset.markId); render(); }));
  document.getElementById('selectPageMarks').onclick = () => { boxes.forEach(box => selected.add(box.dataset.markId)); render(); };
  root.querySelectorAll('[data-select-marks]').forEach(button => button.addEventListener('click', () => {
    boxes.forEach(box => selected.delete(box.dataset.markId));
    boxes.filter(box => box.dataset[button.dataset.selectMarks] === 'yes').forEach(box => selected.add(box.dataset.markId));
    render();
  }));
  document.getElementById('clearMarkSelection').onclick = () => { selected.clear(); render(); };
  const pendingKey = `dlms.markAction.${root.dataset.generation}.${root.dataset.scope}`;
  let pending = null, busy = false;
  let desktopContext = null, desktopChecked = false, desktopBlocked = false;
  function samePayload(a,b) {
    const stable=value=>Array.isArray(value)?value.map(stable):value&&typeof value==='object'?
      Object.fromEntries(Object.keys(value).sort().map(key=>[key,stable(value[key])])):value;
    return JSON.stringify(stable(a))===JSON.stringify(stable(b));
  }
  let exportUrl = null;
  window.addEventListener('pagehide', event => { if (!event.persisted && exportUrl) URL.revokeObjectURL(exportUrl); });
  try { pending=JSON.parse(sessionStorage.getItem(pendingKey) || 'null'); } catch (_) { /* Preserve existing storage. */ }
  const sessionRecord=pending;
  if(pending?.context&&pending?.payload) pending=pending.payload;
  if (pending) { retry.hidden=false; status.textContent='A previous request needs confirmation. Retry the same request before starting another quiz.'; }
  function envelope() { return {kind: pending.action === 'save' ? 'review_save' : 'review_generate',
    payload: pending.data, context: desktopContext}; }
  async function desktopCall(path, value) {
    const response=await fetch('/_desktop/request/'+path,{method:'POST',headers:{'Content-Type':'application/json',
      'X-DLMS-Recovery-Client':'1','X-CSRFToken':document.querySelector('[name=csrf-token]').content},
      body:JSON.stringify(value),cache:'no-store'});
    const result=await response.json();
    if(!response.ok) throw new Error(result.error||'Desktop recovery requires inspection.');
    return result;
  }
  function clearPending() {
    if(desktopContext) localStorage.removeItem(pendingKey);
    sessionStorage.removeItem(pendingKey); pending=null;
  }
  async function checkDesktopRecovery() {
    try {
      const contextResponse=await fetch('/_desktop/request/context',{headers:{'X-DLMS-Recovery-Client':'1'},cache:'no-store'});
      if(contextResponse.status===404) return;
      if(!contextResponse.ok) throw new Error('Desktop recovery context is unavailable.');
      desktopContext=(await contextResponse.json()).context;
      let local=null, localUnavailable=false;
      try {local=JSON.parse(localStorage.getItem(pendingKey)||'null');}
      catch(_) {localUnavailable=true;}
      if(local && sessionRecord && !samePayload(local,sessionRecord)) throw new Error('Conflicting browser request evidence needs inspection.');
      const browser=local||sessionRecord;
      const response=await fetch('/_desktop/request/list',{headers:{'X-DLMS-Recovery-Client':'1'},cache:'no-store'});
      if(!response.ok) throw new Error('Accepted Desktop requests cannot be checked.');
      const records=(await response.json()).records.filter(item=>item.kind==='review_generate'||
        (item.kind==='review_save'&&item.payload.action==='unmark'));
      if(records.length>1) throw new Error('Multiple Review requests need inspection. No request was replayed.');
      if(localUnavailable && !records.length) throw new Error('Browser request storage is unavailable; no new Review action was sent.');
      if(browser?.context) {
        if(!samePayload(browser.context,desktopContext)) throw new Error('Review browser evidence belongs to another Desktop dataset; it was not replayed.');
        pending=browser.payload;
      } else if(browser && browser.action!=='anki' && !records.length) {
        throw new Error('Unbound older Review evidence needs inspection; it was not relabeled.');
      }
      if(records.length) {
        const recovered={action:records[0].kind==='review_save'?'save':'generate',data:records[0].payload};
        if(pending && !samePayload(pending,recovered)) throw new Error('Conflicting Review request evidence needs inspection.');
        pending=recovered;
      }
    } catch(error) {desktopBlocked=true;status.textContent=error.message+' No request was replayed.';}
    finally {desktopChecked=true;if(pending&&!desktopBlocked){retry.hidden=false;status.textContent='A retained Review request needs confirmation. Retry its original ID before starting another.';}}
  }
  async function run() {
    if (busy || !pending || !desktopChecked || desktopBlocked) return;
    busy = true; retry.hidden = true; status.textContent = 'Saving your request…';
    let confirmedSaved=false;
    try {
      let response=null, result=null;
      if(desktopContext && pending.action!=='anki') {
        const original=envelope(), current=await desktopCall('status',original);
        if(current.state==='committed') result=current.result||{url:current.url,title:'Marked practice',location:'Quiz Library → Generated Practice'};
        else if(current.state==='absent'||current.state==='retryable') result=await desktopCall('action',original);
        else throw new Error(`Original Review request is ${current.state}. Check saved marks or Generated Practice before further action.`);
        confirmedSaved=true;
        await desktopCall('ack',original);
      } else {
        response=await fetch(`/api/review-marks/${pending.action}`, {method: 'POST', headers: {'Content-Type':'application/json','X-CSRFToken':document.querySelector('[name=csrf-token]').content}, body:JSON.stringify(pending.data)});
        if (!response.ok) { const error = await response.json(); document.getElementById('uncertainMarkHelp').hidden=!error.uncertain; if (response.status < 500 && !error.uncertain) { clearPending(); } throw new Error(error.error || 'The request failed. Your marks are retained.'); }
      }
      if (pending.action === 'anki') {
        const blob = await response.blob();
        if (exportUrl) URL.revokeObjectURL(exportUrl);
        exportUrl = URL.createObjectURL(blob);
        const link = document.createElement('a'); link.href=exportUrl; link.download='dlms_marked_questions.apkg'; link.textContent='Download Anki package';
        document.getElementById('markExportResult').replaceChildren(link);
        link.addEventListener('click',()=>{status.textContent='Anki download requested. Complete Save As or check your browser downloads. Canceling does not save a file. Your marks remain saved.';});
        status.textContent='Anki package prepared. Complete Save As or use Download Anki package. A file is saved only after the download completes. Your marks remain saved.';
        link.click();
      } else {
        result=result||await response.json();
        if (pending.action === 'save') { sessionStorage.removeItem(key); clearPending(); location.reload(); return; }
        const container=document.getElementById('markPracticeResult'); container.replaceChildren();
        const text=document.createElement('p'); text.textContent=`${result.title} · ${result.location}`;
        const open=document.createElement('a'); open.href=result.url; open.textContent='Open focused quiz'; container.append(text,open);
        status.textContent='Focused quiz ready. Your marks remain saved. Finish Review covers only this practice set.';
      }
      clearPending();
    } catch (error) { status.textContent=confirmedSaved ?
      `Result saved, but recovery cleanup failed: ${error.message} Keep the original request ID for verification.` :
      error.message+(pending ? ' The original request ID and selection were retained. Check the saved result before retrying.' : ''); retry.hidden=!pending; }
    finally { busy=false; }
  }
  function start(action, ids=[...selected]) {
    if (busy || !desktopChecked || desktopBlocked) return;
    if (pending) { status.textContent='Retry the outstanding request before starting another action. Your selection is retained.'; return; }
    if (!ids.length) { status.textContent='Select at least one question.'; return; }
    const operation=action==='generate'?'practice':action;
    if (action!=='save' && (!preview || previewIds!==JSON.stringify(ids) || preview[operation].excluded)) {status.textContent='Check the selection and deselect excluded questions before continuing.';return;}
    if (action==='save' && !confirm(`Unmark exactly ${ids.length} selected ${ids.length===1?'question':'questions'}? Answers, history and other marks remain saved.`)) return;
    try {
      const prepared={action,data:{request_id:requestId(),generation:root.dataset.generation,revision:Number(root.dataset.revision),ids,...(action==='save'?{action:'unmark'}:{})}};
      // Persist before sending. If storage fails, do not send an action whose
      // identity could be lost on reload and accidentally repeated.
      const browserRecord=desktopContext&&action!=='anki'?{context:desktopContext,payload:prepared}:prepared;
      sessionStorage.setItem(pendingKey,JSON.stringify(browserRecord));
      if(desktopContext && action!=='anki') localStorage.setItem(pendingKey,JSON.stringify(browserRecord));
      pending=prepared;
      run();
    } catch (error) {
      status.textContent='Could not prepare this request: '+error.message+' No request was sent. Your selections and saved marks are retained.';
    }
  }
  document.getElementById('separateMarkRequest').onclick=()=>{
    if(desktopContext) {status.textContent='Desktop request evidence must be resolved before a separate Review action.';return;}
    if (busy || !pending || !confirm('Start a separate request only after checking Generated Practice and allowing interrupted work to recover at normal startup. The earlier quiz may already exist. Continue?')) return;
    sessionStorage.setItem(pendingKey+'.previous',JSON.stringify(pending));
    sessionStorage.removeItem(pendingKey); pending=null; retry.hidden=true;
    document.getElementById('uncertainMarkHelp').hidden=true;
    status.textContent='The earlier request was retained separately. Review your selection before starting different work.';
  };
  retry.onclick=run;
  document.getElementById('practiceMarks').onclick=()=>start('generate');
  document.getElementById('exportMarks').onclick=()=>start('anki');
  document.getElementById('unmarkSelected').onclick=()=>start('save');
  root.querySelectorAll('[data-unmark]').forEach(button=>button.onclick=()=>start('save',[button.dataset.unmark]));
  render();
  checkDesktopRecovery();
})();

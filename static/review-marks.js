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
    count.textContent = `${selected.size} ${selected.size === 1 ? 'question' : 'questions'} selected across pages.`;
    try { sessionStorage.setItem(key, JSON.stringify([...selected])); } catch (_) { status.textContent = 'This browser cannot retain selections across pages. Keep this page open while using the selected questions.'; }
    checkSelection();
  }
  boxes.forEach(box => box.addEventListener('change', () => { if (box.checked) selected.add(box.dataset.markId); else selected.delete(box.dataset.markId); render(); }));
  root.querySelectorAll('[data-select-marks]').forEach(button => button.addEventListener('click', () => { boxes.filter(box => box.dataset[button.dataset.selectMarks] === 'yes').forEach(box => selected.add(box.dataset.markId)); render(); }));
  document.getElementById('clearMarkSelection').onclick = () => { selected.clear(); render(); };
  const pendingKey = `dlms.markAction.${root.dataset.generation}.${root.dataset.scope}`;
  let pending = null, busy = false;
  try { pending=JSON.parse(sessionStorage.getItem(pendingKey) || 'null'); } catch (_) { /* Preserve existing storage. */ }
  if (pending) { retry.hidden=false; status.textContent='A previous request needs confirmation. Retry the same request before starting another quiz.'; }
  async function run() {
    if (busy || !pending) return;
    busy = true; retry.hidden = true; status.textContent = 'Saving your request…';
    try {
      const response = await fetch(`/api/review-marks/${pending.action}`, {method: 'POST', headers: {'Content-Type':'application/json','X-CSRFToken':document.querySelector('[name=csrf-token]').content}, body:JSON.stringify(pending.data)});
      if (!response.ok) { const error = await response.json(); document.getElementById('uncertainMarkHelp').hidden=!error.uncertain; if (response.status < 500 && !error.uncertain) { pending=null; sessionStorage.removeItem(pendingKey); } throw new Error(error.error || 'The request failed. Your marks are retained.'); }
      if (pending.action === 'anki') {
        const url = URL.createObjectURL(await response.blob()), link = document.createElement('a'); link.href=url; link.download='dlms_marked_questions.apkg'; link.click(); URL.revokeObjectURL(url);
        status.textContent='Anki package exported. Your marks remain saved.';
      } else {
        const result = await response.json();
        if (pending.action === 'save') { sessionStorage.removeItem(key); sessionStorage.removeItem(pendingKey); location.reload(); return; }
        const container=document.getElementById('markPracticeResult'); container.replaceChildren();
        const text=document.createElement('p'); text.textContent=`${result.title} · ${result.location}`;
        const open=document.createElement('a'); open.href=result.url; open.textContent='Open focused quiz'; container.append(text,open);
        status.textContent='Focused quiz ready. Your marks remain saved. Finish Review covers only this practice set.';
      }
      pending=null; sessionStorage.removeItem(pendingKey);
    } catch (error) { status.textContent=error.message; retry.hidden=!pending; }
    finally { busy=false; }
  }
  function start(action, ids=[...selected]) {
    if (busy) return;
    if (pending) { status.textContent='Retry the outstanding request before starting another action. Your selection is retained.'; return; }
    if (!ids.length) { status.textContent='Select at least one question.'; return; }
    const operation=action==='generate'?'practice':action;
    if (action!=='save' && (!preview || previewIds!==JSON.stringify(ids) || preview[operation].excluded)) {status.textContent='Check the selection and deselect excluded questions before continuing.';return;}
    if (action==='save' && !confirm(`Unmark exactly ${ids.length} selected ${ids.length===1?'question':'questions'}? Answers, history and other marks remain saved.`)) return;
    pending={action,data:{request_id:crypto.randomUUID(),generation:root.dataset.generation,revision:Number(root.dataset.revision),ids,...(action==='save'?{action:'unmark'}:{})}}; sessionStorage.setItem(pendingKey,JSON.stringify(pending)); run();
  }
  document.getElementById('separateMarkRequest').onclick=()=>{
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
})();

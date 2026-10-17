/* Synthetic server instrumentation only: no Desktop bridge or owner content. */
(() => {
 const query=new URLSearchParams(location.search),run=query.get('__wvperf');
 if(!run)return;
 const cycle=Number(query.get('cycle')||0),stage=Number(query.get('stage')||0);
 const pages=['/library','/quiz-composer','/library','/'];
 const mark=()=>performance.timeOrigin+performance.now();
 const navigationStart=Number(sessionStorage.getItem('wvperf-navigation-start')||0);
 const twoFrames=()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
 let dcl=null;document.addEventListener('DOMContentLoaded',()=>{dcl=performance.now()},{once:true});
 window.addEventListener('load',async()=>{
  const loaded=performance.now();await twoFrames();
  const frameReady=performance.now(),filters=[];
  const nav=performance.getEntriesByType('navigation')[0].toJSON();
  const nativeGate=await fetch('/__wvperf/ready',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({run,cycle,stage,path:location.pathname,loaded,frameReady,utc_ms:mark()})});
  if(!nativeGate.ok)throw Error('Synthetic native readiness gate failed: '+nativeGate.status);
  let contentReady=performance.now(),contentReadiness=null;
  if(location.pathname==='/'){
   const begin=performance.now();
   const settled=()=>!document.getElementById('overviewStatus')?.textContent.includes('Loading')
    &&!document.getElementById('dailyReviewCount')?.textContent.includes('Loading');
   while(!settled()&&performance.now()-begin<15000)await twoFrames();
   await twoFrames();contentReady=performance.now();
   contentReadiness={settled:settled(),overview:document.getElementById('overviewStatus')?.textContent,
    dailyReview:document.getElementById('dailyReviewCount')?.textContent};
   if(!contentReadiness.settled||contentReadiness.dailyReview==='Unavailable')throw Error('Synthetic Dashboard data did not become ready');
  }
  if(location.pathname==='/quiz-composer'){
   const folder=document.getElementById('folderFilter'),source=document.getElementById('sourceFilter');
   for(const value of ['synthetic folder 1','','synthetic folder 2','']){
    const begin=performance.now();folder.value=value;folder.dispatchEvent(new Event('input',{bubbles:true}));
    const handlerEnd=performance.now();getComputedStyle(document.getElementById('questionList')).color;
    const styleEnd=performance.now();const height=document.getElementById('questionList').getBoundingClientRect().height;
    const geometryEnd=performance.now();await twoFrames();
    filters.push({folder:value,handler_ms:handlerEnd-begin,style_ms:styleEnd-handlerEnd,
      geometry_ms:geometryEnd-styleEnd,two_frame_ms:performance.now()-begin,height,
      shown:document.querySelectorAll('.mixed-builder-question:not([hidden])').length,
      selected:document.querySelectorAll('[name=question_ids]:checked').length});
   }
   if(document.querySelectorAll('[name=question_ids]').length!==10000)throw Error('Expected 10000 synthetic questions');
  }
  let graphics=null;
  if(stage===0&&cycle===0){const g=document.createElement('canvas').getContext('webgl2');const e=g?.getExtension('WEBGL_debug_renderer_info');
   graphics={renderer:g&&e?g.getParameter(e.UNMASKED_RENDERER_WEBGL):null,version:g?g.getParameter(g.VERSION):null};}
  const payload={run,cycle,stage,path:location.pathname,nav,dcl,loaded,frameReady,contentReady,contentReadiness,filters,graphics,
    apiResources:performance.getEntriesByType('resource').filter(x=>new URL(x.name).pathname.startsWith('/api/')).map(x=>({path:new URL(x.name).pathname,start:x.startTime,duration:x.duration})),
    click_to_two_frames_ms:navigationStart?performance.timeOrigin+frameReady-navigationStart:null,
    rendererCadence:window.__wvperfCadence?window.__wvperfCadence():null,
    viewport:{width:innerWidth,height:innerHeight,dpr:devicePixelRatio},hidden:document.hidden,
    content:{sidebar:!!document.querySelector('.dashboard-sidebar'),main:!!document.querySelector('main'),
      questionCount:document.querySelectorAll('[name=question_ids]').length},utc_ms:mark()};
  const recorded=await fetch('/__wvperf/record',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  if(!recorded.ok)throw Error('Synthetic record gate failed: '+recorded.status);
  const nextStage=stage+1,nextCycle=nextStage===pages.length?cycle+1:cycle;
  if(nextCycle<2){
   // Yield after recording, without an application readiness gate or fixed delay.
   await twoFrames();sessionStorage.setItem('wvperf-navigation-start',String(mark()));
   location.href=pages[nextStage%pages.length]+'?__wvperf='+encodeURIComponent(run)+'&cycle='+nextCycle+'&stage='+(nextStage%pages.length);
  }
 },{once:true});
})();

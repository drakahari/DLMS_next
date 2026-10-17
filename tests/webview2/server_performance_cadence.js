/* Opt-in owned synthetic fixture only: no continuous frame/timer/network loop. */
(() => {
 const observers=[],limit=2048;
 const values={};
 for(const kind of ['longtask','long-animation-frame']){
  const stats=values[kind]={supported:PerformanceObserver.supportedEntryTypes?.includes(kind)||false,
   count:0,total_ms:0,max_ms:0,first_start_ms:null,last_end_ms:null,capped:false};
  const consume=entries=>{
   for(const entry of entries){
    if(stats.count>=limit){stats.capped=true;break;}
    stats.count++;stats.total_ms+=entry.duration;stats.max_ms=Math.max(stats.max_ms,entry.duration);
    if(stats.first_start_ms===null)stats.first_start_ms=entry.startTime;
    stats.last_end_ms=entry.startTime+entry.duration;
   }
  };
  if(stats.supported){
   try{const observer=new PerformanceObserver(list=>consume(list.getEntries()));
    observer.observe({type:kind,buffered:true});observers.push({observer,consume});
   }catch{stats.supported=false;}
  }
 }
 window.__wvperfCadence=()=>{
  for(const item of observers)item.consume(item.observer.takeRecords());
  return JSON.parse(JSON.stringify(values));
 };
})();

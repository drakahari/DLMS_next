// Private, closed-purpose activation observer; no page-visible native command API.
static class AiScripts {
    public const string World="DLMSDesktopAI";
    public const string Binding="__dlmsAIRequest";
    // This relay is deliberately unprivileged. Forging it alone gives no authority.
    // Preserve all unsupported window.open argument/return behavior.
    public const string Relay=@"(()=>{
      if(self!==top)return;
      const open=window.open, dispatch=EventTarget.prototype.dispatchEvent,
            EventCtor=CustomEvent, apply=Reflect.apply;
      Object.defineProperty(window,'open',{configurable:false,writable:false,value:function(...args){
        if(args.length===3&&typeof args[0]==='string'&&args[1]==='_blank'&&
           typeof args[2]==='string'&&args[2].replace(/\s/g,'').toLowerCase()==='noopener,noreferrer'){
          const event=new EventCtor('__dlms_ai_open',{detail:args[0],cancelable:true});
          if(!apply(dispatch,document,[event]))return null;
        }
        return apply(open,this,args);
      }});
    })()";
    public const string Observer=@"(()=>{
      if(self!==top)return;
      const phase=Object.getOwnPropertyDescriptor(Event.prototype,'eventPhase').get,
            call=Function.prototype.call;
      const known=new WeakSet();let policy=null,active=null,sequence=0,repeating=false,serverEpoch=0;
      const text=e=>e.textContent.replace(/\s+/g,' ').trim();
      const attr=(e,n)=>e.getAttribute(n)||'';
      const address=value=>{try{return new URL(value).href;}catch(_){return null;}};
      const approved=value=>['https://chatgpt.com/','https://claude.ai/','https://gemini.google.com/'].includes(address(value));
      const targetMatches=(action,value)=>policy.server?typeof value==='string':address(value)===policy.actions[action];
      function eligible(e,relay=false){
        if(!policy||!e||!e.isConnected||e.disabled||e.ownerDocument!==document)return null;
        let action=null,handler=attr(e,'onclick'),label=text(e),path=location.pathname;
        if(e.tagName==='BUTTON'){
          if(/^\/quizzes\/[^/]+\.html$/.test(path)&&e.id==='studyAiBtn'&&
             handler.replace(/\s/g,'')==='reviewCurrentQuestionWithAI()'&&
             (label==='Review with AI'||label==='✨ Review with AI'))action='study-review';
          else if(path==='/review'||path==='/review.html'){
            if(/^openAIExplain\(\s*\d+\s*,\s*this\s*\)$/.test(handler)&&e.closest('.review-question-actions')&&
               (label==='Explain with AI'||(label==='Prompt Copied'&&(relay||known.has(e)))))action='review-single';
            else if(handler.replace(/\s/g,'')==='explainSelectedWithAI()'&&label==='Explain Selected with AI')action='review-selected';
          } else if((path==='/law/create'||path==='/study-packs/ai-builder')&&label==='Copy Prompt & Open AI'){
            const prefix=path==='/law/create'?'copyPromptAndOpenAi':'copyAndOpen';
            if(handler.startsWith(prefix+'(')&&handler.endsWith(')')){
              try {if(targetMatches(path==='/law/create'?'law-prompt':'study-pack',JSON.parse(handler.slice(prefix.length+1,-1)))&&
                  document.querySelector(path==='/law/create'?'#lawPromptBox':'#studyPrompt'))action=path==='/law/create'?'law-prompt':'study-pack';}catch(_){}
            }
          } else if((path==='/certifications/matches'||/^\/certifications\/[0-9a-f]{32}\/ai$/.test(path))&&
              e.hasAttribute('data-cert-launch')&&label==='Copy & open AI'&&document.querySelector('#certPrompt')&&
              targetMatches('cert-combined',document.querySelector('#certProviderLink')?.href))action='cert-combined';
        } else if(e.tagName==='A'&&(path==='/certifications/matches'||/^\/certifications\/[0-9a-f]{32}\/ai$/.test(path))&&
            e.id==='certProviderLink'&&label==='Open AI manually'&&e.target==='_blank'&&
            targetMatches('cert-manual',e.href)&&e.relList.contains('noopener')&&e.relList.contains('noreferrer'))action='cert-manual';
        return action&&Object.hasOwn(policy.actions,action)?{action,handler,label}:null;
      }
      function send(a){
        if(a.used)return;a.used=true;
        __dlmsAIRequest(JSON.stringify({nonce:policy.nonce,sequence:++sequence,action:a.action,
            href:location.href,timeOrigin:performance.timeOrigin}));
      }
      function retireServer(){
        active=null;
        if(policy?.server)__dlmsAIRequest(JSON.stringify({nonce:policy.nonce,sequence:++serverEpoch,
            href:location.href,timeOrigin:performance.timeOrigin}));
      }
      document.addEventListener('pointerdown',e=>{if(e.isTrusted&&policy?.server)retireServer();},true);
      document.addEventListener('keydown',e=>{if(e.isTrusted){if(policy?.server)retireServer();if(e.key==='Enter'||e.key===' ')repeating=e.repeat;}},true);
      document.addEventListener('keyup',e=>{if(e.isTrusted)repeating=false;},true);
      window.addEventListener('blur',()=>{repeating=false;retireServer();});
      document.addEventListener('visibilitychange',()=>{repeating=false;retireServer();});
      document.addEventListener('click',e=>{
        if(policy?.server){if(!e.isTrusted)return;retireServer();}else active=null;
        if(!e.isTrusted||e.defaultPrevented||!policy||location.href!==policy.href)return;
        const element=e.target instanceof Element?e.target.closest('button,a'):null;
        const match=eligible(element);if(!match)return;
        known.add(element);active={event:e,element,action:match.action,handler:match.handler,used:false,created:performance.now(),gesture:serverEpoch};
        if(repeating&&e.detail===0){active.used=true;e.preventDefault();e.stopImmediatePropagation();return;}
        if(match.action==='cert-manual'&&!policy.server){e.preventDefault();send(active);}
      },true);
      document.addEventListener('__dlms_ai_open',e=>{
        const a=active;
        if(policy?.server)return; // Real WebView2 navigation/popup signal is required.
        // Read the ORIGINAL trusted click's native phase. A timer, forged relay,
        // synthetic .click(), or shadowed eventPhase cannot extend its dispatch.
        if(!a||!policy||!a.event.isTrusted||call.call(phase,a.event)===0||location.href!==policy.href)return;
        const current=eligible(a.element,true);
        if(!current||current.action!==a.action||current.handler!==a.handler||
           typeof e.detail!=='string'||address(e.detail)!==policy.actions[a.action])return;
        e.preventDefault();send(a);
      },true);
      Object.defineProperty(globalThis,'__dlmsConfigureAI',{value:value=>{
        active=null;policy=value;sequence=0;serverEpoch=0;
        if(policy)policy.actions=Object.fromEntries(Object.entries(policy.actions).map(([key,value])=>[key,address(value)]));
      },configurable:false,writable:false});
      // Only the owning host can call this in the private execution context.
      // Remote labels/URLs/messages alone never launch anything. The native
      // caller also requires IsUserInitiated, frame/document identity and its
      // independent HTTPS allowlist. One record is consumed before async work.
      Object.defineProperty(globalThis,'__dlmsTakeServerAI',{value:(target,gesture)=>{
        if(!policy?.server||location.href!==policy.href||!active)return {state:'generic'};
        const a=active;
        if(a.used||a.gesture!==gesture)return {state:'refused'};
        a.used=true;
        const current=eligible(a.element,true);
        if(!a.event.isTrusted||performance.now()-a.created>5000||!current||
           current.action!==a.action||current.handler!==a.handler||!approved(target))return {state:'refused'};
        return {state:'ai',action:a.action,href:location.href,timeOrigin:performance.timeOrigin,gesture:a.gesture};
      },configurable:false,writable:false});
      Object.defineProperty(globalThis,'__dlmsValidateServerAI',{value:gesture=>{
        const a=active,current=a&&eligible(a.element,true);
        return !!(policy?.server&&location.href===policy.href&&a?.used&&a.gesture===gesture&&
            performance.now()-a.created<=5000&&current&&current.action===a.action&&current.handler===a.handler);
      },configurable:false,writable:false});
    })()";
}

using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using Microsoft.Web.WebView2.Core;

sealed partial class DesktopRenderer {
    int aiContext;
    long serverInputEpoch;
#if DLMS_AI_TEST
    string serverRaceStage;
    async Task ServerAITestDelay(string stage) {
        if(serverRaceStage!=stage)return;
        serverRaceStage=null;AIState("server-test-"+stage);await Task.Delay(300);
    }
#endif
    long aiSequence;
    string aiNonce,aiIdentity;
    AiActionLease aiActions;
    int aiRecords;
    void AIState(string state){if(aiRecords++<96)Event("ai-policy",new Dictionary<string,object>{{"state",state},{"generation",generation},{"nav_id",activeNavigation}});}
    static readonly HashSet<string> AIActionNames=new HashSet<string>(new[]{
        "study-review","review-single","review-selected","study-pack","law-prompt","cert-combined","cert-manual"});
    Task aiRetirement=Task.FromResult(0);
    void RetireAI(){
        int context=aiContext;aiContext=0;aiNonce=null;aiIdentity=null;aiSequence=0;aiActions=null;serverInputEpoch=0;
        if(context!=0&&!disposed&&view.CoreWebView2!=null){
            aiRetirement=Cdp("Runtime.evaluate",new{contextId=context,expression="__dlmsConfigureAI(null)",returnByValue=true});
            ObserveFailure(aiRetirement);
        }
    }
    static bool okAIStatus(int status){return status>=200&&status<400;}
    static bool AIPath(string path) {
        return new[]{"/review","/review.html","/study-packs/ai-builder","/law/create","/certifications/matches"}.Contains(path)||
            Regex.IsMatch(path,@"^/certifications/[0-9a-f]{32}/ai$")||Regex.IsMatch(path,@"^/quizzes/[^/\\?#\x00-\x1f]+\.html$");
    }
    static bool DocumentRequest(CoreWebView2WebResourceRequest request) {
        return request.Headers.Contains("Sec-Fetch-Dest")&&request.Headers.GetHeader("Sec-Fetch-Dest")=="document"&&
            request.Headers.Contains("Sec-Fetch-Mode")&&request.Headers.GetHeader("Sec-Fetch-Mode")=="navigate";
    }
    void TagAIFetch(string url,Dictionary<string,string> headers) {
        // Caller has the engine's root-frame + Document resource type. Sec-Fetch
        // headers may not exist yet at Fetch's request-stage pause.
        Navigation nav;
        if(navigations.TryGetValue(activeNavigation,out nav)&&Current(nav,activeNavigation)&&url==nav.Url&&
            AIPath(Uri.UnescapeDataString(new Uri(url).AbsolutePath))){headers["X-DLMS-AI-Document"]=nav.AITag;AIState("fetch-document-tagged");}
    }
    void TagAIDocument(CoreWebView2WebResourceRequest request,bool document) {
        const string header="X-DLMS-AI-Document";
        // Fetch is the sole minting gate. WRR must never relabel an older
        // in-flight document with a newer same-URL navigation's tag.
        if(!request.Headers.Contains(header))return;
        Navigation nav;
        if(!(mode=="local"&&document&&navigations.TryGetValue(activeNavigation,out nav)&&
            Current(nav,activeNavigation)&&request.Uri==nav.Url&&request.Headers.GetHeader(header)==nav.AITag&&
            AIPath(Uri.UnescapeDataString(new Uri(nav.Url).AbsolutePath))))request.Headers.RemoveHeader(header);
    }
    void CaptureAIContract(CoreWebView2WebResourceResponseReceivedEventArgs e,Navigation nav) {
        if(mode=="local"&&AIPath(Uri.UnescapeDataString(new Uri(nav.Url).AbsolutePath)))AIState(
            !DocumentRequest(e.Request)?"response-not-document":!e.Request.Headers.Contains("X-DLMS-AI-Document")?"response-tag-missing":
            !e.Response.Headers.Contains("X-DLMS-AI-Contract")?"response-contract-missing":"response-contract-present");
        if(mode!="local"||nav.Completed||!DocumentRequest(e.Request)||!okAIStatus(e.Response.StatusCode)||
            !e.Request.Headers.Contains("X-DLMS-AI-Document")||e.Request.Headers.GetHeader("X-DLMS-AI-Document")!=nav.AITag||
            !e.Response.Headers.Contains("X-DLMS-AI-Contract"))return;
        try {
            string encoded=e.Response.Headers.GetHeader("X-DLMS-AI-Contract");
            if(encoded.Length>24576||!Regex.IsMatch(encoded,@"^[A-Za-z0-9+/]+={0,2}$"))return;
            var contract=json.Deserialize<Dictionary<string,object>>(Encoding.UTF8.GetString(Convert.FromBase64String(encoded)));
            string path=Uri.UnescapeDataString(new Uri(nav.Url).AbsolutePath);
            if(contract==null||contract.Count!=4||!(contract["version"] is int)||(int)contract["version"]!=1||TextValue(contract,"request")!=nav.AITag||
                TextValue(contract,"path")!=path||!AIPath(path))return;
            var source=contract["actions"] as Dictionary<string,object>;
            if(source==null||source.Count==0||source.Count>7)return;
            var actions=new Dictionary<string,string>();
            foreach(var item in source){
                string value=item.Value as string;Uri target;
                if(!AIActionNames.Contains(item.Key)||value==null||value.Length>8192||
                   !Uri.TryCreate(value,UriKind.Absolute,out target)||(target.Scheme!="https"&&target.Scheme!="http")||
                   target.UserInfo.Length!=0||target.IsLoopback||target.Host.TrimEnd('.').EndsWith(".localhost",StringComparison.OrdinalIgnoreCase))return;
                actions.Add(item.Key,value);
            }
            nav.AIActions=actions;
            AIState("contract-accepted");
        }catch(ArgumentException){}catch(InvalidOperationException){}catch(FormatException){}catch(KeyNotFoundException){}catch(InvalidCastException){}catch(OverflowException){}
    }
    async Task InstallAIObserver() {
        var core=view.CoreWebView2;
        core.GetDevToolsProtocolEventReceiver("Runtime.bindingCalled").DevToolsProtocolEventReceived+=async(s,e)=>await AIRequested(e.ParameterObjectAsJson);
        await Cdp("Runtime.addBinding",new{name=AiScripts.Binding,executionContextName=AiScripts.World});
        await Cdp("Page.addScriptToEvaluateOnNewDocument",new{worldName=AiScripts.World,source=AiScripts.Observer});
        if(mode=="local")await Cdp("Page.addScriptToEvaluateOnNewDocument",new{source=AiScripts.Relay});
    }
    async Task ConfigureAI(Navigation nav,ulong id) {
        if((mode=="local"?nav.AIActions==null:!AIPath(Uri.UnescapeDataString(new Uri(view.CoreWebView2.Source).AbsolutePath)))||
            documentHadChildFrame||!Current(nav,id))return;
        int configuring=0;string configuringNonce=null;
        try {
            try{await aiRetirement;}catch{} // Old context may already have been destroyed.
            if(!Current(nav,id))return;
            var context=await Cdp("Page.createIsolatedWorld",new{frameId=mainFrame,worldName=AiScripts.World,grantUniveralAccess=false});
            if(!Current(nav,id))return;
            int contextId=Convert.ToInt32(context["executionContextId"]);
            string nonce=Guid.NewGuid().ToString("N"),identity=documentIdentity;
            configuring=contextId;configuringNonce=nonce;
            aiContext=contextId;aiNonce=nonce;aiIdentity=identity;aiSequence=0;serverInputEpoch=0;
            aiActions=mode=="local"?new AiActionLease(nav.AIActions):null;
            var serverActions=AIActionNames.ToDictionary(name=>name,name=>"https://chatgpt.com/");
            var policy=new{nonce=nonce,href=view.CoreWebView2.Source,server=mode=="server",
                actions=mode=="local"?aiActions.Policy():serverActions};
            var result=await Cdp("Runtime.evaluate",new{contextId=contextId,expression="__dlmsConfigureAI("+json.Serialize(policy)+");true",returnByValue=true});
            if(!Current(nav,id)||documentHadChildFrame||result.ContainsKey("exceptionDetails")){
                if(aiContext==configuring&&aiNonce==configuringNonce)RetireAI();
                AIState("observer-config-refused");return;
            }
            AIState("observer-configured");
        }catch(Exception){if(Current(nav,id)&&aiContext==configuring&&aiNonce==configuringNonce)RetireAI();} // Optional classification fails back to existing consent.
    }
    static bool ApprovedServerAI(string value) {
        if(value==null||value.Length>128||value.Any(c=>c<=32||c==127||c=='\\'))return false;
        Uri u;
        return Uri.TryCreate(value,UriKind.Absolute,out u)&&u.Scheme=="https"&&u.UserInfo.Length==0&&
            u.IsDefaultPort&&u.AbsolutePath=="/"&&u.Query.Length==0&&u.Fragment.Length==0&&
            new[]{"https://chatgpt.com/","https://claude.ai/","https://gemini.google.com/"}.Contains(u.AbsoluteUri);
    }
    async Task<bool> ServerAIRequest(string target,string source,Navigation nav,ulong id,long inputEpoch) {
        if(mode!="server"||aiContext==0||aiIdentity==null)return false;
        int context=aiContext;string identity=aiIdentity,nonce=aiNonce;
        try {
#if DLMS_AI_TEST
            if(serverRaceStage=="stale-input"){serverRaceStage=null;inputEpoch=Math.Max(0,inputEpoch-1);}
            await ServerAITestDelay("before-take");
#endif
            // The native event has already been canceled/handled. Query only
            // our isolated context, never a page-supplied script/message. No
            // added timer or producer contract; consume the trusted click once.
            var result=await Cdp("Runtime.evaluate",new{contextId=context,
                expression="__dlmsTakeServerAI("+json.Serialize(target)+","+inputEpoch+")",returnByValue=true});
            if(!Current(nav,id)||context!=aiContext||nonce!=aiNonce||documentHadChildFrame||serverInputEpoch!=inputEpoch)return true;
            var remote=result["result"] as Dictionary<string,object>;
            var value=remote!=null&&remote.ContainsKey("value")?remote["value"] as Dictionary<string,object>:null;
            if(value==null)return true;
            string state=TextValue(value,"state");
            if(state=="generic")return false;
            if(state!="ai"||value.Count!=5||Convert.ToInt64(value["gesture"])!=inputEpoch||inputEpoch<=0||
                !AIActionNames.Contains(TextValue(value,"action"))||!ApprovedServerAI(target)){
                NavigationEvent("external-refused",nav,id,new Dictionary<string,object>{{"source",source},{"mode",mode},
                    {"user",true},{"kind","popup"},{"refusal","ai-activation"}});return true;
            }
            var original=json.Deserialize<Dictionary<string,object>>(identity);
            if(TextValue(value,"href")!=source||TextValue(original,"href")!=source||
                Convert.ToDouble(value["timeOrigin"])!=Convert.ToDouble(original["timeOrigin"]))return true;
#if DLMS_AI_TEST
            await ServerAITestDelay("after-take");
#endif
            string current=await Identity();
            if(!Current(nav,id)||context!=aiContext||nonce!=aiNonce||documentHadChildFrame||current!=identity||serverInputEpoch!=inputEpoch)return true;
            var checkedLease=await Cdp("Runtime.evaluate",new{contextId=context,
                expression="__dlmsValidateServerAI("+inputEpoch+")",returnByValue=true});
            var checkedResult=checkedLease["result"] as Dictionary<string,object>;
            if(!Current(nav,id)||context!=aiContext||nonce!=aiNonce||documentHadChildFrame||serverInputEpoch!=inputEpoch||
                checkedResult==null||!checkedResult.ContainsKey("value")||!Object.Equals(checkedResult["value"],true))return true;
            NavigationEvent("external-request",nav,id,new Dictionary<string,object>{{"url",target},{"source",source},
                {"mode",mode},{"user",true},{"native_user",true},{"kind","ai-action"},{"verified_ai",true},
                {"ai_action",TextValue(value,"action")}});return true;
        }catch(Exception){return true;} // Optional direct path fails closed, no fallback launch.
    }
    async Task AIRequested(string args) {
        try {
            if(mode=="server"){ServerInputChanged(args);return;}
            if(mode!="local"||closing||disposed||documentHadChildFrame||aiContext==0||aiNonce==null)return;
            Navigation nav;ulong id=activeNavigation;
            if(!navigations.TryGetValue(id,out nav)||!Current(nav,id)||!nav.Completed||aiActions==null)return;
            var data=json.Deserialize<Dictionary<string,object>>(args);
            if(TextValue(data,"name")!=AiScripts.Binding||Convert.ToInt32(data["executionContextId"])!=aiContext)return;
            string payload=TextValue(data,"payload");if(payload.Length>16384)return;
            var request=json.Deserialize<Dictionary<string,object>>(payload);
            string action=TextValue(request,"action"),target;
            long sequence=Convert.ToInt64(request["sequence"]);
            if(request.Count!=5||TextValue(request,"nonce")!=aiNonce||sequence!=aiSequence+1||sequence<1||
                !aiActions.TryGetTarget(action,out target)||TextValue(request,"href")!=view.CoreWebView2.Source)return;
            aiSequence=sequence; // Consume before asynchronous identity validation.
            int context=aiContext;string nonce=aiNonce,identity=aiIdentity;
            var actions=aiActions;
            // Publish load-finish first on the same owned pipe. An activation in
            // the small configuration interval must not be lost to Python's
            // still-loading context guard or let a retired page launch later.
            if(await Task.WhenAny(nav.AIReady.Task,Task.Delay(1500))!=nav.AIReady.Task||!nav.AIReady.Task.Result||
                !Current(nav,id)||context!=aiContext||nonce!=aiNonce||actions!=aiActions)return;
            string current=await Identity();
            if(!Current(nav,id)||documentHadChildFrame||context!=aiContext||nonce!=aiNonce||actions!=aiActions||current!=identity)return;
            var currentParts=json.Deserialize<Dictionary<string,object>>(current);
            if(TextValue(currentParts,"href")!=TextValue(request,"href")||
                Convert.ToDouble(currentParts["timeOrigin"])!=Convert.ToDouble(request["timeOrigin"]))return;
            NavigationEvent("external-request",nav,id,new Dictionary<string,object>{{"url",target},{"source",view.CoreWebView2.Source},
                {"mode",mode},{"user",true},{"kind","ai-action"},{"verified_ai",true},{"ai_action",action}});
        }catch(Exception){} // No payload/content logging or stale callback feedback.
    }
    void ServerInputChanged(string args) {
        // Cancellation/identity bookkeeping only. A message cannot open a URL.
        if(closing||disposed||documentHadChildFrame||aiContext==0||aiNonce==null)return;
        var data=json.Deserialize<Dictionary<string,object>>(args);
        if(TextValue(data,"name")!=AiScripts.Binding||Convert.ToInt32(data["executionContextId"])!=aiContext)return;
        string payload=TextValue(data,"payload");if(payload.Length>2048)return;
        var input=json.Deserialize<Dictionary<string,object>>(payload);
        var identity=json.Deserialize<Dictionary<string,object>>(aiIdentity);
        long next=Convert.ToInt64(input["sequence"]);
        if(input.Count!=4||TextValue(input,"nonce")!=aiNonce||next!=serverInputEpoch+1||next<=0||
            TextValue(input,"href")!=TextValue(identity,"href")||
            Convert.ToDouble(input["timeOrigin"])!=Convert.ToDouble(identity["timeOrigin"]))return;
        serverInputEpoch=next;
    }
}

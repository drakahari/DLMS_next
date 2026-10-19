// Windows-only renderer process. Its only native command channel is the owning
// Python process's anonymous stdin pipe; pages never receive host objects/messages.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Net;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Win32.SafeHandles;

sealed partial class DesktopRenderer : Form {
    readonly BrowserSurface view = new BrowserSurface();
    readonly Panel serverCover = new Panel();
    readonly Label serverStatus = new Label();
    readonly JavaScriptSerializer json = new JavaScriptSerializer { MaxJsonLength=16*1024*1024, RecursionLimit=128 };
    readonly object outputLock = new object();
    readonly Dictionary<string,object> config;
    readonly string origin, mode, token;
    CoreWebView2Environment environment;
    readonly Dictionary<string,PendingDownload> downloads = new Dictionary<string,PendingDownload>();
    readonly Dictionary<string,CoreWebView2DownloadOperation> operations = new Dictionary<string,CoreWebView2DownloadOperation>();
    readonly Dictionary<string,Picker> pickers = new Dictionary<string,Picker>();
    readonly Dictionary<string,PendingDialog> dialogs = new Dictionary<string,PendingDialog>();
    readonly Dictionary<ulong,Navigation> navigations = new Dictionary<ulong,Navigation>();
    readonly HashSet<string> blockedPaths = new HashSet<string>();
    readonly Dictionary<string,int> mainContexts = new Dictionary<string,int>();
    readonly List<SafeFileHandle> policyHandles = new List<SafeFileHandle>();
    readonly HashSet<string> pinnedPolicyDirectories = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
    const string PolicyName="DLMS Desktop private network policy";
    const string BrowserArguments="--disable-blink-features=SharedWorker";
    const string ManifestHash="5ab945b9d08adc07b3352f2207bf4e5fb3416ee4f47ffc81f614f14d5563a367";
    const string RulesHash="b8cd43300f4cf55024bd792b128d3b0aa457de4bc307b15c457446b4b7376d60";
    string policyDirectory, expectedExtensionId;
    string trustedRuntimeDirectory;
    readonly HashSet<string> verifiedHistoricalComponentRuntimes = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
    ulong activeNavigation;
    long generation;
    string documentIdentity;
    string mainFrame;
    bool closing, disposed;
    bool localPolicyVerified;
    bool browserPolicyReady;
    bool documentHadChildFrame;
    int browserPid;
    int activationWarnings;
    int policyBlocks;
    int permissionRecords, attachmentRecords;
    int blockedDownloadRecords;
    // Every HTTP request must cross the native policy, including requests
    // queued in the same task as window.open. WRR remains defense in depth.
    sealed class PendingRequest {
        public readonly string Id;public string Reason;public bool Sent;public RequestProtocolCall Protocol;
        public PendingRequest(string id){Id=id;}
    }
    readonly Dictionary<string,PendingRequest> pendingRequests=new Dictionary<string,PendingRequest>();
    string requestRootFrame;
    bool requestPolicyFailed;
    readonly HashSet<long> requestLeases=new HashSet<long>();
    long requestLeaseSequence,requestEnvelopeChars;
    async Task RequestDeadline(long lease) {
        await Task.Delay(5000);
        if(!closing&&requestLeases.Contains(lease))await FailRequestPolicy("envelope-decision-timeout");
    }
    async Task FailRequestPolicy(string reason) {
        if(requestPolicyFailed||closing)return;
        requestPolicyFailed=true;localPolicyVerified=false;browserPolicyReady=false;
        Emit("fatal",new{type="RequestPolicyFailure",message="A secure Desktop request could not complete. Close and reopen DLMS Desktop to retry and check pending-save recovery.",code=reason});
        // Disposal cancels requests whose one protocol decision could not be
        // acknowledged. Never send a contradictory second continue/fail.
        await Shutdown();
    }
    static void ObserveRequestTask(Task task) {
        // A timed-out operation can fault after its controller has retired.
        // Observe that fault without logging request data or retrying a decision.
        task.ContinueWith(failed=>failed.Exception.Handle(error=>true),CancellationToken.None,
            TaskContinuationOptions.OnlyOnFaulted|TaskContinuationOptions.ExecuteSynchronously,TaskScheduler.Default);
    }
    static Task<FetchMetadata> ScanRequestMetadata(string envelope) {
        // Capture a separate immutable reference, never the callback's mutable
        // raw variable. A queued scan retains it only until that task finishes.
        var scan=Task.Run(()=>FetchMetadata.Parse(envelope));
        ObserveRequestTask(scan);
        return scan;
    }
    async Task ResolveRequest(PendingRequest item,bool allow,object headers) {
        if(item.Sent)throw new InvalidOperationException("Duplicate request policy decision");
        item.Sent=true;
        // Preserve both native HRESULT and bounded protocol error JSON. The
        // managed Task wrapper loses the latter. This call is bound to this
        // immutable once-owned Fetch ID, after all per-hop policy checks.
        item.Protocol=new RequestProtocolCall();
        object parameters=allow?(object)new{requestId=item.Id,headers=headers}:
            new{requestId=item.Id,errorReason="BlockedByClient"};
        item.Protocol.Start(view.CoreWebView2,allow,json.Serialize(parameters));
        var action=item.Protocol.Task;
        ObserveRequestTask(action);
        if(await Task.WhenAny(action,Task.Delay(5000))!=action) {
            await FailRequestPolicy("request-decision-timeout");return;
        }
        var reply=await action;
        if(item.Protocol.Duplicate||RequestProtocolResult.Decode(item.Protocol.Method,reply.Error,reply.Json)==RequestProtocolOutcome.Rejected)
            throw new InvalidOperationException("Native request decision was not acknowledged or positively retired");
        // Exact missing-interception evidence retires bookkeeping only. Never
        // retry, send a second decision or turn a denial into a continuation.
        pendingRequests.Remove(item.Id);
    }

    async Task HandlePausedRequest(string value) {
        PendingRequest item=null;
        string raw=value;
        value=null;
        int chars=raw==null?0:raw.Length;
        long before=generation;ulong navigation=activeNavigation;
        long lease=0;
        bool failed=false;
        try {
            try {
                if(raw==null||closing||disposed||requestPolicyFailed||requestLeases.Count>=128||chars>FetchMetadata.EnvelopeChars||requestEnvelopeChars+chars>FetchMetadata.EnvelopeChars) {
                    await FailRequestPolicy("envelope-resource-or-context-limit");return;
                }
                lease=++requestLeaseSequence;
                requestLeases.Add(lease);requestEnvelopeChars+=chars;
                ObserveRequestTask(RequestDeadline(lease));
                // The upstream string already contains any body. The scanner
                // skips it structurally off the UI thread without a body copy.
                var scan=ScanRequestMetadata(raw);
                raw=null;
                if(await Task.WhenAny(scan,Task.Delay(5000))!=scan) {
                    await FailRequestPolicy("envelope-parse-timeout");return;
                }
                FetchMetadata data=await scan;
                raw=null;
                if(closing||disposed||requestPolicyFailed)return;
                string id=data.RequestId;
                if(pendingRequests.ContainsKey(id)||pendingRequests.Count>=128) {
                    await FailRequestPolicy("invalid-or-repeated-request-id");return;
                }
                item=new PendingRequest(id);pendingRequests[id]=item;
                string url=data.Url;
                var headers=new Dictionary<string,string>(StringComparer.OrdinalIgnoreCase);
                foreach(var entry in data.Headers) {
                    if(String.Equals(entry.Key,"X-DLMS-Desktop-Token",StringComparison.OrdinalIgnoreCase)||
                        String.Equals(entry.Key,"X-DLMS-AI-Document",StringComparison.OrdinalIgnoreCase)){continue;}
                    headers.Add(entry.Key,entry.Value);
                }
                bool root=data.FrameId==requestRootFrame&&!String.IsNullOrEmpty(requestRootFrame);
                string reason=before!=generation||navigation!=activeNavigation?"stale-context":!Exact(url)?"target":blockedPaths.Contains(Uri.UnescapeDataString(new Uri(url).AbsolutePath))?"blocked-path":null;
                string destination;
                if(headers.TryGetValue("Sec-Fetch-Dest",out destination)) {
                    destination=destination.Trim().ToLowerInvariant();
                    if(destination=="worker"||destination=="serviceworker"||destination=="sharedworker")reason="worker-bootstrap";
                }
                if(data.ResponseStatusPresent||data.ResponseErrorPresent)reason="unexpected-response-stage";
                if(mode=="local") {
                    if(!root)reason="non-root-frame";
                    if(!localPolicyVerified||!browserPolicyReady)reason="unverified-policy";
                    foreach(string name in new[]{"Origin","Referer"}) {
                        string header;if(headers.TryGetValue(name,out header)&&!Exact(header))reason=name=="Origin"?"foreign-origin":"foreign-referer";
                    }
                }
                // Revalidate after off-UI work. No await occurs between this
                // complete per-hop decision and the one continue/fail command.
                if(closing||disposed||requestPolicyFailed||before!=generation||navigation!=activeNavigation)reason="stale-context";
                if(averyParent!=null&&(!AveryLeaseCurrent(averyLease)||!root))reason="avery-context";
                if(averyParent!=null&&reason!=null)AveryState("request-refused-"+reason);
                if(averyParent!=null&&root&&data.ResourceType=="Document")AveryState("document-fetch-"+(reason??"allowed"));
                bool added=reason==null&&mode=="local";
                if(added)headers["X-DLMS-Desktop-Token"]=token;
                if(added&&root&&data.ResourceType=="Document"&&averyParent==null)TagAIFetch(url,headers);
                var outgoing=headers.Select(entry=>new{name=entry.Key,value=entry.Value}).ToArray();
                item.Reason=reason??"allowed";
                await ResolveRequest(item,reason==null,outgoing);
            }catch(Exception ex){
                failed=true;
                // Bounded failure categories only: no URL, ID, header, body,
                // token or native exception message enters diagnostics.
                if(!closing&&!disposed)Event("request-policy-error",new Dictionary<string,object>{
                    {"exception_type",ex.GetType().Name},{"hresult",ex.HResult},
                    {"reason",item==null?"metadata":item.Reason??"metadata"},
                    {"decision_sent",item!=null&&item.Sent},
                    {"native_callback_hresult",item!=null&&item.Protocol!=null&&item.Protocol.Task.Status==TaskStatus.RanToCompletion?(object)item.Protocol.Task.Result.Error:null},
                    {"same_generation",before==generation},{"same_navigation",navigation==activeNavigation}});
            }
            // Native csc is C#5: asynchronous exception handling follows catch.
            if(failed) {
                raw=null;
                if(item!=null&&!item.Sent&&!closing) {
                    try{await ResolveRequest(item,false,null);}catch{}
                }
                await FailRequestPolicy("request-protocol-exception");
            }
        }finally{
            raw=null;
            if(lease!=0&&requestLeases.Remove(lease))requestEnvelopeChars-=chars;
        }
    }
    async Task InstallRequestPolicy() {
        var tree=await Cdp("Page.getFrameTree",new{});
        var item=(Dictionary<string,object>)tree["frameTree"];
        var frame=(Dictionary<string,object>)item["frame"];
        requestRootFrame=TextValue(frame,"id");
        if(String.IsNullOrEmpty(requestRootFrame))throw new InvalidOperationException("Initial root frame unavailable");
        view.CoreWebView2.GetDevToolsProtocolEventReceiver("Fetch.requestPaused").DevToolsProtocolEventReceived+=async(s,e)=>await HandlePausedRequest(e.ParameterObjectAsJson);
        await Cdp("Fetch.enable",new{patterns=new[]{new{urlPattern="*",requestStage="Request"}},handleAuthRequests=false});
        Emit("initialization","request-policy-ready");
    }


    double qtScale=1.0,userZoom=1.0;
    TaskCompletionSource<bool> browserExited = new TaskCompletionSource<bool>();
    readonly HashSet<int> exitedBrowserIds = new HashSet<int>();
    sealed class PendingDownload { public CoreWebView2DownloadStartingEventArgs Args; public CoreWebView2Deferral Deferral; public long Generation; public ulong Navigation; public string Identity,Frame; public bool Blob,Completed; }
    sealed class Picker { public int Node; public string Frame, Identity; public long Generation; public ulong Navigation; public bool Multiple; }
    sealed class PendingDialog { public CoreWebView2ScriptDialogOpeningEventArgs Args; public CoreWebView2Deferral Deferral; public long Generation; public string Source; }
    sealed class Navigation { public string Url, Previous,AITag; public Dictionary<string,string> AIActions,PreviousAIActions; public readonly TaskCompletionSource<bool> AIReady=new TaskCompletionSource<bool>(); public DateTime Started; public bool Download, AttachmentResponse, AutomaticDownloadDenied,Completed; public int ResponseStatus; public long Generation; }
    [DllImport("user32.dll")] static extern IntPtr SetParent(IntPtr child, IntPtr parent);
    [DllImport("user32.dll",EntryPoint="GetWindowLong")] static extern int GetWindowLong(IntPtr h,int index);
    [DllImport("user32.dll",EntryPoint="SetWindowLong")] static extern int SetWindowLong(IntPtr h,int index,int value);
    [DllImport("user32.dll")] static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] static extern bool IsWindow(IntPtr h);
    [DllImport("user32.dll")] static extern uint GetDpiForWindow(IntPtr h);
    [DllImport("kernel32.dll")] static extern IntPtr GetStdHandle(int kind);
    [DllImport("kernel32.dll",SetLastError=true)] static extern bool SetHandleInformation(IntPtr handle,uint mask,uint flags);
    [DllImport("kernel32.dll",SetLastError=true)] static extern bool GetHandleInformation(IntPtr handle,out uint flags);
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern SafeFileHandle CreateFile(string path,uint access,uint share,IntPtr security,uint disposition,uint flags,IntPtr template);
    [DllImport("kernel32.dll",SetLastError=true)] static extern bool GetFileInformationByHandle(SafeFileHandle handle,out FileInformation information);
    [DllImport("wintrust.dll",ExactSpelling=true,PreserveSig=true)] static extern int WinVerifyTrust(IntPtr window,[MarshalAs(UnmanagedType.LPStruct)]Guid action,ref TrustData data);
    [StructLayout(LayoutKind.Sequential,CharSet=CharSet.Unicode)] struct TrustFile {
        public uint Size;[MarshalAs(UnmanagedType.LPWStr)] public string Path;public IntPtr File,Subject;
    }
    [StructLayout(LayoutKind.Sequential)] struct TrustData {
        public uint Size;public IntPtr Callback,Sip;public uint UI,Revocation,Choice;public IntPtr File;public uint Action;public IntPtr State,Url;public uint Flags,Context;public IntPtr SignatureSettings;
    }
    [StructLayout(LayoutKind.Sequential)] struct FileInformation {
        public uint Attributes;
        public System.Runtime.InteropServices.ComTypes.FILETIME Created,Accessed,Written;
        public uint Volume,SizeHigh,SizeLow,Links,IndexHigh,IndexLow;
    }
    static void SealPipe(IntPtr handle) {
        uint flags;
        if(!SetHandleInformation(handle,1,0)||!GetHandleInformation(handle,out flags)||(flags&1)!=0)
            throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error(),"Private renderer handle could not be sealed");
    }
    static void Pipes(bool input) {
        var encoding=new System.Text.UTF8Encoding(false);
        SealPipe(GetStdHandle(-11));SealPipe(GetStdHandle(-12));if(input)SealPipe(GetStdHandle(-10));
        Console.SetOut(new StreamWriter(new FileStream(new SafeFileHandle(GetStdHandle(-11),false),FileAccess.Write),encoding){AutoFlush=true});
        Console.SetError(new StreamWriter(new FileStream(new SafeFileHandle(GetStdHandle(-12),false),FileAccess.Write),encoding){AutoFlush=true});
        if(input)Console.SetIn(new StreamReader(new FileStream(new SafeFileHandle(GetStdHandle(-10),false),FileAccess.Read),encoding));
    }

    void Emit(string kind, object value) { if(averyParent!=null){if(kind=="fatal")AveryFailure("policy-failed");return;} lock(outputLock) Console.WriteLine(json.Serialize(new { @event=kind, value=value })); }
    void Event(string kind, Dictionary<string,object> fields) { if(averyParent!=null){AveryControllerEvent(kind,fields);return;} fields["event"]=kind; lock(outputLock)Console.WriteLine(json.Serialize(fields)); }
    void Reply(object id, bool ok, object value) { Event("reply",new Dictionary<string,object>{{"id",id},{"ok",ok},{"value",value}}); }
    void NavigationEvent(string kind,Navigation nav,ulong id,Dictionary<string,object> fields) {fields["generation"]=nav.Generation;fields["nav_id"]=id;Event(kind,fields);}
    bool Current(Navigation nav,ulong id) {return !closing&&!disposed&&nav.Generation==generation&&id==activeNavigation;}
    async void ExternalRequest(string target,bool user,bool redirected,string kind,CoreWebView2FrameInfo frame=null) {
        if(averyParent!=null){AveryStatus("External links are unavailable in this Avery preview.");return;}
        Navigation nav;
        string source=view.CoreWebView2.Source;
        // FrameInfo IDs are not supplied by every supported Runtime. A page
        // that has ever created a child frame is refused rather than assuming
        // that an exact top-level URL attributes a popup to its main frame.
        bool main=!documentHadChildFrame;
        if(kind=="popup")main=main&&frame!=null&&String.Equals(frame.Source,source,StringComparison.Ordinal);
        if(!user||redirected||!Exact(source)||!navigations.TryGetValue(activeNavigation,out nav)||!Current(nav,activeNavigation)||!nav.Completed)return;
        if(!main) {
            NavigationEvent("external-refused",nav,activeNavigation,new Dictionary<string,object>{{"source",source},{"mode",mode},{"user",true},{"kind",kind},{"refusal","frame-attribution"}});
            return;
        }
        Uri destination;
        if(!Uri.TryCreate(target,UriKind.Absolute,out destination)||(destination.Scheme!="http"&&destination.Scheme!="https")||destination.UserInfo.Length!=0)return;
        ulong id=activeNavigation;
        long inputEpoch=serverInputEpoch; // Pin before any asynchronous call.
        if(mode=="server"&&await ServerAIRequest(target,source,nav,id,inputEpoch))return;
        if(!Current(nav,id)||view.CoreWebView2.Source!=source)return;
        NavigationEvent("external-request",nav,id,new Dictionary<string,object>{{"url",target},{"source",source},{"mode",mode},{"user",true},{"kind",kind}});
    }
    static string TextValue(Dictionary<string,object> obj,string name,string fallback="") { return obj.ContainsKey(name)?Convert.ToString(obj[name]):fallback; }
    static bool Bool(Dictionary<string,object> obj,string name,bool fallback=false) { return obj.ContainsKey(name)?Convert.ToBoolean(obj[name]):fallback; }
    bool Exact(string value) {
        Uri u, expected=new Uri(origin);
        return Uri.TryCreate(value,UriKind.Absolute,out u) && (u.Scheme=="http"||u.Scheme=="https") &&
            u.Scheme==expected.Scheme && String.Equals(u.IdnHost,expected.IdnHost,StringComparison.OrdinalIgnoreCase) &&
            u.Port==expected.Port && u.UserInfo.Length==0;
    }
    static bool BlobDownloadUri(string value,string configuredOrigin) {
        if(value==null||!value.StartsWith("blob:",StringComparison.Ordinal))return false;
        Uri inner,expected;
        if(!Uri.TryCreate(value.Substring(5),UriKind.Absolute,out inner)||!Uri.TryCreate(configuredOrigin,UriKind.Absolute,out expected))return false;
        return (inner.Scheme=="http"||inner.Scheme=="https")&&inner.Scheme==expected.Scheme&&
            String.Equals(inner.IdnHost,expected.IdnHost,StringComparison.OrdinalIgnoreCase)&&inner.Port==expected.Port&&
            inner.UserInfo.Length==0&&inner.Query.Length==0&&inner.Fragment.Length==0&&value=="blob:"+inner.AbsoluteUri&&
            System.Text.RegularExpressions.Regex.IsMatch(inner.AbsolutePath,"^/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$");
    }
    bool StableDownloadDocument(long before,ulong navigation,string identity) {
        Navigation nav;
        return !closing&&!disposed&&before==generation&&navigation==activeNavigation&&identity!=null&&identity==documentIdentity&&
            Exact(view.CoreWebView2.Source)&&navigations.TryGetValue(navigation,out nav)&&Current(nav,navigation)&&nav.Completed;
    }
    void CompleteDownload(PendingDownload pending,bool cancel) {
        if(pending.Completed)return;
        if(cancel)pending.Args.Cancel=true;pending.Completed=true;pending.Deferral.Complete();
    }
    static void PrivatePath(string path,bool file) {
        if(String.IsNullOrWhiteSpace(path)||!Path.IsPathRooted(path)||path.StartsWith(@"\\")||path.IndexOf(':',2)>=0)
            throw new InvalidOperationException("An absolute local path without alternate streams is required");
        string full=Path.GetFullPath(path), p=file?Path.GetDirectoryName(full):full;
        while(p!=null) { string native=NativePath(p);if(Directory.Exists(native)&&(File.GetAttributes(native)&FileAttributes.ReparsePoint)!=0)throw new InvalidOperationException("Reparse-point path refused");p=Path.GetDirectoryName(p); }
        if(file&&(File.Exists(NativePath(full))||Directory.Exists(NativePath(full))))throw new InvalidOperationException("Existing output refused");
    }
    static string NativePath(string path) {
        // Native OPEN_REPARSE_POINT calls need the extended DOS form for long
        // paths. Accept no caller-supplied device/UNC/ADS namespace and only
        // canonicalize an absolute ASCII drive path before adding that prefix.
        if(String.IsNullOrWhiteSpace(path)||path.Length<3||
            !((path[0]>='A'&&path[0]<='Z')||(path[0]>='a'&&path[0]<='z'))||path[1]!=':'||
            (path[2]!='\\'&&path[2]!='/')||path.IndexOf(':',2)>=0||path.StartsWith(@"\\"))
            throw new InvalidOperationException("An absolute canonical local DOS path is required");
        string full=Path.GetFullPath(path).Replace('/','\\');
        if(full.Length>32760)throw new InvalidOperationException("Native path exceeds its bound");
        foreach(string component in full.Substring(3).Split('\\')) {
            if(component.Length==0)continue;
            string stem=component.Split('.')[0].Trim();
            if(component.EndsWith(" ",StringComparison.Ordinal)||component.EndsWith(".",StringComparison.Ordinal)||
                component.IndexOfAny(Path.GetInvalidFileNameChars())>=0||
                System.Text.RegularExpressions.Regex.IsMatch(stem,"^(CON|PRN|AUX|NUL|COM[1-9\u00b9\u00b2\u00b3]|LPT[1-9\u00b9\u00b2\u00b3])$",System.Text.RegularExpressions.RegexOptions.IgnoreCase))
                throw new InvalidOperationException("Ambiguous native path component refused");
        }
        return @"\\?\"+full;
    }
    void SetBackground(Color color) {
        view.DefaultBackgroundColor=color;
        if(mode!="server")return;
        BackColor=color;serverCover.BackColor=color;serverStatus.BackColor=color;
        serverStatus.ForeColor=(color.R*299+color.G*587+color.B*114)>=128000?Color.Black:Color.White;
    }
    double EffectiveZoom(double scale,double zoom) {
        if(Double.IsNaN(scale)||Double.IsInfinity(scale)||scale<0.25||scale>8)throw new InvalidOperationException("Invalid Qt display scale");
        uint dpi=GetDpiForWindow(Handle);if(dpi<24||dpi>768)throw new InvalidOperationException("Native window DPI is unavailable or unsupported");
        double effective=zoom*scale/(dpi/96.0);
        if(Double.IsNaN(effective)||Double.IsInfinity(effective)||effective<0.25||effective>5)throw new InvalidOperationException("Combined display scale and user zoom is outside the supported range");
        return effective;
    }
    void ApplyScale(double scale,double zoom) {
        double effective=EffectiveZoom(scale,zoom);
        view.ZoomFactor=effective;qtScale=scale;userZoom=zoom;
        Event("scale-state",new Dictionary<string,object>{{"qt_scale",qtScale},{"native_dpi",GetDpiForWindow(Handle)},{"user_zoom",userZoom},{"effective_zoom",effective},{"client_width",ClientSize.Width},{"client_height",ClientSize.Height}});
    }
    protected override void WndProc(ref Message message) {
        base.WndProc(ref message);
        if((message.Msg==0x0003||message.Msg==0x0047)&&!closing&&!disposed&&view.CoreWebView2!=null)view.NotifyPosition();
        if((message.Msg==0x02E0||message.Msg==0x02E3)&&!closing&&!disposed&&view.CoreWebView2!=null) {
            try{ApplyScale(qtScale,userZoom);}catch(Exception ex){Emit("scale-failed",ex.GetType().Name);}
        }
    }
    // Closed-purpose Avery destination. Each instance retains its own CDP,
    // request, frame and navigation state; only the root owns environment/pins.
    readonly DesktopRenderer averyParent;
    DesktopRenderer averyChild;
    readonly List<DesktopRenderer> retiredAvery=new List<DesktopRenderer>();
    AveryOpen averyOpening,averyLease;
    Task averyCreation,averyClose;
    readonly TaskCompletionSource<bool> averyPolicyReady=new TaskCompletionSource<bool>();
    int averyBootstrapRequests;
    Label averyLabel;
    bool averyInitialNavigation;
    int averyRecords;
    long serverCoverSerial;
    // Avery-only native print authority. No path, printer or command is accepted
    // from page JavaScript; the private observer only asks for the native UI.
    const string AveryPrintWorld="DLMSDesktopAveryPrint",AveryPrintBinding="__dlmsAveryPrint";
    internal const string AveryPrintObserver=@"(function(nonce){
        'use strict';
        if(self!==top)return;
        let sequence=0;
        document.addEventListener('keydown',function(e){
            if(e.isTrusted&&e.repeat&&(e.key==='Enter'||e.key===' ')&&e.target instanceof Element&&
               e.target.closest('button')===document.querySelector('button[onclick=""window.print()""]')){
                e.preventDefault();e.stopImmediatePropagation();
            }
        },true);
        document.addEventListener('click',function(e){
            if(!e.isTrusted||e.button!==0||!navigator.userActivation.isActive)return;
            const button=e.target instanceof Element?e.target.closest('button'):null;
            if(!button||button!==document.querySelector('button[onclick=""window.print()""]')||
               button.type!=='button'||button.disabled||button.textContent.trim()!=='Print Cards')return;
            e.preventDefault();e.stopImmediatePropagation();
            __dlmsAveryPrint(JSON.stringify({nonce:nonce,sequence:++sequence}));
        },true);
    })";
    internal sealed class AveryPrintPermit {
        internal readonly int Context;internal readonly string Nonce,Identity;
        long sequence;
        internal AveryPrintPermit(int context,string nonce,string identity){Context=context;Nonce=nonce;Identity=identity;}
        internal bool Take(int context,string nonce,long next,bool current) {
            if(!current||Context<=0||context!=Context||nonce!=Nonce||next<=0||next!=sequence+1)return false;
            sequence=next;return true;
        }
    }
    AveryPrintPermit averyPrint;
    async Task ConfigureAveryPrint(Navigation nav,ulong id) {
        averyPrint=null;
        if(!AveryPrintCurrent(nav,id))return;
        var context=await Cdp("Page.createIsolatedWorld",new{frameId=mainFrame,worldName=AveryPrintWorld,grantUniveralAccess=false});
        if(!AveryPrintCurrent(nav,id))return;
        int contextId=Convert.ToInt32(context["executionContextId"]);
        var permit=new AveryPrintPermit(contextId,Guid.NewGuid().ToString("N"),documentIdentity);
        averyPrint=permit;
        var result=await Cdp("Runtime.evaluate",new{contextId=contextId,
            expression=AveryPrintObserver+"("+json.Serialize(permit.Nonce)+");true",returnByValue=true});
        if(!ReferenceEquals(averyPrint,permit)||!AveryPrintCurrent(nav,id)||result.ContainsKey("exceptionDetails")) {
            if(ReferenceEquals(averyPrint,permit))averyPrint=null;
            throw new InvalidOperationException("Avery print context changed");
        }
        AveryState("print-ready");
    }
    bool AveryPrintCurrent(Navigation nav,ulong id) {
        return averyParent!=null&&ReferenceEquals(averyParent.averyChild,this)&&
            !closing&&!disposed&&!requestPolicyFailed&&browserPolicyReady&&!documentHadChildFrame&&
            AveryLeaseCurrent(averyLease)&&Current(nav,id)&&nav.Completed&&documentIdentity!=null&&
            view.CoreWebView2!=null&&AveryUrl(view.CoreWebView2.Source,"/anki/printable");
    }
    void AveryPrintRequested(string args) {
        try {
            var data=json.Deserialize<Dictionary<string,object>>(args);
            if(TextValue(data,"name")!=AveryPrintBinding)return;
            Navigation nav;ulong id=activeNavigation;var permit=averyPrint;
            if(permit==null||!navigations.TryGetValue(id,out nav))return;
            string payload=TextValue(data,"payload");if(payload.Length>256)return;
            var request=json.Deserialize<Dictionary<string,object>>(payload);
            if(request.Count!=2||!(request["sequence"] is int))return;
            // No await/re-entrant page evaluation between the final native
            // ownership check, one-use consume, and printing THIS child.
            if(!permit.Take(Convert.ToInt32(data["executionContextId"]),TextValue(request,"nonce"),
                Convert.ToInt64(request["sequence"]),AveryPrintCurrent(nav,id)&&permit.Identity==documentIdentity)) {
                AveryState("print-refused");return;
            }
            view.CoreWebView2.ShowPrintUI(CoreWebView2PrintDialogKind.Browser);
            AveryStatus("Print preview opened. Choose a printer or Save as PDF, or Cancel. Return keeps the source selection.");
            AveryState("print-ui-requested"); // Not evidence of a saved/printed file.
        }catch(Exception) {
            if(!closing&&!disposed){AveryStatus("The print dialog could not open. Return to the source deck and retry the preview.");AveryState("print-ui-failed");}
        }
    }
    sealed class AveryOpen {
        public CoreWebView2NewWindowRequestedEventArgs Args;
        public CoreWebView2Deferral Deferral;
        public DesktopRenderer Child;
        public long Generation;public ulong Navigation;
        public string Identity,Source,Frame;
        public bool Cancelled,Completed,WarningShown;
    }
    bool AveryUrl(string value,string path) {
        Uri parsed;
        return Exact(value)&&Uri.TryCreate(value,UriKind.Absolute,out parsed)&&
            parsed.AbsolutePath==path&&parsed.Query.Length==0&&parsed.Fragment.Length==0;
    }
    internal static bool AveryHeadersAllowed(string mode,string origin,string source,bool hasOrigin,string requestOrigin,bool hasReferer,string referer) {
        if(mode=="local")return hasOrigin&&hasReferer&&requestOrigin==origin&&referer==source;
        // A Server's no-referrer response policy legitimately removes Referer
        // and serializes Origin as null. Headers never establish authority:
        // the caller still requires the full native one-use opener/frame lease.
        if(mode!="server")return false;
        return (!hasOrigin||requestOrigin=="null"||requestOrigin==origin)&&(!hasReferer||referer==source);
    }
    bool AveryLeaseCurrent(AveryOpen lease) {
        var owner=averyParent??this;Navigation nav;
        return lease!=null&&!lease.Cancelled&&!owner.closing&&!owner.disposed&&
            !owner.requestPolicyFailed&&owner.browserPolicyReady&&(owner.mode!="local"||owner.localPolicyVerified)&&
            owner.generation==lease.Generation&&owner.activeNavigation==lease.Navigation&&
            owner.documentIdentity==lease.Identity&&owner.mainFrame==lease.Frame&&
            owner.view.CoreWebView2!=null&&owner.view.CoreWebView2.Source==lease.Source&&
            owner.AveryUrl(lease.Source,"/anki/custom")&& !owner.documentHadChildFrame&&
            (owner.mode!="server"||(!owner.serverCover.Visible&&owner.view.Visible))&&
            owner.navigations.TryGetValue(lease.Navigation,out nav)&&owner.Current(nav,lease.Navigation)&&nav.Completed;
    }
    void AveryState(string state) {
        var owner=averyParent??this;
        if(owner.averyRecords++<96)owner.Event("avery-state",new Dictionary<string,object>{{"state",state},{"mode",mode},{"source_generation",owner.generation},{"utc",DateTime.UtcNow.ToString("o")}});
    }
    void AveryStatus(string message) {if(averyLabel!=null&&!averyLabel.IsDisposed)averyLabel.Text=message;}
    void AveryFailure(string state) {
        AveryStatus("Avery preview stopped safely. Return to the unchanged custom deck and retry after the page is ready.");
        AveryState(state);ObserveRequestTask(Shutdown());
    }
    void AveryControllerEvent(string kind,Dictionary<string,object> fields) {
        if(kind=="policy-blocked")AveryState("resource-refused-"+TextValue(fields,"reason"));
        if(kind=="load-finish") {
            bool ok=fields.ContainsKey("ok")&&Convert.ToBoolean(fields["ok"]);
            AveryStatus(ok?"Avery preview. Use Print Cards for the native print dialog; Return preserves the source deck. Downloads and file selection remain unavailable.":"Avery preview did not load. Return to the source deck; no selection was changed.");
            AveryState(ok?"rendered":"load-failed");
            var detail=new Dictionary<string,object>();
            foreach(string key in new[]{"error","http_status","identity_error","navigation_success"})if(fields.ContainsKey(key))detail[key]=fields[key];
            detail["event"]="avery-load-result";averyParent.Event("avery-load-result",detail);
        }
        // Never alias child events to the primary Python renderer's identities,
        // dialogs, downloads, print, ready or retirement command transactions.
    }
    void ConfigureAveryWindow() {
        Text="DLMS Avery preview - "+(mode=="local"?"Local":"Server "+origin);
        // The production root is embedded in Qt. Runtime155 refuses a
        // controller under a separate top-level root (0x8007139F). Keep this
        // Avery-only transient under that exact owned root, without reparenting
        // a live controller or navigating/hiding the original page.
        TopLevel=false;FormBorderStyle=FormBorderStyle.None;Dock=DockStyle.Fill;ShowInTaskbar=false;
        averyParent.Controls.Add(this);
        var bar=new FlowLayoutPanel{Dock=DockStyle.Top,Height=68,AutoSize=false,WrapContents=false,Padding=new Padding(8)};
        var back=new Button{Text="Return to custom deck",AutoSize=true,TabStop=true};
        back.Click+=async(s,e)=>await Shutdown();
        averyLabel=new Label{Text="Preparing the original Avery request...",AutoSize=false,Width=750,Height=52,UseMnemonic=false};
        bar.Controls.Add(back);bar.Controls.Add(averyLabel);Controls.Add(bar);bar.SendToBack();
    }
    // Presentation only: the caller supplies the existing native ownership lease.
    // A real cover or invalidated owner retires the preview, never merely buries it.
    internal static async Task<string> ApplyServerCoverStack(Control browser,Control cover,
        Control preview,bool shown,bool browserVisible,bool previewCurrent,bool previewShown,Func<Task> retire,Func<bool> current) {
        if(!current())return "superseded";
        if(shown||!browserVisible||(preview!=null&&!previewCurrent)) {
            await retire();preview=null;
        }
        // Retirement can yield; a later cover/navigation/close owns presentation.
        if(!current())return "superseded";
        browser.Visible=browserVisible;cover.Visible=shown;
        if(shown){cover.BringToFront();return "cover";}
        if(preview!=null&&!preview.IsDisposed&&previewCurrent&&previewShown) {
            preview.BringToFront();return "preview";
        }
        browser.BringToFront();return "source";
    }
    bool CompleteAvery(AveryOpen lease,bool allow) {
        if(lease.Completed)return true;lease.Completed=true;
        try {
            if(!allow)lease.Cancelled=true;
            lease.Deferral.Complete();return true;
        }catch {ObserveRequestTask(FailRequestPolicy("avery-deferral-completion"));return false;}
    }
    void BeginAvery(CoreWebView2NewWindowRequestedEventArgs args) {
        Navigation nav;string source=view.CoreWebView2.Source;
        if(closing||disposed||averyOpening!=null||averyChild!=null||retiredAvery.Count>=32||
            !args.IsUserInitiated||!AveryUrl(source,"/anki/custom")||!AveryUrl(args.Uri,"/anki/printable")||
            documentHadChildFrame||args.OriginalSourceFrameInfo==null||args.OriginalSourceFrameInfo.Source!=source||
            documentIdentity==null||String.IsNullOrEmpty(mainFrame)||!browserPolicyReady||
            !navigations.TryGetValue(activeNavigation,out nav)||!Current(nav,activeNavigation)||!nav.Completed) {
            AveryState("refused");return;
        }
        // This immutable host lease is rechecked after every asynchronous phase.
        // Do not evaluate opener JavaScript while its window request is deferred.
        var lease=new AveryOpen{Args=args,Deferral=args.GetDeferral(),Generation=generation,
            Navigation=activeNavigation,Identity=documentIdentity,Source=source,Frame=mainFrame};
        averyOpening=lease;AveryState("admitted");
        ObserveRequestTask(OpenAvery(lease));ObserveRequestTask(AveryDeadline(lease));
    }
    async Task AveryDeadline(AveryOpen lease) {
        await Task.Delay(15000);
        if(averyOpening==lease&&!lease.Completed){bool report=AveryLeaseCurrent(lease);AveryState("initialization-timeout");await RetireAvery();if(report)AveryInitializationWarning(lease);}
    }
    void AveryInitializationWarning(AveryOpen lease) {
        if(lease.WarningShown||closing||disposed||view.CoreWebView2==null||
            generation!=lease.Generation||activeNavigation!=lease.Navigation||documentIdentity!=lease.Identity)return;
        lease.WarningShown=true;
        MessageBox.Show(this,"The Avery preview could not start safely. Your custom deck and selection are unchanged. Retry after the page is ready.",
            "Avery preview unavailable",MessageBoxButtons.OK,MessageBoxIcon.Warning);
    }
    async Task PrepareAveryController(AveryOpen lease) {
        if(!AveryLeaseCurrent(lease))throw new InvalidOperationException("Stale Avery owner");
        environment=averyParent.environment;
        policyDirectory=averyParent.policyDirectory;expectedExtensionId=averyParent.expectedExtensionId;
        blockedPaths.UnionWith(averyParent.blockedPaths);
        if(mode=="local")await LocalPreflight();
        if(!AveryLeaseCurrent(lease))throw new InvalidOperationException("Avery owner changed before controller creation");
        // No Navigate, Source assignment, Embed, reader or new environment.
        // Materialize the hidden form's HWND first: otherwise WinForms may
        // park the view under an unrelated native window despite Controls.Add.
        var ownedWindow=Handle;if(!IsWindow(ownedWindow))throw new InvalidOperationException("Avery owned window is unavailable");
        averyCreation=view.EnsureCoreWebView2Async(environment);await averyCreation;
        if(!AveryLeaseCurrent(lease))throw new InvalidOperationException("Avery owner changed during controller creation");
        var core=view.CoreWebView2;
        if(!ReferenceEquals(environment,averyParent.environment)||core.BrowserProcessId!=averyParent.view.CoreWebView2.BrowserProcessId||
            core.Profile.ProfileName!=averyParent.view.CoreWebView2.Profile.ProfileName||
            core.Profile.ProfilePath!=averyParent.view.CoreWebView2.Profile.ProfilePath||
            !(String.IsNullOrEmpty(core.Source)||core.Source=="about:blank"))throw new InvalidOperationException("Avery destination profile or blank state mismatch");
        ConfigureControllerSettings();
        await core.AddScriptToExecuteOnDocumentCreatedAsync("Object.defineProperty(window,'print',{value:()=>alert('Use the Print Cards button to open the native print dialog.'),writable:false,configurable:false})");
        if(!AveryLeaseCurrent(lease))throw new InvalidOperationException("Avery owner changed during settings initialization");
    }
    async Task VerifyBorrowedAveryPolicy() {
#if DLMS_AI_TEST
        // Reuse the existing source-only lifetime-probe build. Normal payloads
        // contain no bootstrap delay and cannot enable this retirement fault.
        await Task.Delay(800);
#endif
        if(!AveryLeaseCurrent(averyLease))throw new InvalidOperationException("Avery owner retired");
        averyParent.CheckStablePolicyDirectory();averyParent.VerifyRuntimeComponents();
        var installed=await view.CoreWebView2.Profile.GetBrowserExtensionsAsync();
        if(!AveryLeaseCurrent(averyLease)||installed.Any(item=>!ExpectedExtension(item))||
            installed.Count(item=>item.Id==expectedExtensionId&&item.Name==PolicyName&&item.IsEnabled)!=1)
            throw new InvalidOperationException("Avery inherited policy was not exclusively enabled");
    }
    async Task OpenAvery(AveryOpen lease) {
        bool delivered=false,reportFailure=false;
        try {
            if(!AveryLeaseCurrent(lease))throw new InvalidOperationException("Stale Avery request");
            var settings=new Dictionary<string,object>(config);settings["parent_hwnd"]=0;
            var child=new DesktopRenderer(settings,this);child.averyLease=lease;lease.Child=child;averyChild=child;
            await child.PrepareAveryController(lease);
            if(!AveryLeaseCurrent(lease))throw new InvalidOperationException("Avery opener retired");
            // Microsoft requires handlers tied to replaced web contents AFTER
            // assignment. Keep this deferral pending through Fetch/WRR policy.
            lease.Args.NewWindow=child.view.CoreWebView2;
            await child.AttachControllerPolicy();
            if(!AveryLeaseCurrent(lease)||child.closing||child.disposed||!child.browserPolicyReady)
                throw new InvalidOperationException("Avery request changed before handback");
            child.ApplyScale(qtScale,userZoom);child.Show();child.BringToFront();
            if(!AveryLeaseCurrent(lease))throw new InvalidOperationException("Avery opener changed before completion");
            AveryState("policy-ready");delivered=CompleteAvery(lease,true);
            if(delivered)AveryState("opened");
        }catch {AveryState("initialization-refused");reportFailure=AveryLeaseCurrent(lease);}
        // C#5: all async cleanup follows catch, never an async finally block.
        if(!delivered){CompleteAvery(lease,false);if(lease.Child!=null)await lease.Child.CloseAveryController();}
        if(averyOpening==lease)averyOpening=null;
        if(reportFailure)AveryInitializationWarning(lease);
    }
    bool AveryNavigation(CoreWebView2NavigationStartingEventArgs args) {
        if(!AveryLeaseCurrent(averyLease)){args.Cancel=true;ObserveRequestTask(Shutdown());return false;}
        if(AveryUrl(args.Uri,"/anki/custom")&&args.IsUserInitiated&&!args.IsRedirected) {
            args.Cancel=true;AveryState("return");ObserveRequestTask(Shutdown());return false;
        }
        if(averyInitialNavigation||args.IsRedirected||!AveryUrl(args.Uri,"/anki/printable")) {
            args.Cancel=true;AveryStatus("This Avery preview cannot navigate elsewhere. Return to the source deck.");return false;
        }
        averyInitialNavigation=true;return true;
    }
    async Task RetireAvery() {
        var lease=averyOpening;var child=averyChild??(lease==null?null:lease.Child);
        if(lease!=null){lease.Cancelled=true;CompleteAvery(lease,false);}
        if(child!=null){if(child.averyLease!=null)child.averyLease.Cancelled=true;await child.CloseAveryController();}
        if(averyOpening==lease)averyOpening=null;
    }
    Task CloseAveryController() {
        if(averyClose==null)averyClose=CloseAveryControllerCore();return averyClose;
    }
    async Task CloseAveryControllerCore() {
        averyPrint=null;
        closing=true;browserPolicyReady=false;averyPolicyReady.TrySetResult(false);
        if(averyLease!=null)averyLease.Cancelled=true;
        // BrowserSurface cancels a late CreateController result on disposal.
        try{view.Dispose();}catch{AveryState("controller-close-failed");}
        disposed=true;
        if(averyCreation!=null){try{await averyCreation;}catch{}}
        // Keep any outstanding native callback references until ROOT browser
        // retirement. The admission quota bounds retained closed controllers.
        if(!averyParent.retiredAvery.Contains(this))averyParent.retiredAvery.Add(this);
        if(averyParent.averyChild==this)averyParent.averyChild=null;
        AveryState("closed");Close();
        if(!averyParent.closing&&!averyParent.disposed)averyParent.view.Focus();
        // Never wait for shared BrowserProcessExited or release parent pins.
    }

    public DesktopRenderer(Dictionary<string,object> settings) : this(settings,null) {}
    DesktopRenderer(Dictionary<string,object> settings,DesktopRenderer owner) {
        averyParent=owner;config=settings;origin=TextValue(config,"origin").TrimEnd('/');mode=TextValue(config,"mode");token=TextValue(config,"token");
        Uri endpoint;
        if(!Uri.TryCreate(origin+"/",UriKind.Absolute,out endpoint)||!Exact(origin+"/")||endpoint.AbsolutePath!="/"||endpoint.Query.Length!=0||endpoint.Fragment.Length!=0)
            throw new InvalidOperationException("Invalid origin");
        if(mode!="local"&&mode!="server")throw new InvalidOperationException("Invalid mode");
        if(mode=="local"&&(endpoint.Scheme!="http"||endpoint.Host!="127.0.0.1"||endpoint.Port<1024||token.Length<32||token.Any(c=>!Uri.IsHexDigit(c))))
            throw new InvalidOperationException("Local renderer needs an owned loopback endpoint and nonce");
        if(mode=="server"&&token.Length!=0)throw new InvalidOperationException("Server renderer must not receive a Local nonce");
        PrivatePath(TextValue(config,"storage"),false);
        Text="DLMS Desktop";AutoScaleMode=AutoScaleMode.None;ClientSize=new Size(1280,816);StartPosition=FormStartPosition.Manual;Location=new Point(40,40);
        view.Dock=DockStyle.Fill;view.AllowExternalDrop=false;Controls.Add(view);
        view.FocusBoundary+=reason=> {
            if(averyParent!=null){SelectNextControl(view,reason==CoreWebView2MoveFocusReason.Next,true,true,true);return;}
            if(!closing&&!disposed&&view.CoreWebView2!=null&&Exact(view.CoreWebView2.Source))
                Event("focus-boundary",new Dictionary<string,object>{{"generation",generation},{"nav_id",activeNavigation},{"direction",reason==CoreWebView2MoveFocusReason.Next?"next":"previous"}});
        };
        if(mode=="server") {
            serverCover.Dock=DockStyle.Fill;serverCover.Visible=false;serverCover.AccessibleName="Server connection status";
            serverStatus.Dock=DockStyle.Fill;serverStatus.TextAlign=ContentAlignment.MiddleCenter;serverStatus.UseMnemonic=false;
            serverStatus.AutoEllipsis=false;serverStatus.AccessibleName="Server connection status";serverStatus.Padding=new Padding(28);
            serverCover.Controls.Add(serverStatus);Controls.Add(serverCover);SetBackground(Color.White);
        }
        if(averyParent==null)Shown+=async(s,e)=> { bool failed=false;try { Embed();await Initialize();StartReader(); }catch(Exception ex){Environment.ExitCode=1;Emit("fatal",new{type=ex.GetType().Name,message=ex.Message});failed=true;}if(failed)await Shutdown(); };
        if(averyParent!=null)ConfigureAveryWindow();
        FormClosing+=(s,e)=> { if(!disposed){e.Cancel=true;if(!closing){if(averyParent!=null)ObserveRequestTask(Shutdown());else Event("close-requested",new Dictionary<string,object>());}} };
    }
    void Embed() {
        if(!config.ContainsKey("parent_hwnd")||Convert.ToInt64(config["parent_hwnd"])==0)return;
        var parent=new IntPtr(Convert.ToInt64(config["parent_hwnd"]));if(!IsWindow(parent))throw new InvalidOperationException("Invalid owning window");
        FormBorderStyle=FormBorderStyle.None;ShowInTaskbar=false;
        SetWindowLong(Handle,-16,(GetWindowLong(Handle,-16)&~unchecked((int)0x80000000))|0x40000000);
        SetParent(Handle,parent);Location=Point.Empty;
    }
    async Task<string> Identity() {
        if(!Exact(view.CoreWebView2.Source))return null;
        object value=await Evaluate("JSON.stringify({href:location.href,timeOrigin:performance.timeOrigin})",1);
        return value as string;
    }
    async Task<Dictionary<string,object>> Cdp(string method,object args) {
        string result=await view.CoreWebView2.CallDevToolsProtocolMethodAsync(method,json.Serialize(args));
        return json.Deserialize<Dictionary<string,object>>(result);
    }
    async Task<string> Frame() {
        var tree=await Cdp("Page.getFrameTree",new{});
        var item=(Dictionary<string,object>)tree["frameTree"];var frame=(Dictionary<string,object>)item["frame"];
        if(!Exact(Convert.ToString(frame["url"])))throw new InvalidOperationException("Evaluation refused outside configured origin");
        return Convert.ToString(frame["id"]);
    }
    async Task<object> Evaluate(string script,int world,bool gesture=false) {
        if(!Exact(view.CoreWebView2.Source))throw new InvalidOperationException("Evaluation refused outside configured origin");
        long before=generation;string frame=await Frame();
        if(before!=generation||closing)throw new InvalidOperationException("Document changed during frame lookup");
        var args=new Dictionary<string,object>{{"expression",script},{"awaitPromise",true},{"returnByValue",true},{"userGesture",gesture}};
        if(world!=0) {
            var context=await Cdp("Page.createIsolatedWorld",new{frameId=frame,worldName="DLMSDesktopNative",grantUniveralAccess=false});
            args["contextId"]=context["executionContextId"];
        }
        else {int context;if(!mainContexts.TryGetValue(frame,out context))throw new InvalidOperationException("Main execution context unavailable");args["contextId"]=context;}
        if(before!=generation||!Exact(view.CoreWebView2.Source))throw new InvalidOperationException("Document changed during evaluation");
        var reply=await Cdp("Runtime.evaluate",args);
        if(before!=generation)throw new InvalidOperationException("Stale evaluation result");
        if(reply.ContainsKey("exceptionDetails"))throw new InvalidOperationException("JavaScript evaluation failed");
        var result=(Dictionary<string,object>)reply["result"];
        return result.ContainsKey("value")?result["value"]:null;
    }
    async Task Initialize() {
        if(mode=="local"){Emit("initialization","local-preflight");await LocalPreflight();}
        Emit("initialization","policy-files");PreparePolicyFiles();
        Emit("initialization", "environment");
        var options=new CoreWebView2EnvironmentOptions {ExclusiveUserDataFolderAccess=true,AreBrowserExtensionsEnabled=true,AdditionalBrowserArguments=BrowserArguments};
        environment=await CoreWebView2Environment.CreateAsync(null,TextValue(config,"storage"),options);
        if(!String.Equals(Path.GetFullPath(environment.UserDataFolder).TrimEnd('\\'),Path.GetFullPath(TextValue(config,"storage")).TrimEnd('\\'),StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("WebView2 storage was redirected outside the owned private folder");
        environment.BrowserProcessExited+=(s,e)=>{exitedBrowserIds.Add(checked((int)e.BrowserProcessId));Event("browser-exited",new Dictionary<string,object>{{"pid",e.BrowserProcessId},{"kind",e.BrowserProcessExitKind.ToString()}});browserExited.TrySetResult(true);};
        Emit("initialization", "controller");
        await view.EnsureCoreWebView2Async(environment);
        ConfigureControllerSettings();
        await AttachControllerPolicy();
        Emit("initialization", "ready");Event("runtime",new Dictionary<string,object>{{"version",environment.BrowserVersionString},{"pid",browserPid},{"storage",environment.UserDataFolder},{"exclusive_storage",true},{"host_objects",false},{"web_messages",false},{"custom_browser_arguments",BrowserArguments},{"sandbox","default"},{"certificate_validation","default-refuse-errors"},{"extensions_enabled",true},{"private_extensions_enabled",true},{"shared_workers","blink-feature-disabled"},{"service_worker_bootstrap","best-effort-native-http-guard"},{"service_workers_cleared",true},{"worker_policy_configured","DNR-append-CSP-worker-src-none"},{"socket_policy_configured","private-static-DNR-v2"},{"socket_policy_id",expectedExtensionId}});
        Event("ready",new Dictionary<string,object>{{"hwnd",Handle.ToInt64()},{"version",environment.BrowserVersionString}});
    }
    void ConfigureControllerSettings() {
        var core=view.CoreWebView2;
        core.Settings.AreHostObjectsAllowed=false;core.Settings.IsWebMessageEnabled=false;core.Settings.AreDevToolsEnabled=false;
        core.Settings.AreDefaultContextMenusEnabled=false;core.Settings.IsStatusBarEnabled=false;core.Settings.IsPasswordAutosaveEnabled=false;
        core.Settings.IsGeneralAutofillEnabled=false;core.Settings.AreBrowserAcceleratorKeysEnabled=false;
        core.Settings.AreDefaultScriptDialogsEnabled=false;
        core.Profile.AreWebViewScriptApisEnabledForServiceWorkers=false;
    }
    async Task AttachControllerPolicy() {
        Emit("initialization", "policy");
        var core=view.CoreWebView2;browserPid=(int)core.BrowserProcessId;
        core.NavigationStarting+=(s,e)=> {
            if(averyParent!=null&&!AveryNavigation(e))return;
            if(!Exact(e.Uri)){e.Cancel=true;ExternalRequest(e.Uri,e.IsUserInitiated,e.IsRedirected,"navigation");return;}
            if(averyParent==null)ObserveRequestTask(RetireAvery());
            Navigation redirect;
            if(e.IsRedirected&&e.NavigationId==activeNavigation&&navigations.TryGetValue(e.NavigationId,out redirect)&&Current(redirect,e.NavigationId)) {
                RetireAI();
                redirect.AITag=Guid.NewGuid().ToString("N");redirect.AIActions=null;
                redirect.Url=e.Uri;
                NavigationEvent("navigation-redirect",redirect,e.NavigationId,new Dictionary<string,object>{{"url",e.Uri}});return;
            }
            Navigation prior;
            var previousAI=navigations.TryGetValue(activeNavigation,out prior)&&prior.Completed&&
                aiContext!=0&&aiActions!=null&&aiIdentity!=null&&aiIdentity==documentIdentity?aiActions.Policy():null;
            generation++;activeNavigation=e.NavigationId;pickers.Clear();
            averyPrint=null;
            RetireAI();
            var next=new Navigation{Url=e.Uri,Previous=documentIdentity,Started=DateTime.UtcNow,Generation=generation};
            next.PreviousAIActions=previousAI;
            next.AITag=Guid.NewGuid().ToString("N");
            navigations[e.NavigationId]=next;
            // Dictionary enumeration is slot order, not insertion order on
            // .NET Framework. Reused slots can put the newest navigation first.
            // Retire by generation and never evict the active navigation.
            if(navigations.Count>32)navigations.Remove(navigations.Where(item=>item.Key!=activeNavigation).OrderBy(item=>item.Value.Generation).First().Key);
            NavigationEvent("load-start",next,e.NavigationId,new Dictionary<string,object>{{"url",e.Uri}});
        };
        core.FrameNavigationStarting+=(s,e)=>{if(mode=="local"||averyParent!=null||!Exact(e.Uri))e.Cancel=true;};
        core.FrameCreated+=(s,e)=>{documentHadChildFrame=true;if(averyParent!=null)AveryFailure("frame-refused");else if(mode=="local")LocalViolation("A Local frame context was blocked");};
        core.DedicatedWorkerCreated+=(s,e)=>{if(averyParent!=null)AveryFailure("worker-refused");else if(mode=="local")LocalViolation("A Local worker context was blocked");};
        core.SourceChanged+=async(s,e)=> {
            Navigation nav;if(!navigations.TryGetValue(activeNavigation,out nav)||!Current(nav,activeNavigation))return;ulong id=activeNavigation;
            NavigationEvent("url",nav,id,new Dictionary<string,object>{{"url",core.Source}});
            if(!e.IsNewDocument){try{string identity=await Identity();if(Current(nav,id))documentIdentity=identity;}catch{}}
        };
        core.NavigationCompleted+=async(s,e)=>await NavigationFinished(e);
        core.NewWindowRequested+=(s,e)=> {
            e.Handled=true;
            if(averyParent!=null){AveryStatus("Additional windows are unavailable in this Avery preview.");return;}
            if(Exact(e.Uri)) {
                if(new Uri(e.Uri).AbsolutePath=="/anki/printable"){BeginAvery(e);return;}
                // Preserve the existing unrelated same-origin popup policy.
                if(mode=="local"&&e.IsUserInitiated&&!documentHadChildFrame)core.Navigate(e.Uri);
                return;
            }
            ExternalRequest(e.Uri,e.IsUserInitiated,false,"popup",e.OriginalSourceFrameInfo);
        };
        core.LaunchingExternalUriScheme+=(s,e)=>e.Cancel=true;
        core.BasicAuthenticationRequested+=(s,e)=>e.Cancel=true;
        core.WindowCloseRequested+=(s,e)=>{if(averyParent!=null)ObserveRequestTask(Shutdown());else Event("close-requested",new Dictionary<string,object>());};
        core.ScriptDialogOpening+=(s,e)=> {
            if(averyParent!=null){AveryStatus("Printing and page dialogs are unavailable in this preview. Return to the deck without changing its selection.");return;}
            if(closing||!Exact(e.Uri)||!Exact(core.Source)||dialogs.Count!=0)return; // No Accept means false/cancel.
            string ticket=Guid.NewGuid().ToString("N");
            dialogs[ticket]=new PendingDialog{Args=e,Deferral=e.GetDeferral(),Generation=generation,Source=core.Source};
            Event("script-dialog",new Dictionary<string,object>{{"ticket",ticket},{"kind",e.Kind.ToString()},{"message",e.Message},{"default",e.DefaultText},{"url",e.Uri}});
        };
        core.PermissionRequested+=(s,e)=> {
            e.SavesInProfile=false;e.State=CoreWebView2PermissionState.Deny;
            Navigation nav;if(e.PermissionKind==CoreWebView2PermissionKind.MultipleAutomaticDownloads&&Exact(e.Uri)&&navigations.TryGetValue(activeNavigation,out nav)&&Current(nav,activeNavigation))nav.AutomaticDownloadDenied=true;
            if(permissionRecords++<64)Event("permission",new Dictionary<string,object>{{"kind",e.PermissionKind.ToString()},{"user",e.IsUserInitiated},{"decision","deny"},{"generation",generation},{"nav_id",activeNavigation}});
        };
        core.ServerCertificateErrorDetected+=(s,e)=>{e.Action=CoreWebView2ServerCertificateErrorAction.Cancel;Event("certificate-refused",new Dictionary<string,object>());};
        core.ProcessFailed+=(s,e)=>{if(averyParent!=null)AveryFailure("renderer-failed");else {ObserveRequestTask(RetireAvery());Event("process-failed",new Dictionary<string,object>{{"kind",e.ProcessFailedKind.ToString()},{"reason",e.Reason.ToString()}});}};
        core.AddWebResourceRequestedFilter("*",CoreWebView2WebResourceContext.All,CoreWebView2WebResourceRequestSourceKinds.All);
        core.WebResourceRequested+=async(s,e)=> {
            CoreWebView2Deferral bootstrap=null;
            try {
            if(averyParent!=null&&!browserPolicyReady) {
                bootstrap=e.GetDeferral();
                // Runtime155 begins the engine-owned original request during
                // NewWindow assignment, before Complete and Fetch.enable.
                // Admit exactly this once-bound native main-document POST;
                // every other pre-Fetch request fails closed. Windows omits Sec-Fetch
                // headers here; native top-level navigation, Document source
                // and the immutable attributed opener lease bind this request.
                // Local additionally requires exact Origin/Referer. Server's
                // no-referrer policy may omit them; foreign headers still fail.
                // Never inspect, reconstruct or replay the original body.
                long bootstrapGeneration=generation;ulong bootstrapNavigation=activeNavigation;
                bool original=++averyBootstrapRequests==1&&AveryLeaseCurrent(averyLease)&&
                    averyInitialNavigation&&!documentHadChildFrame&&
                    e.ResourceContext==CoreWebView2WebResourceContext.Document&&
                    e.RequestedSourceKind==CoreWebView2WebResourceRequestSourceKinds.Document&&
                    e.Request.Method=="POST"&&AveryUrl(e.Request.Uri,"/anki/printable")&&
                    AveryHeadersAllowed(mode,origin,averyLease.Source,
                        e.Request.Headers.Contains("Origin"),e.Request.Headers.Contains("Origin")?e.Request.Headers.GetHeader("Origin"):null,
                        e.Request.Headers.Contains("Referer"),e.Request.Headers.Contains("Referer")?e.Request.Headers.GetHeader("Referer"):null);
                if(!original) {
                    var check=new Dictionary<string,object>{{"ordinal",averyBootstrapRequests},{"lease",AveryLeaseCurrent(averyLease)},
                        {"initial_navigation",averyInitialNavigation},{"no_child_frame",!documentHadChildFrame},
                        {"resource_context",e.ResourceContext.ToString()},{"source_kind",e.RequestedSourceKind.ToString()},
                        {"method",e.Request.Method},{"exact_target",AveryUrl(e.Request.Uri,"/anki/printable")}};
                    foreach(string header in new[]{"Sec-Fetch-Dest","Sec-Fetch-Mode","Origin","Referer"})check[header+"_present"]=e.Request.Headers.Contains(header);
                    averyParent.Event("avery-bootstrap-check",check);
                }
                AveryState(original?"original-post-held":"bootstrap-request-refused");
                if(!original||await Task.WhenAny(averyPolicyReady.Task,Task.Delay(5000))!=averyPolicyReady.Task||
                    !averyPolicyReady.Task.Result||closing||disposed||!AveryLeaseCurrent(averyLease)||documentHadChildFrame||
                    generation!=bootstrapGeneration||activeNavigation!=bootstrapNavigation) {
                    e.Response=environment.CreateWebResourceResponse(new MemoryStream(new byte[0]),403,"Blocked","Content-Type: text/plain");return;
                }
            }
            if(averyParent!=null&&!AveryLeaseCurrent(averyLease)){AveryState("resource-refused-owner-context");e.Response=environment.CreateWebResourceResponse(new MemoryStream(new byte[0]),403,"Blocked","Content-Type: text/plain");return;}
            string reason=!Exact(e.Request.Uri)?"target":blockedPaths.Contains(Uri.UnescapeDataString(new Uri(e.Request.Uri).AbsolutePath))?"blocked-path":null;
            // Browser-generated header guard retained as defense in depth.
            // Actual WebView2 tests did not make it sufficient to prevent
            // service-worker startup; the pinned DNR document CSP is required.
            if(e.Request.Headers.Contains("Sec-Fetch-Dest")) {
                string destination=e.Request.Headers.GetHeader("Sec-Fetch-Dest").Trim().ToLowerInvariant();
                if(destination=="serviceworker"||destination=="sharedworker")reason="worker-bootstrap";
            }
            if(mode=="local") {
                var kinds=CoreWebView2WebResourceRequestSourceKinds.ServiceWorker|CoreWebView2WebResourceRequestSourceKinds.SharedWorker;
                if(!localPolicyVerified||!browserPolicyReady)reason="unverified-policy";else if((e.RequestedSourceKind&kinds)!=0)reason="worker-source";
                foreach(string header in new[]{"Origin","Referer"})if(e.Request.Headers.Contains(header)&&!Exact(e.Request.Headers.GetHeader(header)))
                    reason=header=="Origin"?(e.Request.Headers.GetHeader(header)=="null"?"origin-null":"foreign-origin"):"foreign-referer";
            }
            if(reason!=null) {
                e.Response=environment.CreateWebResourceResponse(new MemoryStream(new byte[0]),403,"Blocked","Content-Type: text/plain");
                if(policyBlocks++<64)Event("policy-blocked",new Dictionary<string,object>{{"reason",reason},{"context",e.ResourceContext.ToString()},{"generation",generation},{"nav_id",activeNavigation}});
            }
            else if(mode=="local") {
                e.Request.Headers.SetHeader("X-DLMS-Desktop-Token",token);
                if(averyParent==null)TagAIDocument(e.Request,e.ResourceContext==CoreWebView2WebResourceContext.Document);
            }
            else if(e.Request.Headers.Contains("X-DLMS-Desktop-Token"))e.Request.Headers.RemoveHeader("X-DLMS-Desktop-Token");
            if(averyParent!=null&&e.Request.Headers.Contains("X-DLMS-AI-Document"))e.Request.Headers.RemoveHeader("X-DLMS-AI-Document");
            if(bootstrap!=null&&reason==null)AveryState("original-post-allowed");
            }catch {
                // A once-held native event may resume after controller disposal.
                // Never let async-void teardown escape into the primary host.
                if(averyParent!=null) {
                    if(!closing&&!disposed) {
                        try{e.Response=environment.CreateWebResourceResponse(new MemoryStream(new byte[0]),403,"Blocked","Content-Type: text/plain");}catch{}
                        AveryFailure("resource-policy-failed");
                    }
                }else ObserveRequestTask(FailRequestPolicy("resource-policy-failed"));
            }finally {
                if(bootstrap!=null) {
                    try{bootstrap.Complete();}
                    catch{if(!closing&&!disposed)AveryFailure("resource-deferral-failed");}
                }
            }
        };
        core.WebResourceResponseReceived+=(s,e)=> {
            Navigation nav;if(!navigations.TryGetValue(activeNavigation,out nav)||!Current(nav,activeNavigation)||!Exact(e.Request.Uri)||e.Request.Uri!=nav.Url)return;
            CaptureAIContract(e,nav);
            if(e.Response.StatusCode<200||e.Response.StatusCode>=300||!e.Response.Headers.Contains("Content-Disposition"))return;
            string disposition=e.Response.Headers.GetHeader("Content-Disposition").Split(';')[0].Trim();
            if(!String.Equals(disposition,"attachment",StringComparison.OrdinalIgnoreCase))return;
            nav.AttachmentResponse=true;nav.ResponseStatus=e.Response.StatusCode;
            if(attachmentRecords++<64)NavigationEvent("attachment-response",nav,activeNavigation,new Dictionary<string,object>{{"http_status",e.Response.StatusCode},{"disposition","attachment"},{"request_matches_navigation",true}});
        };
        if(averyParent==null) {
            Emit("initialization","clear-owned-service-workers");await core.Profile.ClearBrowsingDataAsync(CoreWebView2BrowsingDataKinds.ServiceWorkers);
            Emit("initialization","socket-policy");await InstallPolicy();
        } else await VerifyBorrowedAveryPolicy();
        core.DownloadStarting+=DownloadStarting;
        // Browser intercepts the real file dialog, including programmatic .click
        // and showPicker. No JS binding or message API is installed in pages.
        core.GetDevToolsProtocolEventReceiver("Runtime.executionContextCreated").DevToolsProtocolEventReceived+=(s,e)=> {
            var data=json.Deserialize<Dictionary<string,object>>(e.ParameterObjectAsJson);var context=(Dictionary<string,object>)data["context"];
            if(!context.ContainsKey("auxData"))return;var aux=(Dictionary<string,object>)context["auxData"];
            if(Bool(aux,"isDefault")&&aux.ContainsKey("frameId"))mainContexts[TextValue(aux,"frameId")]=Convert.ToInt32(context["id"]);
        };
        core.GetDevToolsProtocolEventReceiver("Runtime.executionContextDestroyed").DevToolsProtocolEventReceived+=(s,e)=> {
            var data=json.Deserialize<Dictionary<string,object>>(e.ParameterObjectAsJson);int context=Convert.ToInt32(data["executionContextId"]);
            foreach(string frame in mainContexts.Where(pair=>pair.Value==context).Select(pair=>pair.Key).ToArray())mainContexts.Remove(frame);
            if(context==aiContext)RetireAI();
            if(averyPrint!=null&&context==averyPrint.Context)averyPrint=null;
        };
        core.GetDevToolsProtocolEventReceiver("Runtime.executionContextsCleared").DevToolsProtocolEventReceived+=(s,e)=>{mainContexts.Clear();RetireAI();averyPrint=null;};
        core.GetDevToolsProtocolEventReceiver("Log.entryAdded").DevToolsProtocolEventReceived+=(s,e)=> {
            var data=json.Deserialize<Dictionary<string,object>>(e.ParameterObjectAsJson);var entry=(Dictionary<string,object>)data["entry"];
            if(TextValue(entry,"text")=="File chooser dialog can only be shown with a user activation."&&activationWarnings++<16)
                Event("console-warning",new Dictionary<string,object>{{"code","file-picker-user-activation"},{"source",TextValue(entry,"source")},{"generation",generation}});
        };
        Emit("initialization", "page-domain");await Cdp("Page.enable",new{});
        await Cdp("Runtime.enable",new{});
        await Cdp("Log.enable",new{});
        core.GetDevToolsProtocolEventReceiver("Page.fileChooserOpened").DevToolsProtocolEventReceived+=async(s,e)=>await PickerOpened(e.ParameterObjectAsJson);
        Emit("initialization", "file-chooser");await Cdp("Page.setInterceptFileChooserDialog",new{enabled=true});
        if(averyParent==null)await InstallAIObserver();
        else {
            core.GetDevToolsProtocolEventReceiver("Runtime.bindingCalled").DevToolsProtocolEventReceived+=(s,e)=>AveryPrintRequested(e.ParameterObjectAsJson);
            await Cdp("Runtime.addBinding",new{name=AveryPrintBinding,executionContextName=AveryPrintWorld});
        }
        if(averyParent==null&&mode=="local") {
            Emit("initialization", "local-print");
            // Closed-purpose PDF request, matching Local window.print semantics.
            // Binding exists only in the private isolated world, never main JS.
            // Server views install neither binding nor either script.
            core.GetDevToolsProtocolEventReceiver("Runtime.bindingCalled").DevToolsProtocolEventReceived+=async(s,e)=>await PrintRequested(e.ParameterObjectAsJson);
            await Cdp("Runtime.addBinding",new{name="__dlmsPrintRequest",executionContextName="DLMSDesktopPrint"});
            await Cdp("Page.addScriptToEvaluateOnNewDocument",new{worldName="DLMSDesktopPrint",source="document.addEventListener('__dlms_pdf_request',()=>{if(self===top)__dlmsPrintRequest('print')},true)"});
            await Cdp("Page.addScriptToEvaluateOnNewDocument",new{source="Object.defineProperty(window,'print',{value:()=>document.dispatchEvent(new Event('__dlms_pdf_request')),writable:false,configurable:false})"});
        }
        else if(averyParent==null)await core.AddScriptToExecuteOnDocumentCreatedAsync("Object.defineProperty(window,'print',{value:()=>alert('Server PDF printing is unavailable in this candidate; use the Server application in your regular browser to print.'),writable:false,configurable:false})");
        await InstallRequestPolicy();
        browserPolicyReady=true;
        if(averyParent!=null)averyPolicyReady.TrySetResult(true);
    }
    void LocalViolation(string message) {
        if(averyParent==null)ObserveRequestTask(RetireAvery());
        localPolicyVerified=false;browserPolicyReady=false;
        view.CoreWebView2.Stop();
        Emit("fatal",new{type="LocalPolicyViolation",message=message});
    }
    SafeFileHandle PinPolicyPath(string path,bool directory,bool allowProtectedRuntimeLinks=false) {
        uint access=0x20000|0x80|(directory?1u:0x80000000u);
        var handle=CreateFile(NativePath(path),access,directory?3u:1u,IntPtr.Zero,3,0x00200000u|(directory?0x02000000u:0u),IntPtr.Zero);
        if(handle.IsInvalid)throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error(),"Policy path could not be pinned");
        try {
            FileInformation value;if(!GetFileInformationByHandle(handle,out value))throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
            if((value.Attributes&0x400)!=0||((value.Attributes&0x10)!=0)!=directory||(!directory&&value.Links!=1&&!allowProtectedRuntimeLinks))throw new InvalidOperationException("Policy path alias, link or type refused");
            SealPipe(handle.DangerousGetHandle());policyHandles.Add(handle);return handle;
        }catch{handle.Dispose();throw;}
    }
    void PinPolicyDirectories(string directory) {
        var paths=new List<string>();string item=Path.GetFullPath(directory);
        while(item!=null){paths.Add(item);item=Path.GetDirectoryName(item);}
        paths.Reverse();foreach(string path in paths)if(pinnedPolicyDirectories.Add(path))PinPolicyPath(path,true);
    }
    byte[] PinnedPolicyFile(string path,string expected) {
        var handle=PinPolicyPath(path,false);FileInformation info;
        if(!GetFileInformationByHandle(handle,out info)||info.SizeHigh!=0||info.SizeLow>4096)throw new InvalidOperationException("Unexpected policy file size");
        byte[] bytes=new byte[(int)info.SizeLow];
        using(var stream=new FileStream(new SafeFileHandle(handle.DangerousGetHandle(),false),FileAccess.Read)) {
            int offset=0,count;while(offset<bytes.Length&&(count=stream.Read(bytes,offset,bytes.Length-offset))>0)offset+=count;
            if(offset!=bytes.Length)throw new InvalidOperationException("Incomplete policy file");
        }
        string hash;using(var sha=SHA256.Create())hash=BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-","").ToLowerInvariant();
        if(hash!=expected)throw new InvalidOperationException("Private browser policy checksum mismatch");return bytes;
    }
    void StablePolicyFile(string path,byte[] bytes,string expected) {
        if(!File.Exists(NativePath(path))) {
            string temporary=Path.Combine(Path.GetDirectoryName(path),".dlms-policy-stage-"+Guid.NewGuid().ToString("N")+".tmp");
            using(var stream=new FileStream(NativePath(temporary),FileMode.CreateNew,FileAccess.Write,FileShare.Read,4096,FileOptions.WriteThrough)){stream.Write(bytes,0,bytes.Length);stream.Flush(true);}
            // Atomic no-overwrite publication avoids a partial live policy after
            // process interruption. Prior interrupted staging files are retained.
            File.Move(NativePath(temporary),NativePath(path));
        }
        PinnedPolicyFile(path,expected);
    }
    void CheckStablePolicyDirectory() {
        foreach(string file in Directory.GetFiles(NativePath(policyDirectory))) {
            string name=Path.GetFileName(file);
            if(name!="manifest.json"&&name!="rules.json"&&!System.Text.RegularExpressions.Regex.IsMatch(name,"^\\.dlms-policy-stage-[0-9a-f]{32}\\.tmp$"))throw new InvalidOperationException("Unknown file in private browser policy folder");
            if((File.GetAttributes(file)&FileAttributes.ReparsePoint)!=0)throw new InvalidOperationException("Policy file reparse point refused");
        }
        foreach(string directory in Directory.GetDirectories(NativePath(policyDirectory))) {
            // Chromium may generate its compiled DNR index inside _metadata.
            // Only the two hash-pinned JSON files are extension source inputs.
            if(Path.GetFileName(directory)!="_metadata"||(File.GetAttributes(directory)&FileAttributes.ReparsePoint)!=0)throw new InvalidOperationException("Unknown policy directory refused");
        }
    }
    void PreparePolicyFiles() {
        string source=Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"extension");PrivatePath(source,false);PinPolicyDirectories(source);
        if(Directory.GetDirectories(NativePath(source)).Length!=0||!Directory.GetFiles(NativePath(source)).Select(Path.GetFileName).OrderBy(x=>x,StringComparer.Ordinal).SequenceEqual(new[]{"manifest.json","rules.json"}))throw new InvalidOperationException("Unexpected browser policy payload inventory");
        byte[] manifest=PinnedPolicyFile(Path.Combine(source,"manifest.json"),ManifestHash),rules=PinnedPolicyFile(Path.Combine(source,"rules.json"),RulesHash);
        string storage=Path.GetFullPath(TextValue(config,"storage"));PinPolicyDirectories(storage);
        policyDirectory=Path.Combine(storage,"dlms-policy-extension-v2");Directory.CreateDirectory(NativePath(policyDirectory));PrivatePath(policyDirectory,false);PinPolicyDirectories(policyDirectory);CheckStablePolicyDirectory();
        StablePolicyFile(Path.Combine(policyDirectory,"manifest.json"),manifest,ManifestHash);StablePolicyFile(Path.Combine(policyDirectory,"rules.json"),rules,RulesHash);CheckStablePolicyDirectory();
        // Chromium's unpacked-extension identity hashes the UTF-16 Windows path
        // after uppercasing its drive letter. No signing key is generated.
        string normalized=Char.ToUpperInvariant(policyDirectory[0])+policyDirectory.Substring(1);byte[] digest;
        using(var sha=SHA256.Create())digest=sha.ComputeHash(System.Text.Encoding.Unicode.GetBytes(normalized));
        expectedExtensionId=String.Concat(digest.Take(16).SelectMany(b=>new[]{(char)('a'+(b>>4)),(char)('a'+(b&15))}));
    }
    async Task InstallPolicy() {
        VerifyRuntimeComponents();
        var existing=await view.CoreWebView2.Profile.GetBrowserExtensionsAsync();
        Event("extension-inventory",new Dictionary<string,object>{{"phase","before-policy"},{"expected_id",expectedExtensionId},{"extensions",existing.Take(16).Select(item=>new{id=item.Id,name=item.Name,enabled=item.IsEnabled}).ToArray()},{"count",existing.Count}});
        if(existing.Any(item=>!ExpectedExtension(item)))throw new InvalidOperationException("Unsupported extension or older experimental policy exists in the private browser profile; use a separate disposable profile. Nothing was removed");
        var extension=await view.CoreWebView2.Profile.AddBrowserExtensionAsync(policyDirectory);
        if(extension.Id!=expectedExtensionId||extension.Name!=PolicyName)throw new InvalidOperationException("Installed policy identity did not match the pinned private path");
        if(!extension.IsEnabled)await extension.EnableAsync(true);
        var installed=await view.CoreWebView2.Profile.GetBrowserExtensionsAsync();
        if(installed.Any(item=>!ExpectedExtension(item))||installed.Count(item=>item.Id==expectedExtensionId&&item.Name==PolicyName&&item.IsEnabled)!=1)throw new InvalidOperationException("Private browser policy was not exclusively enabled");
        Event("socket-policy",new Dictionary<string,object>{{"kind","private-static-DNR-v2"},{"id",expectedExtensionId},{"enabled",true},{"scripts",false},{"worker_document_csp","append-worker-src-none"},{"host_permissions","http-and-https-only"},{"manifest_sha256",ManifestHash},{"rules_sha256",RulesHash}});
    }
    bool ExpectedExtension(CoreWebView2BrowserExtension item) {
        if(item.Id==expectedExtensionId&&item.Name==PolicyName)return true;
        if(item.Id=="dgiklkfkllikcanfonkcabmbdfmgleag"&&item.Name=="Microsoft Clipboard Extension")return true;
        return item.Id=="mhjfbmdgcfjbbpaeojofohoefgiehjai"&&item.Name=="Microsoft Edge PDF Viewer";
    }
    static bool TrustedSystemSid(string sid) {
        return sid=="S-1-5-18"||sid=="S-1-5-32-544"||sid=="S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464";
    }
    void ProtectedRuntimePath(string path,bool directory,bool strictDirectory=false) {
        if((File.GetAttributes(path)&FileAttributes.ReparsePoint)!=0)throw new InvalidOperationException("Runtime reparse path refused");
        FileSystemSecurity acl=directory?(FileSystemSecurity)Directory.GetAccessControl(path):File.GetAccessControl(path);
        CheckRuntimeAcl(acl,directory&&!strictDirectory&&!String.Equals(path,trustedRuntimeDirectory,StringComparison.OrdinalIgnoreCase));
        // Runtime servicing uses hardlinks for its signed executable. Every
        // alias has the same protected file ACL, and this retained handle denies
        // writes/deletion through every alias. Policy JSON never permits links.
        if(directory)PinPolicyDirectories(path);else PinPolicyPath(path,false,true);
    }
    static void CheckRuntimeAcl(FileSystemSecurity acl,bool relaxedAncestor) {
        if(!TrustedSystemSid(acl.GetOwner(typeof(SecurityIdentifier)).Value))throw new InvalidOperationException("Runtime path is not system-owned");
        const FileSystemRights writes=FileSystemRights.WriteData|FileSystemRights.AppendData|FileSystemRights.WriteExtendedAttributes|FileSystemRights.DeleteSubdirectoriesAndFiles|FileSystemRights.WriteAttributes|FileSystemRights.Delete|FileSystemRights.ChangePermissions|FileSystemRights.TakeOwnership;
        // Creating an unrelated sibling on an ancestor such as C:\ does not
        // replace our existing retained path. The version directory and image
        // themselves must disallow every untrusted write; ancestors must forbid
        // altering/deleting existing entries or their security/reparse metadata.
        FileSystemRights denied=relaxedAncestor?writes&~(FileSystemRights.WriteData|FileSystemRights.AppendData|FileSystemRights.WriteExtendedAttributes):writes;
        foreach(FileSystemAccessRule rule in acl.GetAccessRules(true,true,typeof(SecurityIdentifier)))
            if(rule.AccessControlType==AccessControlType.Allow&&(rule.PropagationFlags&PropagationFlags.InheritOnly)==0&&((rule.FileSystemRights&denied)!=0||(unchecked((uint)rule.FileSystemRights)&0x50000000u)!=0)&&!TrustedSystemSid(rule.IdentityReference.Value))throw new InvalidOperationException("Runtime path permits untrusted writes");
    }
    void VerifyRuntimeComponents() {
        string image;using(var process=Process.GetProcessById(browserPid))image=Path.GetFullPath(process.MainModule.FileName);
        string version=environment.BrowserVersionString.Split(' ')[0];
        trustedRuntimeDirectory=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86),"Microsoft","EdgeWebView","Application",version);
        string expected=Path.Combine(trustedRuntimeDirectory,"msedgewebview2.exe");
        if(!String.Equals(image,expected,StringComparison.OrdinalIgnoreCase)||FileVersionInfo.GetVersionInfo(image).FileVersion!=version)throw new InvalidOperationException("Browser image did not match the protected installed Runtime version");
        var paths=new List<string>();string current=trustedRuntimeDirectory;
        while(current!=null){paths.Add(current);current=Path.GetDirectoryName(current);}
        paths.Reverse();foreach(string path in paths)ProtectedRuntimePath(path,true);ProtectedRuntimePath(image,false);
        VerifySignedRuntimeImage(image,version);
        CheckComponentPreferences();
        Event("runtime-trust",new Dictionary<string,object>{{"image",image},{"version",version},{"microsoft_authenticode",true},{"system_protected_path",true},{"components","exact-id-name-runtime-trust-inference"}});
    }
    static void VerifySignedRuntimeImage(string image,string version) {
        if(FileVersionInfo.GetVersionInfo(image).FileVersion!=version)throw new InvalidOperationException("Runtime image version did not match its exact protected version directory");
        var file=new TrustFile{Size=(uint)Marshal.SizeOf(typeof(TrustFile)),Path=image};IntPtr memory=Marshal.AllocHGlobal(Marshal.SizeOf(typeof(TrustFile)));
        try {
            Marshal.StructureToPtr(file,memory,false);
            var trust=new TrustData{Size=(uint)Marshal.SizeOf(typeof(TrustData)),UI=2,Choice=1,File=memory,Action=1,Flags=0x1010};
            int status;
            try{status=WinVerifyTrust(new IntPtr(-1),new Guid("00AAC56B-CD44-11d0-8CC2-00C04FC295EE"),ref trust);}
            finally{trust.Action=2;WinVerifyTrust(new IntPtr(-1),new Guid("00AAC56B-CD44-11d0-8CC2-00C04FC295EE"),ref trust);}
            if(status!=0)throw new InvalidOperationException("Runtime Authenticode validation failed: "+status);
            using(var certificate=new X509Certificate2(X509Certificate.CreateFromSignedFile(image)))
                if(certificate.GetNameInfo(X509NameType.SimpleName,false)!="Microsoft Corporation")throw new InvalidOperationException("Runtime publisher was not Microsoft Corporation");
        }finally{Marshal.DestroyStructure(memory,typeof(TrustFile));Marshal.FreeHGlobal(memory);}
    }
    static string ComponentMetadataRuntime(object location,string path,string activeDirectory,string resource) {
        const string refused="Runtime component Preferences metadata did not match an exact supported protected virtual resource";
        if(!(location is int)||(int)location!=5||(resource!="edge_clipboard"&&resource!="edge_pdf"))throw new InvalidOperationException(refused);
        NativePath(path);string full=Path.GetFullPath(path),family=Path.GetDirectoryName(activeDirectory);
        if(!String.Equals(full,path.Replace('/','\\'),StringComparison.OrdinalIgnoreCase))throw new InvalidOperationException(refused);
        string directory=Path.GetDirectoryName(Path.GetDirectoryName(full));
        if(directory==null||!String.Equals(Path.GetDirectoryName(directory),family,StringComparison.OrdinalIgnoreCase)||
           !String.Equals(full,Path.Combine(directory,"resources",resource),StringComparison.OrdinalIgnoreCase))throw new InvalidOperationException(refused);
        string recorded=Path.GetFileName(directory),running=Path.GetFileName(activeDirectory);Version recordedVersion,runningVersion;
        if(!Version.TryParse(recorded,out recordedVersion)||recordedVersion.Revision<0||recordedVersion.ToString(4)!=recorded||
           recordedVersion.Major>65535||recordedVersion.Minor>65535||recordedVersion.Build>65535||recordedVersion.Revision>65535||
           !Version.TryParse(running,out runningVersion)||runningVersion.Revision<0||runningVersion.ToString(4)!=running||
           runningVersion.Major>65535||runningVersion.Minor>65535||runningVersion.Build>65535||runningVersion.Revision>65535||
           recordedVersion.CompareTo(runningVersion)>0||
           (!String.Equals(directory,activeDirectory,StringComparison.OrdinalIgnoreCase)&&recordedVersion.CompareTo(new Version(155,0,4283,45))<0))throw new InvalidOperationException(refused);
        return directory;
    }
    static bool RuntimeObjectMissing(string path,bool directory) {
        using(var existing=CreateFile(NativePath(path),0x20080u,3,IntPtr.Zero,3,0x00200000u|(directory?0x02000000u:0u),IntPtr.Zero)) {
            if(existing.IsInvalid) {
                int error=Marshal.GetLastWin32Error();
                if(error!=2)throw new System.ComponentModel.Win32Exception(error,"Historical Runtime lookup failed; nothing was reset");
                return true;
            }
            FileInformation info;
            if(!GetFileInformationByHandle(existing,out info))throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
            if((info.Attributes&0x400)!=0||((info.Attributes&0x10)!=0)!=directory)throw new InvalidOperationException("Historical Runtime object alias or type refused");
            return false;
        }
    }
    void VerifyHistoricalComponentRuntime(string directory) {
        if(verifiedHistoricalComponentRuntimes.Contains(directory))return;
        string family=Path.GetDirectoryName(trustedRuntimeDirectory);
        if(!String.Equals(Path.GetDirectoryName(directory),family,StringComparison.OrdinalIgnoreCase))throw new InvalidOperationException("Historical component escaped the protected Runtime family");
        // The active signed Runtime is already verified. Before accepting an
        // absent old directory/image, prove its namespace forbids untrusted
        // creation; relaxed ancestor ACL rules are insufficient here.
        ProtectedRuntimePath(family,true,true);
        if(!RuntimeObjectMissing(directory,true)) {
            ProtectedRuntimePath(directory,true,true);
            string image=Path.Combine(directory,"msedgewebview2.exe");
            // Evergreen can leave a protected version directory after deleting
            // its executable. No old code is selected or recreated in that case.
            if(!RuntimeObjectMissing(image,false)) {
                ProtectedRuntimePath(image,false);
                VerifySignedRuntimeImage(image,Path.GetFileName(directory));
            }
        }
        // No removed executable is selected, loaded or recreated. The active
        // protected Microsoft Runtime and exact component ID/location/resource
        // plus the exclusive extension inventory remain the authority.
        verifiedHistoricalComponentRuntimes.Add(directory);
    }
    void CheckComponentPreferences() {
        string profile=Path.GetFullPath(view.CoreWebView2.Profile.ProfilePath),storage=Path.GetFullPath(TextValue(config,"storage")).TrimEnd('\\')+"\\";
        if(!profile.StartsWith(storage,StringComparison.OrdinalIgnoreCase))throw new InvalidOperationException("Runtime profile escaped the owned user-data folder");
        PrivatePath(profile,false);PinPolicyDirectories(profile);
        foreach(string name in new[]{"Preferences","Secure Preferences"})CheckComponentMetadata(Path.Combine(profile,name));
    }
    void CheckComponentMetadata(string path) {
        if(!File.Exists(NativePath(path)))return;
        Dictionary<string,object> preferences;
        using(var handle=CreateFile(NativePath(path),0x80020080u,7,IntPtr.Zero,3,0x00200000u,IntPtr.Zero)) {
            if(handle.IsInvalid)throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error(),"Component metadata could not be read");
            SealPipe(handle.DangerousGetHandle());FileInformation info;
            if(!GetFileInformationByHandle(handle,out info)||(info.Attributes&0x410)!=0||info.Links!=1||info.SizeHigh!=0||info.SizeLow>16*1024*1024)throw new InvalidOperationException("Component metadata alias, type or size refused");
            using(var stream=new FileStream(handle,FileAccess.Read))using(var reader=new StreamReader(stream)) {
                var body=new System.Text.StringBuilder();var buffer=new char[4096];int count;
                while((count=reader.Read(buffer,0,buffer.Length))>0){if(body.Length+count>16*1024*1024)throw new InvalidOperationException("Component metadata grew beyond its bound");body.Append(buffer,0,count);}
                preferences=json.Deserialize<Dictionary<string,object>>(body.ToString());
            }
        }
        object extensions,settings;
        if(!preferences.TryGetValue("extensions",out extensions)||!(extensions is Dictionary<string,object>)||!((Dictionary<string,object>)extensions).TryGetValue("settings",out settings)||!(settings is Dictionary<string,object>))return;
        var entries=(Dictionary<string,object>)settings;
        foreach(var pair in new[]{new[]{"dgiklkfkllikcanfonkcabmbdfmgleag","edge_clipboard"},new[]{"mhjfbmdgcfjbbpaeojofohoefgiehjai","edge_pdf"}}) {
            object entry;if(!entries.TryGetValue(pair[0],out entry))continue;
            var value=entry as Dictionary<string,object>;
            if(value==null||!value.ContainsKey("location"))throw new InvalidOperationException("Runtime component Preferences metadata was malformed");
            string directory=ComponentMetadataRuntime(value["location"],TextValue(value,"path"),trustedRuntimeDirectory,pair[1]);
            // Evergreen may retain the previous installed version's component
            // paths in this private profile. Those are virtual resource paths,
            // not ordinary resource directories. Accept only an exact known
            // component in the verified protected Runtime namespace;
            // never rewrite preferences or trust an arbitrary version pathname.
            if(!String.Equals(directory,trustedRuntimeDirectory,StringComparison.OrdinalIgnoreCase))VerifyHistoricalComponentRuntime(directory);
        }
    }
    static bool RestrictedCsp(string[] headers) {
        if(headers==null)return false;
        foreach(string header in headers)foreach(string policy in header.Split(',')) {
            var directives=new Dictionary<string,string[]>(StringComparer.OrdinalIgnoreCase);
            foreach(string directive in policy.Split(';')) {
                var tokens=directive.Split((char[])null,StringSplitOptions.RemoveEmptyEntries);
                if(tokens.Length>0&&!directives.ContainsKey(tokens[0]))directives[tokens[0]]=tokens.Skip(1).ToArray();
            }
            bool restrictive=true;
            foreach(string name in new[]{"frame-src","child-src","worker-src","object-src"}) {
                string[] value;if(!directives.TryGetValue(name,out value)||value.Length!=1||value[0]!="'none'")restrictive=false;
            }
            if(restrictive)return true;
        }
        return false;
    }
    static void ObserveFailure(Task task) {task.ContinueWith(t=>{var ignored=t.Exception;},TaskContinuationOptions.OnlyOnFaulted);}
    async Task LocalPreflight() {
        var request=(HttpWebRequest)WebRequest.Create(origin+"/_desktop/ready");
        request.AllowAutoRedirect=false;request.Proxy=null;request.Timeout=5000;request.ReadWriteTimeout=5000;
        request.Headers["X-DLMS-Desktop-Token"]=token;request.Headers["X-DLMS-Desktop-Nonce"]=token;
        try {
            var responseTask=Task<WebResponse>.Factory.FromAsync(request.BeginGetResponse,request.EndGetResponse,null);
            if(await Task.WhenAny(responseTask,Task.Delay(5000))!=responseTask){request.Abort();ObserveFailure(responseTask);throw new TimeoutException("Owned backend security preflight timed out");}
            using(var response=(HttpWebResponse)await responseTask) {
                byte[] expected=System.Text.Encoding.ASCII.GetBytes("DLMS Desktop Block A ready"),body=new byte[expected.Length];
                if(response.StatusCode!=HttpStatusCode.OK||response.ContentLength!=expected.Length||!RestrictedCsp(response.Headers.GetValues("Content-Security-Policy")))
                    throw new InvalidOperationException("Local backend must enforce the Windows frames/workers policy before rendering");
                using(var stream=response.GetResponseStream()){int offset=0,count;while(offset<body.Length&&(count=stream.Read(body,offset,body.Length-offset))>0)offset+=count;if(offset!=body.Length||!body.SequenceEqual(expected))throw new InvalidOperationException("Owned backend readiness identity did not match");}
            }
            localPolicyVerified=true;
            Event("local-policy",new Dictionary<string,object>{{"csp_verified",true},{"ready_identity",true},{"frames",false},{"workers",false},{"opaque_origin_requests",false}});
        }finally{request.Abort();}
    }
    async Task PrintRequested(string args) {
        try {
            if(mode!="local"||closing||!Exact(view.CoreWebView2.Source))return;
            var data=json.Deserialize<Dictionary<string,object>>(args);
            if(TextValue(data,"name")!="__dlmsPrintRequest"||TextValue(data,"payload")!="print")return;
            long before=generation;
            var result=await Cdp("Runtime.evaluate",new{contextId=Convert.ToInt32(data["executionContextId"]),expression="self===top ? JSON.stringify({href:location.href,timeOrigin:performance.timeOrigin}) : null",returnByValue=true});
            if(result.ContainsKey("exceptionDetails"))return;
            var remote=(Dictionary<string,object>)result["result"];
            string identity=remote.ContainsKey("value")?remote["value"] as string:null;
            if(identity==null||before!=generation)return;string current=await Identity();
            if(!closing&&before==generation&&identity==current)Event("print",new Dictionary<string,object>());
        }catch(Exception ex){Emit("print-request-failed",ex.GetType().Name);}
    }
    async Task NavigationFinished(CoreWebView2NavigationCompletedEventArgs e) {
        Navigation nav;if(!navigations.TryGetValue(e.NavigationId,out nav)||!Current(nav,e.NavigationId))return;
        try {
            if(e.IsSuccess) {
                string frame=await Frame();if(!Current(nav,e.NavigationId))return;
                string identity=await Identity();if(!Current(nav,e.NavigationId))return;
                mainFrame=frame;documentIdentity=identity;
                nav.Completed=true;
                if(averyParent==null&&okAIStatus(e.HttpStatusCode))await ConfigureAI(nav,e.NavigationId);
                if(averyParent!=null&&okAIStatus(e.HttpStatusCode))await ConfigureAveryPrint(nav,e.NavigationId);
#if DLMS_AI_TEST
                // Separate, explicitly marked source-host probe. Normal builds
                // contain neither this timing fault nor a way to enable it.
                if(nav.AIActions!=null)await Task.Delay(800);
#endif
                if(!Current(nav,e.NavigationId))return;
                bool ok=e.HttpStatusCode>=200&&e.HttpStatusCode<400;
                NavigationEvent("load-finish",nav,e.NavigationId,new Dictionary<string,object>{{"url",view.CoreWebView2.Source},{"ok",ok},{"download",false},{"http_status",e.HttpStatusCode},{"error",ok?null:"HTTP "+e.HttpStatusCode}});
                nav.AIReady.TrySetResult(ok);return;
            }
            // DownloadStarting and NavigationCompleted can be delivered in either
            // order. Only actual attachment + unchanged prior document qualifies.
            await Task.Delay(350);
            if(!Current(nav,e.NavigationId))return;
            bool attachment=false,declined=false;
            bool cancelled=e.WebErrorStatus==CoreWebView2WebErrorStatus.OperationCanceled||e.WebErrorStatus==CoreWebView2WebErrorStatus.ConnectionAborted;
            if((nav.Download||(nav.AttachmentResponse&&cancelled))&&nav.Previous!=null) {
                string failedIdentity=await Identity();if(!Current(nav,e.NavigationId))return;
                attachment=failedIdentity==nav.Previous;
                declined=attachment&&!nav.Download&&nav.AttachmentResponse;
            }
            if(attachment){
                nav.Completed=true;
                nav.AIActions=nav.PreviousAIActions;
                if(averyParent==null)await ConfigureAI(nav,e.NavigationId);
                if(!Current(nav,e.NavigationId))return;
            }
            NavigationEvent("load-finish",nav,e.NavigationId,new Dictionary<string,object>{{"url",nav.Url},{"ok",false},{"download",attachment},{"attachment_declined",declined},{"error",e.WebErrorStatus.ToString()},{"http_status",e.HttpStatusCode}});
            nav.AIReady.TrySetResult(attachment);
            if(declined&&Current(nav,e.NavigationId))NavigationEvent("attachment-declined",nav,e.NavigationId,new Dictionary<string,object>{{"url",nav.Url},{"reason",nav.AutomaticDownloadDenied?"automatic-downloads-denied":"browser-declined"},{"http_status",nav.ResponseStatus}});
        }catch(Exception ex){if(Current(nav,e.NavigationId))NavigationEvent("load-finish",nav,e.NavigationId,new Dictionary<string,object>{{"url",nav.Url},{"ok",false},{"download",false},{"error",e.WebErrorStatus.ToString()},{"http_status",e.HttpStatusCode},{"identity_error",ex.GetType().Name},{"navigation_success",e.IsSuccess}});}
    }
    async void DownloadStarting(object sender,CoreWebView2DownloadStartingEventArgs e) {
        e.Handled=true;
        if(averyParent!=null){e.Cancel=true;AveryStatus("Downloads are unavailable in this Avery preview.");return;}
        bool blob=BlobDownloadUri(e.DownloadOperation.Uri,origin);
        if(!Exact(e.DownloadOperation.Uri)&&!blob){
            e.Cancel=true;
            if(blockedDownloadRecords++<64){Uri parsed;string kind=Uri.TryCreate(e.DownloadOperation.Uri,UriKind.Absolute,out parsed)?parsed.Scheme:"invalid";
                Event("download-blocked",new Dictionary<string,object>{{"reason",kind=="http"||kind=="https"?"origin":"kind"},{"kind",new[]{"http","https","blob","data"}.Contains(kind)?kind:"other"},{"generation",generation},{"nav_id",activeNavigation}});}
            return;
        }
        var pending=new PendingDownload{Args=e,Deferral=e.GetDeferral(),Generation=generation,Navigation=activeNavigation,Identity=documentIdentity,Frame=mainFrame,Blob=blob};
        string id=Guid.NewGuid().ToString("N");downloads[id]=pending;
        try {
            if(blob) {
                if(!StableDownloadDocument(pending.Generation,pending.Navigation,pending.Identity))throw new InvalidOperationException("Blob download has no stable exact-origin document");
                string frame=await Frame();
                if(pending.Completed||!StableDownloadDocument(pending.Generation,pending.Navigation,pending.Identity)||frame!=pending.Frame)throw new InvalidOperationException("Blob download frame changed");
                string identity=await Identity();
                if(pending.Completed||!StableDownloadDocument(pending.Generation,pending.Navigation,pending.Identity)||identity!=pending.Identity)throw new InvalidOperationException("Blob download document changed");
            }
        }catch {
            downloads.Remove(id);CompleteDownload(pending,true);
            if(blockedDownloadRecords++<64)Event("download-blocked",new Dictionary<string,object>{{"reason","context"},{"kind","blob"},{"generation",pending.Generation},{"nav_id",pending.Navigation}});return;
        }
        Navigation nav;
        if(navigations.TryGetValue(activeNavigation,out nav)&&Current(nav,activeNavigation)&&nav.Url==e.DownloadOperation.Uri)nav.Download=true;
        operations[id]=e.DownloadOperation;
        e.DownloadOperation.BytesReceivedChanged+=(s,x)=>Event("download-progress",new Dictionary<string,object>{{"download_id",id},{"bytes",e.DownloadOperation.BytesReceived}});
        e.DownloadOperation.StateChanged+=(s,x)=> {
            var d=e.DownloadOperation;if(d.State==CoreWebView2DownloadState.InProgress)return;
            operations.Remove(id);
            Event("download-state",new Dictionary<string,object>{{"download_id",id},{"state",d.State==CoreWebView2DownloadState.Completed?"completed":d.InterruptReason==CoreWebView2DownloadInterruptReason.UserCanceled?"cancelled":"interrupted"},{"reason",d.InterruptReason.ToString()}});
        };
        Event("download",new Dictionary<string,object>{{"download_id",id},{"url",e.DownloadOperation.Uri},{"name",Path.GetFileName(e.ResultFilePath)},{"mime",e.DownloadOperation.MimeType},{"blob",blob},{"generation",pending.Generation},{"nav_id",pending.Navigation},{"document_url",blob?view.CoreWebView2.Source:null},{"context",blob?"stable-exact-main-document":null}});
    }
    void PickerRefused(string reason,long before,ulong navigation) {
        Event("file-picker-failed",new Dictionary<string,object>{{"error",reason},{"generation",before},{"nav_id",navigation}});
    }
    bool PickerCurrent(Picker picker) {return !closing&&!disposed&&picker.Generation==generation&&picker.Navigation==activeNavigation;}
    async Task PickerOpened(string args) {
        if(averyParent!=null){AveryStatus("File selection is unavailable in this Avery preview.");return;}
        long before=generation;ulong navigation=activeNavigation;
        try {
            if(closing||disposed){PickerRefused("retiring",before,navigation);return;}
            if(pickers.Count!=0){PickerRefused("chooser-active",before,navigation);return;}
            var data=json.Deserialize<Dictionary<string,object>>(args);
            string frame=Convert.ToString(data["frameId"]);
            string current=await Frame();
            if(before!=generation||navigation!=activeNavigation||closing){PickerRefused("document-changed",before,navigation);return;}
            if(frame!=current){PickerRefused("main-frame-required",before,navigation);return;}
            if(!Exact(view.CoreWebView2.Source)||!data.ContainsKey("backendNodeId")){PickerRefused("input-unavailable",before,navigation);return;}
            string identity=await Identity();
            if(before!=generation||navigation!=activeNavigation||closing){PickerRefused("document-changed",before,navigation);return;}
            if(pickers.Count!=0){PickerRefused("chooser-active",before,navigation);return;}
            string ticket=Guid.NewGuid().ToString("N");
            var picker=new Picker{Node=Convert.ToInt32(data["backendNodeId"]),Frame=frame,Generation=before,Navigation=navigation,Identity=identity,Multiple=TextValue(data,"mode")=="selectMultiple"};
            pickers[ticket]=picker;
            Event("file-picker",new Dictionary<string,object>{{"ticket",ticket},{"multiple",picker.Multiple},{"url",view.CoreWebView2.Source},{"generation",before},{"nav_id",navigation}});
        }catch{PickerRefused("input-unavailable",before,navigation);}
    }

    async Task Command(Dictionary<string,object> command) {
        object id=command.ContainsKey("id")?command["id"]:null;
        bool filesOperation=TextValue(command,"op")=="files",filesExposed=false;
        try {
            string op=TextValue(command,"op");object value=null;
            switch(op) {
#if DLMS_AI_TEST
                case "server-ai-race":
                    if(mode!="server"||!new[]{"before-take","after-take","stale-input"}.Contains(TextValue(command,"stage")))throw new InvalidOperationException("Unknown source-only race stage");
                    serverRaceStage=TextValue(command,"stage");break;
#endif
                case "navigate": string url=TextValue(command,"url");if(!Exact(url))throw new InvalidOperationException("Navigation origin refused");view.CoreWebView2.Navigate(url);break;
                case "eval": value=await Evaluate(TextValue(command,"script"),command.ContainsKey("world")?Convert.ToInt32(command["world"]):1,Bool(command,"gesture"));break;
                case "enter":
                case "space":
                case "tab": {
                    long before=generation;ulong navigation=activeNavigation;
                    if(!Exact(view.CoreWebView2.Source)||closing)throw new InvalidOperationException("Keyboard probe refused outside the current document");
                    await Frame();if(before!=generation||navigation!=activeNavigation||closing)throw new InvalidOperationException("Document changed before keyboard probe");
                    int modifiers=op=="tab"&&Bool(command,"backward")?8:0;
                    string key=op=="enter"?"Enter":op=="space"?" ":"Tab",code=op=="space"?"Space":key;
                    int keyCode=op=="enter"?13:op=="space"?32:9;
                    await Cdp("Input.dispatchKeyEvent",new{type="keyDown",key=key,code=code,text=op=="enter"?"\r":op=="space"?" ":"",windowsVirtualKeyCode=keyCode,nativeVirtualKeyCode=keyCode,modifiers=modifiers,autoRepeat=Bool(command,"repeat")});
                    // Release the renderer key even if a page key handler navigates.
                    // This is a fixed application-local probe, never OS input.
                    await Cdp("Input.dispatchKeyEvent",new{type="keyUp",key=key,code=code,windowsVirtualKeyCode=keyCode,nativeVirtualKeyCode=keyCode,modifiers=modifiers});
                    if(before!=generation||navigation!=activeNavigation||closing)throw new InvalidOperationException("Document changed during keyboard probe");
                    object active=await Evaluate("({tag:document.activeElement?.tagName||null,type:document.activeElement?.type||null,is_body:document.activeElement===document.body,document_has_focus:document.hasFocus()})",1);
                    if(before!=generation||navigation!=activeNavigation||closing)throw new InvalidOperationException("Stale keyboard probe result");
                    var state=new Dictionary<string,object>{{"generation",before},{"nav_id",navigation},{"backward",modifiers!=0},{"dom",active},{"host_contains_focus",ContainsFocus},{"view_contains_focus",view.ContainsFocus},{"view_focused",view.Focused}};
                    Event("focus-probe",state);value=state;break;
                }
                case "click": {
                    long before=generation;if(!Exact(view.CoreWebView2.Source))throw new InvalidOperationException("Input refused outside configured origin");
                    double x=Convert.ToDouble(command["x"]),y=Convert.ToDouble(command["y"]);
                    var metrics=await Cdp("Page.getLayoutMetrics",new{});if(before!=generation||closing)throw new InvalidOperationException("Document changed before input");
                    var viewport=(Dictionary<string,object>)metrics["cssVisualViewport"];
                    if(Double.IsNaN(x)||Double.IsInfinity(x)||Double.IsNaN(y)||Double.IsInfinity(y)||x<0||y<0||x>=Convert.ToDouble(viewport["clientWidth"])||y>=Convert.ToDouble(viewport["clientHeight"]))throw new InvalidOperationException("Input point outside browser viewport");
                    await Cdp("Input.dispatchMouseEvent",new{type="mousePressed",x=x,y=y,button="left",buttons=1,clickCount=1});
                    // Release the renderer's button even if mousedown navigated.
                    // This is application-local CDP input, never OS input.
                    await Cdp("Input.dispatchMouseEvent",new{type="mouseReleased",x=x,y=y,button="left",buttons=0,clickCount=1});
                    value=new{generation_changed=before!=generation};break;
                }
                case "stop":view.CoreWebView2.Stop();break;
                case "visible":Visible=Bool(command,"value");break;
                case "enabled":Enabled=Bool(command,"value");break;
                case "focus": {
                    string reason=TextValue(command,"reason","programmatic");
                    if(reason!="programmatic"&&reason!="next"&&reason!="previous")throw new InvalidOperationException("Invalid native focus direction");
                    value=view.Focus(reason=="next"?CoreWebView2MoveFocusReason.Next:reason=="previous"?CoreWebView2MoveFocusReason.Previous:CoreWebView2MoveFocusReason.Programmatic);break;
                }
                case "position":view.NotifyPosition();break;
                case "zoom": {
                    double zoom=Convert.ToDouble(command["value"]);if(Double.IsNaN(zoom)||Double.IsInfinity(zoom)||zoom<0.25||zoom>5)throw new InvalidOperationException("Invalid browser zoom");ApplyScale(qtScale,zoom);value=zoom;break;
                }
                case "modules":value=Modules();break;
                case "background": {
                    string color=TextValue(command,"value");
                    if(!System.Text.RegularExpressions.Regex.IsMatch(color,"^#[0-9a-fA-F]{6}$"))throw new InvalidOperationException("Invalid canvas color");
                    SetBackground(ColorTranslator.FromHtml(color));break;
                }
                case "cover": {
                    if(mode!="server")throw new InvalidOperationException("Native connection cover is Server-only");
                    string message=TextValue(command,"text");if(message.Length>8192)throw new InvalidOperationException("Server status is too long");
                    serverStatus.Text=message;serverStatus.AccessibleDescription=message;
                    var preview=averyChild;
                    long coverSerial=++serverCoverSerial,coverGeneration=generation;
                    bool previewCurrent=preview!=null&&!preview.closing&&!preview.disposed&&AveryLeaseCurrent(preview.averyLease);
                    string foreground=await ApplyServerCoverStack(view,serverCover,preview,
                        Bool(command,"shown"),Bool(command,"browser_visible",true),previewCurrent,preview!=null&&preview.Visible,RetireAvery,
                        ()=>!closing&&!disposed&&serverCoverSerial==coverSerial&&generation==coverGeneration);
                    if(preview!=null)AveryState("cover-front-"+foreground);
                    var state=new Dictionary<string,object>{{"hwnd",serverCover.Handle.ToInt64()},{"shown",serverCover.Visible},{"browser_visible",view.Visible}};
                    Event("cover-state",state);value=new{hwnd=serverCover.Handle.ToInt64(),shown=serverCover.Visible,browser_visible=view.Visible};break;
                }
                case "policy":await RetireAvery();blockedPaths.Clear();if(command.ContainsKey("blocked_paths"))foreach(object path in (System.Collections.IEnumerable)command["blocked_paths"])blockedPaths.Add(Convert.ToString(path));break;
                case "resize": {
                    double scale=command.ContainsKey("scale")?Convert.ToDouble(command["scale"]):qtScale;
                    EffectiveZoom(scale,userZoom); // Validate before changing geometry.
                    ClientSize=new Size(Math.Max(1,Math.Min(16384,Convert.ToInt32(command["width"]))),Math.Max(1,Math.Min(16384,Convert.ToInt32(command["height"]))));
                    ApplyScale(scale,userZoom);break;
                }
                case "download": {
                    string key=TextValue(command,"download_id",TextValue(command,"ticket"));PendingDownload pending;
                    if(TextValue(command,"action")=="cancel") {
                        CoreWebView2DownloadOperation operation;if(operations.TryGetValue(key,out operation))operation.Cancel();
                        if(downloads.TryGetValue(key,out pending)){downloads.Remove(key);CompleteDownload(pending,true);}
                        break;
                    }
                    if(!downloads.TryGetValue(key,out pending))throw new InvalidOperationException("Unknown download ticket");
                    try {if(TextValue(command,"action")=="accept") {
                        if(pending.Blob) {
                            if(pending.Completed||!StableDownloadDocument(pending.Generation,pending.Navigation,pending.Identity))throw new InvalidOperationException("Stale blob download refused");
                            string frame=await Frame();if(pending.Completed||!StableDownloadDocument(pending.Generation,pending.Navigation,pending.Identity)||frame!=pending.Frame)throw new InvalidOperationException("Stale blob download frame refused");
                            string identity=await Identity();if(pending.Completed||!StableDownloadDocument(pending.Generation,pending.Navigation,pending.Identity)||identity!=pending.Identity)throw new InvalidOperationException("Stale blob download document refused");
                        }
                        string path=TextValue(command,"path");PrivatePath(path,true);if(!Directory.Exists(NativePath(Path.GetDirectoryName(path))))throw new InvalidOperationException("Missing staging parent");pending.Args.ResultFilePath=Path.GetFullPath(path);
                    }else pending.Args.Cancel=true;}
                    catch {if(!pending.Completed)pending.Args.Cancel=true;throw;}finally{downloads.Remove(key);CompleteDownload(pending,false);}break;
                }
                case "files": {
                    string key=TextValue(command,"ticket");Picker picker;if(!pickers.TryGetValue(key,out picker))throw new InvalidOperationException("Unknown file ticket");pickers.Remove(key);
                    if(!PickerCurrent(picker))throw new InvalidOperationException("Stale file picker refused");
                    string frame=await Frame();if(!PickerCurrent(picker)||picker.Frame!=frame)throw new InvalidOperationException("Stale file frame refused");
                    string identity=await Identity();if(!PickerCurrent(picker)||picker.Identity!=identity)throw new InvalidOperationException("Stale file document refused");
                    var paths=((System.Collections.IEnumerable)command["paths"]).Cast<object>().Select(Convert.ToString).ToArray();
                    if((!picker.Multiple&&paths.Length>1)||paths.Length>256)throw new InvalidOperationException("Invalid selection size");
                    if(paths.Length==0){value=new{files_applied=false,files_exposed=false};break;} // Cancel preserves the prior FileList.
                    foreach(string path in paths) {PrivatePath(path,false);if(!File.Exists(NativePath(path))||(File.GetAttributes(NativePath(path))&FileAttributes.ReparsePoint)!=0)throw new InvalidOperationException("Unsafe input path");}
                    filesExposed=true; // From this point even an RPC failure may have exposed bytes.
                    await Cdp("DOM.setFileInputFiles",new{files=paths.Select(Path.GetFullPath).ToArray(),backendNodeId=picker.Node});
                    if(!PickerCurrent(picker))throw new InvalidOperationException("Document changed during file handback");
                    frame=await Frame();if(!PickerCurrent(picker)||picker.Frame!=frame)throw new InvalidOperationException("File handback frame changed");
                    identity=await Identity();if(!PickerCurrent(picker)||picker.Identity!=identity)throw new InvalidOperationException("File handback document changed");
                    value=new{files_applied=true,files_exposed=true};break;
                }
                case "dialog": {
                    string key=TextValue(command,"ticket");PendingDialog pending;if(!dialogs.TryGetValue(key,out pending))throw new InvalidOperationException("Unknown dialog ticket");dialogs.Remove(key);
                    try {if(!closing&&pending.Generation==generation&&pending.Source==view.CoreWebView2.Source&&Exact(pending.Args.Uri)&&Exact(view.CoreWebView2.Source)&&Bool(command,"accepted")){pending.Args.ResultText=TextValue(command,"text");pending.Args.Accept();}}
                    finally{pending.Deferral.Complete();}break;
                }
                case "print": {
                    string path=TextValue(command,"path");PrivatePath(path,true);bool ok=await view.CoreWebView2.PrintToPdfAsync(Path.GetFullPath(path));
                    Event("print-finished",new Dictionary<string,object>{{"path",path},{"ok",ok}});value=ok;break;
                }
                case "close":Reply(id,true,null);await Shutdown();return;
                default:throw new InvalidOperationException("Unknown renderer command");
            }
            Reply(id,true,value);
        }catch(Exception ex){
            var error=new Dictionary<string,object>{{"type",ex.GetType().Name},{"message",ex.Message}};
            if(filesOperation){error["files_exposed"]=filesExposed;error["files_applied"]=filesExposed?null:(object)false;}
            Reply(id,false,error);
        }
    }
    object Modules() {
        var rows=new List<object>();
        foreach(var info in environment.GetProcessInfos()) {
            var modules=new List<object>();string error=null;
            try {using(var process=Process.GetProcessById(info.ProcessId))foreach(ProcessModule module in process.Modules)
                if(new[]{"nvspcap64.dll","d3d11.dll","dxgi.dll","nvldumdx.dll","nvwgf2umx.dll"}.Contains(module.ModuleName.ToLowerInvariant()))modules.Add(new{name=module.ModuleName,version=module.FileVersionInfo.FileVersion});}
            catch(Exception ex){error=ex.GetType().Name;}
            rows.Add(new{pid=info.ProcessId,role=info.Kind.ToString(),modules,error});
        }
        return rows;
    }
    void StartReader() {
        var reader=new Thread(()=> {
            try {string line;while((line=Console.ReadLine())!=null){if(line.Length>16*1024*1024)throw new InvalidOperationException("Oversized renderer command");var item=json.Deserialize<Dictionary<string,object>>(line);BeginInvoke(new Action(async()=>await Command(item)));}}
            catch(Exception ex){Emit("protocol-error",ex.GetType().Name);}
            try{BeginInvoke(new Action(async()=>await Shutdown()));}catch(InvalidOperationException){}
        });reader.IsBackground=true;reader.Start();
    }
    async Task RecoverBrowserForRetirement() {
        if(environment==null)return;
        bool reported=false;
        while(true) {
            bool failed=false;
            try {
                var browsers=environment.GetProcessInfos().Where(info=>info.Kind==CoreWebView2ProcessKind.Browser).ToArray();
                if(browsers.Length>1)throw new InvalidOperationException("Ambiguous browser retirement ownership");
                if(browsers.Length==1) {
                    int recovered=browsers[0].ProcessId;
                    if(browserPid!=recovered)Event("retirement-recovered",new Dictionary<string,object>{{"pid",recovered},{"scope","exclusive-owned-environment"}});
                    browserPid=recovered;
                }
            }catch{failed=true;}
            if(!failed)return;
            // Never release storage/policy pins when initialization failed and
            // the exclusive environment's process inventory is unavailable.
            if(!reported){reported=true;Event("retirement-wait",new Dictionary<string,object>{{"reason","owned-environment-inventory-unavailable"}});}
            await Task.Delay(500);
        }
    }
    async Task Shutdown() {
        if(averyParent!=null){await CloseAveryController();return;}
        if(closing)return;closing=true;
        browserPolicyReady=false;
        await RetireAvery();
        // Controller disposal below cancels any unresolved request pauses.
        foreach(var pending in dialogs.Values){try{pending.Deferral.Complete();}catch{}}dialogs.Clear();
        foreach(var pending in downloads.Values){try{CompleteDownload(pending,true);}catch{}}
        foreach(var operation in operations.Values.ToArray()){try{operation.Cancel();}catch{}}
        downloads.Clear();pickers.Clear();
        try{view.Dispose();}catch{Event("retirement-controller-close",new Dictionary<string,object>{{"error","controller-close-failed"}});}
        disposed=true;
        // EnsureCoreWebView2Async may start its browser then fail before Core
        // and its PID become available. Dispose first, then recover only from
        // this exclusive environment; never infer that pid0 means no browser.
        await RecoverBrowserForRetirement();
        if(browserPid!=0) {
            bool warned=false;
            while(!exitedBrowserIds.Contains(browserPid)) {
                if(browserExited.Task.IsCompleted)browserExited=new TaskCompletionSource<bool>();
                Task completed=await Task.WhenAny(browserExited.Task,Task.Delay(15000));
                if(completed!=browserExited.Task&&!warned){warned=true;Event("retirement-wait",new Dictionary<string,object>{{"pid",browserPid}});}
            }
            Event("retired",new Dictionary<string,object>{{"browser_exited",true},{"pid",browserPid}});
        }
        // Retain even timed-out COM callbacks through actual controller/browser
        // retirement; no per-call reference can release ownership prematurely.
        pendingRequests.Clear();
        foreach(var child in retiredAvery){child.pendingRequests.Clear();child.requestLeases.Clear();}
        retiredAvery.Clear();
        foreach(var handle in policyHandles.AsEnumerable().Reverse())handle.Dispose();policyHandles.Clear();
        Close();
    }
    [STAThread] static int Main(string[] args) {
        // Per-process compatibility switches for the installed modern .NET
        // Framework; no machine registry, policy or security setting changes.
        AppContext.SetSwitch("Switch.System.IO.UseLegacyPathHandling",false);
        AppContext.SetSwitch("Switch.System.IO.BlockLongPaths",false);
        try {
            Pipes(!(args.Length==1&&args[0]=="--runtime-version"));
            if(args.Length==1&&args[0]=="--external-browser")return BrowserHandoff.Run();
            if(args.Length==1&&args[0]=="--runtime-version"){Console.WriteLine(CoreWebView2Environment.GetAvailableBrowserVersionString());return 0;}
            SetProcessDPIAware();Application.EnableVisualStyles();
            var config=new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(Console.ReadLine());Application.Run(new DesktopRenderer(config));return Environment.ExitCode;
        }catch(Exception ex){Console.Error.WriteLine(ex.GetType().Name+": "+ex.Message);return 1;}
    }
}

"""Prepare, never compile, an ignored timing-only copy of reviewed host51.

No policy, evaluation, navigation, visibility or browser-flag behavior is changed.
All new output travels through the existing private owner pipe as bounded
metadata. Parameters/results/scripts/URLs/headers/bodies/tokens are never logged.
"""
import difflib
import hashlib
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[2]
AREA=ROOT/'.gate1/windows-native'
PINNED={
 'Host.cs':'ee1cf09b94ec7d4532d0a2262de7796ac72edf4a0993466abfc5944a7478c47f',
 'BrowserSurface.cs':'9d8f09501821b2ed4c80473ea683598622af510022c0f24211749ffef864832e',
 'FetchMetadata.cs':'a75ac1155fd0be150279d974867273e5c52f077bdc26112f22d2d7de6da4badf',
}

HELPERS=r'''
    // Diagnostic52 only. Bounded metadata; no arguments or results.
    readonly Stopwatch phaseClock=Stopwatch.StartNew();
    System.Windows.Forms.Timer phaseTimer;
    long phaseCall;
    int phaseRecords,phaseOutstanding,phasePulses;
    double phasePreviousPulse;
    [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] static extern bool IsChild(IntPtr parent,IntPtr child);
    [DllImport("user32.dll")] static extern IntPtr GetAncestor(IntPtr window,uint flags);
    [DllImport("dwmapi.dll")] static extern int DwmGetWindowAttribute(IntPtr window,uint attribute,out int value,int size);
    void PhaseRecord(string stage,long call,string operation,string method,double began) {
        if(phaseRecords++>=4096)return;
        Event("diagnostic-phase",new Dictionary<string,object>{{"sequence",phaseRecords},{"call",call},{"operation",operation},{"method",method},{"stage",stage},{"host_ms",phaseClock.Elapsed.TotalMilliseconds},{"elapsed_ms",phaseClock.Elapsed.TotalMilliseconds-began},{"utc_ticks",DateTime.UtcNow.Ticks},{"qpc_ticks",Stopwatch.GetTimestamp()},{"qpc_frequency",Stopwatch.Frequency},{"outstanding",phaseOutstanding},{"generation",generation},{"nav_id",activeNavigation}});
    }
    long PhaseBegin(string operation,string method,out double began) {
        long call=++phaseCall;began=phaseClock.Elapsed.TotalMilliseconds;
        ++phaseOutstanding;PhaseRecord("start",call,operation,method,began);return call;
    }
    void PhaseEnd(long call,string operation,string method,double began) {
        --phaseOutstanding;PhaseRecord("end",call,operation,method,began);
    }
    void StartPhaseHeartbeat() {
        phaseTimer=new System.Windows.Forms.Timer();phaseTimer.Interval=100;
        phasePreviousPulse=phaseClock.Elapsed.TotalMilliseconds;
        phaseTimer.Tick+=(sender,args)=> {
            if(closing||disposed||++phasePulses>1800){phaseTimer.Stop();return;}
            double now=phaseClock.Elapsed.TotalMilliseconds;
            try {
                IntPtr top=GetAncestor(Handle,2),foreground=GetForegroundWindow();int cloak=0;
                int cloakResult=DwmGetWindowAttribute(top,14,out cloak,4);
                var bounds=view.Bounds;var controller=view.DiagnosticControllerState;
                Event("diagnostic-native-state",new Dictionary<string,object>{{"sequence",phasePulses},{"host_ms",now},{"utc_ticks",DateTime.UtcNow.Ticks},{"qpc_ticks",Stopwatch.GetTimestamp()},{"qpc_frequency",Stopwatch.Frequency},{"heartbeat_gap_ms",now-phasePreviousPulse},{"own_foreground",foreground==top||foreground==Handle||IsChild(top,foreground)},{"contains_focus",ContainsFocus},{"view_contains_focus",view.ContainsFocus},{"form_visible",Visible},{"view_visible",view.Visible},{"cover_visible",serverCover.Visible},{"cloaked",cloakResult==0?(object)cloak:null},{"cloak_hresult",cloakResult},{"view_bounds",new[]{bounds.X,bounds.Y,bounds.Width,bounds.Height}},{"controller",controller},{"outstanding",phaseOutstanding},{"generation",generation},{"nav_id",activeNavigation}});
            }catch(Exception ex){Event("diagnostic-native-state-error",new Dictionary<string,object>{{"type",ex.GetType().Name}});}
            phasePreviousPulse=now;
        };
        phaseTimer.Start();
    }
'''

def wrap_method(text,signature,operation,method):
    """These selected original methods have balanced braces inside strings."""
    start=text.index(signature);opening=text.index('{',start);depth=1;end=opening+1
    while depth:
        depth+=(text[end]=='{')-(text[end]=='}');end+=1
    body=text[opening+1:end-1]
    begin='\n        double phaseBegan;long phaseId=PhaseBegin('+json.dumps(operation)+','+method+',out phaseBegan);\n        try {'
    finish='\n        }finally{PhaseEnd(phaseId,'+json.dumps(operation)+','+method+',phaseBegan);}\n    '
    return text[:opening+1]+begin+body+finish+text[end-1:]

def main():
    out=AREA/'webview2-host-candidate-52'
    assert not out.exists(),'Preserve diagnostic evidence; choose a new reviewed scope'
    original={}
    for name,expected in PINNED.items():
        raw=(ROOT/'windows_webview2'/name).read_bytes()
        assert hashlib.sha256(raw).hexdigest()==expected,(name,'Reviewed51 source changed')
        original[name]=raw.decode('utf-8').replace('\r\n','\n')
    out.mkdir(mode=0o700)
    payload=out/'payload';payload.mkdir()
    for path in (AREA/'webview2-host-candidate-51/payload').rglob('*'):
        if path.is_file() and path.name!='DLMS-WebView2-Host.exe':
            destination=payload/path.relative_to(AREA/'webview2-host-candidate-51/payload')
            destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,destination)
    host=original['Host.cs']
    host=host.replace('    void Emit(string kind, object value)',HELPERS+'\n    void Emit(string kind, object value)',1)
    for signature,operation,method in [
      ('    async Task<string> Identity()','Identity','"identity"'),
      ('    async Task<Dictionary<string,object>> Cdp(string method,object args)','Cdp','method'),
      ('    async Task<string> Frame()','Frame','"frame"'),
      ('    async Task NavigationFinished(CoreWebView2NavigationCompletedEventArgs e)','NavigationFinished','"navigation-finished"'),
      ('    async Task<object> Evaluate(string script,int world,bool gesture=false)','Evaluate',
       '(script=="document.querySelector(\'.dashboard-sidebar\')?.dataset.theme || \'\'"?"theme":script.IndexOf("responseStatus",StringComparison.Ordinal)>=0?"readiness":script.StartsWith("JSON.stringify({href:",StringComparison.Ordinal)?"identity":"other")'),
    ]:host=wrap_method(host,signature,operation,method)
    host=host.replace('Embed();await Initialize();StartReader();','Embed();StartPhaseHeartbeat();await Initialize();StartReader();',1)
    host=host.replace('if(closing)return;closing=true;','if(closing)return;closing=true;if(phaseTimer!=null){phaseTimer.Stop();phaseTimer.Dispose();}',1)
    surface=original['BrowserSurface.cs'].replace('    public BrowserSurface()',r'''
    // Diagnostic52 getter only; never changes the public controller state.
    public object DiagnosticControllerState {get {
        if(controller==null)return new {available=false};
        var bounds=controller.Bounds;
        return new {available=true,visible=controller.IsVisible,bounds=new[]{bounds.X,bounds.Y,bounds.Width,bounds.Height}};
    }}
    public BrowserSurface()''',1)
    changed={'Host.cs':host,'BrowserSurface.cs':surface,'FetchMetadata.cs':original['FetchMetadata.cs']}
    diffs=[]
    for name,text in changed.items():
        (out/name).write_text(text,encoding='utf-8',newline='\n')
        diffs.extend(difflib.unified_diff(original[name].splitlines(True),text.splitlines(True),fromfile='reviewed51/'+name,tofile='diagnostic52/'+name))
    (out/'DIFF.patch').write_text(''.join(diffs),encoding='utf-8')
    (out/'DIAGNOSTIC.json').write_text(json.dumps({'diagnostic_only':True,'compiled':False,'base':'reviewed host51 / normal candidate09','base_source_sha256':PINNED,'no_policy_or_flags_changed':True,'output_limit':{'phase_events':4096,'native_heartbeat_events':1800,'heartbeat_interval_ms':100},'no_arguments_results_scripts_urls_headers_bodies_tokens_logged':True},indent=2))
    print(out/'DIFF.patch')

if __name__=='__main__':main()

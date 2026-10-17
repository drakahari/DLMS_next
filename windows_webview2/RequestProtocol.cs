// Windows x64, pinned WebView2 public COM ABI. Pages have no access to this API.
// The managed Task wrapper discards protocol error JSON; only request decisions
// use this narrow adapter. Other CDP errors retain their existing fatal handling.
using System;
using System.Runtime.InteropServices;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Web.WebView2.Core;

sealed class RequestProtocolReply {
    public int Error;
    public string Json;
}

[ComVisible(true),Guid("5c4889f0-5ef6-4c5a-952c-d8f1b92d0574"),InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IRequestProtocolCompletion {
    [PreserveSig] int Invoke(int errorCode,[MarshalAs(UnmanagedType.LPWStr)]string result);
}

[ComVisible(true),ClassInterface(ClassInterfaceType.None)]
public sealed class RequestProtocolCompletion:IRequestProtocolCompletion {
    internal readonly TaskCompletionSource<RequestProtocolReply> Done=
        new TaskCompletionSource<RequestProtocolReply>(TaskCreationOptions.RunContinuationsAsynchronously);
    int invoked,duplicate;
    internal bool Duplicate{get{return Volatile.Read(ref duplicate)!=0;}}
    public int Invoke(int errorCode,string result){
        if(Interlocked.Exchange(ref invoked,1)!=0){Interlocked.Exchange(ref duplicate,1);return unchecked((int)0x8000FFFF);}
        try{
            Done.TrySetResult(new RequestProtocolReply{Error=errorCode,Json=result!=null&&result.Length<=1024?result:null});
            return 0;
        }catch(Exception){return unchecked((int)0x80004005);} // Never unwind managed exceptions across COM.
    }
}

sealed class RequestProtocolCall {
    // ICoreWebView2 IID76eceacb-0462-4d94-ac83-423a6793775e: method slot36,
    // including IUnknown0..2. Stable original interface, checked against the
    // pinned SDK header by native regression; no private reflection/new DLL.
    internal const int MethodSlot=36;
    readonly RequestProtocolCompletion completion=new RequestProtocolCompletion();
    bool started;
    public string Method{get;private set;}
    public Task<RequestProtocolReply> Task{get{return completion.Done.Task;}}
    public bool Duplicate{get{return completion.Duplicate;}}
    [UnmanagedFunctionPointer(CallingConvention.StdCall)]
    delegate int InvokeMethod(IntPtr self,[MarshalAs(UnmanagedType.LPWStr)]string method,
        [MarshalAs(UnmanagedType.LPWStr)]string parameters,IntPtr callback);

    public void Start(CoreWebView2 core,bool allow,string parameters){
        if(started)throw new InvalidOperationException("Repeated native request decision");
        started=true;Method=allow?"Fetch.continueRequest":"Fetch.failRequest";
        if(IntPtr.Size!=8)throw new PlatformNotSupportedException("Windows x64 request adapter required");
        IntPtr pointer=IntPtr.Zero,callback=IntPtr.Zero;
        try{
            pointer=core.GetComICoreWebView2();
            if(pointer==IntPtr.Zero)throw new InvalidOperationException("Native controller unavailable");
            callback=Marshal.GetComInterfaceForObject(completion,typeof(IRequestProtocolCompletion));
            IntPtr function=Marshal.ReadIntPtr(Marshal.ReadIntPtr(pointer),MethodSlot*IntPtr.Size);
            if(function==IntPtr.Zero)throw new InvalidOperationException("Native request interface unavailable");
            var invoke=(InvokeMethod)Marshal.GetDelegateForFunctionPointer(function,typeof(InvokeMethod));
            // Initial call failure has no completion proof and is always fatal.
            int result=invoke(pointer,Method,parameters,callback);
            if(result!=0)throw new COMException("Native request call refused before completion",result);
        }finally{
            if(callback!=IntPtr.Zero)Marshal.Release(callback);
            if(pointer!=IntPtr.Zero)Marshal.Release(pointer);
        }
    }
}

enum RequestProtocolOutcome { Rejected, Acknowledged, Retired }

static class RequestProtocolResult {
    public static RequestProtocolOutcome Decode(string method,int error,string value){
        if(method!="Fetch.continueRequest"&&method!="Fetch.failRequest")return RequestProtocolOutcome.Rejected;
        if(value==null||value.Length>1024)return RequestProtocolOutcome.Rejected;
        var scan=new Scanner(value);
        if(error==0)return scan.EmptyObject()?RequestProtocolOutcome.Acknowledged:RequestProtocolOutcome.Rejected;
        if(error!=unchecked((int)0x80070057))return RequestProtocolOutcome.Rejected;
        return scan.MissingInterception()?RequestProtocolOutcome.Retired:RequestProtocolOutcome.Rejected;
    }

    // Strict bounded grammar for the actual native producer. No escaped/case-
    // ambiguous keys, duplicate/extra fields or coercion. Future formats fail
    // closed. The numeric envelope ID is NOT the opaque Fetch request ID.
    sealed class Scanner {
        readonly string value;int at;
        public Scanner(string source){value=source;}
        void White(){while(at<value.Length&&" \t\r\n".IndexOf(value[at])>=0)at++;}
        bool Take(char c){White();if(at>=value.Length||value[at]!=c)return false;at++;return true;}
        bool End(){White();return at==value.Length;}
        string Text(){
            if(!Take('"'))return null;int start=at;
            while(at<value.Length&&value[at]!='"'){
                if(value[at]=='\\'||value[at]<32||value[at]>126||at-start>=64)return null;at++;
            }
            if(at>=value.Length)return null;string result=value.Substring(start,at-start);at++;return result;
        }
        bool Id(){
            White();int start=at;
            while(at<value.Length&&value[at]>='0'&&value[at]<='9')at++;
            int size=at-start,number;
            return size>0&&size<=10&&(size==1||value[start]!='0')&&
                Int32.TryParse(value.Substring(start,size),System.Globalization.NumberStyles.None,System.Globalization.CultureInfo.InvariantCulture,out number);
        }
        bool Code(){White();const string code="-32602";if(at+code.Length>value.Length||String.CompareOrdinal(value,at,code,0,code.Length)!=0)return false;at+=code.Length;return true;}
        bool Error(){
            if(!Take('{'))return false;bool code=false,message=false;
            for(int i=0;i<2;i++){
                string key=Text();if(!Take(':'))return false;
                if(key=="code"&&!code){if(!Code())return false;code=true;}
                else if(key=="message"&&!message){if(Text()!="Invalid InterceptionId.")return false;message=true;}
                else return false;
                if(i==0&&!Take(','))return false;
            }
            return code&&message&&Take('}');
        }
        public bool EmptyObject(){return Take('{')&&Take('}')&&End();}
        public bool MissingInterception(){
            if(!Take('{'))return false;bool id=false,error=false;
            for(int i=0;i<2;i++){
                string key=Text();if(!Take(':'))return false;
                if(key=="id"&&!id){if(!Id())return false;id=true;}
                else if(key=="error"&&!error){if(!Error())return false;error=true;}
                else return false;
                if(i==0&&!Take(','))return false;
            }
            return id&&error&&Take('}')&&End();
        }
    }
}

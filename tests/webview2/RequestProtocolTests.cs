using System;
sealed class RequestProtocolTests {
    static int checks;
    const int Invalid=unchecked((int)0x80070057);
    const string Missing="{\"error\":{\"code\":-32602,\"message\":\"Invalid InterceptionId.\"},\"id\":123}";
    static void Check(bool value){if(!value)throw new Exception("Protocol boundary check "+checks);checks++;}
    static RequestProtocolOutcome Decode(string text,int error=Invalid,string method="Fetch.continueRequest"){
        return RequestProtocolResult.Decode(method,error,text);
    }
    static int Main(){
        Check(Decode("{}",0)==RequestProtocolOutcome.Acknowledged);
        Check(Decode(" \r\n{ \t} ",0)==RequestProtocolOutcome.Acknowledged);
        Check(Decode(Missing)==RequestProtocolOutcome.Retired);
        Check(Decode(Missing,Invalid,"Fetch.failRequest")==RequestProtocolOutcome.Retired);
        Check(Decode("{\"id\":0,\"error\":{\"message\":\"Invalid InterceptionId.\",\"code\":-32602}}")==RequestProtocolOutcome.Retired);
        Check(Decode(Missing.Replace("123","2147483647"))==RequestProtocolOutcome.Retired);
        foreach(string raw in new[]{null,"","null","[]","1","{","{}",Missing+"true",Missing+Missing,
            Missing.Replace("123","-1"),Missing.Replace("123","01"),Missing.Replace("123","1.0"),Missing.Replace("123","1e2"),
            Missing.Replace("123","2147483648"),Missing.Replace("123","\"123\""),Missing.Replace("123","null"),
            Missing.Replace("\"id\":123","\"id\":123,\"id\":124"),Missing.Replace("\"error\":","\"Error\":"),
            Missing.Replace("\"id\":","\"ID\":"),Missing.Replace("\"code\":","\"Code\":"),
            Missing.Replace("\"message\":","\"Message\":"),Missing.Replace("-32602","-32603"),
            Missing.Replace("-32602","\"-32602\""),Missing.Replace("-32602","-326020"),
            Missing.Replace("Invalid InterceptionId.","Invalid requestId."),Missing.Replace("Invalid InterceptionId.","Invalid InterceptionId"),
            Missing.Replace("Invalid InterceptionId.","invalid interceptionid."),Missing.Replace("Invalid InterceptionId.","Invalid InterceptionId. extra"),
            Missing.Replace("Invalid", "\\u0049nvalid"),Missing.Replace("InterceptionId.","InterceptionId.\\n"),
            Missing.Replace("\"id\":123","\"id\":123,\"extra\":true"),Missing.Replace("\"code\":-32602","\"code\":-32602,\"code\":-32602"),
            Missing.Replace("\"code\":-32602","\"code\":-32602,\"data\":null"),Missing.Replace("\"id\":123","\"transportId\":123"),
            "{\"error\":{\"code\":-32602,\"message\":\"Invalid InterceptionId.\"}}",new string(' ',1025)+Missing}){
            Check(Decode(raw)==RequestProtocolOutcome.Rejected);
        }
        Check(Decode(Missing,0)==RequestProtocolOutcome.Rejected);
        Check(Decode(Missing,unchecked((int)0x80004005))==RequestProtocolOutcome.Rejected);
        Check(Decode(Missing,Invalid,"Network.enable")==RequestProtocolOutcome.Rejected);
        Check(Decode("{}",Invalid)==RequestProtocolOutcome.Rejected);
        Check(Decode("{}",1)==RequestProtocolOutcome.Rejected);
        Check(Decode("{\"error\":{}}",0)==RequestProtocolOutcome.Rejected);
        var callback=new RequestProtocolCompletion();
        Check(callback.Invoke(0,"{}")==0);
        Check(callback.Done.Task.Result.Error==0&&callback.Done.Task.Result.Json=="{}");
        Check(callback.Invoke(Invalid,Missing)!=0&&callback.Duplicate);
        Check(callback.Done.Task.Result.Error==0&&callback.Done.Task.Result.Json=="{}");
        callback=new RequestProtocolCompletion();Check(callback.Invoke(Invalid,new string('x',1025))==0);
        Check(callback.Done.Task.Result.Json==null);
        Check(RequestProtocolCall.MethodSlot==36);
        Check(typeof(IRequestProtocolCompletion).GUID==new Guid("5c4889f0-5ef6-4c5a-952c-d8f1b92d0574"));
        Console.WriteLine("{\"passed\":true,\"checks\":"+checks+",\"browser_launched\":false}");return 0;
    }
}

// Standalone console regressions only; no WebView, network or profile access.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Text;
using System.Web.Script.Serialization;

static class FetchMetadataTests {
    static int tests;
    static void Check(bool condition,string name){tests++;if(!condition)throw new Exception("FAILED "+name);}
    static string Envelope(string body="",string root="",string extraRequest=""){
        return "{\"requestId\":\"owned\",\"frameId\":\"root\",\"resourceType\":\"Fetch\",\"request\":{\"url\":\"http://127.0.0.1:1/_desktop/recovery/action\",\"method\":\"POST\",\"headers\":{\"Origin\":\"http://127.0.0.1:1\",\"X-Test\":\"value\"}"+extraRequest+body+"}"+root+"}";
    }
    static void Refuse(string input,string name){
        bool refused=false;try{FetchMetadata.Parse(input);}catch(FormatException){refused=true;}
        Check(refused,name);
    }
    public static int Main(){
        var json=new JavaScriptSerializer();
        var m=FetchMetadata.Parse(Envelope());
        Check(m.RequestId=="owned"&&m.FrameId=="root"&&m.ResourceType=="Fetch"&&m.Method=="POST"&&m.Headers.Count==2,"baseline");
        Check(!m.PostDataPresent&&!m.PostDataEntriesPresent&&!m.ResponseStatusPresent&&!m.ResponseErrorPresent,"absent-presence");
        m=FetchMetadata.Parse(Envelope(",\"postData\":"+json.Serialize("\"requestId\":\"forged\",\"headers\":{\"Origin\":\"http://foreign.invalid\"},\\end")+",\"postDataEntries\":[{\"bytes\":\"ZmFrZQ==\",\"nested\":[{\"requestId\":\"forged\"}]}]",
            ",\"responseStatusCode\":403,\"responseErrorReason\":\"BlockedByClient\""));
        Check(m.RequestId=="owned"&&m.Headers[0].Value=="http://127.0.0.1:1"&&m.PostDataPresent&&m.PostDataEntriesPresent&&m.ResponseStatusPresent&&m.ResponseErrorPresent,"body-does-not-spoof-authority");
        m=FetchMetadata.Parse(Envelope(",\"postData\":\"\\u0041\\n\\t\\b\\f\\r\\/\\\\\\\"\\ud83d\\ude00\""));
        Check(m.PostDataPresent,"escaped-body");
        m=FetchMetadata.Parse(Envelope(",\"postDataEntries\":[{\"bytes\":\"QQ==\"},null,1.5e-2,true,false,[1,2,3]]"));
        Check(m.PostDataEntriesPresent,"nested-structural-skip");
        Refuse(Envelope(root:",\"requestId\":\"duplicate\""),"duplicate-root-authority");
        Refuse(Envelope(root:",\"RequestId\":\"case-ambiguity\""),"case-ambiguous-root-authority");
        Refuse(Envelope(extraRequest:",\"url\":\"http://foreign.invalid\""),"duplicate-url");
        Refuse(Envelope(extraRequest:",\"Headers\":{}"),"case-ambiguous-headers");
        Refuse(Envelope(extraRequest:",\"postData\":\"first\",\"postData\":\"second\""),"duplicate-body-field");
        Refuse(Envelope().Replace("\"X-Test\":\"value\"","\"X-Test\":\"value\",\"x-test\":\"duplicate\""),"case-duplicate-http-header");
        Refuse(Envelope().Replace("\"X-Test\":\"value\"","\"X-Test\":\"line\\r\\ninjection\""),"header-linebreak");
        Refuse(Envelope().Replace("\"X-Test\":\"value\"","\"bad header\":\"value\""),"invalid-header-name");
        Refuse(Envelope()+"true","trailing-value");
        Refuse(Envelope().Substring(0,20),"truncated-envelope");
        Refuse(Envelope(",\"postData\":\"bad\\qescape\""),"invalid-body-escape");
        Refuse(Envelope(",\"postData\":\"bad\ncontrol\""),"unescaped-body-control");
        Refuse(Envelope(",\"postDataEntries\":[{\"bytes\":\"QQ==\"},]"),"trailing-array-comma");
        Refuse(Envelope(",\"postData\":{\"value\":01}"),"invalid-skipped-number-leading-zero");
        Refuse(Envelope(",\"postData\":{\"value\":1e+}"),"invalid-skipped-exponent");
        m=FetchMetadata.Parse(Envelope(",\"postData\":\"\\ud800\""));
        Check(m.PostDataPresent,"skipped-body-lone-high-surrogate-grammar");
        m=FetchMetadata.Parse(Envelope(",\"postData\":\"\\udc00\""));
        Check(m.PostDataPresent,"skipped-body-lone-low-surrogate-grammar");
        m=FetchMetadata.Parse(Envelope(root:",\"unknown\":\"\\ud800\""));
        Check(m.RequestId=="owned","skipped-unknown-lone-surrogate-grammar");
        Refuse(Envelope().Replace("\"requestId\":\"owned\"","\"requestId\":\"\\ud800\""),"retained-lone-high-surrogate");
        Refuse(Envelope().Replace("\"X-Test\":\"value\"","\"X-Test\":\"\\udc00\""),"retained-header-lone-low-surrogate");
        string nested=new string('[',33)+"0"+new string(']',33);
        Refuse(Envelope(",\"postDataEntries\":"+nested),"depth-bound-even-body");
        Refuse(Envelope(root:",\"unknownMetadata\":\""+new string('A',FetchMetadata.MetadataChars)+"\""),"metadata-limit-unknown-field");
        Refuse(Envelope().Replace("\"frameId\":\"root\",",""),"missing-frame");
        Refuse(Envelope().Replace("\"headers\":{\"Origin\":\"http://127.0.0.1:1\",\"X-Test\":\"value\"}","\"headers\":[]"),"headers-wrong-type");
        m=FetchMetadata.Parse(Envelope().Replace("/_desktop/recovery/action", "/"+new string('q',20000)));
        Check(m.Url.Length>16*1024,"large-valid-url-not-newly-restricted");
        m=FetchMetadata.Parse(Envelope().Replace("\"X-Test\":\"value\"", "\"X-Test\":\""+new string('C',100000)+"\""));
        Check(m.Headers[1].Value.Length==100000,"large-valid-header-not-newly-restricted");
        // More than the previous serializer's16MiB cap. Hold the original
        // envelope throughout measurement; the parser may not allocate a body
        // copy or retain one in the returned metadata object.
        string big=Envelope(",\"postData\":\""+new string('A',20*1024*1024)+"\",\"postDataEntries\":[{\"bytes\":\""+new string('Q',28*1024*1024)+"\"}]");
        GC.Collect();GC.WaitForPendingFinalizers();GC.Collect();
        AppDomain.MonitoringIsEnabled=true;
        long before=GC.GetTotalMemory(true);
        long allocatedBefore=AppDomain.CurrentDomain.MonitoringTotalAllocatedMemorySize;
        var timer=Stopwatch.StartNew();m=FetchMetadata.Parse(big);timer.Stop();
        long after=GC.GetTotalMemory(true);
        long allocated=AppDomain.CurrentDomain.MonitoringTotalAllocatedMemorySize-allocatedBefore;
        GC.KeepAlive(big);
        Check(m.PostDataPresent&&m.PostDataEntriesPresent&&m.Headers.Count==2,"large-body-and-entries-skipped");
        Check(after-before<1024*1024,"no-large-body-copy-retained");
        Check(allocated<1024*1024,"no-large-body-copy-allocated");
        Check(FetchMetadata.EnvelopeChars==256L*1024*1024&&FetchMetadata.EnvelopeChars<Int32.MaxValue,"production-resource-envelope-bound");
        Console.WriteLine("{\"passed\":true,\"tests\":"+tests+",\"large_envelope_chars\":"+big.Length+",\"scan_milliseconds\":"+timer.ElapsedMilliseconds+",\"retained_growth_bytes\":"+(after-before)+",\"allocated_bytes\":"+allocated+",\"body_values_logged\":false,\"native_or_normal_acceptance\":false}");
        return 0;
    }
}

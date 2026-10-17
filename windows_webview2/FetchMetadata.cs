// Bounded structural metadata scanner for native Fetch.requestPaused policy.
// Body values already exist in the upstream CDP envelope string. This scanner
// does not deserialize or copy them; continueRequest leaves Chromium body intact.
using System;
using System.Collections.Generic;
using System.Text;

sealed class FetchMetadata {
    // Native envelope resource bound is256MiB characters aggregate in flight, not
    // a receiver/File size limit. Tested disk File requests omit their bytes
    // from this envelope. Arbitrary256MiB raw-body transport is unqualified.
    public const long WorkflowBytes=256L*1024*1024;
    public const int MetadataChars=16*1024*1024;
    public const long EnvelopeChars=256L*1024*1024;
    public string RequestId,FrameId,ResourceType,Url,Method;
    public bool ResponseStatusPresent,ResponseErrorPresent,PostDataPresent,PostDataEntriesPresent;
    public readonly List<KeyValuePair<string,string>> Headers=new List<KeyValuePair<string,string>>();

    public static FetchMetadata Parse(string source) {
        if(source==null)throw new FormatException("Missing envelope");
        if(source.Length>EnvelopeChars)throw new FormatException("Envelope limit");
        var scanner=new Scanner(source);
        return scanner.Run();
    }
    sealed class Scanner {
        readonly string source;
        readonly FetchMetadata value=new FetchMetadata();
        int offset,depth,metadata;
        bool body;
        public Scanner(string input){source=input;}
        void Error(){throw new FormatException("Malformed or oversized Fetch metadata");}
        char Peek(){return offset<source.Length?source[offset]:'\0';}
        char Take(){
            if(offset>=source.Length)Error();
            if(!body&&++metadata>MetadataChars)Error();
            return source[offset++];
        }
        void White(){while(Peek()==' '||Peek()=='\t'||Peek()=='\r'||Peek()=='\n')Take();}
        void Expect(char expected){if(Take()!=expected)Error();}
        void Enter(){if(++depth>32)Error();}
        void Leave(){depth--;}
        bool End(char close){White();if(Peek()==close){Take();return true;}return false;}
        void Separator(){White();Expect(',');White();}
        static bool Eq(string a,string b){return String.Equals(a,b,StringComparison.OrdinalIgnoreCase);}
        void Unique(HashSet<string> seen,string key){if(!seen.Add(key))Error();}
        int Hex(){
            char item=Take();
            if(item>='0'&&item<='9')return item-'0';
            if(item>='a'&&item<='f')return item-'a'+10;
            if(item>='A'&&item<='F')return item-'A'+10;
            Error();return 0;
        }
        char Unicode(){return (char)((Hex()<<12)|(Hex()<<8)|(Hex()<<4)|Hex());}
        string StringValue(int limit,bool retain){
            Expect('"');
            StringBuilder result=retain?new StringBuilder():null;
            int length=0;
            while(true){
                char item=Take();
                if(item=='"')break;
                if(item<' ')Error();
                if(item=='\\'){
                    char escaped=Take();
                    switch(escaped){
                        case '"':item='"';break;case '\\':item='\\';break;case '/':item='/';break;
                        case 'b':item='\b';break;case 'f':item='\f';break;case 'n':item='\n';break;
                        case 'r':item='\r';break;case 't':item='\t';break;
                        case 'u':item=Unicode();break;
                        default:Error();break;
                    }
                }
                // Skipped values preserve JSON grammar, which permits lone
                // surrogate escapes. They are never retained as authority.
                if(!retain){length++;continue;}
                // Treat escaped and literal surrogate pairs identically. Lone
                // surrogates are refused rather than reinterpreted by another
                // parser or by URI/header APIs.
                if(Char.IsHighSurrogate(item)){
                    char low=Take();
                    if(low=='\\'){Expect('u');low=Unicode();}
                    if(!Char.IsLowSurrogate(low))Error();
                    length+=2;if(retain){if(length>limit)Error();result.Append(item);result.Append(low);}
                }else{
                    if(Char.IsLowSurrogate(item))Error();
                    length++;if(retain){if(length>limit)Error();result.Append(item);}
                }
            }
            return retain?result.ToString():null;
        }
        string Text(int limit){White();return StringValue(limit,true);}
        string Key(){White();return StringValue(MetadataChars,true);}
        void Literal(string text){foreach(char item in text)Expect(item);}
        void Number(){
            if(Peek()=='-')Take();
            char c=Peek();
            if(c=='0')Take();
            else{if(c<'1'||c>'9')Error();do{Take();c=Peek();}while(c>='0'&&c<='9');}
            if(Peek()=='.'){Take();c=Peek();if(c<'0'||c>'9')Error();do{Take();c=Peek();}while(c>='0'&&c<='9');}
            if(Peek()=='e'||Peek()=='E'){
                Take();if(Peek()=='+'||Peek()=='-')Take();c=Peek();if(c<'0'||c>'9')Error();
                do{Take();c=Peek();}while(c>='0'&&c<='9');
            }
        }
        void Skip(){
            White();char current=Peek();
            if(current=='"'){StringValue(0,false);return;}
            if(current=='{'){
                Enter();Take();if(!End('}')){while(true){StringValue(0,false);White();Expect(':');Skip();if(End('}'))break;Separator();}}
                Leave();return;
            }
            if(current=='['){
                Enter();Take();if(!End(']')){while(true){Skip();if(End(']'))break;Separator();}}
                Leave();return;
            }
            if(current=='t'){Literal("true");return;}
            if(current=='f'){Literal("false");return;}
            if(current=='n'){Literal("null");return;}
            Number();
        }
        void SkipBody(){bool prior=body;body=true;try{Skip();}finally{body=prior;}}
        void Headers(){
            Enter();White();Expect('{');
            var names=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            if(!End('}')){while(true){
                string name=Key();Unique(names,name);White();Expect(':');
                string content=Text(MetadataChars);
                // HTTP field names are ASCII tokens. CR/LF/NUL values cannot
                // be valid CDP header metadata and may not enter native APIs.
                if(name.Length==0)Error();
                foreach(char c in name)if(!((c>='a'&&c<='z')||(c>='A'&&c<='Z')||(c>='0'&&c<='9')||"!#$%&'*+-.^_`|~".IndexOf(c)>=0))Error();
                if(content.IndexOf('\r')>=0||content.IndexOf('\n')>=0||content.IndexOf('\0')>=0)Error();
                value.Headers.Add(new KeyValuePair<string,string>(name,content));
                if(End('}'))break;Separator();
            }}Leave();
        }
        void Request(){
            Enter();White();Expect('{');
            var seen=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            bool url=false,method=false,headers=false;
            if(!End('}')){while(true){
                string key=Key();White();Expect(':');
                if(Eq(key,"url")){Unique(seen,key);if(key!="url")Error();value.Url=Text(MetadataChars);url=true;}
                else if(Eq(key,"method")){Unique(seen,key);if(key!="method")Error();value.Method=Text(MetadataChars);method=true;}
                else if(Eq(key,"headers")){Unique(seen,key);if(key!="headers")Error();Headers();headers=true;}
                else if(Eq(key,"postData")){Unique(seen,key);if(key!="postData")Error();value.PostDataPresent=true;SkipBody();}
                else if(Eq(key,"postDataEntries")){Unique(seen,key);if(key!="postDataEntries")Error();value.PostDataEntriesPresent=true;SkipBody();}
                else Skip();
                if(End('}'))break;Separator();
            }}Leave();
            if(!url||!method||!headers||String.IsNullOrEmpty(value.Url)||String.IsNullOrEmpty(value.Method))Error();
        }
        public FetchMetadata Run(){
            White();Enter();Expect('{');
            var seen=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            bool request=false;
            if(!End('}')){while(true){
                string key=Key();White();Expect(':');
                if(Eq(key,"requestId")){Unique(seen,key);if(key!="requestId")Error();value.RequestId=Text(MetadataChars);}
                else if(Eq(key,"frameId")){Unique(seen,key);if(key!="frameId")Error();value.FrameId=Text(MetadataChars);}
                else if(Eq(key,"resourceType")){Unique(seen,key);if(key!="resourceType")Error();value.ResourceType=Text(MetadataChars);}
                else if(Eq(key,"request")){Unique(seen,key);if(key!="request")Error();Request();request=true;}
                else if(Eq(key,"responseStatusCode")){Unique(seen,key);if(key!="responseStatusCode")Error();value.ResponseStatusPresent=true;Skip();}
                else if(Eq(key,"responseErrorReason")){Unique(seen,key);if(key!="responseErrorReason")Error();value.ResponseErrorPresent=true;Skip();}
                else Skip();
                if(End('}'))break;Separator();
            }}Leave();White();
            if(offset!=source.Length||!request||String.IsNullOrEmpty(value.RequestId)||String.IsNullOrEmpty(value.FrameId)||String.IsNullOrEmpty(value.ResourceType))Error();
            return value;
        }
    }
}

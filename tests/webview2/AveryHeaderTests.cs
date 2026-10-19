using System;
class AveryHeaderTests {
    static int checks;
    static void Check(bool actual,bool expected){checks++;if(actual!=expected)throw new Exception("Avery header case "+checks);}
    static void Main(){
        const string o="https://server.example:443",s=o+"/anki/custom";
        foreach(string mode in new[]{"local","server"}) {
            Check(DesktopRenderer.AveryHeadersAllowed(mode,o,s,true,o,true,s),true);
            foreach(string bad in new[]{"https://foreign.example","null ","",o+"/", "null.evil"})
                Check(DesktopRenderer.AveryHeadersAllowed(mode,o,s,true,bad,true,s),false);
            foreach(string bad in new[]{"https://foreign.example/anki/custom","null","",o+"/other",s+"#fragment"})
                Check(DesktopRenderer.AveryHeadersAllowed(mode,o,s,true,o,true,bad),false);
        }
        foreach(string mode in new[]{"local","server"}) {
            bool remote=mode=="server";
            Check(DesktopRenderer.AveryHeadersAllowed(mode,o,s,false,null,false,null),remote);
            Check(DesktopRenderer.AveryHeadersAllowed(mode,o,s,true,"null",false,null),remote);
            Check(DesktopRenderer.AveryHeadersAllowed(mode,o,s,true,o,false,null),remote);
            Check(DesktopRenderer.AveryHeadersAllowed(mode,o,s,false,null,true,s),remote);
            Check(DesktopRenderer.AveryHeadersAllowed(mode,o,s,true,"null",true,s),remote);
        }
        Check(DesktopRenderer.AveryHeadersAllowed("invalid",o,s,false,null,false,null),false);
        Console.WriteLine("{\"passed\":true,\"checks\":"+checks+",\"browser_launched\":false}");
    }
}

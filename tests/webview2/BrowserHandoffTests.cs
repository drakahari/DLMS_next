// Read-only desktop COM and input-boundary regression. Never opens a URL.
using System;
using System.Collections.Generic;
using System.Reflection;
using System.Runtime.InteropServices;

class BrowserHandoffTests {
    [STAThread] static int Main() {
        int passed=0;
        foreach(string value in new[]{"https://example.invalid/", "http://example.invalid/path?x=a%20b#part", "https://xn--bcher-kva.invalid/%E6%97%A5"}) {
            if(BrowserHandoff.Target(value)!=value)throw new Exception("Destination changed");passed++;
        }
        foreach(string value in new[]{"", "file:///C:/Windows/notepad.exe", "javascript:alert(1)", "ms-settings:defaultapps", "C:/Windows/notepad.exe",
            "https://u:p@example.invalid/", "https://localhost/", "http://a.localhost/", "http://127.0.0.1/", "https://[::1]/", "https://example.invalid/\n", "https://example.invalid/\\bad",new string('x',8193)}) {
            bool refused=false;try{BrowserHandoff.Target(value);}catch(ArgumentException){refused=true;}
            if(!refused)throw new Exception("Invalid destination accepted");passed++;
        }
        var held=new List<object>();
        try {
            object shell=typeof(BrowserHandoff).GetMethod("Desktop",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,new object[]{held});
            if(shell==null)throw new Exception("No desktop dispatch");passed++;
            Console.WriteLine("{\"passed\":true,\"tests\":"+passed+",\"desktop_dispatch_resolved\":true,\"browser_launched\":false}");
        }finally{
            var released=new HashSet<object>();
            for(int i=held.Count-1;i>=0;i--)if(held[i]!=null&&released.Add(held[i])&&Marshal.IsComObject(held[i]))Marshal.FinalReleaseComObject(held[i]);
        }
        return 0;
    }
}

using System;
using System.Collections.Generic;
static class AiActionLeaseTests {
    static int checks;
    static void Check(bool value){checks++;if(!value)throw new Exception("Action destination lease mismatch");}
    static void Main(){
        var source=new Dictionary<string,string>{{"study-review","https://chatgpt.com/"}};
        var lease=new AiActionLease(source);var observer=lease.Policy();string target;
        source["study-review"]="https://unexpected.invalid/";
        Check(lease.TryGetTarget("study-review",out target)&&target==observer["study-review"]);
        source.Clear();Check(lease.TryGetTarget("study-review",out target)&&target=="https://chatgpt.com/");
        observer["study-review"]="https://different.invalid/";
        Check(lease.TryGetTarget("study-review",out target)&&target=="https://chatgpt.com/");
        Check(!lease.TryGetTarget("Open ChatGPT",out target));
        Check(lease.Policy()["study-review"]=="https://chatgpt.com/");
        var later=new AiActionLease(new Dictionary<string,string>{{"study-review","https://claude.ai/"}});
        Check(later.TryGetTarget("study-review",out target)&&target=="https://claude.ai/");
        Check(lease.TryGetTarget("study-review",out target)&&target=="https://chatgpt.com/");
        Console.WriteLine("{\"passed\":true,\"checks\":"+checks+",\"browser_launched\":false}");
    }
}

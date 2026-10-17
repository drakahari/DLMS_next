using System;
using System.Collections.Generic;

// The armed observer and native dispatcher must use the same immutable target
// set, even if a late response or caller mutates its original metadata map.
sealed class AiActionLease {
    readonly Dictionary<string,string> targets;
    public AiActionLease(IDictionary<string,string> source) {
        if(source==null)throw new ArgumentNullException("source");
        targets=new Dictionary<string,string>(source,StringComparer.Ordinal);
    }
    public Dictionary<string,string> Policy() {return new Dictionary<string,string>(targets,StringComparer.Ordinal);}
    public bool TryGetTarget(string action,out string target) {return targets.TryGetValue(action,out target);}
}

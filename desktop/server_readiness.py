"""Read-only presentation readiness; never a save, authentication or action ack."""
from __future__ import annotations
import math

# ApplicationWorld prevents application JavaScript replacing these browser APIs.
# No JS-to-native channel, observer callback or native object is exposed.
READINESS_SCRIPT = """(() => {
 const nav = performance.getEntriesByType('navigation')[0];
 return JSON.stringify({href:location.href, timeOrigin:performance.timeOrigin,
   ready:document.readyState, responseStatus:nav?.responseStatus,
   responseEnd:nav?.responseEnd, theme:document.querySelector('.dashboard-sidebar')?.dataset.theme || ''});
})()"""


def document_identity(snapshot):
    if not isinstance(snapshot, dict):return None
    href, stamp = snapshot.get('href'), snapshot.get('timeOrigin')
    if not isinstance(href,str) or not href or isinstance(stamp,bool) or not isinstance(stamp,(float,int)) or not math.isfinite(stamp) or stamp<=0:return None
    return (href,stamp)


def ready_new_document(snapshot, previous, url):
    identity=document_identity(snapshot)
    # Missing previous evidence means keep the conservative loadFinished path.
    if previous is None or identity is None or identity==previous or identity[1]==previous[1]:return False
    if identity[0]!=url or not isinstance(snapshot.get('ready'),str) or snapshot['ready'] not in {'interactive','complete'}:return False
    end=snapshot.get('responseEnd')
    return type(snapshot.get('responseStatus')) is int and snapshot['responseStatus']==200 and not isinstance(end,bool) and isinstance(end,(int,float)) and math.isfinite(end) and end>0

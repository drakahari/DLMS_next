"""Fixed, read-only content-layer metadata for opt-in window diagnostics."""

ROLES=('shell','sidebar','main','cards')
LAYER_PROBE="""(() => {
const bounded=n=>Math.max(-1000000,Math.min(1000000,Math.round(n)));
const choice=(v,allowed)=>allowed.includes(v)?v:'other';
const layer=selector=>{const n=document.querySelector(selector);if(!n)return null;
const s=getComputedStyle(n),r=n.getBoundingClientRect();
const left=Math.max(0,r.left),right=Math.min(innerWidth,r.right),top=Math.max(0,r.top),bottom=Math.min(innerHeight,r.bottom);
const inside=right>left&&bottom>top;
const hit=inside?document.elementFromPoint((left+right)/2,(top+bottom)/2):null;
return {display:choice(s.display,['none','block','inline','inline-block','flex','grid','contents']),
visibility:choice(s.visibility,['visible','hidden','collapse']),opacity:Math.round(Number(s.opacity)*100),
content_visibility:choice(s.contentVisibility,['visible','hidden','auto']),
pointer_events:choice(s.pointerEvents,['auto','none']),
x:bounded(r.x),y:bounded(r.y),width:bounded(r.width),height:bounded(r.height),
hidden:Boolean(n.hidden),connected:n.isConnected,inside_viewport:inside,
center_hits_self:inside?Boolean(hit&&(hit===n||n.contains(hit))):null,
transform:s.transform!=='none',filter:s.filter!=='none',
backdrop:Boolean(s.backdropFilter&&s.backdropFilter!=='none'),clip:s.clipPath!=='none',
children:Math.min(100000,n.childElementCount)};};
return {shell:layer('.dashboard-shell'),sidebar:layer('.dashboard-sidebar'),
main:layer('.dashboard-main'),cards:layer('.dashboard-action-grid')};})()"""

def valid_layers(value):
    if not isinstance(value,dict) or set(value)!=set(ROLES):return False
    enum_fields={'display':('none','block','inline','inline-block','flex','grid','contents','other'),
                 'visibility':('visible','hidden','collapse','other'),
                 'content_visibility':('visible','hidden','auto','other'),
                 'pointer_events':('auto','none','other')}
    bool_fields=('hidden','connected','inside_viewport','transform','filter','backdrop','clip')
    integer_fields={'x':(-1000000,1000000),'y':(-1000000,1000000),'width':(0,1000000),
                    'height':(0,1000000),'opacity':(0,100),'children':(0,100000)}
    fields=set(enum_fields)|set(bool_fields)|set(integer_fields)|{'center_hits_self'}
    for layer in value.values():
        if layer is None:continue
        if not isinstance(layer,dict) or set(layer)!=fields:return False
        if any(type(layer[k]) is not str or layer[k] not in allowed for k,allowed in enum_fields.items()):return False
        if any(type(layer[k]) is not bool for k in bool_fields):return False
        if any(type(layer[k]) is not int or not limits[0]<=layer[k]<=limits[1] for k,limits in integer_fields.items()):return False
        if layer['center_hits_self'] is not None and type(layer['center_hits_self']) is not bool:return False
    return True

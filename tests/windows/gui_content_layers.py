"""Source-only classifier calibration, never a physical blanking reproduction."""
import argparse
import json

from desktop.isolation import PROJECT
from desktop.window_events import WindowEvents,document_sample,PROBE
from tests.gate1.qt_checks import QtChecks

def main():
    p=argparse.ArgumentParser();p.add_argument('--profile',required=True);a=p.parse_args()
    output=PROJECT/'.gate1/windows-native/chooser-blanking-01'/f'{a.profile}-content-layers.json'
    if output.exists():raise ValueError('Choose fresh evidence/profile names')
    q=QtChecks(a.profile,automated=True)
    collector=WindowEvents(q.window);q.window.window_events=collector;collector.bind(q.window.view)
    try:
        q.delay(1.5)
        normal=document_sample(q.js(PROBE));assert normal and normal['layers']['shell']['opacity']==100
        assert normal['layers']['shell']['width']>0 and normal['layers']['sidebar']['width']>0
        # Synthetic app only: simulate a layout-preserving missing shell for
        # twenty seconds, with root/body still visible. Never a product repair.
        q.js("const s=document.createElement('style');s.id='synthetic-layer-calibration';s.textContent='.dashboard-shell{opacity:0!important}';document.head.appendChild(s);true")
        q.delay(20)
        hidden=document_sample(q.js(PROBE));assert hidden and hidden['layers']['shell']['opacity']==0
        assert hidden['presentation']['body']['opacity']==100 and hidden['layers']['shell']['width']>0
        q.js("document.getElementById('synthetic-layer-calibration').textContent='.dashboard-shell{display:none!important}';true")
        q.delay(2)
        collapsed=document_sample(q.js(PROBE));assert collapsed and collapsed['layers']['shell']['display']=='none'
        assert collapsed['layers']['shell']['width']==0
        q.js("document.getElementById('synthetic-layer-calibration').remove();true")
        q.delay(1.5)
        restored=document_sample(q.js(PROBE));assert restored and restored['layers']['shell']['opacity']==100
        assert restored['layers']['shell']['width']>0
        q.js("const cover=document.createElement('div');cover.id='synthetic-layer-cover';cover.style.cssText='position:fixed;inset:0;z-index:2147483647;background:#4a1d5a';document.body.appendChild(cover);true")
        q.delay(2)
        covered=document_sample(q.js(PROBE));assert covered and covered['layers']['sidebar']['center_hits_self'] is False
        assert covered['layers']['main']['center_hits_self'] is False and covered['layers']['shell']['opacity']==100
        q.js("document.getElementById('synthetic-layer-cover').remove();true")
        collector.stop()
        rows=[json.loads(x) for x in collector.path.read_text().splitlines()]
        opaque_hidden=[r for r in rows if r['event']=='document-state' and r.get('layers',{}).get('shell') and r['layers']['shell']['opacity']==0]
        assert len(opaque_hidden)>=18
        assert all(r['presentation']['body']['opacity']==100 for r in opaque_hidden)
        assert any(r['event']=='sample' and r['content_children'] for r in rows)
        assert not any(r['event'] in ('load-start','renderer-terminated') for r in rows)
        result={'source_Qt':True,'classifier_calibration_only':True,'normal_package_physical_acceptance':False,
                'owner_episode_reproduced':False,'synthetic_hidden_seconds':20,'hidden_samples':len(opaque_hidden),
                'normal':normal,'hidden':hidden,'collapsed':collapsed,'restored':restored,'covered':covered,'trace':str(collector.path)}
        output.write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps({k:v for k,v in result.items() if k not in ('normal','hidden','collapsed','restored','covered')},indent=2))
    finally:
        try:q.js("document.getElementById('synthetic-layer-calibration')?.remove();document.getElementById('synthetic-layer-cover')?.remove();true")
        finally:collector.stop();q.close()

if __name__=='__main__':main()

"""Bounded source-Qt sidebar probe; no OS mouse movement or physical acceptance."""
import argparse
import json

from PySide6.QtCore import QEvent,QPoint,QPointF,Qt
from PySide6.QtGui import QEnterEvent,QMouseEvent
from PySide6.QtWidgets import QApplication

from desktop.isolation import PROJECT
from tests.gate1.qt_checks import QtChecks

SELECTOR='.dashboard-sidebar [data-nav-key="library"]'
PROBE="""JSON.stringify((()=>({hover:document.querySelector('.dashboard-sidebar [data-nav-key="library"]').matches(':hover'),
enter:window.__hoverProbe.enter,move:window.__hoverProbe.move,
layers:['html','body','.dashboard-shell','.dashboard-sidebar','.dashboard-main'].map(selector=>{
const node=document.querySelector(selector);if(!node)return null;const s=getComputedStyle(node),r=node.getBoundingClientRect();
return {selector,display:s.display,visibility:s.visibility,opacity:Number(s.opacity),
width:Math.round(r.width),height:Math.round(r.height),transform:s.transform,backdrop:s.backdropFilter};})}))())"""

def main():
    p=argparse.ArgumentParser();p.add_argument('--profile',required=True);a=p.parse_args()
    output=PROJECT/'.gate1/windows-native/chooser-blanking-01'/f'{a.profile}-content-hover.json'
    if output.exists():raise ValueError('Choose a fresh evidence/profile name')
    q=QtChecks(a.profile,automated=True);samples=[];events=[]
    try:
        view=q.window.view;page=view.page()
        page.loadStarted.connect(lambda:events.append('load-start'))
        page.renderProcessTerminated.connect(lambda *_:events.append('renderer-terminated'))
        q.wait("Boolean(document.querySelector('.dashboard-sidebar [data-nav-key=library]'))")
        q.js("window.__hoverProbe={enter:0,move:0};const n=document.querySelector('.dashboard-sidebar [data-nav-key=library]');n.addEventListener('pointerenter',()=>++window.__hoverProbe.enter);n.addEventListener('pointermove',()=>++window.__hoverProbe.move);true")
        points=json.loads(q.js("JSON.stringify((()=>{const r=document.querySelector('.dashboard-sidebar [data-nav-key=library]').getBoundingClientRect();return [{x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2)},{x:innerWidth-25,y:Math.round(innerHeight/2)}]})())"))
        q.delay(3)
        for _ in range(16):
            for point in points:
                position=QPoint(point['x'],point['y'])
                target=view.childAt(position) or view
                local=target.mapFrom(view,position);global_position=target.mapToGlobal(local)
                # Direct QObject delivery stays inside this synthetic app. No
                # QTest.mouseMove, QCursor.setPos, SendInput or desktop input.
                QApplication.sendEvent(target,QEnterEvent(QPointF(local),QPointF(target.mapTo(q.window,local)),QPointF(global_position)))
                QApplication.sendEvent(target,QMouseEvent(QEvent.Type.MouseMove,QPointF(local),QPointF(global_position),Qt.MouseButton.NoButton,Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier))
                q.delay(.18)
                samples.append(json.loads(q.js(PROBE)))
        assert not events,events
        assert all(layer['display']!='none' and layer['visibility']=='visible' and layer['opacity']>0 and layer['width']>0 and layer['height']>0
                   for sample in samples for layer in sample['layers'] if layer is not None)
        result={'source_Qt':True,'normal_package':False,'physical_acceptance':False,
                'OS_pointer_movement':False,'actual_hover_observed':any(s['hover'] for s in samples),
                'pointer_enter_count':samples[-1]['enter'],'pointer_move_count':samples[-1]['move'],
                'samples':samples,'events':events,'visual_blanking_measured':False,
                'long_idle_reproduced':False,'window_active_at_end':q.window.isActiveWindow()}
        output.write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps({k:v for k,v in result.items() if k!='samples'},indent=2))
    finally:q.close()

if __name__=='__main__':main()

import json
import os

import pytest
from PySide6.QtWidgets import QApplication,QMainWindow

import desktop.window_events as events

@pytest.fixture
def capture(tmp_path):
    app=QApplication.instance() or QApplication([])
    window=QMainWindow();window.owner_root=tmp_path;window._closing=False;window.backend=None;window.view=None
    collector=events.WindowEvents(window);collector.timer.stop()
    try:yield collector,window
    finally:collector.stop();window.close()

def rows(collector):
    return [json.loads(x) for x in collector.path.read_text().splitlines()]

def test_capture_survives_old_cutoff_and_finishes_with_utc_and_reason(capture,monkeypatch):
    collector,window=capture
    monkeypatch.setattr(events.time,'monotonic',lambda:collector.started+181)
    collector.sample()
    assert not collector.stopped
    monkeypatch.setattr(events.time,'monotonic',lambda:collector.started+901)
    collector.sample()
    assert not collector.stopped
    monkeypatch.setattr(events.time,'monotonic',lambda:collector.started+1801)
    collector.sample()
    result=rows(collector)
    assert collector.stopped and result[-1]['event']=='capture-stop' and result[-1]['reason']=='duration'
    assert result[-1]['ms']==1801000 and result[0]['seconds']==1800
    assert all(x['utc'].endswith('Z') for x in result)
    assert not window._closing

def test_record_cap_reserves_explicit_end_record(capture,monkeypatch):
    collector,_=capture
    monkeypatch.setattr(events,'RECORD_LIMIT',5)
    for _ in range(20):collector.emit('test-count',count=1)
    result=rows(collector)
    assert len(result)==5 and result[-1]['reason']=='limit'
    assert collector.stopped and 'fd' not in collector.resource

def test_byte_cap_reserves_footer(capture,monkeypatch):
    collector,_=capture
    monkeypatch.setattr(events,'LIMIT',2048)
    for _ in range(30):collector.emit('test-size',padding='x'*400)
    assert collector.path.stat().st_size<=2048
    assert rows(collector)[-1]['reason']=='limit' and collector.stopped

def test_capture_write_failure_stops_only_capture(capture,monkeypatch):
    collector,window=capture
    def refuse(*args):raise OSError('Synthetic diagnostic write refusal')
    monkeypatch.setattr(events.os,'write',refuse)
    collector.emit('test-count',count=1)
    assert collector.stopped and not window._closing

def test_presentation_probe_is_numeric_and_allowlisted():
    style={'display':'block','visibility':'visible','opacity':100}
    value={'epoch':100,'ready':'complete','visibility':'visible','navigation':'navigate',
           'presentation':{'root':style.copy(),'body':style.copy()}}
    assert events.document_sample(json.dumps(value))==value
    for key,bad in (('display','private text'),('visibility','https://secret.invalid'),('opacity',True),('opacity',101)):
        changed=json.loads(json.dumps(value));changed['presentation']['body'][key]=bad
        assert events.document_sample(json.dumps(changed)) is None

def test_content_layer_schema_rejects_content_urls_and_unbounded_numbers():
    from desktop.content_layers import valid_layers,ROLES
    layer={'display':'grid','visibility':'visible','opacity':100,'content_visibility':'visible','pointer_events':'auto',
           'x':0,'y':10,'width':100,'height':100,'hidden':False,'connected':True,'inside_viewport':True,
           'center_hits_self':True,'transform':False,'filter':False,'backdrop':True,'clip':False,'children':2}
    value={role:layer.copy() for role in ROLES}
    assert valid_layers(value)
    assert valid_layers({role:None for role in ROLES})
    for key,bad in (('display','private text'),('filter','https://secret.invalid'),('x',1000001),
                    ('width',-1),('children',True),('opacity',101),('center_hits_self',1)):
        changed=json.loads(json.dumps(value));changed['shell'][key]=bad
        assert not valid_layers(changed)
    changed=json.loads(json.dumps(value));changed['shell']['text']='private'
    assert not valid_layers(changed)
    assert not valid_layers({**value,'untrusted':None})

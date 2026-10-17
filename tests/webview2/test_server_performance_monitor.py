"""Regression for actual native-cover identity and active JSONL reads."""
import pytest
from tests.webview2.normal_server_performance import native_uncovered,rows

def controls(text,shown=False):
 rectangle=[8,31,1288,847]
 return [dict(hwnd=1,parent=0,pid=10,text='DLMS Desktop',visible=True,rect=rectangle,**{'class':'WindowsForms10.Window.8'}),
  dict(hwnd=2,parent=1,pid=10,text='',visible=shown,rect=rectangle,**{'class':'WindowsForms10.Window.8'}),
  dict(hwnd=3,parent=2,pid=10,text=text,visible=shown,rect=rectangle,**{'class':'WindowsForms10.STATIC.app.0'}),
  dict(hwnd=4,parent=1,pid=11,text='Chrome Legacy Window',visible=True,rect=rectangle,**{'class':'Chrome_RenderWidgetHostHWND'})]

@pytest.mark.parametrize('text',['Connecting to synthetic Server…','Loading Server page…','Cannot connect to synthetic Server'])
def test_uncovery_uses_control_identity_independent_of_label(text):
 assert native_uncovered(controls(text))
 assert not native_uncovered(controls(text,True))

def test_uncovery_refuses_unrelated_label_or_different_renderer_geometry():
 items=controls('Connecting');items[0]['text']='Other application'
 assert not native_uncovered(items)
 items=controls('Connecting');items[3]['rect']=[0,0,100,100]
 assert not native_uncovered(items)

def test_jsonl_reader_waits_for_unfinished_last_line_but_rejects_corrupt_completed_record(tmp_path):
 path=tmp_path/'events.jsonl';path.write_text('{"phase":1}\n{"phase":')
 assert rows(path)==[{'phase':1}]
 path.write_text('{"phase":1}\ncorrupt\n')
 with pytest.raises(ValueError):rows(path)

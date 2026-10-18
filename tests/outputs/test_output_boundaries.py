"""Download-only Blob exception and original-request handoff contracts."""
from types import SimpleNamespace as NS
from unittest.mock import Mock
import pytest
from PySide6.QtCore import QUrl
from desktop.marked_exports import allowed_blob
from desktop.shell import LocalPage
from desktop.server_browser import ServerPage

UUID='11111111-2222-3333-4444-555555555555'

def setup(mode='local',document='/marked-questions',blob=None,name='dlms_marked_questions.apkg'):
    origin='http://127.0.0.1:8134' if mode=='local' else 'https://synthetic.example:443'
    page=NS(url=lambda:QUrl(origin+document))
    owner=NS(mode=mode,port=8134,mode_config={'server':{'origin':origin}},
             _closing=False,_retiring_browser=None,view=NS(page=lambda:page))
    request=NS(page=lambda:page,url=lambda:QUrl(blob or 'blob:'+origin+'/'+UUID),downloadFileName=lambda:name)
    return owner,request,page

@pytest.mark.parametrize('mode',['local','server'])
def test_only_active_exact_origin_marked_apkg_is_eligible(mode):
    owner,request,page=setup(mode)
    assert allowed_blob(owner,request)
    owner._closing=True;assert not allowed_blob(owner,request)
    owner._closing=False;owner._retiring_browser=object();assert not allowed_blob(owner,request)
    owner._retiring_browser=None;owner.view=NS(page=lambda:object());assert not allowed_blob(owner,request)

@pytest.mark.parametrize('document,blob,name',[
 ('/library',None,'dlms_marked_questions.apkg'),
 ('/marked-questions/extra',None,'dlms_marked_questions.apkg'),
 ('/marked-questions','blob:http://127.0.0.1:8135/'+UUID,'dlms_marked_questions.apkg'),
 ('/marked-questions','blob:http://127.0.0.2:8134/'+UUID,'dlms_marked_questions.apkg'),
 ('/marked-questions','blob:http://u:p@127.0.0.1:8134/'+UUID,'dlms_marked_questions.apkg'),
 ('/marked-questions','blob:http://127.0.0.1:8134/'+UUID+'?x=1','dlms_marked_questions.apkg'),
 ('/marked-questions','blob:null/'+UUID,'dlms_marked_questions.apkg'),
 ('/marked-questions','data:text/plain,example','dlms_marked_questions.apkg'),
 ('/marked-questions',None,'other.apkg'),
])
def test_blob_origin_document_and_filename_refusals(document,blob,name):
    owner,request,_=setup(document=document,blob=blob,name=name)
    assert not allowed_blob(owner,request)

@pytest.mark.parametrize('mode',['local','server'])
def test_original_print_request_transfers_without_url_only_navigation(mode):
    origin='http://127.0.0.1:8134' if mode=='local' else 'https://synthetic.example:443'
    owner=NS(_closing=False,_retiring_browser=None,port=8134,note_blocked=Mock(),open_external=Mock())
    page=NS(owner=owner,origin=origin,url=lambda:QUrl(origin+'/anki/custom'),ai_handoff=NS(handle=Mock()))
    owner.view=NS(page=lambda:page,setUrl=Mock())
    request=NS(requestedUrl=lambda:QUrl(origin+'/anki/printable'),isUserInitiated=lambda:True,openIn=Mock())
    handler=LocalPage._new_window if mode=='local' else ServerPage._new_window
    handler(page,request)
    request.openIn.assert_called_once_with(page);owner.view.setUrl.assert_not_called()
    page.ai_handoff.handle.assert_not_called()
    request.openIn.reset_mock();owner._retiring_browser=object();handler(page,request);request.openIn.assert_not_called()

@pytest.mark.parametrize('target,user,source',[
 ('/anki/printable',False,'/anki/custom'),('/library',True,'/anki/custom'),
 ('/anki/printable?x=1',True,'/anki/custom'),('/anki/printable',True,'/elsewhere'),
 ('https://elsewhere.example/anki/printable',True,'/anki/custom'),
])
def test_server_print_exception_does_not_broaden_other_popup_permissions(target,user,source):
    origin='https://synthetic.example:443'
    owner=NS(_closing=False,_retiring_browser=None,note_blocked=Mock(),open_external=Mock())
    page=NS(owner=owner,origin=origin,url=lambda:QUrl(origin+source),ai_handoff=NS(handle=Mock()))
    owner.view=NS(page=lambda:page)
    request=NS(requestedUrl=lambda:QUrl(target if '://' in target else origin+target),isUserInitiated=lambda:user,openIn=Mock())
    ServerPage._new_window(page,request);request.openIn.assert_not_called()


def test_blob_consent_and_outcome_callbacks_cannot_follow_navigation_or_newer_feedback(monkeypatch):
    from desktop import marked_exports as m
    import desktop.exports as exports
    alive=[True];calls=[]
    monkeypatch.setattr(exports,'current',lambda owner,captured:alive[0])
    page=NS(runJavaScript=lambda *args:calls.append(args))
    owner=NS(operation_feedback=NS(serial=7));record={'marked_blob_url':'blob:https://synthetic.example/'+UUID,'feedback_ticket':7,'published_path':'/never/send/native/path'}
    captured=(page,);outcomes=[]
    m.authorize(owner,record,captured,outcomes.append)
    alive[0]=False;calls.pop()[2](True)
    assert outcomes==[False]
    m.report(owner,record,captured,'completed');assert not calls
    alive[0]=True;owner.operation_feedback.serial=8
    m.report(owner,record,captured,'completed');assert not calls
    owner.operation_feedback.serial=7;m.report(owner,record,captured,'cancelled')
    assert 'Save As canceled' in calls[-1][0] and '/never/send/native/path' not in calls[-1][0]

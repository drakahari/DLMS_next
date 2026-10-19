"""Qt-only print authorization/lifetime guards; no network or printer."""
from types import SimpleNamespace as NS
from unittest.mock import Mock
import pytest
from PySide6.QtCore import QUrl
from desktop import qt_printing as printing


def setup(mode='local', path='/anki/printable'):
    page=NS(url=lambda:QUrl('http://127.0.0.1:8134'+path),isLoading=lambda:False)
    owner=NS(mode=mode,port=8134,_closing=False,_retiring_browser=None,
             mode_config={'server':{'origin':'http://127.0.0.1:8134'}},
             _server_page_exposed=True,server_unreachable=False,view=NS(page=lambda:page))
    return owner,page


@pytest.mark.parametrize('mode',['local','server'])
def test_exact_completed_print_document_only(mode):
    owner,page=setup(mode);assert printing.allowed(owner,page)
    for change in ('closing','retired','loading','other-page','origin','query','fragment','elsewhere'):
        owner,page=setup(mode)
        if change=='closing':owner._closing=True
        elif change=='retired':owner._retiring_browser=object()
        elif change=='loading':page.isLoading=lambda:True
        elif change=='other-page':owner.view.page=lambda:object()
        else:
            url={'origin':'http://127.0.0.1:9999/anki/printable','query':'http://127.0.0.1:8134/anki/printable?extra=1',
                 'fragment':'http://127.0.0.1:8134/anki/printable#frame','elsewhere':'http://127.0.0.1:8134/library'}[change]
            page.url=lambda:QUrl(url)
        assert not printing.allowed(owner,page),change


@pytest.mark.parametrize('exposed,outage',[(False,False),(True,True),(False,True)])
def test_server_cover_and_outage_cannot_print(exposed,outage):
    owner,page=setup('server');owner._server_page_exposed=exposed;owner.server_unreachable=outage
    assert not printing.allowed(owner,page)


def test_scripted_or_stale_permission_does_not_generate(monkeypatch):
    owner,page=setup();callbacks=[]
    owner._begin_feedback=lambda _:7
    page.runJavaScript=lambda script,world,callback:callbacks.append(callback)
    obj=NS(owner=owner,page=page,record=None,captured=None,operation=0,
           valid=lambda:True,generate=Mock(),failed=Mock(),retire=Mock())
    monkeypatch.setattr(printing.exports,'context',lambda _:('captured',))
    monkeypatch.setattr(printing,'isValid',lambda _:True)
    printing.AveryPrint.request(obj)
    callbacks.pop()(False);obj.failed.assert_called_once();obj.generate.assert_not_called()
    obj.record=None;printing.AveryPrint.request(obj)
    callback=callbacks.pop();obj.operation+=1;callback(True)
    obj.generate.assert_not_called()


def test_failed_or_late_pdf_callback_cannot_publish(monkeypatch,tmp_path):
    owner,page=setup();owner.paths={'downloads':tmp_path};owner.pdf_results=[]
    callbacks=[];page.printToPdf=lambda cb,layout:callbacks.append(cb)
    obj=NS(owner=owner,page=page,record={'feedback_ticket':1},captured=('old',),operation=1,
           valid=lambda:True,retire=Mock(),failed=Mock(),message=Mock(),deadline=Mock(),timer=Mock())
    monkeypatch.setattr(printing,'isValid',lambda _:True)
    begin=Mock();monkeypatch.setattr(printing.exports,'begin',begin)
    printing.AveryPrint.generate(obj,1);callbacks.pop()(b'')
    obj.failed.assert_called_once();begin.assert_not_called();assert not list(tmp_path.iterdir())
    obj.failed.reset_mock();printing.AveryPrint.generate(obj,1);late=callbacks.pop();obj.operation=2
    late(b'%PDF-synthetic stale');begin.assert_not_called();assert not list(tmp_path.iterdir())


def test_pdf_staging_write_failure_has_feedback(monkeypatch,tmp_path):
    owner,page=setup();owner.paths={'downloads':tmp_path};owner.pdf_results=[];callbacks=[]
    page.printToPdf=lambda cb,layout:callbacks.append(cb)
    obj=NS(owner=owner,page=page,record={'feedback_ticket':1},captured=('page',),operation=1,
           valid=lambda:True,retire=Mock(),failed=Mock(),message=Mock(),deadline=Mock(),timer=Mock())
    monkeypatch.setattr(printing,'isValid',lambda _:True)
    begin=Mock();monkeypatch.setattr(printing.exports,'begin',begin)
    printing.AveryPrint.generate(obj,1)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(printing.os,'open',Mock(side_effect=OSError('synthetic failure')))
        callbacks.pop()(b'%PDF-synthetic')
    obj.failed.assert_called_once();begin.assert_not_called()


def test_destroyed_controller_callback_does_not_touch_page_or_destination(monkeypatch,tmp_path):
    owner,page=setup();owner.paths={'downloads':tmp_path};owner.pdf_results=[];callbacks=[]
    page.printToPdf=lambda cb,layout:callbacks.append(cb)
    obj=NS(owner=owner,page=page,record={'feedback_ticket':1},captured=('page',),operation=1,
           valid=Mock(return_value=True),retire=Mock(),failed=Mock(),message=Mock(),deadline=Mock(),timer=Mock())
    monkeypatch.setattr(printing,'isValid',lambda _:True)
    begin=Mock();monkeypatch.setattr(printing.exports,'begin',begin)
    printing.AveryPrint.generate(obj,1)
    obj.valid.reset_mock();monkeypatch.setattr(printing,'isValid',lambda _:False)
    callbacks.pop()(b'%PDF-destruction-callback')
    obj.valid.assert_not_called();begin.assert_not_called();assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('mode',['local','server'])
def test_retirement_invalidates_late_callback_and_reports_cancel(mode):
    owner,_=setup(mode);owner.operation_feedback=NS(serial=9);owner._feedback=Mock()
    record={'state':'generating','feedback_ticket':9}
    obj=NS(owner=owner,record=record,captured=('document',),operation=3,timer=Mock(),deadline=Mock())
    printing.AveryPrint.retire(obj)
    assert record['state']=='retired' and obj.operation==4 and obj.record is None and obj.captured is None
    owner._feedback.assert_called_once()
    assert 'No destination was changed' in owner._feedback.call_args.args[1]

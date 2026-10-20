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
             _server_page_exposed=True,server_unreachable=False,view=NS(page=lambda:page,isEnabled=lambda:True,setEnabled=Mock()))
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
           valid=lambda:True,print_dialog=Mock(),generate=Mock(),failed=Mock(),retire=Mock())
    monkeypatch.setattr(printing.exports,'context',lambda _:('captured',))
    monkeypatch.setattr(printing,'isValid',lambda _:True)
    printing.AveryPrint.request(obj)
    callbacks.pop()(False);obj.failed.assert_called_once();obj.print_dialog.assert_not_called()
    obj.record=None;printing.AveryPrint.request(obj)
    callback=callbacks.pop();obj.operation+=1;callback(True)
    obj.print_dialog.assert_not_called()
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


@pytest.mark.parametrize('mode',['local','server'])
def test_native_completion_error_does_not_claim_destination_unchanged(monkeypatch,tmp_path,mode):
    from contextlib import nullcontext
    from desktop import macos_printing
    owner,page=setup(mode);owner.paths=owner.server_paths={'downloads':tmp_path};owner.pdf_results=[]
    callbacks=[];page.printToPdf=lambda cb,layout:callbacks.append(cb)
    obj=NS(owner=owner,page=page,record={'feedback_ticket':1,'native_duplex':'short'},
           captured=('page',),operation=1,valid=lambda:True,retire=Mock(),failed=Mock(),
           message=Mock(),deadline=Mock(),native_busy=False)
    monkeypatch.setattr(printing,'isValid',lambda _:True)
    monkeypatch.setattr(printing,'browser_dialog',lambda _:nullcontext())
    monkeypatch.setattr(macos_printing,'print_avery',Mock(side_effect=RuntimeError('completion unknown')))
    printing.AveryPrint.generate(obj,1);callbacks.pop()(b'%PDF-synthetic')
    text=obj.failed.call_args.args[0]
    assert 'could not be confirmed' in text and 'printer queue' in text
    assert 'No destination was changed' not in text
    assert not obj.native_busy
    owner.view.setEnabled.assert_called_with(True)


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


def dialog_setup(monkeypatch, *, accepted=True, filename='', valid=True, duplex=None, layout=None):
    from contextlib import nullcontext
    enum = printing.QPrinter
    printer = Mock()
    printer.duplex.return_value = duplex or enum.DuplexMode.DuplexShortSide
    printer.pageLayout.return_value = layout or printing.avery_layout()
    printer.outputFileName.return_value = filename
    printer.outputFormat.return_value = enum.OutputFormat.PdfFormat if filename else enum.OutputFormat.NativeFormat
    printer.printerName.return_value = 'Synthetic printer (no submission)'
    printer.isValid.return_value = True
    printer.docName.return_value = 'DLMS Avery cards'
    maker = Mock(return_value=printer)
    for key in ('PrinterMode','OutputFormat','DuplexMode'):
        setattr(maker,key,getattr(enum,key))
    monkeypatch.setattr(printing,'QPrinter',maker)
    dialog=Mock();dialog.exec.return_value=printing.QDialog.DialogCode.Accepted if accepted else printing.QDialog.DialogCode.Rejected
    monkeypatch.setattr(printing,'QPrintDialog',Mock(return_value=dialog))
    monkeypatch.setattr(printing,'browser_dialog',lambda _:nullcontext())
    owner,page=setup()
    obj=NS(owner=owner,page=page,record={'layout_digest':printing.hashlib.sha256(b'fixed layout').hexdigest()},operation=3,valid=Mock(return_value=valid),
           retire=Mock(),failed=Mock(),message=Mock(),generate=Mock())
    page.runJavaScript=lambda script,world,callback:callback('fixed layout')
    job=Mock();monkeypatch.setattr(printing,'PrinterJob',job)
    return obj,printer,dialog,job


@pytest.mark.parametrize('mode',['local','server'])
def test_print_cancel_sends_no_job_or_pdf(monkeypatch,mode):
    obj,printer,dialog,job=dialog_setup(monkeypatch,accepted=False)
    obj.owner.mode=mode
    printing.AveryPrint.print_dialog(obj,'short')
    dialog.exec.assert_called_once();job.assert_not_called();obj.generate.assert_not_called()
    assert 'No job was sent' in obj.message.call_args.args[0]
    obj.retire.assert_called_once()


def test_only_accepted_current_physical_printer_submits(monkeypatch):
    obj,printer,dialog,job=dialog_setup(monkeypatch)
    printing.AveryPrint.print_dialog(obj,'short')
    printer.setFullPage.assert_called_once_with(True)
    printer.setResolution.assert_called_once_with(600)
    job.assert_called_once_with(obj,printer);job.return_value.start.assert_called_once()
    obj.generate.assert_not_called()


def test_context_changed_inside_native_dialog_cannot_submit(monkeypatch):
    obj,printer,dialog,job=dialog_setup(monkeypatch)
    obj.valid.side_effect=[True,False]
    printing.AveryPrint.print_dialog(obj,'short')
    job.assert_not_called();obj.generate.assert_not_called();obj.retire.assert_called_once()


def test_native_pdf_choice_uses_the_accepted_system_printer(monkeypatch):
    # Revised contract: Qt owns file selection/overwrite confirmation, not the
    # custom no-replace export queue. The accepted QPrinter is used unchanged.
    obj,printer,dialog,job=dialog_setup(monkeypatch,filename='/Users/synthetic/Documents/chosen.pdf')
    printing.AveryPrint.print_dialog(obj,'short')
    job.assert_called_once_with(obj,printer)
    job.return_value.start.assert_called_once()
    obj.generate.assert_not_called()
    assert 'native_print_destination' not in obj.record


def test_unavailable_print_destination_refuses_before_job(monkeypatch):
    obj,printer,dialog,job=dialog_setup(monkeypatch)
    printer.isValid.return_value=False
    printing.AveryPrint.print_dialog(obj,'short')
    obj.failed.assert_called_once();job.assert_not_called()


def test_layout_mutation_during_system_dialog_refuses_job(monkeypatch):
    obj,printer,dialog,job=dialog_setup(monkeypatch)
    obj.page.runJavaScript=lambda script,world,callback:callback('different selected questions')
    printing.AveryPrint.print_dialog(obj,'short')
    obj.failed.assert_called_once();job.assert_not_called()
    assert 'document changed' in obj.failed.call_args.args[0]


def test_native_job_retained_until_finished_even_after_controller_retired(monkeypatch):
    from contextlib import contextmanager
    guards=[]
    @contextmanager
    def guard(owner):
        guards.append('held');yield;guards.append('released')
    monkeypatch.setattr(printing,'browser_dialog',guard)
    monkeypatch.setattr(printing,'isValid',lambda _:True)
    controller=Mock();controller.operation=1;controller.owner=setup()[0];controller.owner.view=Mock()
    controller.owner.view.isEnabled.return_value=True
    printer=object();job=printing.PrinterJob(controller,printer)
    assert job in printing._JOBS and job.printer is printer and guards==['held']
    job.start();controller.owner.view.print.assert_called_once_with(printer)
    controller.operation=2  # A retired page cannot receive stale completion feedback.
    job.finished(True)
    assert job not in printing._JOBS and guards==['held','released']
    controller.message.assert_not_called();controller.retire.assert_not_called()
    controller.owner.view.setEnabled.assert_called_with(True)


@pytest.mark.parametrize('mode',['local','server'])
def test_navigation_is_locked_while_native_print_owns_document(mode):
    from desktop.shell import LocalPage
    from desktop.server_browser import ServerPage
    page=NS(avery_print=NS(native_busy=True))
    cls=LocalPage if mode=='local' else ServerPage
    assert cls.acceptNavigationRequest(page,QUrl('http://127.0.0.1:8134/library'),None,True) is False


@pytest.mark.parametrize('exposed,outage',[(False,False),(True,True),(False,True)])
def test_print_completion_cannot_reenable_unavailable_Server(monkeypatch,exposed,outage):
    owner,page=setup('server');owner._server_page_exposed=exposed;owner.server_unreachable=outage
    monkeypatch.setattr(printing,'isValid',lambda _:True)
    printing.restore_view(owner,owner.view,True)
    owner.view.setEnabled.assert_called_once_with(False)


@pytest.mark.parametrize('success',[True,False])
def test_mac_operation_owns_standard_dialog_and_PDF_choices(monkeypatch,success):
    from desktop import macos_printing as mac
    calls=[];copied=[]
    class API:
        def __init__(self):self.pm=NS(PMSetDuplex=Mock(return_value=0))
        def cls(self,name):return name
        def string(self,text):return text
        def key(self,key):return key
        def number(self,value):return value
        def sheet(self,operation,window):
            calls.append(('native-standard-operation',operation));return success
        def send(self,receiver,selector,result=None,types=(),args=()):
            calls.append((receiver,selector,args))
            if selector=='dataWithBytes:length:':
                import ctypes as C
                copied.append(C.string_at(args[0],args[1]));return 'immutable-data'
            if selector=='retain':return receiver
            return {'new':'pool','sharedPrintInfo':'shared','copy':'info','dictionary':'dictionary',
                'PMPrintSettings':'settings','alloc':'allocated','initWithData:':'document','pageCount':2,
                'printOperationForPrintInfo:scalingMode:autoRotate:':'operation'}.get(selector)
    api=API();monkeypatch.setattr(mac,'NativePrint',lambda:api)
    content=b'%PDF-selected frozen ALPHA CHARLIE'
    result=mac.print_avery(content,'short',lambda:True,object())
    assert result['kind']==('completed' if success else 'not_completed')
    assert copied==[content]
    assert ('operation','setShowsPrintPanel:',(True,)) in calls
    assert ('native-standard-operation','operation') in calls
    assert not any(call[1] in ('printPanel','PMSessionGetDestinationType') for call in calls)
    if not success:assert 'No job was sent' not in result['message']
    assert ('document','release',()) in calls and ('pool','drain',()) in calls


def test_mac_stale_authorization_never_starts_native_operation(monkeypatch):
    from desktop import macos_printing as mac
    factory=Mock();monkeypatch.setattr(mac,'NativePrint',factory)
    result=mac.print_avery(b'%PDF-synthetic','short',lambda:False,object())
    assert result['kind']=='refused';factory.assert_not_called()


def test_no_separate_pdf_action_is_exposed():
    import inspect
    from desktop.shell import DesktopWindow
    assert not hasattr(printing,'save_pdf') and not hasattr(printing.AveryPrint,'request_pdf')
    assert 'Save Avery PDF' not in inspect.getsource(DesktopWindow._create_mode_toolbar)

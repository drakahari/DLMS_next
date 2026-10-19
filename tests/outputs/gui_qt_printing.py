"""Focused real source-Qt Avery journey; native Save As answers are simulated.

No installed app, production endpoint or personal profile is used. QTest sends
trusted app-local clicks; this is not a claim of physical native-sheet coverage.
"""
import argparse,hashlib,json,os,socket,subprocess,sys,time
from pathlib import Path


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--work',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--legacy-server-only',action='store_true',help='only the existing-server no-ID/no-status print compatibility case')
    args=parser.parse_args()
    args.work.mkdir(mode=0o700,parents=True,exist_ok=False)
    args.output.mkdir(mode=0o700,parents=True,exist_ok=False)
    if sys.platform=='darwin':
        import package_macos
        from desktop.macos_paths import prepare_root
        package_macos.ACTIVE=True
        os.environ['DLMS_MACOS_DATA_ROOT']=str(prepare_root(args.work/'private-data'))
    import desktop.shell as shell
    shell.instance_socket_name=lambda root:'/tmp/dlms-avery-'+hashlib.sha256(str(root).encode()).hexdigest()[:18]+'.sock'
    from tests.gate1.qt_checks import QtChecks
    from desktop.server_mode import configured_server,write_config
    from PySide6.QtCore import QUrl,QTimer
    from PySide6.QtWidgets import QFileDialog,QMessageBox
    from pypdf import PdfReader
    q=QtChecks('averyfocused01',automated=True)
    answers=[];dialogs=[];server=None;server_port=None
    report={'kind':'source Qt / actual QTest clicks; native Save As responses simulated',
            'physical_printer_alignment':'unqualified','modes':{},'refusals':{}}
    original=QFileDialog.getSaveFileName
    def picker(*pos,**kwargs):
        dialogs.append({'title':pos[1],'initial_name':Path(pos[2]).name})
        assert answers,'Unexpected Save As request'
        return answers.pop(0),''
    QFileDialog.getSaveFileName=picker
    timer=QTimer();timer.setInterval(40)
    def dismiss():
        for widget in q.app.topLevelWidgets():
            if isinstance(widget,QMessageBox) and widget.isVisible():widget.reject()
    timer.timeout.connect(dismiss);timer.start()
    def until(condition,seconds=15):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            if condition():return
            q.delay(.05)
        raise TimeoutError('Focused print condition did not complete')
    def go(path):
        origin=f'http://127.0.0.1:{q.window.port}' if q.window.mode=='local' else q.window.mode_config['server']['origin']
        q.window.view.setUrl(QUrl(origin+path))
        q.wait('location.pathname==='+json.dumps(path)+"&&document.readyState==='complete'")
        until(lambda:not q.window.view.page().isLoading())
        if q.window.mode=='server':until(lambda:q.window._server_page_exposed)
    def seed():
        q.js("""(async()=>{let f=new FormData();f.append('quiz_title','Avery focused synthetic');f.append('file',new File(['1. ALPHA chosen card?\\nA. ALPHA answer\\nB. Other\\nCorrect Answer: A\\n\\n2. BRAVO excluded card?\\nA. BRAVO answer\\nB. Other\\nCorrect Answer: A\\n\\n3. CHARLIE chosen card?\\nA. CHARLIE answer\\nB. Other\\nCorrect Answer: A\\n'],'avery-synthetic.txt'));window.printSeed=(await fetch('/process',{method:'POST',body:f})).status;})()""")
        q.wait('window.printSeed===200')
    def open_layout():
        go('/anki/custom')
        q.js("document.querySelectorAll('input[type=checkbox]').forEach(e=>e.checked=false);document.querySelectorAll('input[name=quiz_cards]').forEach(e=>{e.checked=/ALPHA chosen|CHARLIE chosen/.test(e.closest('label').textContent)});document.querySelector('[name=deck_name]').value='Avery selected ALPHA CHARLIE';document.querySelector('[name=duplex_flip]').value='short';true")
        selected=q.js("JSON.stringify([...document.querySelectorAll('input[name=quiz_cards]:checked')].map(e=>e.value))")
        assert len(json.loads(selected))==2
        q.click_css('button[formaction="/anki/printable"]')
        q.wait("location.pathname==='/anki/printable'&&document.readyState==='complete'")
        until(lambda:not q.window.view.page().isLoading())
        if q.window.mode=='server':until(lambda:q.window._server_page_exposed)
        assert q.js("document.querySelectorAll('.front-sheet .avery-card pre').length")==2
        return selected
    def output(mode,answer,expected):
        before=len(q.window.pdf_results)
        answers.append(str(answer) if answer else '')
        q.click_css('#printCards')
        until(lambda:len(q.window.pdf_results)>before and q.window.pdf_results[-1]['state'] in ('completed','cancelled','failed'))
        until(lambda:q.window.view.page().avery_print.record is None)
        row=q.window.pdf_results[-1]
        assert row['state']==expected,(row,q.window.statusBar().currentMessage())
        message=q.js("document.getElementById('printCardsStatus').textContent")
        assert {'completed':'PDF saved','cancelled':'canceled','failed':'not saved'}[expected] in message,message
        stage=Path(row['path'])
        assert stage.is_relative_to(q.window.paths['downloads'] if mode=='local' else q.window.server_paths['downloads'])
        result={'state':row['state'],'page_feedback':message,'private_stage_mode':mode}
        if expected=='completed':
            reader=PdfReader(answer);text='\n'.join(page.extract_text() or '' for page in reader.pages)
            assert len(reader.pages)==2
            assert all(abs(float(page.mediabox.width)-612)<.1 and abs(float(page.mediabox.height)-792)<.1 for page in reader.pages)
            assert all(word in text for word in ('ALPHA chosen','CHARLIE chosen','ALPHA answer','CHARLIE answer'))
            assert 'BRAVO' not in text and 'Generating Avery PDF' not in text
            result.update(file=str(answer),sha256=hashlib.sha256(answer.read_bytes()).hexdigest(),pages=2,paper='US Letter',selected_only=True)
        return result
    def refusals(mode):
        count=len(dialogs);records=len(q.window.pdf_results)
        q.js('document.getElementById("printCards").click();true');q.delay(.4)
        assert len(dialogs)==count and len(q.window.pdf_results)==records
        assert 'refused' in q.window.statusBar().currentMessage()
        q.js('window.print();true');q.delay(.4)
        assert len(dialogs)==count and len(q.window.pdf_results)==records
        # An actual trusted click inside a child frame must never authorize top-page printing.
        q.js("(()=>{let f=document.createElement('iframe');f.id='printFrame';f.width=500;f.height=100;f.srcdoc='<button onclick=\"window.print()\" style=\"width:450px;height:80px\">Frame print</button>';document.body.append(f);return true})()")
        q.delay(.3);q.click_css('#printFrame');q.delay(.4)
        assert len(dialogs)==count and len(q.window.pdf_results)==records
        q.js('document.getElementById("printFrame").remove();true')
        report['refusals'][mode]={'scripted_button':True,'scripted_window_print':True,'child_frame':True,'no_extra_chooser':True}
    def journey(mode):
        seed();selected=open_layout();results=[]
        results.append(output(mode,args.output/(mode+'-selected-avery.pdf'),'completed'))
        results.append(output(mode,None,'cancelled'))
        existing=args.output/(mode+'-DO-NOT-REPLACE.pdf');existing.write_bytes(b'SYNTHETIC PRESERVE')
        previous=existing.read_bytes();results.append(output(mode,existing,'failed'));assert existing.read_bytes()==previous
        refusals(mode)
        q.click_css('#returnCustomDeck');q.wait("location.pathname==='/anki/custom'&&document.readyState==='complete'")
        actual=q.js("JSON.stringify([...document.querySelectorAll('input[name=quiz_cards]:checked')].map(e=>e.value))")
        assert actual==selected
        assert q.js("document.querySelector('[name=deck_name]').value")=='Avery selected ALPHA CHARLIE'
        assert q.js("document.querySelector('[name=duplex_flip]').value")=='short'
        report['modes'][mode]={'outputs':results,'Return_selection_name_and_short_edge':True}
    def legacy_server():
        seed();open_layout()
        q.js('document.getElementById("printCards").removeAttribute("id");document.getElementById("printCardsStatus").remove();true')
        target=args.output/'legacy-server-selected-avery.pdf';answers.append(str(target));before=len(q.window.pdf_results)
        q.click_css('.print-toolbar .print-actions > button[type="button"]')
        until(lambda:len(q.window.pdf_results)>before and q.window.pdf_results[-1]['state']=='completed')
        until(lambda:q.window.view.page().avery_print.record is None)
        reader=PdfReader(target);text='\n'.join(page.extract_text() or '' for page in reader.pages)
        assert len(reader.pages)==2 and all(word in text for word in ('ALPHA chosen','CHARLIE chosen','ALPHA answer','CHARLIE answer'))
        assert 'BRAVO' not in text and 'Generating Avery' not in text
        assert all(abs(float(page.mediabox.width)-612)<.1 and abs(float(page.mediabox.height)-792)<.1 for page in reader.pages)
        assert 'Export saved:' in q.window.statusBar().currentMessage()
        report['legacy_server']={'no_button_ID_or_status_node':True,'selected_only':True,'pages':2,
          'paper':'US Letter','native_feedback_visible':True,'file':str(target),'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}
    try:
        if not args.legacy_server_only:journey('local')
        local_stages={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in q.window.paths['downloads'].glob('*.pdf')}
        sr=args.work/'server';sr.mkdir(mode=0o700)
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));server_port=sock.getsockname()[1]
        env={k:v for k,v in os.environ.items() if not k.startswith(('DLMS_','QUIZAPP_'))}
        env.update(QUIZAPP_DATA_DIR=str(sr/'data'),DLMS_NO_BROWSER='1',DLMS_BROWSER_TEST_BIND_HOST='127.0.0.1',DLMS_BROWSER_TEST_PORT=str(server_port),PYTHONDONTWRITEBYTECODE='1')
        log=(sr/'server.log').open('x');server=subprocess.Popen([sys.executable,'tests/browser/_server.py'],env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        until(lambda:(sr/'data/browser_fixture.json').is_file(),25)
        cfg=dict(q.window.mode_config,server=configured_server(q.window.mode_config,f'http://127.0.0.1:{server_port}','Synthetic Avery only',private_http_opt_in=True))
        write_config(q.window.profile_name,cfg);q.window.mode_config=cfg;assert q.window.switch_to_server()
        q.wait("location.pathname==='/'&&document.readyState==='complete'",30);until(lambda:q.window._server_page_exposed)
        if args.legacy_server_only:legacy_server()
        else:journey('server')
        assert local_stages=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in q.window.paths['downloads'].glob('*.pdf')}
        report['Local_Server_staging_isolation']=True;report['status']='passed'
    except BaseException as exc:
        report['status']='failed';report['error']=type(exc).__name__+': '+str(exc);raise
    finally:
        timer.stop();QFileDialog.getSaveFileName=original;q.close()
        if server is not None:server.terminate();server.wait(timeout=15)
        report['task_server_stopped']=server is None or server.poll() is not None
        with (args.work/'RESULT.json').open('x') as out:json.dump(report,out,indent=2);out.write('\n')
        print(json.dumps(report),flush=True)


if __name__=='__main__':main()

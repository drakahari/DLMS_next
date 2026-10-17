"""Real embedded File inputs; explicit test selection is app-local, not host input.

The fixture copy lives outside Desktop's data area. Unchanged receivers validate
and commit actual selected sealed bytes. Reopen is always a separate process.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import time
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QFileDialog, QMessageBox, QProgressDialog
from tests.gate1.qt_checks import QtChecks


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def select(q,selector,path):
    q.window.file_selection_for_test=path
    q.click_css(selector)
    q.wait(f'document.querySelector({json.dumps(selector)}).files.length>0')
    q.js('window.selectedDigest=null;(async()=>{const f=document.querySelector('+json.dumps(selector)+').files[0];'
         'const b=await f.arrayBuffer();const h=await crypto.subtle.digest("SHA-256",b);'
         'window.selectedDigest={name:f.name,size:f.size,sha:[...new Uint8Array(h)].map(x=>x.toString(16).padStart(2,"0")).join("")}})();true')
    q.wait('window.selectedDigest!==null')
    actual=json.loads(q.js('JSON.stringify(window.selectedDigest)'))
    assert actual==dict(name=path.name,size=path.stat().st_size,sha=sha(path)),actual
    return actual


def state(root):
    with sqlite3.connect(root/'results.db') as conn:
        return {t:conn.execute(f'SELECT * FROM {t} ORDER BY 1').fetchall()
                for t in ('quizzes','questions','choices','matching_pairs','certifications','certification_attachments')}


def main():
    p=argparse.ArgumentParser();p.add_argument('--profile',required=True);p.add_argument('--fixtures',type=Path)
    p.add_argument('--reopen',action='store_true');a=p.parse_args()
    if not a.profile.startswith('filepick'):raise ValueError('Dedicated fixture profile required')
    q=QtChecks(a.profile,automated=True)
    report={'profile':a.profile,'kind':'instrumented-frozen' if getattr(sys,'frozen',False) else 'source-Qt',
            'platform':q.app.platformName(),'reopen':a.reopen,'selections':[]}
    record=q.paths['root']/'file-selection-record.json'
    timer=None
    try:
        if a.reopen:
            prior=json.loads(record.read_text())
            current=state(q.paths['backend'])
            # SQLite attachment bytes are compared by digest below.
            actual=hashlib.sha256(repr(current).encode()).hexdigest()
            assert actual==prior['state_digest'],(actual,prior['state_digest'])
            for rel,digest in prior['assets'].items():assert sha(q.paths['backend']/rel)==digest
            q.go('/library');assert q.js("document.body.innerText.includes('Ordinary Folder Quiz')")
            report['separate_process_records_assets_equal']=True
        else:
            ordinary=Path(tempfile.mkdtemp(prefix='dlms-file-selection-', dir='/tmp'))/'Visible Documents é';ordinary.mkdir()
            report['ordinary_folder']=str(ordinary)
            assert not ordinary.is_relative_to(q.paths['root'])
            for src in a.fixtures.iterdir():
                if src.is_file():shutil.copyfile(src,ordinary/src.name)
            text=ordinary/'quiz α space.txt'
            from desktop.isolation import PROJECT
            # Instrumented fixtures supplied externally; normal runtime has no test code.
            text.write_text((a.fixtures/'neutral.txt').read_text())
            q.go('/upload')
            report['selections'].append(select(q,'input[name=file]',text))
            from PIL import Image
            logo=ordinary/'logo 空间.gif';Image.new('RGB',(10,10),'cyan').save(logo)
            report['selections'].append(select(q,'input[name=quiz_logo]',logo))
            original=text.read_bytes();text.write_bytes(b'Changed after selection')
            q.js('window.selectedText=null;document.querySelector("input[name=file]").files[0].text().then(x=>window.selectedText=x);true')
            q.wait('window.selectedText!==null');assert q.js('window.selectedText')==original.decode()
            q.js("document.querySelector('[name=quiz_title]').value='Ordinary Folder Quiz';document.querySelector('form[action=\"/process\"]').requestSubmit();true")
            q.wait("location.pathname==='/library'",30)
            with sqlite3.connect(q.paths['backend']/'results.db') as conn:
                assert conn.execute("SELECT count(*) FROM quizzes WHERE title='Ordinary Folder Quiz'").fetchone()[0]==1
            report['source_changed_after_selection_original_committed']=True
            csv=ordinary/'terms 空间.csv';csv.write_text('term,definition\nAlpha,First\nBeta,Second\n')
            q.go('/matching_bank_import')
            report['selections'].append(select(q,'input[name=csv_file]',csv))
            q.js("document.querySelector('[name=quiz_title]').value='Ordinary CSV';document.querySelector('input[name=csv_file]').form.requestSubmit();true")
            q.wait("location.pathname.startsWith('/edit_quiz/')",30)
            from tests.closure.gui_portable_content import import_bundle
            report['ordinary_bundle']=import_bundle(q,ordinary/'media matching.zip')
            from tests.closure.gui_pack_datasets import install,generate
            report['study_pack']=install(q,ordinary/'study pack.zip');report['pack_generated']=generate(q)
            q.go('/pdf-import')
            report['selections'].append(select(q,'input[name=pdf_file]',ordinary/'scan 空间.pdf'))
            q.js("(()=>{let f=document.querySelector('input[name=pdf_file]').form;f.elements.rights_ok.checked=true;f.requestSubmit();return true})()")
            q.wait("location.pathname!='/pdf-import'",60)
            assert '/pdf-import/' in q.js('location.pathname')
            report['pdf_receiver_path']=q.js('location.pathname')
            if q.js("!!document.querySelector('input[name=ocr_pages]')"):
                q.js("(()=>{let e=document.querySelector('input[name=ocr_pages]');e.checked=true;e.form.requestSubmit();return true})()")
                q.wait("location.pathname.startsWith('/pdf-import/review/')",60)
                values=json.loads(q.js("JSON.stringify([...document.querySelectorAll('input,textarea')].map(e=>e.value))"))
                assert any('three sides' in x.lower() for x in values),values
                report['scanned_pdf_ocr_review_recognized']=True
            q.go('/pdf-import')
            png=ordinary/'image é.png';second_png=ordinary/'second image 空间.png';shutil.copyfile(png,second_png)
            q.window.file_selection_for_test=[second_png,png];q.click_css('input[name=screenshots]')
            q.wait('document.querySelector("input[name=screenshots]").files.length===2')
            assert json.loads(q.js('JSON.stringify([...document.querySelector("input[name=screenshots]").files].map(f=>f.name))'))==[second_png.name,png.name]
            report['ordered_multi_image_input']=True
            q.js("(()=>{let f=document.getElementById('pdfOcrUploadForm');f.elements.rights_ok.checked=true;f.elements.quiz_title.value='Ordinary OCR';f.requestSubmit();return true})()")
            q.wait("location.pathname.startsWith('/pdf-import/review/')",60)
            ocr_values=json.loads(q.js("JSON.stringify([...document.querySelectorAll('input,textarea')].map(e=>e.value))"))
            assert any('three sides' in value.lower() for value in ocr_values),report
            report['png_ocr_review_recognized']=True
            # The selected-file path is sealed, including through receiver OCR.
            q.go('/certifications/new')
            q.js("(()=>{let f=document.querySelector('form.cert-form');f.elements.field_name.value='Ordinary Credential';f.elements.field_issuer.value='Synthetic';f.elements.field_earned.value='2026-01-03';return true})()")
            report['selections'].append(select(q,'input[name=badge]',ordinary/'image é.png'))
            report['selections'].append(select(q,'input[name=certificate]',ordinary/'scan 空间.pdf'))
            q.js("document.querySelector('form.cert-form').requestSubmit();true")
            deadline=time.monotonic()+25
            while time.monotonic()<deadline:
                with sqlite3.connect(q.paths['backend']/'results.db') as conn:
                    attachments=conn.execute('SELECT content FROM certification_attachments').fetchall()
                if len(attachments)==2:break
                q.delay(.1)
            hashes=sorted(hashlib.sha256(x[0]).hexdigest() for x in attachments)
            assert sha(ordinary/'scan 空间.pdf') in hashes
            from PIL import Image
            from io import BytesIO
            stored_image=next(x[0] for x in attachments if not x[0].startswith(b'%PDF-'))
            with Image.open(BytesIO(stored_image)) as saved_image, Image.open(ordinary/'image é.png') as selected_image:
                assert saved_image.size==selected_image.size
                assert saved_image.convert('RGB').tobytes()==selected_image.convert('RGB').tobytes()
            report['attachment_image_reencoded_same_pixels']=True
            report['attachment_hashes']=hashes
            # Real app-local QFileDialog cancellation; no global input or portal control.
            q.go('/upload');q.js('document.querySelector("input[name=file]").focus();true')
            before=q.js('document.activeElement.name')
            dialogs=[]
            def cancel_owned_dialog():
                for w in q.app.topLevelWidgets():
                    if isinstance(w,QFileDialog) and w.parent() is q.window:
                        dialogs.append(w.windowTitle());w.reject()
            timer=QTimer();timer.setInterval(100);timer.timeout.connect(cancel_owned_dialog);timer.start()
            # Own QWidget dialog is necessary for bounded app-local rejection.
            old=QFileDialog.getOpenFileName
            def owned_picker(parent,title,start,filters):
                dlg=QFileDialog(parent,title,start,filters);dlg.setOption(QFileDialog.Option.DontUseNativeDialog)
                dlg.exec();dlg.deleteLater();return ('','')
            QFileDialog.getOpenFileName=owned_picker
            focus_before={'active':q.window.isActiveWindow(),'focus':type(q.app.focusWidget()).__name__ if q.app.focusWidget() else None}
            try:q.click_css('input[name=file]')
            finally:QFileDialog.getOpenFileName=old;timer.stop()
            q.delay(.2)
            assert dialogs and q.js('document.querySelector("input[name=file]").files.length')==0
            assert q.js('document.activeElement.name')==before=='file'
            report['cancel_focus']={'dialogs':dialogs,'before':focus_before,'after_active':q.window.isActiveWindow(),
                                    'after_dom_focus':q.js('document.activeElement.name'),'widget_focus':type(q.app.focusWidget()).__name__ if q.app.focusWidget() else None,
                                    'native_portal_or_physical_acceptance':False}
            assets={str(path.relative_to(q.paths['backend'])):sha(path) for folder in ('quiz_assets','content_packs','static/logos')
                    for path in (q.paths['backend']/folder).rglob('*') if path.is_file()}
            report['assets']=assets
            report['screenshot']=str(q.screenshot('ordinary-file-focus.png'))
            report['state_digest']=hashlib.sha256(repr(state(q.paths['backend'])).encode()).hexdigest()
            record.write_text(json.dumps(report,indent=2)+'\n')
        report['pass']=True
    except Exception as exc:
        import traceback;traceback.print_exc();report['error']=repr(exc);raise
    finally:
        if timer:timer.stop()
        (q.paths['root']/('file-selection-reopen.json' if a.reopen else 'file-selection.json')).write_text(json.dumps(report,indent=2)+'\n')
        q.close()
        print(json.dumps(report,indent=2),flush=True)

if __name__=='__main__':main()

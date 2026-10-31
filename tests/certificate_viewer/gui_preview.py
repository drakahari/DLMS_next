"""Bounded source Qt Local/Server preview, synthetic files and app-local input."""
import argparse
from base64 import b64decode
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch

from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject


def certificate(path):
    writer = PdfWriter()
    for label in ('SYNTHETIC CERTIFICATE PAGE ONE', 'SYNTHETIC CERTIFICATE PAGE TWO'):
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                                 NameObject('/Subtype'): NameObject('/Type1'),
                                 NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(('0.1 0.2 0.6 rg 40 500 530 160 re f\nBT /F1 20 Tf 45 450 Td ('+label+') Tj ET').encode())
        page[NameObject('/Contents')] = writer._add_object(stream)
    writer.write(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not args.profile.startswith('cert331'):
        raise ValueError('Use a new cert331-prefixed synthetic profile')
    args.output.mkdir(parents=True, exist_ok=False)
    from desktop.isolation import profile_paths
    if profile_paths(args.profile, create=False)['root'].exists():
        raise ValueError('Preserve existing profiles')
    from tests.gate1.qt_checks import QtChecks
    from desktop.server_mode import configured_server, write_config
    q = server = server_log = None
    report = {'layer': 'source Qt; app-local synthetic input; simulated Server upload consent and Save As', 'modes': {}}
    try:
        q = QtChecks(args.profile, automated=True)
        pdf = args.output / 'synthetic-certificate.pdf'
        certificate(pdf)

        def go(path):
            if q.window.mode == 'local':
                q.go(path)
            else:
                from PySide6.QtCore import QUrl
                origin = q.window.mode_config['server']['origin']
                q.window.view.setUrl(QUrl(origin+path))
                q.wait("location.origin==="+json.dumps(origin)+" && location.pathname==="+json.dumps(path)+" && document.readyState==='complete'", 30)
                deadline = time.monotonic()+30
                while (q.window.view.page().isLoading() or not q.window._server_page_exposed) and time.monotonic()<deadline:
                    q.delay(.05)
                assert not q.window.view.page().isLoading() and q.window._server_page_exposed

        def journey(mode):
            result = {}
            for kind in ('pdf', 'png', 'jpeg', 'webp'):
                source = pdf if kind == 'pdf' else args.output / ('synthetic-certificate.'+kind)
                if kind != 'pdf':
                    Image.new('RGB', (120, 80), 'navy').save(source, kind.upper())
                go('/certifications/new')
                q.js("document.querySelector('[name=field_name]').value='Synthetic preview '+"+json.dumps(kind)+";document.querySelector('[name=field_issuer]').value='Synthetic issuer';true")
                q.window.file_selection_for_test = source
                if mode == 'server':
                    from PySide6.QtWidgets import QMessageBox
                    with patch('PySide6.QtWidgets.QMessageBox.exec', return_value=QMessageBox.StandardButton.Yes):
                        q.click_css('input[name=certificate]')
                else:
                    q.click_css('input[name=certificate]')
                q.wait("document.querySelector('input[name=certificate]').files.length===1")
                q.js("document.querySelector('form.cert-form').requestSubmit();true")
                q.wait("!!document.querySelector('.cert-hero')", 25)
                detail = q.js('location.pathname')
                before = len(q.window.download_results)
                q.click_css('.cert-hero a[href$="/view"]')
                q.wait("!!document.querySelector('.certificate-preview')?.complete && document.querySelector('.certificate-preview').naturalWidth>0", 25)
                assert len(q.window.download_results) == before
                first = q.js("document.querySelector('.certificate-preview').src.split(',')[1]")
                with Image.open(BytesIO(b64decode(first))) as image:
                    assert max(image.size) <= 1600
                    if kind == 'pdf':
                        assert image.getpixel((0, 0)) != image.getpixel((image.width//2, image.height//3))
                if kind == 'pdf':
                    q.click_css('a[href="?page=2"]')
                    q.wait("document.body.innerText.includes('Page 2 of 2') && document.querySelector('.certificate-preview')?.complete")
                    second = q.js("document.querySelector('.certificate-preview').src.split(',')[1]")
                    assert sha256(b64decode(first)).digest() != sha256(b64decode(second)).digest()
                    target = args.output / (mode+'-download.pdf')
                    with patch('desktop.exports.QFileDialog.getSaveFileName', return_value=(str(target), '')):
                        q.click_css('a[download]')
                        deadline = time.monotonic()+20
                        while not target.exists() and time.monotonic()<deadline:
                            q.delay(.05)
                        assert target.read_bytes() == source.read_bytes()
                        q.delay(.1)
                    with patch('desktop.exports.QFileDialog.getSaveFileName', return_value=('', '')):
                        count = len(q.window.download_results)
                        q.click_css('a[download]')
                        deadline = time.monotonic()+20
                        while time.monotonic()<deadline and not any(r['state']=='cancelled' for r in q.window.download_results[count:]):
                            q.delay(.05)
                        assert any(r['state']=='cancelled' for r in q.window.download_results[count:])
                    result['original_pdf_sha256'] = sha256(target.read_bytes()).hexdigest()
                go(detail)
                assert q.js("document.body.innerText.includes('Synthetic preview')")
                result[kind] = 'displayed; no view download; detail usable'
            report['modes'][mode] = result

        journey('local')
        port_file = args.output/'server-port'
        env = {k:v for k,v in os.environ.items() if not k.startswith(('DLMS_', 'QUIZAPP_'))}
        env.update(QUIZAPP_DATA_DIR=str(args.output/'server-data'), DLMS_NO_BROWSER='1', PYTHONDONTWRITEBYTECODE='1')
        code = "from pathlib import Path; import app; from werkzeug.serving import make_server; s=make_server('127.0.0.2',0,app.app,threaded=True); Path("+repr(str(port_file))+").write_text(str(s.server_port)); s.serve_forever()"
        server_log = (args.output/'server.log').open('x')
        server = subprocess.Popen([sys.executable, '-c', code], env=env, stdout=server_log, stderr=subprocess.STDOUT,
                                  cwd=Path(__file__).resolve().parents[2], start_new_session=True)
        deadline = time.monotonic()+25
        while not port_file.exists() and time.monotonic()<deadline:
            if server.poll() is not None:
                raise RuntimeError('Synthetic server failed')
            q.delay(.05)
        origin = 'http://127.0.0.2:'+port_file.read_text()
        cfg = dict(q.window.mode_config)
        cfg['server'] = configured_server(cfg, origin, 'Synthetic certificate server', private_http_opt_in=True)
        write_config(args.profile, cfg)
        q.window.mode_config = cfg
        assert q.window.switch_to_server()
        q.wait("location.origin==="+json.dumps(origin)+" && document.readyState==='complete'", 30)
        journey('server')
        assert q.window.switch_to_local()
        q.wait("location.pathname==='/'&&document.readyState==='complete'", 30)
        report['status'] = 'passed'
    finally:
        try:
            if q is not None:
                if q.window.mode == 'server':
                    q.window._confirm_server_close = lambda: True
                q.close()
                deadline = time.monotonic()+12
                while not q.window._close_complete and time.monotonic()<deadline:
                    q.delay(.05)
                report['normal_close_complete'] = q.window._close_complete
                report['backend_stopped'] = q.window.backend is None or q.window.backend.poll() is not None
        finally:
            if server is not None:
                server.terminate()
                try: server.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    server.kill(); server.wait(timeout=5)
                report['synthetic_server_stopped'] = server.poll() is not None
            if server_log is not None:
                server_log.close()
        (args.output/'RESULT.json').write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    main()

"""Actual native strict decoder/callback tests and pinned public COM ABI check."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from zipfile import ZipFile
import pytest

@pytest.mark.skipif(os.name!='nt',reason='Native Windows compiler and pinned SDK')
def test_native_request_protocol(tmp_path):
    root=Path(__file__).resolve().parents[2]
    compiler=Path('C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe')
    if not compiler.is_file():pytest.skip('Existing compiler unavailable')
    sdk=root/'.gate1/windows-native/webview2-inputs-01'
    archive=sdk/'webview2.nupkg'
    assert hashlib.sha256(archive.read_bytes()).hexdigest()=='56f7f4b8bf9aee4b8efefbbdd4f67d5f74ebd1b100ed0806da71bf76af481aa9'
    with ZipFile(archive) as z:
        header=z.read('build/native/include/WebView2.h').decode('utf-8-sig')
        core=z.read('lib/net462/Microsoft.Web.WebView2.Core.dll')
    assert '76eceacb-0462-4d94-ac83-423a6793775e' in header.lower()
    assert '5c4889f0-5ef6-4c5a-952c-d8f1b92d0574' in header.lower()
    vtable=header.split('typedef struct ICoreWebView2Vtbl',1)[1].split('} ICoreWebView2Vtbl',1)[0]
    methods=re.findall(r'\*\s*(\w+)\s*\)\s*\(',vtable)
    assert methods[35:38]==['remove_WebMessageReceived','CallDevToolsProtocolMethod','get_BrowserProcessId']
    library=tmp_path/'Microsoft.Web.WebView2.Core.dll';library.write_bytes(core)
    exe=tmp_path/'RequestProtocolTests.exe'
    built=subprocess.run([str(compiler),'/nologo','/target:exe','/platform:x64','/reference:System.dll','/reference:System.Core.dll',
        f'/reference:{library}',f'/out:{exe}',str(root/'windows_webview2/RequestProtocol.cs'),
        str(root/'tests/webview2/RequestProtocolTests.cs')],capture_output=True,text=True,timeout=30)
    assert built.returncode==0,built.stdout+built.stderr
    result=subprocess.run([str(exe)],capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stdout+result.stderr
    receipt=json.loads(result.stdout)
    assert receipt['passed'] and receipt['checks']>=55 and not receipt['browser_launched']

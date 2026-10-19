"""Compile the actual host header policy with a no-browser native entry point."""
import json
import os
from pathlib import Path
import subprocess
import pytest

@pytest.mark.skipif(os.name!='nt',reason='Native Windows host/compiler; Linux Qt is a separate host')
def test_actual_native_avery_header_policy(tmp_path):
    root=Path(__file__).resolve().parents[2]
    compiler=Path('C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe')
    assert compiler.is_file(),'Existing Windows build prerequisite is required'
    sdk=root/'.gate1/windows-native/webview2-inputs-01/sdk/lib/net462'
    exe=tmp_path/'AveryHeaderTests.exe'
    files=['Host.cs','BrowserSurface.cs','FetchMetadata.cs','BrowserHandoff.cs','AiActions.cs','AiScripts.cs','AiActionLease.cs','RequestProtocol.cs']
    args=[str(compiler),'/nologo','/target:exe','/platform:x64','/main:AveryHeaderTests',f'/out:{exe}',
          '/reference:System.dll','/reference:System.Core.dll','/reference:System.Drawing.dll','/reference:System.Windows.Forms.dll','/reference:System.Web.Extensions.dll']
    for name in ['Microsoft.Web.WebView2.Core.dll','Microsoft.Web.WebView2.WinForms.dll']:
        library=sdk/name
        (tmp_path/name).write_bytes(library.read_bytes())
        args.append(f'/reference:{library}')
    args += [str(root/'windows_webview2'/name) for name in files]
    args.append(str(root/'tests/webview2/AveryHeaderTests.cs'))
    built=subprocess.run(args,capture_output=True,text=True,timeout=30)
    assert built.returncode==0,built.stdout+built.stderr
    run=subprocess.run([str(exe)],capture_output=True,text=True,timeout=15)
    assert run.returncode==0,run.stdout+run.stderr
    receipt=json.loads(run.stdout)
    assert receipt['passed'] and receipt['checks']==33 and not receipt['browser_launched']

"""Actual native immutable destination lease; no browser or profile access."""
import json
import os
from pathlib import Path
import subprocess
import pytest

@pytest.mark.skipif(os.name!='nt',reason='Native Windows compiler')
def test_late_metadata_cannot_change_armed_destination(tmp_path):
    root=Path(__file__).resolve().parents[2]
    compiler=Path('C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe')
    if not compiler.is_file():pytest.skip('Existing native compiler unavailable')
    exe=tmp_path/'AiActionLeaseTests.exe'
    result=subprocess.run([str(compiler),'/nologo','/target:exe','/platform:x64','/optimize+',
        '/reference:System.dll',f'/out:{exe}',str(root/'windows_webview2/AiActionLease.cs'),
        str(root/'tests/webview2/AiActionLeaseTests.cs')],capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
    result=subprocess.run([str(exe)],capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stdout+result.stderr
    assert json.loads(result.stdout)=={'passed':True,'checks':7,'browser_launched':False}

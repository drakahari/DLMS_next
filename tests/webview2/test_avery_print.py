"""Closed-purpose Avery print activation; native PDF acceptance is separate."""
import json
import os
from pathlib import Path
import re
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(os.name != 'nt', reason='Windows WebView2 host; Linux Qt is separate')
def test_actual_native_avery_print_permit(tmp_path):
    sdk = ROOT / '.gate1/windows-native/webview2-inputs-01/sdk/lib/net462'
    exe = tmp_path / 'AveryPrintTests.exe'
    args = ['C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe', '/nologo',
            '/target:exe', '/platform:x64', '/main:AveryPrintTests', f'/out:{exe}']
    args += ['/reference:' + x + '.dll' for x in
             ['System', 'System.Core', 'System.Drawing', 'System.Windows.Forms', 'System.Web.Extensions']]
    for name in ['Microsoft.Web.WebView2.Core.dll', 'Microsoft.Web.WebView2.WinForms.dll']:
        library = sdk / name
        (tmp_path / name).write_bytes(library.read_bytes())
        args.append(f'/reference:{library}')
    args += [str(ROOT / 'windows_webview2' / (name + '.cs')) for name in
             ['Host', 'BrowserSurface', 'FetchMetadata', 'BrowserHandoff', 'AiActions',
              'AiScripts', 'AiActionLease', 'RequestProtocol']]
    args.append(str(ROOT / 'tests/webview2/AveryPrintTests.cs'))
    built = subprocess.run(args, capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stdout + built.stderr
    run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=15)
    assert run.returncode == 0, run.stdout + run.stderr
    assert json.loads(run.stdout) == dict(passed=True, checks=12, browser_launched=False)


def test_exact_observer_trusted_mouse_keyboard_and_rejected_script(tmp_path):
    source = (ROOT / 'windows_webview2/Host.cs').read_text(encoding='utf-8')
    observer = re.search(r'AveryPrintObserver=@"(.*?)";', source, re.S)[1].replace('""', '"')
    # Execute the exact production isolated-world listener in a minimal DOM.
    harness = r"""
const vm=require('node:vm'),assert=require('node:assert/strict');
const calls=[],handlers={};let selector;
class Element {closest(){return this;}}
const button=new Element();button.type='button';button.disabled=false;button.textContent='Print Cards';selector=button;
const navigator={userActivation:{isActive:true}};
const document={addEventListener:(n,f)=>handlers[n]=f,querySelector:()=>selector};
const top={},context={document,Element,navigator,self:top,top,__dlmsAveryPrint:x=>calls.push(JSON.parse(x))};
vm.runInNewContext(OBSERVER+'("nonce")',context);
function fire(overrides={}){const e={isTrusted:true,button:0,target:button,preventDefault(){this.prevented=true},stopImmediatePropagation(){this.stopped=true},...overrides};handlers.click(e);return e;}
assert.equal(fire({isTrusted:false}).prevented,undefined); // .click()/dispatchEvent.
assert.equal(fire({button:1}).prevented,undefined);
navigator.userActivation.isActive=false;fire();navigator.userActivation.isActive=true;
button.disabled=true;fire();button.disabled=false;
selector=new Element();fire();selector=button;
button.textContent='Unrelated';fire();button.textContent='Print Cards';
assert.equal(calls.length,0);
let e=fire();assert.ok(e.prevented&&e.stopped);
e=fire({detail:0});assert.ok(e.prevented&&e.stopped); // Trusted keyboard-generated click.
assert.deepEqual(calls,[{nonce:'nonce',sequence:1},{nonce:'nonce',sequence:2}]);
e={isTrusted:true,repeat:true,key:'Enter',target:button,preventDefault(){this.prevented=true},stopImmediatePropagation(){this.stopped=true}};
handlers.keydown(e);assert.ok(e.prevented&&e.stopped);
// No timer, script-request event, window.print callback, or page-message listener exists.
assert.deepEqual(Object.keys(handlers).sort(),['click','keydown']);
console.log(JSON.stringify({passed:true,checks:11}));
""".replace('OBSERVER', json.dumps(observer))
    script = tmp_path / 'observer.cjs'
    script.write_text(harness, encoding='utf-8')
    run = subprocess.run(['node', str(script)], capture_output=True, text=True, timeout=15)
    assert run.returncode == 0, run.stdout + run.stderr
    assert json.loads(run.stdout)['passed']


def test_native_wiring_keeps_child_lease_and_no_parent_print_alias():
    source = (ROOT / 'windows_webview2/Host.cs').read_text(encoding='utf-8')
    current = source.split('bool AveryPrintCurrent(', 1)[1].split('void AveryPrintRequested', 1)[0]
    for guard in ['ReferenceEquals(averyParent.averyChild,this)', '!closing&&!disposed',
                  '!requestPolicyFailed&&browserPolicyReady&&!documentHadChildFrame',
                  'AveryLeaseCurrent(averyLease)', 'Current(nav,id)&&nav.Completed',
                  'AveryUrl(view.CoreWebView2.Source,"/anki/printable")']:
        assert guard in current
    requested = source.split('void AveryPrintRequested(', 1)[1].split('sealed class AveryOpen', 1)[0]
    assert 'permit.Identity==documentIdentity' in requested and 'permit.Take(' in requested
    assert 'await ' not in requested.replace('// No await/', '// No yielding/')
    assert 'view.CoreWebView2.ShowPrintUI(CoreWebView2PrintDialogKind.Browser)' in requested
    assert 'Event("print"' not in requested and 'PrintToPdfAsync' not in requested
    assert 'if(context==aiContext)RetireAI();\n            if(averyPrint!=null&&context==averyPrint.Context)averyPrint=null;' in source
    close = source.split('async Task CloseAveryControllerCore()', 1)[1].split('public DesktopRenderer', 1)[0]
    assert close.index('averyPrint=null;') < close.index('view.Dispose()')
    assert 'if(averyParent!=null){e.Cancel=true;AveryStatus("Downloads are unavailable' in source
    assert 'AreDefaultContextMenusEnabled=false' in source and 'IsWebMessageEnabled=false' in source
    assert "value:()=>alert('Use the Print Cards button" in source

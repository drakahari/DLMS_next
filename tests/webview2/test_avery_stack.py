"""Native sibling stacking without a browser, visible window or UI automation."""
import json
import ast
import os
from pathlib import Path
import subprocess
import pytest

@pytest.mark.skipif(os.name != 'nt', reason='Windows native stacking; Qt host is separate')
def test_actual_native_cover_priority(tmp_path):
    root = Path(__file__).resolve().parents[2]
    sdk = root / '.gate1/windows-native/webview2-inputs-01/sdk/lib/net462'
    exe = tmp_path / 'AveryStackTests.exe'
    args = ['C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe', '/nologo',
            '/target:exe', '/platform:x64', '/main:AveryStackTests', f'/out:{exe}']
    args += ['/reference:' + x + '.dll' for x in
             ['System', 'System.Core', 'System.Drawing', 'System.Windows.Forms', 'System.Web.Extensions']]
    for name in ['Microsoft.Web.WebView2.Core.dll', 'Microsoft.Web.WebView2.WinForms.dll']:
        library = sdk / name
        (tmp_path / name).write_bytes(library.read_bytes())
        args.append(f'/reference:{library}')
    args += [str(root / 'windows_webview2' / (name + '.cs')) for name in
             ['Host', 'BrowserSurface', 'FetchMetadata', 'BrowserHandoff', 'AiActions',
              'AiScripts', 'AiActionLease', 'RequestProtocol']]
    args.append(str(root / 'tests/webview2/AveryStackTests.cs'))
    built = subprocess.run(args, capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stdout + built.stderr
    run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=15)
    assert run.returncode == 0, run.stdout + run.stderr
    receipt = json.loads(run.stdout)
    assert receipt == dict(passed=True, checks=80, browser_launched=False, window_shown=False)

def test_real_navigation_and_cover_keep_native_lease_guards():
    source = (Path(__file__).resolve().parents[2] / 'windows_webview2/Host.cs').read_text(encoding='utf-8')
    navigation = source.split('core.NavigationStarting+=', 1)[1].split('core.FrameNavigationStarting', 1)[0]
    assert 'if(averyParent==null)ObserveRequestTask(RetireAvery());' in navigation
    lease = source.split('bool AveryLeaseCurrent(', 1)[1].split('void AveryState', 1)[0]
    for check in ['!owner.serverCover.Visible&&owner.view.Visible',
                  'owner.generation==lease.Generation', 'owner.activeNavigation==lease.Navigation',
                  'owner.documentIdentity==lease.Identity', 'owner.mainFrame==lease.Frame']:
        assert check in lease
    cover = source.split('case "cover":', 1)[1].split('case "policy":', 1)[0]
    assert 'AveryLeaseCurrent(preview.averyLease)' in cover
    assert 'ApplyServerCoverStack(' in cover and ',RetireAvery,' in cover
    assert 'serverCoverSerial==coverSerial&&generation==coverGeneration' in cover

def test_opt_in_avery_capture_is_bounded_and_content_free():
    from types import SimpleNamespace
    source = Path(__file__).resolve().parents[2] / 'desktop/webview2_browser.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == '_event')
    scope = {}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), 'exec'), scope)
    records = []
    owner = SimpleNamespace(window_events=SimpleNamespace(emit=lambda *a, **k: records.append((a, k))))
    receiver = SimpleNamespace(page=lambda: SimpleNamespace(owner=owner))
    event = dict(event='avery-state', state='cover-front-preview', utc='2026-10-19T20:00:00.0000000Z',
                 url='https://not-recorded.invalid/', body='not recorded')
    scope['_event'](receiver, event)
    assert records == [(('avery-native',), dict(state=event['state'], host_utc=event['utc']))]
    for state in ['x' * 81, 'https://invalid/', 'body with spaces', '']:
        scope['_event'](receiver, dict(event, state=state))
    assert len(records) == 1
    owner.window_events = None
    scope['_event'](receiver, event)
    assert len(records) == 1

"""Windows WebView2 omitted-root ownership; no GUI or owner data."""
import ctypes as c
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import subprocess
import sys
import sysconfig

import pytest

if os.name != 'nt':
    pytest.skip('Windows process ownership', allow_module_level=True)

import package_windows_webview2 as package
from desktop import ownership, windows_processes as processes, windows_files


@pytest.fixture
def frozen_webview2(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(package, 'ACTIVE', True)
    monkeypatch.setattr(ownership, 'FROZEN', True)
    monkeypatch.setattr(processes, '_webview2_default_root', None)
    root = tmp_path / 'Captured LocalAppData 日本語' / 'WebView2Candidate'
    root.mkdir(mode=0o700, parents=True)
    monkeypatch.setenv('DLMS_DESKTOP_DATA_ROOT', str(root))
    return root


def test_capture_is_private_idempotent_and_never_resolves_scoped_folder(frozen_webview2, monkeypatch):
    root = frozen_webview2
    monkeypatch.setattr(processes, 'default_data_root', lambda: pytest.fail('KnownFolder lookup after isolation'))
    assert ownership.windows_default_data_root() is None
    processes.capture_webview2_default_root(str(root))
    processes.capture_webview2_default_root(str(root))
    assert ownership.windows_default_data_root() == root
    with pytest.raises(RuntimeError, match='capture changed'):
        processes.capture_webview2_default_root(str(root.parent / 'Other'))
    assert ownership.windows_default_data_root() == root


@pytest.mark.parametrize('value', [None, True, 5, '', 'relative', 'C:relative',
    'C:/not-canonical', 'C:\\path\\..\\other', 'C:\\path\\.\\other',
    '\\\\server\\share\\root', '\\\\?\\C:\\root', 'C:\\path\\CON.txt',
    'C:\\path\\unsafe:stream', 'C:\\path\\trailing. ', 'C:\\' + 'a'*9000])
def test_malformed_capture_rejected(frozen_webview2, value):
    with pytest.raises((ValueError, OSError)):
        processes.capture_webview2_default_root(value)
    assert processes.captured_webview2_default_root() is None


def test_reparse_capture_refused(frozen_webview2):
    root = frozen_webview2
    junction = root.parent / 'junction'
    subprocess.run(['cmd.exe', '/c', 'mklink', '/J', str(junction), str(root)], capture_output=True, check=True)
    try:
        with pytest.raises(ValueError, match='reparse'):
            processes.capture_webview2_default_root(str(junction))
    finally:
        junction.rmdir()


@pytest.mark.parametrize('capture', [False, True])
def test_tagged_transport_roundtrip_and_explicit_root_without_default(frozen_webview2, monkeypatch, capture):
    root = frozen_webview2
    if capture: processes.capture_webview2_default_root(str(root))
    value = processes._webview2_ownership_payload(dict(os.environ))
    assert value == {'renderer': 'webview2', 'default_root': str(root) if capture else None}
    monkeypatch.setattr(processes, '_webview2_default_root', None)
    processes._restore_webview2_ownership({'socket': None, 'webview2_ownership': value})
    assert processes.captured_webview2_default_root() == (root if capture else None)
    assert ownership.windows_launch_matches(['app', '--data-root', str(root)], 'default', root, None)
    assert ownership.windows_launch_matches(['app'], 'default', root, processes.captured_webview2_default_root()) == capture


@pytest.mark.parametrize('payload', [None, [], {}, {'webview2_ownership': None},
    {'webview2_ownership': {}}, {'webview2_ownership': {'renderer': 'qt', 'default_root': None}},
    {'webview2_ownership': {'renderer': 'webview2', 'default_root': None, 'extra': 1}},
    {'webview2_ownership': {'renderer': 'webview2', 'default_root': 'relative'}}])
def test_missing_malformed_or_wrong_renderer_transport_refused(frozen_webview2, payload):
    with pytest.raises((RuntimeError, ValueError)):
        processes._restore_webview2_ownership(payload)
    assert processes.captured_webview2_default_root() is None


def test_transport_root_must_match_exact_authenticated_worker_root(frozen_webview2, monkeypatch):
    root = frozen_webview2
    processes.capture_webview2_default_root(str(root))
    with pytest.raises(RuntimeError, match='differs from worker data root'):
        processes._webview2_ownership_payload({'DLMS_DESKTOP_DATA_ROOT': str(root.parent / 'Other')})
    monkeypatch.setattr(processes, '_webview2_default_root', None)
    with pytest.raises(RuntimeError, match='differs from authenticated data root'):
        processes._restore_webview2_ownership({'webview2_ownership': {'renderer': 'webview2',
            'default_root': str(root.parent / 'Other')}})
    processes.capture_webview2_default_root(str(root))
    with pytest.raises(RuntimeError, match='lost its default'):
        processes._restore_webview2_ownership({'webview2_ownership': {'renderer': 'webview2', 'default_root': None}})


@pytest.mark.parametrize('frozen,active', [(False, True), (True, False), (False, False)])
def test_qt_and_source_bootstrap_packets_unchanged(monkeypatch, frozen, active):
    monkeypatch.setattr(sys, 'frozen', frozen, raising=False)
    monkeypatch.setattr(package, 'ACTIVE', active)
    monkeypatch.setattr(processes, '_webview2_default_root', None)
    assert processes._webview2_ownership_payload({}) is None
    processes._restore_webview2_ownership({'socket': None})
    with pytest.raises(RuntimeError, match='renderer does not match'):
        processes._restore_webview2_ownership({'webview2_ownership': {'renderer': 'webview2', 'default_root': None}})
    with pytest.raises(RuntimeError, match='requires the frozen'):
        processes.capture_webview2_default_root('C:\\Captured')


@pytest.mark.parametrize('arguments', [[], ['--profile'], ['--data-root'], ['--unknown'],
    ['--native-check', 'backup'], ['--profile=a'], ['--data-root='],
    ['--data-root', 'C:\\one', '--data-root=C:\\two'], ['--capture-window-events=1']])
def test_invalid_or_instrumented_argv_fails_closed_before_default(frozen_webview2, arguments):
    assert not ownership.windows_launch_matches(['app', *arguments], 'synthetic', frozen_webview2, None)


@pytest.mark.parametrize('explicit,captured,expected', [(False, False, False), (False, True, True),
    (True, False, True), (True, True, True)])
def test_verified_owner_uses_captured_default_only_and_keeps_identity_checks(frozen_webview2, monkeypatch,
                                                                                       explicit, captured, expected):
    root = frozen_webview2
    descriptor = root / 'instance-owner.json'
    descriptor.write_text(json.dumps({'pid': 42, 'name': 'default', 'start_ticks': 123, 'secret': 'a'*64}))
    monkeypatch.setattr(ownership, 'AREA', root)
    monkeypatch.setattr(ownership, 'process_start_ticks', lambda pid: 123)
    monkeypatch.setattr(processes, 'default_data_root', lambda: pytest.fail('Scoped KnownFolder query'))
    monkeypatch.setattr(processes, 'identity', lambda pid: {'start': 123, 'image': 'same.exe', 'sid': 'owner'})
    monkeypatch.setattr(processes, 'arguments', lambda pid: ['same.exe', *(['--data-root', str(root)] if explicit else [])])
    monkeypatch.setattr(windows_files, 'owned', lambda *args, **kwargs: None)
    if captured: processes.capture_webview2_default_root(str(root))
    assert ownership.verified_instance(descriptor, 'default') == ('a'*64 if expected else None)
    monkeypatch.setattr(processes, 'identity', lambda pid: {'start': 123, 'image': 'other.exe' if pid == 42 else 'same.exe', 'sid': 'owner'})
    assert ownership.verified_instance(descriptor, 'default') is None


def test_entry_captures_validated_omitted_root_before_existing_entry(frozen_webview2, monkeypatch):
    from package_windows_webview2 import entry
    import package_windows.entry as inherited
    root, events = frozen_webview2, []
    monkeypatch.setattr(sys, 'argv', ['app'])
    monkeypatch.setattr(entry, 'default_data_root', lambda: events.append('known-folder') or root)
    monkeypatch.setattr(inherited, 'root_path', lambda path, **kw: events.append('validated') or root)
    def existing():
        events.append('existing-entry')
        assert processes.captured_webview2_default_root() == root
        assert sys.argv == ['app', '--data-root', str(root)]
        return 7
    monkeypatch.setattr(inherited, 'main', existing)
    assert entry.main() == 7
    assert events == ['known-folder', 'validated', 'existing-entry']


@pytest.mark.parametrize('arguments', [['app', '--data-root', 'C:\\Explicit'],
    ['app', '--data-root=C:\\Explicit'], ['app', '--desktop-worker', 'adopt']])
def test_explicit_entry_and_worker_do_not_query_default(frozen_webview2, monkeypatch, arguments):
    from package_windows_webview2 import entry
    import package_windows.entry as inherited
    monkeypatch.setattr(sys, 'argv', arguments.copy())
    monkeypatch.setattr(entry, 'default_data_root', lambda: pytest.fail('Unnecessary KnownFolder query'))
    monkeypatch.setattr(inherited, 'main', lambda: 8)
    assert entry.main() == 8
    assert processes.captured_webview2_default_root() is None


@pytest.mark.parametrize('mismatch', ['identity', 'sid', 'image'])
def test_parent_authentication_failure_cannot_restore_capture(frozen_webview2, monkeypatch, mismatch):
    expected = {'start': 123, 'image': 'same.exe', 'sid': 'owner'}
    monkeypatch.setenv('DLMS_WINDOWS_PARENT', json.dumps(dict(expected, pid=42)))
    monkeypatch.setenv('DLMS_WINDOWS_BOOTSTRAP', '0')
    def identity(pid):
        value = expected.copy()
        if mismatch == 'identity' and pid == 42: value['start'] = 124
        if mismatch == 'image' and pid != 42: value['image'] = 'other.exe'
        return value
    monkeypatch.setattr(processes, 'identity', identity)
    monkeypatch.setattr(processes, 'process_sid', lambda handle: 'other' if mismatch == 'sid' else 'owner')
    restored = []
    monkeypatch.setattr(processes, '_restore_webview2_ownership', lambda payload: restored.append(payload))
    with pytest.raises(RuntimeError, match='parent'):
        processes.bootstrap()
    assert not restored and processes.captured_webview2_default_root() is None


@pytest.mark.parametrize('malformed', [False, True])
def test_actual_owned_spawn_and_bootstrap_restore_or_reject_tag(frozen_webview2, monkeypatch, malformed):
    root = frozen_webview2
    processes.capture_webview2_default_root(str(root))
    if malformed:
        monkeypatch.setattr(processes, '_webview2_ownership_payload', lambda env: {'renderer': 'qt', 'default_root': str(root)})
    code = '''import sys,json
sys.frozen=True
import package_windows_webview2
package_windows_webview2.ACTIVE=True
from desktop.windows_processes import bootstrap,captured_webview2_default_root,default_data_root
bootstrap()
print(json.dumps({'captured':str(captured_webview2_default_root())}),flush=True)
'''
    environment = dict(os.environ)
    environment['PYTHONPATH'] = os.pathsep.join((str(Path(__file__).resolve().parents[2]), sysconfig.get_path('purelib')))
    proc = processes.spawn([sys._base_executable, '-S', '-c', code], cwd=Path(__file__).resolve().parents[2],
        env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        output, errors = proc.communicate(timeout=15)
        if malformed:
            assert proc.returncode != 0 and b'ownership capture is missing or malformed' in errors
        else:
            assert proc.returncode == 0, errors.decode(errors='replace')
            assert json.loads(output)['captured'] == str(root)
    finally:
        processes.reap(proc.pid, environment.get('DLMS_DESKTOP_NONCE'))
        if proc.poll() is None:
            proc.kill(); proc.communicate(timeout=5)


@pytest.mark.parametrize('existing_unmarked', [False, True])
def test_cold_default_first_root_creation_binds_environment_before_isolation(tmp_path, existing_unmarked):
    """A new interpreter must exercise root_path's real atomic_json import."""
    payload, root = tmp_path / 'Synthetic frozen payload', tmp_path / 'AppData 日本語' / 'WebView2Candidate'
    payload.mkdir(mode=0o700)
    if existing_unmarked:
        root.mkdir(mode=0o700, parents=True)
        (root / 'preserve.txt').write_bytes(b'private synthetic preexisting bytes')
    code = '''import json,os,sys
from pathlib import Path
payload,root=map(Path,sys.argv[1:3])
unmarked=sys.argv[3]=='yes'
os.environ.pop('DLMS_DESKTOP_DATA_ROOT',None)
os.environ.pop('DLMS_DESKTOP_ROOT_KIND',None)
sys.frozen=True
sys._MEIPASS=str(payload)
sys.argv=['cold-candidate.exe']
from package_windows_webview2 import entry
import package_windows.entry as inherited
assert 'desktop.isolation' not in sys.modules
entry.default_data_root=lambda:root
def after_creation():
    from desktop import isolation
    from desktop.windows_processes import captured_webview2_default_root
    assert isolation.FROZEN and isolation.PROJECT==payload and isolation.AREA==root
    assert os.environ['DLMS_DESKTOP_DATA_ROOT']==str(root)
    assert os.environ['DLMS_DESKTOP_ROOT_KIND']=='windows-candidate'
    assert json.loads((root/inherited.MARKER).read_text())==inherited.IDENTITY
    assert captured_webview2_default_root()==root
    assert sys.argv==['cold-candidate.exe','--data-root',str(root)]
    return 0
inherited.main=after_creation
if unmarked:
    try: entry.main()
    except ValueError as exc: assert 'marker is missing or invalid' in str(exc)
    else: raise AssertionError('Existing unmarked root was adopted')
    assert not (root/inherited.MARKER).exists()
    assert (root/'preserve.txt').read_bytes()==b'private synthetic preexisting bytes'
    print(json.dumps({'unmarked_refused':True,'preserved':True}))
else:
    assert not root.exists()
    assert entry.main()==0
    print(json.dumps({'cold_first_root_created':True,'marker_valid':True,'startup_area_bound':True,'capture_valid':True}))
'''
    environment = {key: value for key, value in os.environ.items()
                   if key not in {'DLMS_DESKTOP_DATA_ROOT', 'DLMS_DESKTOP_ROOT_KIND'}}
    environment['PYTHONPATH'] = os.pathsep.join((str(Path(__file__).resolve().parents[2]), sysconfig.get_path('purelib')))
    child = subprocess.run([sys._base_executable, '-S', '-c', code, str(payload), str(root),
                            'yes' if existing_unmarked else 'no'], env=environment,
                           capture_output=True, timeout=15)
    (tmp_path / 'cold-default-result.json').write_bytes(child.stdout)
    assert child.returncode == 0, child.stderr.decode(errors='replace')
    result = json.loads(child.stdout)
    assert result == ({'unmarked_refused': True, 'preserved': True} if existing_unmarked else
        {'cold_first_root_created': True, 'marker_valid': True, 'startup_area_bound': True, 'capture_valid': True})

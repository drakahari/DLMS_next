"""Native release gates without creating a real release or foreign-platform claims."""
import importlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMMIT = 'a' * 40


@pytest.fixture
def tool(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'tools'))
    return importlib.import_module('build_native_release')


@pytest.mark.parametrize('version,valid', [
    ('5.5.3', True), ('v5.5.3.20260724', True), ('V5.0.0', True),
    ('5.5.3-rc1', True), ('4.1.0', False), ('v6.0.0', False),
    ('50.0', False), ('5garbage', False), ('', False),
])
def test_tesseract_major_gate(tool, version, valid):
    from ocr_packaging_probe import supported_tesseract_version
    from dlms.services.ocr import _read_engine_version
    if not version:
        assert supported_tesseract_version(version) is False
        return
    with mock.patch('dlms.services.ocr.subprocess.run', return_value=SimpleNamespace(
            returncode=0, stdout=f'tesseract {version}\nother details'.encode())):
        detected = _read_engine_version(Path('tesseract'), Path('tessdata'))
    assert detected == version
    assert supported_tesseract_version(detected) is valid


@pytest.mark.parametrize('actual', ['3.2.0', '3.1.0', None, '3.2.0-stale'])
def test_runtime_version_gate(tool, actual):
    import verify_release_artifact as verifier
    if actual == '3.2.0':
        verifier._assert_runtime_version(actual, '3.2.0')
    else:
        with pytest.raises(RuntimeError, match='Runtime version mismatch'):
            verifier._assert_runtime_version(actual, '3.2.0')


def test_smoke_reads_version_from_running_server_header(tool):
    import verify_release_artifact as verifier
    client = verifier.SmokeHttpClient()
    response = mock.MagicMock()
    response.status = 200
    response.headers = {'X-DLMS-Version': '3.1.0'}
    response.read.return_value = b'DLMS'
    response.__enter__.return_value = response
    with mock.patch.object(client.opener, 'open', return_value=response):
        assert verifier._request('/', client=client) == (200, b'DLMS')
    assert client.runtime_version == '3.1.0'
    with mock.patch.object(verifier, '_request', side_effect=[
            (200, marker) for marker in [b'DLMS', b'body', b'<symbol id="settings"',
                                         b'Help', b'Settings', b'Quiz Library']]):
        with pytest.raises(RuntimeError, match='version mismatch'):
            verifier._assert_smoke_routes(client, '3.2.0')


@pytest.mark.parametrize('problem', ['commit', 'short-sha', 'dirty', 'version', None])
def test_source_preflight(tool, tmp_path, monkeypatch, problem):
    (tmp_path / 'app.py').write_text('APP_VERSION = "3.2.0"\n')
    monkeypatch.setattr(tool.subprocess, 'check_output', lambda cmd, **kw:
                        (' M app.py' if problem == 'dirty' else '') if 'status' in cmd else COMMIT)
    commit = 'b' * 40 if problem == 'commit' else COMMIT[:7] if problem == 'short-sha' else COMMIT
    version = '3.1.0' if problem == 'version' else '3.2.0'
    if problem:
        with pytest.raises(tool.ReleaseError): tool.source_preflight(tmp_path, commit, version)
    else:
        assert tool.source_preflight(tmp_path, commit, version) == (COMMIT, version)


def test_build_refuses_existing_output_before_pyinstaller(tool, tmp_path, monkeypatch):
    destination = tmp_path / 'old'
    destination.mkdir()
    (destination / 'stale.exe').write_bytes(b'old')
    run = mock.Mock()
    monkeypatch.setattr(tool, 'run_stage', run)
    with pytest.raises(FileExistsError):
        tool.build_frozen(tmp_path / 'DLMS.spec', destination, root=tmp_path, environment={})
    run.assert_not_called()
    assert (destination / 'stale.exe').read_bytes() == b'old'


@pytest.fixture
def pipeline(tool, tmp_path, monkeypatch):
    args = tool.parser().parse_args(['--target', 'fedora44-x86_64', '--expected-commit', COMMIT,
        '--expected-version', '3.2.0', '--output-dir', str(tmp_path / 'accepted')])
    calls = []
    monkeypatch.setattr(tool, 'source_preflight', mock.Mock(return_value=(COMMIT, '3.2.0')))
    monkeypatch.setattr(tool, '_assert_smoke_host', mock.Mock())
    monkeypatch.setattr(tool, 'linux_preflight', mock.Mock(return_value={}))
    monkeypatch.setattr(tool, '_assert_port_available', mock.Mock())
    monkeypatch.setattr(tool, 'verify_artifact', mock.Mock(return_value=[]))
    monkeypatch.setattr(tool, 'smoke_test', mock.Mock())
    def stage(name, command, *, root, environment):
        calls.append((name, command, dict(environment)))
        if '-m' in command and 'PyInstaller' in command:
            dist = Path(command[command.index('--distpath') + 1]); dist.mkdir()
            if name == 'DLMS':
                (dist / 'DLMS').write_bytes(b'fresh native application')
                (dist / 'DLMS.exe').write_bytes(b'fresh Windows application')
            else:
                (dist / 'DLMS-OCR-Probe').write_bytes(b'probe')
        if name == 'native macOS archive': Path(command[-1]).write_bytes(b'native ditto ZIP')
    monkeypatch.setattr(tool, 'run_stage', stage)
    def package(target, artifact, output, root, smoke):
        assert smoke is True
        output.mkdir()
        name = tool._single_target_contract(target, '3.2.0')[2]
        path = output / name; path.write_bytes(artifact.read_bytes()); return path
    monkeypatch.setattr(tool, 'package_single_target', mock.Mock(side_effect=package))
    return args, calls, stage


@pytest.mark.parametrize('target', ['fedora44-x86_64', 'ubuntu24.04-x86_64', 'ubuntu26.04-x86_64',
                                   'omarchy-quattro-x86_64', 'windows11-x86_64', 'macos-arm64'])
def test_successful_orchestration_and_acceptance(tool, pipeline, tmp_path, target):
    args, calls, _ = pipeline; args.target = target
    for folder in ['build', 'dist']:
        (tmp_path / folder).mkdir(); (tmp_path / folder / 'DLMS').write_bytes(b'stale 3.1.0')
    result = tool.orchestrate(args, root=tmp_path)
    assert result['status'] == 'accepted' and result['commit'] == COMMIT
    assert result['target'] == target and result['version'] == '3.2.0'
    assert Path(result['package']).is_file()
    assert tool.sha256_file(Path(result['package'])) == result['sha256']
    assert json.loads((args.output_dir / 'acceptance.json').read_text()) == result
    assert (args.output_dir / 'SHA256SUMS.txt').read_text().startswith(result['sha256'])
    assert 'DLMS NATIVE RELEASE ACCEPTED' in tool.acceptance_text(result)
    assert str(Path(result['package'])) in tool.acceptance_text(result)
    for folder in ['build', 'dist']:
        assert (tmp_path / folder / 'DLMS').read_bytes() == b'stale 3.1.0'
    builds = [(cmd, env) for name, cmd, env in calls if name in {'DLMS', 'DLMS-OCR-Probe'}]
    assert len(builds) == 2
    assert builds[0][0][builds[0][0].index('--workpath')+1] != builds[1][0][builds[1][0].index('--workpath')+1]
    assert all('.dlms-native-release-' in env['PYINSTALLER_CONFIG_DIR'] for _,env in builds)
    tool.smoke_test.assert_called_once()
    assert tool.smoke_test.call_args.args[2] == '3.2.0'
    tool._assert_smoke_host.assert_called_once_with(tool._single_target_contract(target, '3.2.0')[0])
    assert tool.source_preflight.call_count == 2
    assert not list(tmp_path.glob('.dlms-native-release-*'))


@pytest.mark.parametrize('failed_stage', ['dependency preflight', 'OCR bundle validation', 'DLMS-OCR-Probe',
                                         'frozen OCR probe', 'DLMS', 'artifact', 'smoke', 'package'])
def test_stage_failure_never_publishes_acceptance(tool, pipeline, tmp_path, monkeypatch, failed_stage):
    args, calls, original = pipeline
    def stage(name, *a, **kw):
        if name == failed_stage: raise tool.ReleaseError('injected stage failure')
        return original(name, *a, **kw)
    monkeypatch.setattr(tool, 'run_stage', stage)
    if failed_stage == 'artifact': tool.verify_artifact.return_value = ['bad native architecture']
    if failed_stage == 'smoke': tool.smoke_test.side_effect = RuntimeError('runtime mismatch')
    if failed_stage == 'package': tool.package_single_target.side_effect = RuntimeError('final extraction failed')
    with pytest.raises(RuntimeError): tool.orchestrate(args, root=tmp_path)
    assert not args.output_dir.exists()
    assert not list(tmp_path.glob('.dlms-native-release-*'))


def test_command_failure_has_stage_name(tool, tmp_path, monkeypatch):
    monkeypatch.setattr(tool.subprocess, 'run', mock.Mock(side_effect=subprocess.CalledProcessError(7, ['builder'])))
    with pytest.raises(tool.ReleaseError, match='build failed'):
        tool.run_stage('build', ['builder'], root=tmp_path, environment={})


def test_incomplete_python_stops_before_ocr_or_build(tool, pipeline, tmp_path, monkeypatch):
    args, calls, _ = pipeline
    def fail_dependencies(name, command, **kwargs):
        assert name == 'dependency preflight'
        assert command == [tool.sys.executable, '-B', tmp_path / 'tools/check_release_dependencies.py']
        raise tool.ReleaseError('incomplete active Python environment')
    monkeypatch.setattr(tool, 'run_stage', fail_dependencies)
    build = mock.Mock()
    monkeypatch.setattr(tool, 'build_frozen', build)
    with pytest.raises(tool.ReleaseError, match='incomplete active Python'):
        tool.orchestrate(args, root=tmp_path)
    build.assert_not_called()
    assert not args.output_dir.exists()


def test_arguments_and_existing_output_fail_closed(tool, pipeline, tmp_path):
    with pytest.raises(SystemExit): tool.parser().parse_args(['--target', 'macos-x86_64'])
    with pytest.raises(SystemExit): tool.main(['--target', 'fedora44-x86_64', '--expected-commit', COMMIT,
                                             '--expected-version', '3.2.0', '--download-missing-licenses'])
    args, calls, _ = pipeline; args.output_dir.mkdir()
    with pytest.raises(tool.ReleaseError, match='replace existing'): tool.orchestrate(args, root=tmp_path)
    assert not calls


def test_main_failure_summary(tool, monkeypatch, capsys):
    monkeypatch.setattr(tool, 'orchestrate', mock.Mock(side_effect=tool.ReleaseError('probe failed')))
    assert tool.main(['--target', 'windows11-x86_64', '--expected-commit', COMMIT,
                      '--expected-version', '3.2.0']) == 1
    text = capsys.readouterr().err
    assert 'DLMS NATIVE RELEASE FAILED' in text and 'probe failed' in text
    assert COMMIT in text and 'windows11-x86_64' in text


def test_main_success_summary(tool, monkeypatch, capsys):
    record = dict(target='macos-arm64', version='3.2.0', commit=COMMIT,
                  package='/native/DLMS-3.2.0-macos-arm64.zip', sha256='b' * 64)
    monkeypatch.setattr(tool, 'orchestrate', mock.Mock(return_value=record))
    assert tool.main(['--target', 'macos-arm64', '--expected-commit', COMMIT,
                      '--expected-version', '3.2.0']) == 0
    text = capsys.readouterr().out
    assert all(value in text for value in record.values())
    assert 'DLMS NATIVE RELEASE ACCEPTED' in text


def test_source_change_during_build_prevents_acceptance(tool, pipeline, tmp_path):
    args, _, _ = pipeline
    tool.source_preflight.side_effect = [(COMMIT, '3.2.0'), tool.ReleaseError('source changed')]
    with pytest.raises(tool.ReleaseError, match='source changed'):
        tool.orchestrate(args, root=tmp_path)
    assert not args.output_dir.exists()
    assert not list(tmp_path.glob('.dlms-native-release-*'))


def test_foreign_host_fails_before_any_build(tool, pipeline, tmp_path):
    args, calls, _ = pipeline
    tool._assert_smoke_host.side_effect = RuntimeError('must run on native host')
    with pytest.raises(RuntimeError, match='native host'):
        tool.orchestrate(args, root=tmp_path)
    assert not calls and not args.output_dir.exists()


def test_ocr_preparation_options_use_existing_helper(tool, pipeline, tmp_path):
    args, calls, _ = pipeline
    args.prepare_ocr = True
    args.tesseract_license = '/native/license.txt'
    args.download_missing_licenses = True
    tool.orchestrate(args, root=tmp_path)
    command = next(cmd for name, cmd, _ in calls if name == 'OCR bundle preparation')
    assert '--validate-only' not in command
    assert command[command.index('--tesseract-license') + 1] == '/native/license.txt'
    assert '--download-missing-licenses' in command


@pytest.mark.parametrize('target,identifier,version,valid', [
    ('fedora44-x86_64', 'fedora', '44', True),
    ('fedora44-x86_64', 'fedora', '43', False),
    ('ubuntu24.04-x86_64', 'ubuntu', '24.04', True),
    ('ubuntu26.04-x86_64', 'ubuntu', '26.04', True),
    ('ubuntu26.04-x86_64', 'fedora', '44', False),
    ('omarchy-quattro-x86_64', 'arch', '', True),
    ('omarchy-quattro-x86_64', 'ubuntu', '26.04', False),
])
def test_linux_target_preflight(tool, monkeypatch, target, identifier, version, valid):
    monkeypatch.setattr(tool.platform, 'freedesktop_os_release',
                        lambda: {'ID': identifier, 'VERSION_ID': version})
    if valid:
        assert tool.linux_preflight(target)['ID'] == identifier
    else:
        with pytest.raises(tool.ReleaseError): tool.linux_preflight(target)

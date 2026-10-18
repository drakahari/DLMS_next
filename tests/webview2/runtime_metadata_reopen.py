"""Bounded real-host Evergreen metadata regression; only disposable storage.

Can target the actual installed host without changing its payload or owner data.
Creates old metadata naturally with an explicitly selected, already installed
protected older Runtime in this test process only. Never changes machine settings.
Standalone host evidence is not normal Desktop UI/installer acceptance.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import secrets
import subprocess
from unittest.mock import patch

from tests.webview2.host_security import Fixture, Host, fresh

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / '.gate1/windows-native'
COMPONENTS = {'dgiklkfkllikcanfonkcabmbdfmgleag': 'edge_clipboard',
              'mhjfbmdgcfjbbpaeojofohoefgiehjai': 'edge_pdf'}
ERROR = 'Runtime component Preferences metadata did not match the exact protected virtual resource'


def metadata(storage):
    result = []
    for path in storage.rglob('Secure Preferences'):
        settings = json.loads(path.read_text(encoding='utf-8')).get('extensions', {}).get('settings', {})
        for identifier, resource in COMPONENTS.items():
            if identifier in settings:
                item = settings[identifier]
                result.append({'file': str(path.relative_to(storage)), 'component': identifier,
                               'resource': resource, 'location': item.get('location'), 'path': item.get('path')})
    return result


def runtime(host):
    rows = [row for row in host.events if row.get('event') == 'runtime']
    assert rows, 'Actual runtime event missing'
    return rows[-1]['version'].split(' ')[0]


def bootstrap(executable, case, fixture, mode, old_runtime):
    original = subprocess.Popen
    def selected(*args, **kwargs):
        # Only this standalone child sees the documented runtime selector.
        # Host current-image, signature, protected-path and sandbox checks run.
        kwargs['env'] = dict(kwargs['env'], WEBVIEW2_BROWSER_EXECUTABLE_FOLDER=str(old_runtime))
        return original(*args, **kwargs)
    with patch('tests.webview2.host_security.subprocess.Popen', selected):
        return Host(executable, case, fixture, mode)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--baseline-host', type=Path, required=True)
    p.add_argument('--fixed-host', type=Path)
    p.add_argument('--old-runtime', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--reuse-baseline', action='store_true')
    p.add_argument('--removed-version', help='Synthetic absent version in persisted metadata; never removes a machine Runtime')
    args = p.parse_args()
    args.baseline_host = args.baseline_host.absolute()
    args.old_runtime = args.old_runtime.absolute()
    if args.fixed_host: args.fixed_host = args.fixed_host.absolute()
    from desktop.windows_processes import own_launcher
    from desktop.windows_files import assert_path
    own_launcher()
    out = args.output.absolute()
    if not out.is_relative_to(WORK): raise ValueError('Disposable task-local evidence only')
    for path in (args.baseline_host, args.old_runtime): assert_path(path)
    if args.fixed_host: assert_path(args.fixed_host)
    if args.reuse_baseline:
        initial = json.loads((out/'result.json').read_text())
        assert args.fixed_host and initial['baseline_reproduced']
    else:
        fresh(out)
        initial = {'actual_baseline_host': str(args.baseline_host),
                   'baseline_host_sha256': hashlib.sha256(args.baseline_host.read_bytes()).hexdigest(),
                   'old_runtime_selector_test_process_only': str(args.old_runtime),
                   'owner_profiles_used': False, 'installed_payload_modified': False,
                   'standalone_host': True, 'normal_desktop_ui_acceptance': False, 'modes': {}}
    for mode in ('server', 'local'):
        fixture = Fixture(secrets.token_hex(32)).start()
        host = None
        try:
            if not args.reuse_baseline:
                case = fresh(out/(mode+'-old-bootstrap'))
                host = bootstrap(args.baseline_host, case, fixture, mode, args.old_runtime)
                host.loaded()
                old_version = runtime(host)
                assert old_version == args.old_runtime.name
                storage = host.storage
                host.close(); host = None
                before = metadata(storage)
                assert len(before) == 2 and all(row['location'] == 5 and old_version in row['path'] for row in before)
                host = Host(args.baseline_host, fresh(out/(mode+'-baseline-reopen')), fixture, mode, reuse_storage=storage)
                fatal = host.wait(lambda rows: next((r for r in rows if r.get('event') == 'fatal'), None))
                assert fatal.get('value', {}).get('message') == ERROR, fatal
                host.proc.wait(timeout=30)
                assert host.proc.returncode == 1
                host.close(); host = None
                initial['modes'][mode] = {'storage': str(storage), 'old_runtime': old_version,
                    'naturally_persisted_component_fields': before, 'baseline_fatal': fatal,
                    'baseline_exit': 1, 'baseline_reproduced': True}
                initial['baseline_reproduced'] = all(v.get('baseline_reproduced') for v in initial['modes'].values())
                (out/'result.json').write_text(json.dumps(initial, indent=2)+'\n')
            if args.fixed_host:
                row = initial['modes'][mode]
                storage = Path(row['storage'])
                assert storage.is_relative_to(out)
                before = metadata(storage)
                assert len(before) == 2 and all(row['old_runtime'] in item['path'] for item in before)
                case = fresh(out/(mode+'-fixed-reopen'))
                host = Host(args.fixed_host, case, fixture, mode, reuse_storage=storage)
                host.loaded()
                selected_version = runtime(host)
                assert selected_version != row['old_runtime']
                assert not any(r.get('event') == 'fatal' for r in host.events)
                row['fixed_runtime'] = selected_version
                row['fixed_policy'] = [r for r in host.events if r.get('event') == 'socket-policy']
                assert len(row['fixed_policy']) == 1
                row['fixed_component_metadata_before_start'] = before
                row['fixed_reopen_passed'] = True
                assert host.evaluate("localStorage.setItem('runtime-transition-marker','synthetic-retained');'stored'").get('value') == 'stored'
                host.close(); host = None
                if args.removed_version:
                    removed = args.old_runtime.parent / args.removed_version
                    assert not removed.exists(), 'Never remove or hide a real installed Runtime'
                    rewrites = []
                    for path in storage.rglob('Secure Preferences'):
                        original = path.read_bytes()
                        data = json.loads(original)
                        settings = data.get('extensions', {}).get('settings', {})
                        for identifier, resource in COMPONENTS.items():
                            if identifier in settings:
                                settings[identifier]['path'] = str(removed / 'resources' / resource)
                        (case / ('before-synthetic-removed-' + str(len(rewrites)) + '.json')).write_bytes(original)
                        path.write_text(json.dumps(data), encoding='utf-8')
                        rewrites.append(str(path.relative_to(storage)))
                    assert len(metadata(storage)) == 2 and rewrites
                    host = Host(args.baseline_host, fresh(out/(mode+'-removed-baseline')), fixture, mode, reuse_storage=storage)
                    fatal = host.wait(lambda rows: next((r for r in rows if r.get('event') == 'fatal'), None))
                    assert fatal.get('value', {}).get('message') == ERROR, fatal
                    host.proc.wait(timeout=30)
                    assert host.proc.returncode == 1
                    row['removed_baseline_reproduced'] = True
                    host.close(); host = None
                    for attempt in range(2):
                        host = Host(args.fixed_host, fresh(out/(mode+'-removed-reopen-'+str(attempt))), fixture, mode, reuse_storage=storage)
                        host.loaded()
                        assert host.evaluate("localStorage.getItem('runtime-transition-marker')").get('value') == 'synthetic-retained'
                        assert not any(r.get('event') == 'fatal' for r in host.events)
                        host.close(); host = None
                    assert not removed.exists()
                    row['removed_version'] = args.removed_version
                    row['removed_case_is_synthetic_metadata_not_machine_uninstall'] = True
                    row['removed_runtime_two_reopens_and_storage_marker_passed'] = True
                (out/'result.json').write_text(json.dumps(initial, indent=2)+'\n')
        finally:
            if host: host.close()
            fixture.close()
    if args.fixed_host:
        initial['fixed_host_sha256'] = hashlib.sha256(args.fixed_host.read_bytes()).hexdigest()
        initial['passed'] = all(v.get('fixed_reopen_passed') for v in initial['modes'].values())
    (out/'result.json').write_text(json.dumps(initial, indent=2)+'\n')
    print(json.dumps({'baseline_reproduced': initial['baseline_reproduced'],
                      'fixed_passed': initial.get('passed'), 'output': str(out)}))


if __name__ == '__main__': main()

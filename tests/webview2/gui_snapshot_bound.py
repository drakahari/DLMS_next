"""Actual source File bytes at candidate239 bound and whole-new-batch240 refusal."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import uuid


def units(path): return len(str(path).encode('utf-16-le')) // 2


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--profile', required=True); args = parser.parse_args()
    import package_windows_webview2
    package_windows_webview2.ACTIVE = True
    from PySide6.QtCore import QStandardPaths
    import PySide6
    from desktop import webview2_file_selection as fs
    from desktop import windows_file_selection as native
    from desktop.webview2_shell import DesktopWindow
    from desktop.isolation import PROJECT
    roots = fs._known_private_roots()
    documents = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation))
    import desktop.shell
    desktop.shell.DesktopWindow = lambda *a, **k: DesktopWindow(*a, selection_private_roots=roots, documents_folder=documents, **k)
    from tests.gate1.qt_checks import QtChecks
    q = QtChecks(args.profile, automated=True)
    original_warning = fs._warning; warnings = []
    fs._warning = lambda context, ticket, message: warnings.append(str(message)) or fs._feedback(context, ticket, message, 'error')
    report = {'source_instrumented': True, 'normal_package': False, 'physical_acceptance': False, 'passed': False,
              'python_version': sys.version, 'pyside_version': PySide6.__version__, 'activation': 'owned-eval-gesture-untrusted-DOM-click'}
    store = None
    try:
        expected_parent = q.paths['root'] / 'selected' / ('.wv-s-' + 'a' * 26) / ('a' * 26)
        name_units = 239 - units(expected_parent) - 1
        assert 6 <= name_units <= 200
        name = '界' * (name_units - 6) + '😀.txt'
        fixture = PROJECT / 'fixtures/webview2-ordinary' / uuid.uuid4().hex; fixture.mkdir(mode=0o700, parents=True)
        source = fixture / name; original = (PROJECT / 'fixtures/gate1-neutral-quiz.txt').read_bytes(); source.write_bytes(original)
        bad = fixture / ('a' + name); bad.write_bytes(original)
        q.go('/upload'); q.window.file_selection_for_test = str(source)
        q.window.view.command('eval', script="document.querySelector('input[name=file]').click();true", world=0, gesture=True)
        q.wait("document.querySelector('input[name=file]').files.length===1")
        q.wait('true'); q.delay(.1)
        store = q.window.view._selection_store; snapshot, = store.snapshots
        assert units(snapshot.path) == 239
        actual = q.js("""(async()=>{const f=document.querySelector('input[name=file]').files[0];return {name:f.name,size:f.size,sha256:[...new Uint8Array(await crypto.subtle.digest('SHA-256',await f.arrayBuffer()))].map(v=>v.toString(16).padStart(2,'0')).join('')}})()""")
        assert actual == {'name': name, 'size': len(original), 'sha256': hashlib.sha256(original).hexdigest()}, actual
        baseline = native._launcher_bytes
        q.js("const i=document.createElement('input');i.type='file';i.multiple=true;i.id='bounds-new';document.body.append(i);true")
        q.window.file_selection_for_test = [str(source), str(bad)]
        q.window.view.command('eval', script="document.getElementById('bounds-new').click();true", world=0, gesture=True)
        deadline = time.monotonic() + 15
        while not warnings and time.monotonic() < deadline: q.delay(.05)
        assert warnings and 'shorter --data-root or filename' in warnings[-1]
        assert q.js("document.getElementById('bounds-new').files.length") == 0
        assert q.js("document.querySelector('input[name=file]').files.length") == 1
        assert store.snapshots == [snapshot] and native._launcher_bytes == baseline
        assert snapshot.path.read_bytes() == original
        assert not q.window.view._pending_file_selections
        report.update(passed=True, private_path_utf16=239, actual_file=actual, refused_new_path_utf16=240,
                      whole_new_batch_refused=True, previous_file_and_quota_preserved=True, warnings=warnings)
    finally:
        fs._warning = original_warning; q.close(); q.delay(.2)
        report['close_complete'] = q.window._close_complete
        report['cleanup'] = {'store_closed': store.closed, 'root_removed': not store.path.exists(), 'errors': store.cleanup_errors} if store else None
        (q.paths['root'] / 'wv-snapshot-bound.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2), flush=True)
    assert report['passed'] and report['close_complete'] and report['cleanup']['root_removed'] and not report['cleanup']['errors']


if __name__ == '__main__': main()

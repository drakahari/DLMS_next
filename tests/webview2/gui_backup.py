"""Actual native WebView2 backup export; synthetic source instrumentation only."""
import argparse
import hashlib
import json
import time
import zipfile


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--profile', required=True)
    p.add_argument('--attempt', type=int, required=True)
    a = p.parse_args()
    if not 1 <= a.attempt <= 99:
        raise ValueError('Use a bounded fresh evidence identity')
    import package_windows_webview2
    package_windows_webview2.ACTIVE = True
    from desktop.webview2_shell import DesktopWindow
    import desktop.shell
    desktop.shell.DesktopWindow = DesktopWindow
    from tests.gate1.qt_checks import QtChecks
    from tests.settings.gui_native_roundtrip import facts
    q = QtChecks(a.profile, automated=True)
    original = q.window._choose_backup_destination
    report = {'source_instrumented': True, 'normal_package': False}
    try:
        before = facts(q.paths['backend'])
        assert all(before['rows'][key] for key in ('quizzes', 'questions', 'choices', 'study_responses', 'attempts'))
        oracle = q.paths['root'] / 'backup-facts.json'
        if oracle.exists():
            assert json.loads(oracle.read_text(encoding='utf-8')) == before
        else:
            oracle.write_text(json.dumps(before, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        from desktop.isolation import PROJECT
        output = PROJECT / '.gate1/windows-native' / (a.profile + f'-rich-backup-{a.attempt:02} 日本語')
        output.mkdir(mode=0o700, exist_ok=False)
        archive = output / 'synthetic rich backup.zip'
        q.go('/settings/backup')
        deadline = time.monotonic() + 20
        while not q.window._settings_ready('backup') and time.monotonic() < deadline:
            q.delay(.05)
        assert q.window._settings_ready('backup')
        q.window._choose_backup_destination = lambda: (str(archive), '')
        q.window.settings_buttons['create_backup'].click()
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            q.delay(.1)
            if not q.window._backup_creating and q.window._settings_ready('backup'):
                break
        assert archive.is_file(), q.window.statusBar().currentMessage()
        assert 'Backup saved:' in q.window.statusBar().currentMessage()
        assert not q.window._backup_creating and q.window._settings_ready('backup')
        with zipfile.ZipFile(archive) as bundle:
            assert bundle.testzip() is None
        assert facts(q.paths['backend']) == before
        report.update(passed=True, archive=str(archive), oracle=str(oracle),
                      sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
                      row_counts={key: len(value) for key, value in before['rows'].items()},
                      source_unchanged=True)
    finally:
        q.window._choose_backup_destination = original
        q.close()
        q.delay(.3)
        report['close_complete'] = q.window._close_complete
        with (q.paths['root'] / f'wv-backup-export-{a.attempt:02}.json').open('x') as stream:
            stream.write(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2), flush=True)
    assert report.get('passed') and report['close_complete']


if __name__ == '__main__':
    main()

"""Source optional trace compatibility; no physical/rendered-pixel acceptance."""
import argparse
import json
import sys
import time


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--profile', required=True); args = parser.parse_args()
    import package_windows_webview2
    package_windows_webview2.ACTIVE = True
    from desktop.webview2_shell import DesktopWindow
    import desktop.shell
    desktop.shell.DesktopWindow = DesktopWindow
    from tests.gate1.qt_checks import QtChecks
    from desktop.window_events import WindowEvents
    import PySide6
    q = QtChecks(args.profile, automated=True)
    report = {'source_instrumented': True, 'normal_package': False, 'physical_acceptance': False,
              'python_version': sys.version, 'pyside_version': PySide6.__version__, 'passed': False}
    capture = None
    try:
        capture = WindowEvents(q.window); q.window.window_events = capture; capture.bind(q.window.view)
        capture.sample(); q.delay(2.3); capture.stop()
        rows = [json.loads(line) for line in capture.path.read_text().splitlines()]
        samples = [row for row in rows if row['event'] == 'sample']
        states = [row for row in rows if row['event'] == 'document-state']
        assert samples and all(row['renderer'] == 0 and row['lifecycle'] == -1 for row in samples)
        assert states and any(row['ready'] == 'complete' for row in states)
        assert rows[-1]['event'] == 'capture-stop'
        report.update(passed=True, trace=str(capture.path), sample_count=len(samples), document_state_count=len(states),
                      renderer_pid_unavailable=0, qt_lifecycle_unknown=-1)
    finally:
        if capture is not None: capture.stop()
        q.close(); q.delay(.2); report['close_complete'] = q.window._close_complete
        (q.paths['root'] / 'wv-optional-trace.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2), flush=True)
    assert report['passed'] and report['close_complete']


if __name__ == '__main__': main()

"""Pre-log test-entry refusals must not crash again writing windowed stderr."""
import io

import pytest
from package_windows_webview2 import entry_instrumented as entry


@pytest.mark.parametrize('stream', [None, 'broken', 'closed'])
def test_prelog_refusal_has_single_plain_message_without_changing_permissions(monkeypatch, stream):
    class Broken:
        def write(self, value): raise OSError(22, 'Invalid argument')
    if stream == 'broken': stream = Broken()
    elif stream == 'closed':
        stream = io.StringIO(); stream.close()
    monkeypatch.setattr(entry.sys, 'stderr', stream)
    notices = []
    entry._report_error(ValueError('Windows object permits another account access'), notify=notices.append)
    assert len(notices) == 1 and 'separate instrumented test' in notices[0]
    assert 'ValueError' in notices[0] and 'another account access' in notices[0]
    assert 'Traceback' not in notices[0]


def test_private_log_records_original_error_without_extra_dialog(monkeypatch):
    stream = io.StringIO()
    monkeypatch.setattr(entry.sys, 'stderr', stream)
    notices = []
    try: raise ValueError('synthetic setup refusal')
    except ValueError as error: entry._report_error(error, notify=notices.append)
    assert 'synthetic setup refusal' in stream.getvalue() and not notices

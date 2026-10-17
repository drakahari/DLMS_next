"""Qualified239-UTF16 candidate limit and private staging publication safeguards."""
import os
from pathlib import Path
import re

import pytest

from desktop.webview2_paths import BrowserPathError, require_browser_path


@pytest.fixture(scope='module', autouse=True)
def application():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def units(value): return len(str(value).encode('utf-16-le')) // 2


def test_full_dos_path_boundary_counts_astral_unicode_as_two_units():
    exact = 'C:\\' + 'a' * 234 + '😀'
    assert units(exact) == 239 and len(exact) == 238
    require_browser_path(exact, 'Test staging')
    with pytest.raises(BrowserPathError, match='shorter --data-root or filename'):
        require_browser_path(exact + 'b', 'Test staging')


@pytest.mark.parametrize('path', ['relative.txt', r'\\server\share\file.txt', r'\\?\C:\file.txt', r'C:\safe\..\file.txt'])
def test_path_boundary_requires_unambiguous_local_drive_spelling(path):
    with pytest.raises(BrowserPathError): require_browser_path(path, 'Test staging')


def private_parent(tmp_path, wanted):
    amount = wanted - units(tmp_path) - 1
    assert 1 <= amount <= 255, 'Use a short, fresh project-local pytest basetemp'
    path = tmp_path / ('é' * amount)
    path.mkdir(mode=0o700)
    assert units(path) == wanted
    return path


@pytest.mark.skipif(os.name != 'nt', reason='Native private publication')
def test_download_exact239_private_path_publishes_uncapped_native_final(tmp_path, monkeypatch):
    from tests.webview2.test_browser_adapter import request
    import desktop.webview2_browser as browser
    sizes = []; original = browser.secrets.token_hex
    monkeypatch.setattr(browser.secrets, 'token_hex', lambda amount: sizes.append(amount) or original(amount))
    parent = private_parent(tmp_path, 197)
    view, download = request(); download.setDownloadFileName('final-' + 'z' * 42 + '.txt')
    download.setDownloadDirectory(str(parent)); download.accept()
    partial = Path(view.commands[-1][1]['path'])
    assert units(partial) == 239 and re.fullmatch(r'\.wv-[0-9a-f]{32}\.part', partial.name)
    assert sizes == [16]  #128random bits survive Windows filename case-folding.
    payload = b'Exact synthetic download bytes\r\n'
    partial.write_bytes(payload); download.finish('completed')
    target = parent / download.downloadFileName()
    assert units(target) > 239 and target.read_bytes() == payload
    assert download.state() == download.DownloadState.DownloadCompleted and not partial.exists()


@pytest.mark.skipif(os.name != 'nt', reason='Native private publication')
def test_download240_refused_before_sdk_accept_no_late_publication_or_held_pins(tmp_path):
    from tests.webview2.test_browser_adapter import request
    parent = private_parent(tmp_path, 198)
    view, download = request(); download.setDownloadDirectory(str(parent)); download.accept()
    assert download.state() == download.DownloadState.DownloadInterrupted
    assert 'shorter --data-root or filename' in download.interruptReasonString()
    assert not any(values.get('action') == 'accept' for op, values in view.commands)
    assert download._pins is None and not download._native_pending
    download.finish('completed')
    assert download.state() == download.DownloadState.DownloadInterrupted and list(parent.iterdir()) == []
    parent.rename(tmp_path / 'refused-download-unpinned')


@pytest.mark.skipif(os.name != 'nt', reason='Native private PDF publication')
def test_print_exact239_private_path_preserves_no_replace_publication(tmp_path, monkeypatch):
    from tests.webview2.test_browser_adapter import PrintView
    from desktop.webview2_browser import View
    parent = private_parent(tmp_path, 197); target = parent / ('final-' + 'z' * 42 + '.pdf')
    view = PrintView(); View.printToPdf(view, target)
    partial = Path(view.commands[-1][1]['path'])
    assert units(partial) == 239 and re.fullmatch(r'\.p-[0-9a-f]{32}', partial.parent.name) and partial.name == 'p.pdf'
    payload = b'%PDF-1.7\nSynthetic PDF bytes\n%%EOF\n'; partial.write_bytes(payload)
    View._event(view, {'event': 'print-finished', 'path': str(partial), 'ok': True})
    assert view.results == [(str(target), True)] and units(target) > 239 and target.read_bytes() == payload


@pytest.mark.skipif(os.name != 'nt', reason='Native private PDF publication')
def test_print240_refused_before_native_write_and_before_creating_staging_job(tmp_path):
    from tests.webview2.test_browser_adapter import PrintView
    from desktop.webview2_browser import View
    parent = private_parent(tmp_path, 198); target = parent / 'final.pdf'
    view = PrintView(); View.printToPdf(view, target)
    assert view.commands == [] and view._prints == {} and view.results == [(str(target), False)]
    assert 'shorter --data-root or filename' in view.notices[-1]
    assert list(parent.iterdir()) == []
    parent.rename(tmp_path / 'refused-print-unpinned')

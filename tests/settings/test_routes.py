"""Exact route authorization for Qt-owned Settings controls."""
from PySide6.QtCore import QUrl

from desktop.shell import managed_settings_page


def test_only_recorded_settings_documents_are_eligible():
    port = 47123
    allowed = {
        "/settings/backup": "backup",
        "/settings/backup?storage=1": "backup",
        "/settings/backup?storage=1#storage-health": "backup",
        "/settings/reset-remove": "reset-remove",
    }
    for path, kind in allowed.items():
        assert managed_settings_page(QUrl(f"http://127.0.0.1:{port}{path}"), port) == kind
    for url in (
        f"http://127.0.0.1:{port}/settings/backup/anything",
        f"http://127.0.0.1:{port}/settings/backup?storage=2",
        f"http://127.0.0.1:{port}/settings/backup?storage=1&action=remove",
        f"http://127.0.0.1:{port}/settings/reset-remove#remove",
        f"http://127.0.0.1:{port}/settings/reset-remove?x=1",
        f"http://127.0.0.1:{port}/not-settings/backup",
        f"http://127.0.0.1:{port+1}/settings/backup",
        f"http://localhost:{port}/settings/backup",
        f"http://user@127.0.0.1:{port}/settings/backup",
        "https://example.org/settings/backup",
        "data:text/html,<title>Backup & Restore</title>",
    ):
        assert managed_settings_page(QUrl(url), port) is None, url

"""Narrow mode-configuration and exact-origin security regressions."""
from __future__ import annotations

import json
import os

import pytest
from PySide6.QtCore import QUrl

from desktop import server_mode
from desktop.server_browser import exact_server_origin


@pytest.mark.parametrize("raw,consent", [
    ("http://192.168.50.10:9001/", False),
    ("http://example.org/", True),
    ("http://127.0.0.1:0/", True),
    ("https://user:pass@example.org/", False),
    ("file:///tmp/quiz", False),
    ("https://example.org/dlms", False),
    ("https://example.org/?next=evil", False),
    ("https://example.org/#fragment", False),
    ("https://example.org\\@evil.test/", False),
])
def test_unsafe_or_unapproved_endpoints_are_refused(raw, consent):
    with pytest.raises(ValueError):
        server_mode.canonical_endpoint(raw, private_http_opt_in=consent)


def test_exact_origin_and_explicit_private_http():
    assert server_mode.canonical_endpoint("HTTPS://EXAMPLE.ORG/", private_http_opt_in=False) == "https://example.org:443"
    assert server_mode.canonical_endpoint("http://127.0.0.2:9123/", private_http_opt_in=True) == "http://127.0.0.2:9123"
    origin = "http://127.0.0.2:9123"
    assert exact_server_origin(QUrl(origin + "/study"), origin)
    for target in ("http://127.0.0.1:9123/", "http://127.0.0.2:9124/", "https://127.0.0.2:9123/",
                   "http://127.0.0.2.evil.test:9123/", "file:///tmp/x"):
        assert not exact_server_origin(QUrl(target), origin)


def test_origin_change_rotates_browser_identity_and_invalid_config_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(server_mode, "AREA", tmp_path)
    first = server_mode.default_config("synthetic01")
    first["server"] = server_mode.configured_server(first, "https://example.org/", "One", private_http_opt_in=False)
    server_mode.write_config("synthetic01", first)
    assert server_mode.read_config("synthetic01") == first
    same = server_mode.configured_server(first, "https://example.org:443/", "Renamed", private_http_opt_in=False)
    changed = server_mode.configured_server(first, "https://example.net/", "Other", private_http_opt_in=False)
    assert same["id"] == first["server"]["id"]
    assert changed["id"] != first["server"]["id"]
    roots = server_mode.server_root(first["server"]["id"]), server_mode.server_root(changed["id"])
    assert roots[0]["storage"] != roots[1]["storage"]
    config = server_mode.shell_root("synthetic01") / "mode.json"
    config.write_text(json.dumps(dict(first, mode="server", server=None)))
    with pytest.raises(ValueError, match="needs inspection"):
        server_mode.read_config("synthetic01")


def test_server_storage_refuses_world_readable_existing_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(server_mode, "AREA", tmp_path)
    identity = "4f985421-2cb4-497e-a030-573b12eed781"
    folders = server_mode.server_root(identity)
    if os.name == "nt":
        import subprocess
        # chmod does not change a Windows DACL. Grant read access only to this
        # disposable directory, assert refusal, then remove that exact ACE.
        path = str(folders["storage"])
        subprocess.run(["icacls", path, "/grant", "*S-1-1-0:(R)"], check=True, capture_output=True)
        try:
            with pytest.raises(ValueError, match="another account"):
                server_mode.server_root(identity)
        finally:
            subprocess.run(["icacls", path, "/remove:g", "*S-1-1-0"], check=True, capture_output=True)
        return
    folders["storage"].chmod(0o755)
    try:
        with pytest.raises(ValueError, match="not private"):
            server_mode.server_root(identity)
    finally:
        folders["storage"].chmod(0o700)

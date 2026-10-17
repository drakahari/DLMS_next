"""The recovery-only Local service retains WebView2 policy and exact authority."""
from types import SimpleNamespace

import pytest

from desktop import maintenance
from desktop import webview2_runtime


@pytest.mark.parametrize("active", [False, True])
@pytest.mark.parametrize("path,authorized,status", [
    ("/_desktop/ready", True, "200 OK"),
    ("/_desktop/maintenance", True, "200 OK"),
    ("/_desktop/ready", False, "403 Forbidden"),
    ("/library", True, "403 Forbidden"),
])
def test_transition_service_applies_required_policy_before_every_response(monkeypatch, active, path, authorized, status):
    import waitress
    captured = {}
    marker = {"phase": "browser_check_pending", "profile_uuid": "synthetic-uuid", "epoch": "synthetic-epoch"}
    monkeypatch.setattr(maintenance, "read_marker", lambda name: marker)
    monkeypatch.setattr(maintenance, "read_manifest", lambda *a: {"uuid": "synthetic-uuid", "epoch": "synthetic-epoch"})
    monkeypatch.setattr(webview2_runtime, "worker_active", lambda: active)
    def server(wsgi, **kwargs):
        captured["wsgi"] = wsgi
        return SimpleNamespace(run=lambda: None)
    monkeypatch.setattr(waitress, "create_server", server)
    maintenance.serve_transition({}, "synthetic", object(), 43171, "n" * 64)
    response = {}
    def start(code, headers, exc_info=None): response.update(status=code, headers=headers)
    environ = {"PATH_INFO": path, "HTTP_HOST": "127.0.0.1:43171", "wsgi.url_scheme": "http",
        "REQUEST_METHOD": "GET", "HTTP_ORIGIN": "http://127.0.0.1:43171",
        "HTTP_X_DLMS_DESKTOP_NONCE": "n" * 64,
        "HTTP_X_DLMS_DESKTOP_TOKEN": "n" * 64 if authorized else "wrong"}
    body = b"".join(captured["wsgi"](environ, start))
    assert response["status"] == status
    policies = [value for key, value in response["headers"] if key.lower() == "content-security-policy"]
    assert (webview2_runtime.LOCAL_CONTENT_POLICY in policies) is active
    if path == "/_desktop/maintenance" and authorized:
        assert "default-src 'none'; style-src 'unsafe-inline'" in policies
        assert b"Finishing profile maintenance" in body and b"Quiz Library" not in body
    if status.startswith("403"): assert body == b""
    if active: assert ("Referrer-Policy", "same-origin") in response["headers"]

"""CSRF errors honor browser and API content negotiation."""

import pytest

from tests._isolation import ensure_test_data_isolation

ensure_test_data_isolation()
import app as dlms


@pytest.mark.parametrize("path,method,accept,body_kind,expected", [
    ("/library", "GET", "text/html", None, "text/html"),
    ("/library", "POST", "text/html", "form", "text/html"),
    ("/api/example", "POST", "text/html", "form", "application/json"),
    ("/library", "POST", "text/html", "json", "application/json"),
    ("/library", "GET", "application/json", None, "application/json"),
    ("/library", "GET", "application/json, text/html", None, "text/html"),
    ("/library", "GET", "text/html, application/json", None, "text/html"),
    ("/library", "GET", "*/*", None, "text/html"),
    ("/library", "GET", "text/html;q=0.8, application/json;q=0.9", None, "application/json"),
])
def test_csrf_error_response_prefers_html_on_accept_ties(
    path, method, accept, body_kind, expected
):
    kwargs = {"path": path, "method": method, "headers": {"Accept": accept}}
    if body_kind == "form":
        kwargs["data"] = {"name": "example"}
    elif body_kind == "json":
        kwargs["json"] = {"name": "example"}
    with dlms.app.test_request_context(**kwargs):
        response = dlms.app.make_response(dlms.handle_csrf_error(None))
    assert response.status_code == 400
    assert response.mimetype == expected

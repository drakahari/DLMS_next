def csrf_token(client, path="/"):
    response = client.get(path)
    if response.status_code >= 400:
        raise AssertionError(f"Could not initialize CSRF session from {path}: {response.status_code}")
    cookie = client.get_cookie("dlms_csrf_token")
    if cookie is None:
        raise AssertionError(f"No CSRF cookie was delivered by {path}")
    return cookie.value


def csrf_headers(client, path="/"):
    return {"X-CSRFToken": csrf_token(client, path)}

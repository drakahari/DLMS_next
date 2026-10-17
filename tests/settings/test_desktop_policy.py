"""The local Qt adapter must preserve every effective source restriction."""
from desktop.policy import local_webengine_policy


SOURCE = "camera=(), geolocation=(), microphone=(), payment=(), usb=()"


def test_pinned_engine_omits_only_unrecognized_features():
    headers = [("Content-Security-Policy", "default-src 'self'"),
               ("Permissions-Policy", SOURCE), ("X-Frame-Options", "DENY")]
    changed = local_webengine_policy(headers, qt="6.11.2", webengine="6.11.2",
                                     chromium="140.0.7339.225")
    assert changed == [("Content-Security-Policy", "default-src 'self'"),
                       ("Permissions-Policy", "camera=(), geolocation=(), microphone=()"),
                       ("X-Frame-Options", "DENY")]
    assert headers[1][1] == SOURCE


def test_other_engine_and_nonempty_directives_are_unchanged():
    headers = [("Permissions-Policy", "camera=(), payment=(self), usb=(), geolocation=()")]
    assert local_webengine_policy(headers, qt="6.11.3", webengine="6.11.2", chromium="140.0.7339.225") is headers
    assert local_webengine_policy(headers, qt="6.11.2", webengine="6.11.3", chromium="140.0.7339.225") is headers
    assert local_webengine_policy(headers, qt="6.11.2", webengine="6.11.2", chromium="141.0.0.0") is headers
    assert local_webengine_policy(headers, qt="6.11.2", webengine="6.11.2", chromium="140.0.7339.225") == [
        ("Permissions-Policy", "camera=(), payment=(self), geolocation=()")]

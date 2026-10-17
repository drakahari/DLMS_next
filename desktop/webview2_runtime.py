"""Windows renderer selection; never selects a renderer from page content."""
import os
import sys
import re

MIN_RUNTIME_VERSION = '155.0.4283.45'


def canonical_blob_download(value, origin):
    """Download-only spelling; never grants blob navigation or native authority."""
    if not isinstance(value, str) or not isinstance(origin, str): return False
    prefix = 'blob:' + origin + '/'
    return (value.startswith(prefix) and re.fullmatch(
        r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
        value[len(prefix):]) is not None)


def compatible_runtime(value):
    if not isinstance(value, str) or re.fullmatch(r'[0-9]{1,5}\.[0-9]{1,5}\.[0-9]{1,5}\.[0-9]{1,5}', value) is None:
        return False
    parts=tuple(map(int,value.split('.')))
    return all(part<=65535 for part in parts) and parts >= tuple(map(int,MIN_RUNTIME_VERSION.split('.')))

# Local UI has no child documents or workers. Deny their execution before
# requests can acquire the owned backend credential, including opaque srcdoc
# and sandbox documents. This is an additional policy, never a replacement for
# the captured application's CSP. This middleware applies only to Local;
# the separate browser-private worker policy also restricts Server documents.
LOCAL_CONTENT_POLICY = "frame-src 'none'; child-src 'none'; worker-src 'none'; object-src 'none'"


def local_response_policy(start_response):
    def protected_response(status, headers, exc_info=None):
        # no-referrer makes ordinary POST navigations send Origin:null. Keep
        # rejecting opaque origins instead of guessing their initiator. The
        # owned Local browser permits only its exact origin, so same-origin
        # discloses no referrer to another endpoint. Server headers are untouched.
        scoped=[(key,value) for key,value in headers if key.lower()!='referrer-policy']
        return start_response(status, [*scoped, ('Referrer-Policy','same-origin'),
                                     ('Content-Security-Policy', LOCAL_CONTENT_POLICY)], exc_info)
    return protected_response


def active():
    package=sys.modules.get('package_windows_webview2')
    return os.name=='nt' and getattr(package,'ACTIVE',False) is True


def worker_active():
    # This flag only selects stricter response policies. The
    # authenticated existing worker bootstrap remains the process authority.
    return os.name=='nt' and (active() or os.environ.get('DLMS_WINDOWS_WEBVIEW2_POLICY')=='1')


def configure_backend_stdio(streams=None):
    """Encode this Windows worker's logs without changing locale or data formats."""
    if not worker_active(): return
    for stream in (sys.stdout, sys.stderr) if streams is None else streams:
        configure = getattr(stream, 'reconfigure', None)
        if callable(configure): configure(encoding='utf-8', errors='backslashreplace')

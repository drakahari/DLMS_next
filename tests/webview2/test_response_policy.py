"""Additional Local policy composes with the captured CSP, without rewriting it."""
from desktop.webview2_runtime import LOCAL_CONTENT_POLICY, local_response_policy
from desktop.webview2_runtime import compatible_runtime
import pytest


@pytest.mark.parametrize('version,expected',[
    ('155.0.4283.45',True),('155.0.4283.60',True),('156.0.0.1',True),
    ('155.0.4283.44',False),('154.0.9999.99',False),('',False),
    ('155.0.4283.45 beta',False),('155',False),(None,False)])
def test_supported_runtime_floor(version,expected):
    assert compatible_runtime(version) is expected


def test_additional_policy_preserves_headers_status_and_exception():
    calls=[]
    def response(*args):calls.append(args);return 'writer'
    headers=[('Content-Security-Policy',"default-src 'self'"),('Permissions-Policy','usb=(), payment=()'),
             ('Referrer-Policy','no-referrer')]
    marker=object()
    assert local_response_policy(response)('422 Unprocessable Content',headers,marker)=='writer'
    assert calls==[('422 Unprocessable Content',headers[:2]+[('Referrer-Policy','same-origin'),('Content-Security-Policy',LOCAL_CONTENT_POLICY)],marker)]
    assert len(headers)==3


def test_policy_denies_all_child_execution_categories():
    assert dict(item.strip().split(' ',1) for item in LOCAL_CONTENT_POLICY.split(';'))=={
        'frame-src':"'none'",'child-src':"'none'",'worker-src':"'none'",'object-src':"'none'"}


@pytest.mark.parametrize('suffix', [
    '12345678-1234-1234-1234-123456789abc',
    '00000000-0000-0000-0000-000000000000',
])
def test_canonical_blob_download_spelling(suffix):
    from desktop.webview2_runtime import canonical_blob_download
    for origin in ('http://127.0.0.1:42424', 'https://synthetic.invalid', 'https://[::1]:9443'):
        assert canonical_blob_download('blob:' + origin + '/' + suffix, origin)


@pytest.mark.parametrize('value', [
    'blob:null/12345678-1234-1234-1234-123456789abc',
    'blob:https://foreign.invalid/12345678-1234-1234-1234-123456789abc',
    'blob:https://synthetic.invalid.evil/12345678-1234-1234-1234-123456789abc',
    'blob:https://synthetic.invalid:443/12345678-1234-1234-1234-123456789abc',
    'blob:https://synthetic.invalid/12345678-1234-1234-1234-123456789abc#x',
    'blob:https://synthetic.invalid/12345678-1234-1234-1234-123456789abc?x',
    'blob:https://synthetic.invalid/12345678-1234-1234-1234-123456789ABC',
    'blob:https://synthetic.invalid/%31%32%33',
    'blob:https://synthetic.invalid/../settings/backup/create',
    'data:text/plain,synthetic', 'https://synthetic.invalid/export', '', None,
])
def test_blob_download_refuses_opaque_foreign_and_ambiguous_values(value):
    from desktop.webview2_runtime import canonical_blob_download
    assert not canonical_blob_download(value, 'https://synthetic.invalid')


@pytest.mark.parametrize('selected', [False, True])
def test_unicode_logging_is_scoped_to_windows_webview2_worker(monkeypatch, selected):
    import io
    from desktop import webview2_runtime as runtime
    monkeypatch.setattr(runtime, 'worker_active', lambda: selected)
    output = io.BytesIO()
    with io.TextIOWrapper(output, encoding='cp1252') as stream:
        runtime.configure_backend_stdio((stream, None))
        if selected:
            stream.write('Uploaded logo → 日本語\ud800')
            stream.flush()
            assert output.getvalue() == 'Uploaded logo → 日本語\\ud800'.encode('utf-8')
        else:
            assert stream.encoding == 'cp1252'
            with pytest.raises(UnicodeEncodeError): stream.write('Uploaded logo → 日本語')

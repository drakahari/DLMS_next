"""Ephemeral action metadata from the owned Local producer, never remote DOM.

Only the Windows WebView2 backend installs this hook. It changes response headers
for supported HTML producers, not captured HTML/scripts, data or save semantics.
The request tag correlates a native main-document request, not a web capability.
"""
from __future__ import annotations

import base64
import ipaddress
import json
import re
from urllib.parse import urlsplit

HEADER = 'X-DLMS-AI-Contract'
REQUEST_HEADER = 'X-DLMS-AI-Document'
PROVIDERS = {'chatgpt':'https://chatgpt.com/', 'claude':'https://claude.ai/',
             'gemini':'https://gemini.google.com/'}
TAG = re.compile(r'[0-9a-f]{32}\Z')


def supported_path(path):
    return (path in ('/review', '/review.html', '/study-packs/ai-builder',
                     '/law/create', '/certifications/matches')
            or re.fullmatch(r'/certifications/[0-9a-f]{32}/ai', path) is not None
            or re.fullmatch(r'/quizzes/[^/\\?#\x00-\x1f]+\.html', path) is not None)


def provider_url(provider, config):
    value = (config.get('ai_custom_url', '') if provider == 'local'
             else PROVIDERS.get(provider, ''))
    if not isinstance(value, str) or not value or len(value.encode('utf-8')) > 8192:
        return None
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value) or '\\' in value:
        return None
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or '').lower().rstrip('.')
        if (parsed.scheme not in ('http', 'https') or not host or parsed.username
                or parsed.password or host == 'localhost' or host.endswith('.localhost')):
            return None
        _ = parsed.port
        try:
            if ipaddress.ip_address(host).is_loopback:return None
        except ValueError:pass
    except ValueError:return None
    # Configured URLs are already validated/normalized by the captured producer.
    # Built-ins are fixed. Unusual spelling can fall back to native confirmation.
    return value


def contract(path, method, form, config, tag):
    if (not isinstance(path, str) or not supported_path(path) or not isinstance(tag, str)
            or not TAG.fullmatch(tag) or not isinstance(config, dict)):
        return None
    provider = str(config.get('ai_provider') or 'chatgpt').strip().lower()
    if path in ('/law/create', '/study-packs/ai-builder'):
        if method != 'POST':return None
        if path == '/law/create':provider = str(form.get('ai_provider', 'chatgpt')).strip().lower()
        else:
            if provider not in (*PROVIDERS, 'local'):provider='chatgpt'
            provider = str(form.get('ai_provider') or provider).strip().lower()
            if provider not in (*PROVIDERS, 'local'):provider='chatgpt'
        actions = ['law-prompt' if path == '/law/create' else 'study-pack']
    else:
        if config.get('ai_helper_enabled') is not True:return None
        if path.startswith('/quizzes/'):actions=['study-review']
        elif path in ('/review', '/review.html'):actions=['review-single', 'review-selected']
        else:actions=['cert-combined', 'cert-manual']
    target = provider_url(provider, config)
    if not target:return None
    value = {'version':1, 'path':path, 'request':tag,
             'actions':{action:target for action in actions}}
    encoded = base64.b64encode(json.dumps(value, ensure_ascii=True,
        separators=(',', ':')).encode('ascii')).decode('ascii')
    return encoded if len(encoded) <= 24576 else None


def install(application, read_config):
    from flask import request
    @application.after_request
    def annotate(response):
        response.headers.pop(HEADER, None)
        if (response.status_code not in (200, 304) or not supported_path(request.path)
                or (response.status_code != 304 and response.mimetype != 'text/html')):
            return response
        tag = request.headers.get(REQUEST_HEADER, '')
        if not TAG.fullmatch(tag):return response
        try:
            value = contract(request.path, request.method, request.form, read_config(), tag)
        except (OSError, ValueError, TypeError, AttributeError):
            value = None  # Optional direct classification fails closed.
        if value:response.headers[HEADER] = value
        return response

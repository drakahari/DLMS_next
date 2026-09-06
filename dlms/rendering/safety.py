"""Escaping helpers for DLMS-generated markup."""

import html
import json


def _html_text(value):
    """Encode plain text for insertion into generated HTML text content."""
    return html.escape(str(value or ""), quote=False)


def _html_attribute(value):
    """Encode a value for a quoted generated-HTML attribute."""
    return html.escape(str(value or ""), quote=True)


def _json_for_inline_script(value):
    """Serialize data without allowing it to terminate an inline script element."""
    serialized = json.dumps(value, ensure_ascii=False)
    return (
        serialized
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )

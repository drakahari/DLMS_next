"""Candidate-supported browser path bound; native publication checks are separate."""
from pathlib import PureWindowsPath

MAX_BROWSER_PATH_UTF16 = 239


class BrowserPathError(ValueError):
    pass


def require_browser_path(path, operation):
    """Count the full DOS path as UTF16, including astral surrogate pairs."""
    value = PureWindowsPath(str(path))
    if not value.is_absolute() or len(value.drive) != 2 or '..' in value.parts:
        raise BrowserPathError('WebView2 requires an absolute local Windows drive path.')
    try:
        length = len(str(value).encode('utf-16-le')) // 2
    except UnicodeEncodeError as exc:
        raise BrowserPathError('The Windows path contains an invalid Unicode character.') from exc
    if length > MAX_BROWSER_PATH_UTF16:
        raise BrowserPathError(f'{operation} path exceeds this candidate\'s supported WebView2 limit ({MAX_BROWSER_PATH_UTF16} UTF-16 code units). '
                               'Use a shorter --data-root or filename, then retry.')

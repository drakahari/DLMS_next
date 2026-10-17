"""LaunchServices handoff using the real user's session, never scoped HOME."""
import os
import subprocess
from urllib.parse import urlsplit
from .macos_paths import real_home


def environment():
    result = {key: value for key, value in os.environ.items()
              if not key.startswith(('DLMS_', 'QUIZAPP_', 'QT', 'XDG_', 'PYTHON', 'DYLD_'))
              and key not in {'TMPDIR', 'TMP', 'TEMP'}}
    result['HOME'] = str(real_home())
    result['PATH'] = '/usr/bin:/bin:/usr/sbin:/sbin'
    return result


def dispatch(url):
    value = url.toString() if hasattr(url, 'toString') else str(url)
    parsed = urlsplit(value)
    if (parsed.scheme not in {'http', 'https'} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError('Only an approved HTTP(S) browser destination may leave Desktop')
    try:
        completed = subprocess.run(['/usr/bin/open', '--', value], env=environment(),
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.PIPE, close_fds=True, timeout=10)
    except subprocess.TimeoutExpired as exc:
        raise OSError('Default-browser handoff timed out; inspect your browser before retrying') from exc
    return completed.returncode == 0

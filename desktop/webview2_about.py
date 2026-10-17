"""Read-only Windows identity, separate from the Linux/Qt metadata contract."""
import json
from pathlib import Path
import platform
import re
import sys

from PySide6.QtCore import qVersion


def information():
    root = Path(sys._MEIPASS) if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1]
    path = root / 'desktop_assets/build-info.json'
    if not getattr(sys, 'frozen', False) and not path.exists():
        return {'application_version': '0.1.0-dev', 'release': 'source-tree',
                'source_commit': 'unpackaged development',
                'target': 'Windows x86-64 WebView2 development',
                'support': 'Private development build; not an installed release.',
                'browser_runtime': 'Installed Microsoft WebView2 Evergreen',
                'backend_version': 'not recorded in this source build'}
    if path.is_symlink() or path.stat().st_size > 32768:
        raise ValueError('Build information is unavailable')
    value = json.loads(path.read_text(encoding='utf-8'))
    required = {'application_version', 'release', 'source_commit', 'target', 'support', 'browser_runtime'}
    if (not isinstance(value, dict) or not required <= set(value)
            or set(value) - required - {'backend_version'}
            or not all(isinstance(x, str) and 0 < len(x) < 512
                       and not any(ord(c) < 32 for c in x) for x in value.values())):
        raise ValueError('Invalid Windows build information')
    return value


def about_text(*, mode, runtime_version):
    value = information()
    # Native, detected identity only. Never display a remote page's supplied
    # version, a user-data path, configured origin, profile name or credentials.
    runtime = runtime_version if (isinstance(runtime_version, str)
        and re.fullmatch(r'[0-9]+(?:\.[0-9]+){3}', runtime_version)) else 'not available'
    backend = value.get('backend_version', 'not recorded in this build')
    text = (f"DLMS Desktop {value['application_version']}\n"
            f"Desktop release: {value['release']}\n"
            f"Desktop source/build: {value['source_commit']}\n"
            f"Target: {value['target']}\n"
            f"Bundled Local DLMS backend: {backend}\n"
            f"Python: {platform.python_version()} ({platform.architecture()[0]})\n"
            f"Qt Widgets: {qVersion()}\n"
            "Rendering host: native C# Microsoft Edge WebView2\n"
            f"Detected WebView2 Runtime: {runtime}\n"
            "Runtime servicing: installed Evergreen Runtime, updated separately\n\n"
            f"Active mode: {'Server' if mode == 'server' else 'Local'}\n")
    if mode == 'server':
        text += 'The Server owns its dataset. Its deployed backend version is not established by this bundled Local build.\n'
    return text + ('Local and Server storage remain separate; switching never copies or synchronizes data.\n\n'
                   + value['support'])

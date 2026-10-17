"""Read-only bundled build identity. Never infer a remote server's version."""
import json
from pathlib import Path
import sys


def information():
    root=Path(sys._MEIPASS) if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1]
    path=root/'desktop_assets/build-info.json'
    if not path.exists():
        return {'application_version':'0.1.0-dev','release':'source-tree','source_commit':'unpackaged development',
                'target':'Fedora 44 x86_64 candidate','support':'Private candidate; other platforms and public distribution unqualified'}
    if path.is_symlink() or path.stat().st_size>32768:raise ValueError('Build information is unavailable')
    value=json.loads(path.read_text())
    if set(value)!={'application_version','release','source_commit','target','support'} or not all(isinstance(x,str) and len(x)<512 for x in value.values()):raise ValueError('Invalid build information')
    return value


def about_text(*,mode,profile,local_origin,server=None):
    value=information()
    import platform
    from PySide6.QtCore import qVersion
    from PySide6.QtWebEngineCore import qWebEngineVersion, qWebEngineChromiumVersion
    text=(f"DLMS Desktop {value['application_version']}\nBundled Local release: {value['release']}\n"
          f"Desktop source/build: {value['source_commit']}\nTarget: {value['target']}\n{value['support']}\n\n")
    text+=f"Python: {platform.python_version()}\nQt: {qVersion()} · Qt WebEngine: {qWebEngineVersion()}\nChromium: {qWebEngineChromiumVersion()}\n\n"
    if mode=='server' and server:
        text+=f"Active mode: Server — {server['label']}\nServer origin: {server['origin']}\nThe server owns this dataset. Its deployed version is not established by the bundled Local build.\n\n"
    else:text+=f"Active mode: Local\nLocal origin: {local_origin or 'backend not started'}\n\n"
    return text+f"Local profile: {profile}\nLocal and Server storage remain separate. Switching never synchronizes or copies data."

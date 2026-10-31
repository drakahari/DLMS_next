"""Read-only bundled build identity. Never infer a remote server's version."""
import json
from pathlib import Path
import sys
import ast


def application_version(root=None):
    """Read canonical metadata without starting the application or opening data."""
    root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    values = [node.value.value for node in ast.parse((root / 'app.py').read_text(encoding='utf-8')).body
              if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'APP_VERSION' for t in node.targets)
              and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)]
    if len(values) != 1:
        raise ValueError('Application version must be one literal')
    return values[0]


def information():
    root=Path(sys._MEIPASS) if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1]
    path=root/'desktop_assets/build-info.json'
    if not path.exists():
        return {'application_version':application_version(root),'release':'source-tree candidate (unpublished)','source_commit':'unpackaged development',
                'target':sys.platform+' source tree','support':'Development source; packaged platform qualification is separate'}
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

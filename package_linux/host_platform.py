"""Keep host configuration/driver consumers with their host implementations.

Opt-in portable Linux packaging boundary, not a runtime library search override.
Qt/WebEngine still requires both SONAMEs; the system loader resolves them normally.
Other fonts, graphics, PDF and OCR dependencies remain unchanged.
"""
from pathlib import Path, PurePosixPath
import json
import re


SONAMES = ('libfontconfig.so.1', 'libgbm.so.1')
MANIFEST = 'host-platform.json'
POLICY = {
    'format': 1,
    'host_sonames': list(SONAMES),
    'resolution': 'ordinary host loader; no distro paths or environment overrides',
    'fontconfig': 'host library reads matching host font rules and system/profile fonts',
    'gbm': 'host library uses host graphics backends alongside host EGL/GL/DRM/drivers',
    'limits': 'Other supporting libraries may be bundled; native resolution still requires qualification',
    'portal': 'No desktop integration; registration warning may remain without a discoverable desktop entry',
}


def platform_library(path):
    """Match only the two normal library names/versioned aliases, not assets."""
    name = PurePosixPath(path).name
    match = re.fullmatch(r'(libfontconfig|libgbm)\.so(?:\.\d+)*', name)
    return match.group(1) if match else None


def prune(binaries, datas):
    removed = []
    def kept(rows):
        result = []
        for row in rows:
            family = platform_library(str(row[0]))
            if family:
                removed.append({'path': str(row[0]), 'type': row[2],
                                'reason': family + ' must use the host configuration/driver implementation'})
            else:
                result.append(row)
        return result
    return kept(binaries), kept(datas), sorted(removed, key=lambda x: x['path'])


def write_manifest(path, removed):
    path = Path(path)
    if path.exists() or path.is_symlink():
        raise FileExistsError('Preserve previous platform-library evidence')
    path.write_text(json.dumps(POLICY | {'removed': removed}, indent=2) + '\n')


def verify_payload(payload):
    payload = Path(payload)
    manifest = payload / '_internal' / 'desktop_assets' / MANIFEST
    if manifest.is_symlink() or not manifest.is_file():
        raise ValueError('Missing regular host-platform manifest')
    value = json.loads(manifest.read_text())
    if any(value.get(key) != expected for key, expected in POLICY.items()):
        raise ValueError('Host-platform policy differs from the reviewed boundary')
    if not isinstance(value.get('removed'), list):
        raise ValueError('Missing platform-library removal inventory')
    for path in payload.rglob('*'):
        if platform_library(path.name) and (path.is_file() or path.is_symlink()):
            raise ValueError('Host platform library was bundled: ' + str(path.relative_to(payload)))
    return value

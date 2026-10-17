"""Pure installation format/path validation; release identities are not paths."""
from __future__ import annotations
import os
from pathlib import Path
import re

FORMAT = 3
NORMAL_FORMAT = 4
APP_ID = 'io.github.drakahari.DLMSDesktop'
SHA = re.compile(r'[0-9a-f]{64}\Z')
RELEASE = re.compile(r'[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z')


def release_id(value):
    if not isinstance(value, str) or len(value) > 64 or not RELEASE.fullmatch(value):
        raise ValueError('Invalid release identifier (lowercase letters/digits/hyphens, maximum 64)')
    return value


def layout(home):
    opt = home / '.local/opt/dlms-desktop'
    data = home / '.local/share/dlms-desktop-pilot'
    return dict(opt=opt, version=opt/'versions/pilot-01', current=opt/'current',
                manifest=opt/'pilot-install.json', launcher=home/'.local/bin/dlms-desktop-pilot',
                entry=home/f'.local/share/applications/{APP_ID}.desktop', data=data,
                marker=data/'.dlms-desktop-installed-pilot.json',
                **{f'icon_{s}': home/f'.local/share/icons/hicolor/{s}x{s}/apps/{APP_ID}.png'
                   for s in (16,24,32,48,64)})


def decode(value, home, *, phases=('complete',)):
    """Return (complete inventory, active, guard); reject unknown format versions."""
    p = layout(home)
    if (not isinstance(value, dict) or value.get('phase') not in phases
            or value.get('home') != str(home)
            or not isinstance(value.get('install_id'), str)
            or not re.fullmatch('[0-9a-f]{32}', value['install_id'])
            or value.get('owned_paths') != {k:str(v) for k,v in p.items()}):
        raise ValueError('Installation manifest identity or phase needs inspection')
    if type(value.get('version')) is not int:
        raise ValueError('Unknown legacy manifest version type')
    if 'manifest_format' in value:
        if type(value['manifest_format']) is not int or value['manifest_format'] not in (FORMAT, NORMAL_FORMAT):
            raise ValueError('Unknown installation manifest format')
        releases = value.get('releases')
        active, guard = release_id(value.get('active_release')), release_id(value.get('guard_release'))
        # Format 3 keeps the reviewed legacy compatibility projection. Fresh
        # format 4 has one real release and must not invent pilot payload copies.
        if value['manifest_format'] == FORMAT:
            legacy = value.get('version_inventories')
            if (value.get('version') != 2 or not isinstance(legacy, dict)
                    or set(legacy) != {'pilot-01','pilot-02'} or not isinstance(releases,dict)
                    or any(releases.get(k) != v for k,v in legacy.items())):
                raise ValueError('Legacy compatibility inventory differs')
        elif (value.get('version') != 2 or value.get('installation_kind') != 'normal'
              or 'version_inventories' in value or not isinstance(releases, dict)):
            raise ValueError('Normal installation inventory differs')
        previous = value.get('previous_release')
        if previous is not None and release_id(previous) not in releases:
            raise ValueError('Unknown previous release')
    elif value.get('version') == 1:
        releases = {'pilot-01': value.get('payload_inventory_sha256')}
        active = guard = 'pilot-01'
    elif value.get('version') == 2:
        releases = value.get('version_inventories')
        if not isinstance(releases,dict) or set(releases) != {'pilot-01','pilot-02'}:
            raise ValueError('Legacy installation inventory differs')
        target = value.get('current_target')
        if target not in {'versions/pilot-01','versions/pilot-02'}:
            raise ValueError('Legacy installation target differs')
        active, guard = target.split('/')[1], 'pilot-02'
    else:
        raise ValueError('Unknown installation manifest format')
    if not isinstance(releases,dict) or not 1 <= len(releases) <= 128:
        raise ValueError('Installation release inventory is missing or exceeds bound')
    for name,digest in releases.items():
        release_id(name)
        if not isinstance(digest,str) or not SHA.fullmatch(digest):
            raise ValueError('Installation inventory digest is malformed')
    if (active not in releases or guard not in releases
            or value.get('current_target') != f'versions/{active}'
            or value.get('payload_inventory_sha256') != releases[active]):
        raise ValueError('Installation active release inventory differs')
    integration = value.get('normal_integration')
    if integration is not None:
        if (not isinstance(integration, dict) or set(integration) != {'format','launcher_sha256','desktop_name'}
                or type(integration.get('format')) is not int or integration['format'] != 1
                or integration.get('desktop_name') != 'DLMS Desktop'
                or not isinstance(integration.get('launcher_sha256'), str)
                or not SHA.fullmatch(integration['launcher_sha256'])):
            raise ValueError('Normal integration identity differs')
    elif value.get('manifest_format') == NORMAL_FORMAT:
        raise ValueError('Normal installation integration is missing')
    return dict(releases),active,guard


def owned_chain(path, home):
    if not path.is_relative_to(home):
        raise ValueError('Installation path escapes its home')
    for part in (path,*path.parents):
        if part.is_symlink() or not part.exists() or part.stat().st_uid != os.getuid():
            raise ValueError(f'Installation path is not plain and owned: {part}')
        if part.stat().st_mode & 0o022:
            raise ValueError(f'Installation path is writable by another user: {part}')
        if part == home:
            break


def validate_paths(value, home):
    releases,active,guard=decode(value,home)
    p=layout(home)
    owned_chain(p['manifest'],home)
    for name in releases:
        leaf=p['opt']/'versions'/name/'DLMS-Desktop'/'DLMS-Desktop'
        owned_chain(leaf,home)
        if not leaf.is_file():
            raise ValueError('Installation executable is not regular')
    if not p['current'].is_symlink() or os.readlink(p['current']) != value['current_target']:
        raise ValueError('Installation pointer and manifest disagree')
    return releases,active,guard

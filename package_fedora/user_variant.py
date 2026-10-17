"""Create a distinct user-modified candidate outside an installation.

This does not bless library compatibility, alter an installed release, bypass
recovery, or authenticate a publisher. The ordinary manager remains authority.
"""
from pathlib import Path
import json
import shutil
import tarfile

from desktop.install_manifest import release_id
from .manual_replace import payload_inventory, COMPATIBILITY
from .install_pilot import paths, sha256


def prepare_variant(home: Path, base: Path, modified: Path, output: Path, release: str, expected_base: str) -> dict:
    if any('..' in path.parts for path in (home,base,modified,output)):raise ValueError('Parent traversal is not allowed in variant paths')
    home=home.absolute();base=base.absolute();modified=modified.absolute();output=output.absolute()
    release_id(release)
    forbidden=(paths(home)['opt'],paths(home)['data'],home/'.local/state/dlms-desktop-management')
    for target in (base,modified,output):
        if any(target.is_relative_to(root) or root.is_relative_to(target) for root in forbidden):raise ValueError('Use separate external copies; installed payload/data/management targets are forbidden')
        for part in (target,*target.parents):
            if part.is_symlink():raise ValueError('Variant path has a symlink parent')
    if base.is_relative_to(modified) or modified.is_relative_to(base) or any(output.is_relative_to(root) or root.is_relative_to(output) for root in (base,modified)):raise ValueError('Variant copies/output must be separate')
    if output.exists():raise FileExistsError('Variant output exists; preserve it')
    if payload_inventory(base)!=expected_base:raise ValueError('Base payload differs from the reviewed inventory')
    payload_inventory(modified)  # Validate complete ownership, regular files/contained links.
    for relative in ('_internal/desktop_assets/install-format.json','_internal/desktop_assets/install-compatibility.json'):
        if (base/relative).read_bytes()!=(modified/relative).read_bytes():raise ValueError('Compatibility metadata cannot be silently changed')
    before=json.loads((base/'_internal/desktop_assets/build-info.json').read_text())
    if release==before['release']:raise ValueError('A user modification needs a distinct release identity')
    output.mkdir(mode=0o700)
    payload=output/'DLMS-Desktop'
    shutil.copytree(modified,payload,symlinks=True)
    payload_inventory(payload)  # Copied links must still resolve inside the new root.
    for path in (payload/'_internal',payload/'_internal/desktop_assets',payload/'_internal/desktop_assets/build-info.json'):
        if path.is_symlink():raise ValueError('Generated build metadata must have a plain owned path')
    info=dict(before,release=release,support='User-modified local candidate; not publisher authenticated or vendor-qualified')
    (payload/'_internal/desktop_assets/build-info.json').write_text(json.dumps(info,indent=2)+'\n')
    candidate={'format':1,'release':release,'target':'fedora44-x86_64','payload_inventory':payload_inventory(payload),'compatibility':COMPATIBILITY,'build':info}
    (output/'candidate.json').write_text(json.dumps(candidate,indent=2)+'\n')
    archive=output/'candidate.tar.zst'
    with tarfile.open(archive,'w:zst') as tar:
        tar.add(payload,arcname='DLMS-Desktop');tar.add(output/'candidate.json',arcname='candidate.json')
    result={'archive':str(archive),'sha256':sha256(archive),'release':release,'base_payload_inventory':expected_base,'payload_inventory':candidate['payload_inventory'],'publisher_authenticated':False,'application_compatibility_tested':False,'next':'Use the ordinary manager update preview/confirmation; never edit installed inventories or locks'}
    (output/'variant-provenance.json').write_text(json.dumps(result,indent=2)+'\n')
    return result

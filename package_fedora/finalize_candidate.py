"""Create owner-facing script and integrity metadata in a fresh build output."""
import argparse
import json
from pathlib import Path
from .install_pilot import inventory
from .manual_replace import COMPATIBILITY
from desktop.install_manifest import release_id


def main():
    p=argparse.ArgumentParser();p.add_argument('--dist',required=True,type=Path)
    p.add_argument('--distribution-root',type=Path);a=p.parse_args()
    dist=a.dist.resolve();payload=dist/'DLMS-Desktop'
    build=json.loads((payload/'_internal/desktop_assets/build-info.json').read_text())
    release_id(build['release'])
    script=payload/'Install-DLMS-Desktop'
    if script.exists() or (dist/'candidate.json').exists():raise FileExistsError('Finalization target already exists; never overwrite candidate')
    if a.distribution_root:
        from .assemble_distribution import verify_materials
        materials = verify_materials(a.distribution_root)
        target=payload/'THIRD-PARTY-NOTICES.txt'
        if target.exists() or target.is_symlink():raise FileExistsError('Notice entry point exists; preserve it')
        if materials['format'] == 2:
            target.write_text('''DLMS Desktop uses Qt/PySide/WebEngine and other third-party libraries.
Application and original badge: MIT; Copyright (c) 2026 Mike Buchanan.
Third-party copyrights and licenses remain applicable; this is not legal certification.

Read the exact-build licenses and redistribution information:
  _internal/notices/distribution/REDISTRIBUTION.md
  _internal/notices/distribution/BUILD_AND_REPLACEMENT.md
  _internal/notices/distribution/SOURCE_MATERIALS.json
  _internal/notices/distribution/upstream-texts/
  _internal/notices/distribution/ubuntu/
  _internal/notices/distribution/wheels/

Qt/PySide use their LGPL route. The separate OCR program includes GPL-bearing
libraries; its applicable terms and corresponding source are supplied separately.
No additional library-modification or reverse-engineering debugging restriction
is imposed. Obtain the matching source companions alongside this preview.
''')
        else:
            target.write_text('''DLMS Desktop uses Qt/PySide and other third-party libraries.
Qt/PySide portions have LGPL/GPL and alternative license paths; preserve their
copyright and license notices. This private candidate is NOT PUBLICLY CLEARED.

Available exact-version texts and source-superset attributions:
  _internal/notices/distribution/upstream-texts/
Technical obligations, missing correspondence and replacement instructions:
  _internal/notices/distribution/technical-records/OBLIGATIONS.md
  _internal/notices/distribution/technical-records/SOURCE_AND_REPLACEMENT.md
Existing wheel/CPython and captured application notices:
  _internal/notices/available-build-texts/
  _internal/notices/source/LICENSE

No additional library-modification or reverse-engineering debugging restriction
is imposed by this package. License elections/source obligations remain open.
''')
    script.write_text('''#!/bin/sh
# Bundled manual manager. No venv, sudo, server start or environment overrides.
case "$0" in */*) manager_parent=${0%/*} ;; *) manager_parent=. ;; esac
manager_dir=$(CDPATH= cd -P "$manager_parent" && pwd) || exit 2
exec "$manager_dir/DLMS-Desktop" --manage "$@"
''');script.chmod(0o755)
    candidate={'format':1,'release':build['release'],'target':'fedora44-x86_64','payload_inventory':inventory(payload),'compatibility':COMPATIBILITY,'build':build}
    (dist/'candidate.json').write_text(json.dumps(candidate,sort_keys=True,indent=2)+'\n')
    print(json.dumps(candidate,indent=2))

if __name__=='__main__':main()

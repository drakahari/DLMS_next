"""Inventory actual ELF imported symbol versions, not wheel tag assumptions."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


def required_versions(text):
    # Marker dependencies such as GLIBC_ABI_GNU2_TLS need not occur on an
    # undefined dynamic symbol. Read the version-needs table, not definitions.
    needs = text.split('Version needs section', 1)
    return sorted(set(re.findall(r'Name:\s+((?:GLIBC|CXXABI)[^\s]+)', needs[1]))) if len(needs) == 2 else []


def inventory(root):
    rows = []
    for path in sorted(Path(root).rglob('*')):
        if path.is_symlink() or not path.is_file():
            continue
        with path.open('rb') as stream:
            if stream.read(4) != b'\x7fELF':
                continue
        versions = subprocess.check_output(['readelf', '-W', '--version-info', str(path)], text=True)
        imports = required_versions(versions)
        dynamic = subprocess.check_output(['readelf', '-d', str(path)], text=True)
        h = hashlib.sha256()
        with path.open('rb') as stream:
            while data := stream.read(1048576):
                h.update(data)
        rows.append(dict(path=path.relative_to(root).as_posix(), sha256=h.hexdigest(),
                         imports=imports,
                         needed=re.findall(r'\(NEEDED\).*?\[([^\]]+)\]', dynamic),
                         search_paths=re.findall(r'\((?:RUNPATH|RPATH)\).*?\[([^\]]+)\]', dynamic)))
    return rows


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--payload', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--require-ubuntu24', action='store_true')
    a = p.parse_args()
    rows = inventory(a.payload.absolute())
    blockers = []
    for row in rows:
        for version in row['imports']:
            match = re.fullmatch(r'GLIBC_(\d+)\.(\d+)(?:\.(\d+))?', version)
            if version == 'GLIBC_ABI_GNU2_TLS' or match and tuple(map(int, match.groups(default='0'))) > (2,39,0):
                blockers.append(dict(path=row['path'], version=version))
    a.output.write_text(json.dumps(dict(ELF_files=len(rows), components=rows,
        Ubuntu24_glibc_import_blockers=blockers,
        limits='Imported-symbol scan; actual loader/Qt/OCR tests still required. GLIBCXX/CXXABI requirements must be checked against shipped libstdc++ where included.'), indent=2)+'\n')
    print(f'{len(rows)} ELF files; {len(blockers)} glibc import blockers for Ubuntu24.04')
    if a.require_ubuntu24 and blockers:
        raise SystemExit(1)


if __name__ == '__main__':
    main()

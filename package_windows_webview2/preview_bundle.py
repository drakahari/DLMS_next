"""Windows-only counterpart of the reviewed Linux unused-Qt exclusions."""
from pathlib import PurePosixPath

from package_fedora.minimal_bundle import FAMILIES, QML

OPTIONAL_PLUGINS = {
    'PySide6/plugins/platforminputcontexts/qtvirtualkeyboardplugin.dll',
    'PySide6/plugins/qmltooling/qmldbg_quick3dprofiler.dll',
}


def exclusion(name):
    path = name.replace('\\', '/').removeprefix('_internal/')
    if path in OPTIONAL_PLUGINS:
        return 'optional plugin for an unused Qt family'
    leaf = PurePosixPath(path).name
    for family in FAMILIES:
        if ((leaf.startswith('Qt6'+family) and leaf.endswith('.dll'))
                or (leaf.startswith('Qt'+family) and leaf.endswith('.pyd'))):
            return family
    for prefix in ('PySide6/qml/', 'PySide6/Qt/qml/'):
        if path.startswith(prefix):
            rest = path[len(prefix):]
            for family, roots in QML.items():
                if any(rest == root or rest.startswith(root + '/') for root in roots):
                    return family
    return None


def prune(binaries, datas):
    import pefile
    removed = [row for row in [*binaries, *datas] if exclusion(row[0])]
    names = {PurePosixPath(row[0].replace('\\', '/')).name.lower() for row in removed}
    kept = [[row for row in rows if not exclusion(row[0])] for rows in (binaries, datas)]
    for name, source, kind in kept[0]:
        if str(source).lower().endswith(('.dll', '.pyd', '.exe')):
            with pefile.PE(source, fast_load=True) as image:
                image.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT'],
                                                         pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT']])
                imports = [entry.dll.decode('ascii').lower() for group in ('DIRECTORY_ENTRY_IMPORT', 'DIRECTORY_ENTRY_DELAY_IMPORT')
                           for entry in getattr(image, group, [])]
            if names.intersection(imports):
                raise ValueError(f'Retained Windows binary requires excluded Qt family: {name}')
    return *kept, [{'path': row[0], 'reason': exclusion(row[0])} for row in removed]

"""Mac packaging exclusions for unused Qt families, with dependency checks.

Keep Qt Quick/QML and WebEngine support. An unreviewed retained consumer of an
excluded family is a packaging error, never a reason to remove more features.
"""
from pathlib import Path, PurePosixPath
import posixpath
import re
import subprocess

from package_fedora.minimal_bundle import FAMILIES, QML

OPTIONAL_PLUGINS = {
    'PySide6/Qt/plugins/platforminputcontexts/libqtvirtualkeyboardplugin.dylib',
    'PySide6/Qt/plugins/qmltooling/libqmldbg_quick3dprofiler.dylib',
}
MACHO_MAGICS = {
    b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf',
    b'\xce\xfa\xed\xfe', b'\xfe\xed\xfa\xce',
    b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca',
    b'\xca\xfe\xba\xbf', b'\xbf\xba\xfe\xca',
}
LOAD_COMMANDS = {
    'LC_LOAD_DYLIB', 'LC_LOAD_WEAK_DYLIB', 'LC_REEXPORT_DYLIB',
    'LC_LAZY_LOAD_DYLIB', 'LC_LOAD_UPWARD_DYLIB',
}


def _normalized(name):
    return str(name).replace('\\', '/').removeprefix('_internal/')


def exclusion(name):
    """Recognize only the reviewed family, binding, plugin and QML paths."""
    path = _normalized(name)
    if path in OPTIONAL_PLUGINS:
        return 'optional plugin for an unused Qt family'
    parts = PurePosixPath(path).parts
    leaf = PurePosixPath(path).name
    for family in FAMILIES:
        if any(part.startswith('Qt' + family) and part.endswith('.framework') for part in parts):
            return family + ' unused framework'
        if leaf.startswith('libQt6' + family) and leaf.endswith('.dylib'):
            return family + ' unused native family'
        if leaf.startswith('Qt' + family) and '.' not in leaf:
            return family + ' unused native framework alias'
        if leaf.startswith('Qt' + family) and re.search(r'\.(?:abi3|cpython-[^.]+)\.so$', leaf):
            return family + ' unused Python binding'
    # Contents/Resources and Contents/Frameworks prefixes appear after BUNDLE.
    for prefix in ('PySide6/Qt/qml/', 'PySide6/qml/'):
        start = path.find(prefix)
        if start < 0 or (start and path[start - 1] != '/'):
            continue
        rest = path[start + len(prefix):]
        for family, roots in QML.items():
            if any(rest == root or rest.startswith(root + '/') for root in roots):
                return family + ' unused QML resource/plugin'
    # BUNDLE may add Contents/Frameworks to an optional plugin's TOC path.
    if any(path.endswith('/' + plugin) for plugin in OPTIONAL_PLUGINS):
        return 'optional plugin for an unused Qt family'
    return None


def needed(source):
    """Return actual Mach-O load-command edges, excluding LC_ID_DYLIB.

    Weak, re-export and upward imports matter too. A dylib's own install name
    in ``otool -L`` is not a dependency, so parse load commands instead.
    """
    source = Path(source)
    if not source.is_file():
        raise FileNotFoundError(source)
    with source.open('rb') as stream:
        if stream.read(4) not in MACHO_MAGICS:
            return []
    result = subprocess.run(['/usr/bin/otool', '-l', str(source)],
                            capture_output=True, text=True, check=True)
    command = None
    dependencies = []
    for line in result.stdout.splitlines():
        match = re.match(r'\s*cmd (\S+)\s*$', line)
        if match:
            command = match[1]
        elif command in LOAD_COMMANDS:
            match = re.match(r'\s*name (.*?) \(offset \d+\)\s*$', line)
            if match:
                dependencies.append(match[1])
                command = None
    return dependencies


def _toc_name(name):
    path = _normalized(name)
    if path.startswith('/') or posixpath.normpath(path) != path or path in ('', '.', '..') or path.startswith('../'):
        raise ValueError('Escaping or noncanonical TOC path: ' + path)
    return path


def _alias_target(row):
    name = _toc_name(row[0])
    target = str(row[1]).replace('\\', '/')
    if target.startswith('/'):
        raise ValueError('Escaping packaged alias: ' + name)
    return _toc_name(posixpath.normpath(posixpath.join(posixpath.dirname(name), target)))


def prune(binaries, datas, read_needed=needed):
    """Return kept TOCs and exclusions; refuse unexpected native consumers.

    Data TOCs can contain executable Qt plugins and binary convenience aliases.
    Check both collections and propagate explicitly excluded aliases to a fixed
    point; never infer that an arbitrary consumer is safe to drop.
    """
    rows = [*binaries, *datas]
    names = [_toc_name(row[0]) for row in rows]
    reasons = {name: exclusion(name) for name in names if exclusion(name)}
    aliases = {_toc_name(row[0]): _alias_target(row) for row in rows if row[2] == 'SYMLINK'}
    for alias in aliases:
        visited = set()
        target = alias
        while target in aliases:
            if target in visited:
                raise ValueError('Cyclic packaged alias: ' + alias)
            visited.add(target)
            target = aliases[target]
    while True:
        added = {name: 'alias of explicitly excluded ' + target
                 for name, target in aliases.items() if name not in reasons
                 and (target in reasons or exclusion(target))}
        if not added:
            break
        reasons.update(added)
    removed_names = {PurePosixPath(name).name for name in reasons}
    for row in rows:
        name = _toc_name(row[0])
        if name in reasons or row[2] == 'SYMLINK':
            continue
        for dependency in read_needed(row[1]):
            if exclusion(dependency) or PurePosixPath(dependency).name in removed_names:
                raise ValueError(f'Unexpected retained dependency: {name} needs removed {dependency}')
    kept = [[row for row in collection if _toc_name(row[0]) not in reasons]
            for collection in (binaries, datas)]
    return *kept, [{'path': name, 'reason': reason} for name, reason in sorted(reasons.items())]


def verify_payload(app, read_needed=needed):
    """Assert exclusions survived BUNDLE and no native developer links remain."""
    root = Path(app).resolve(strict=True)
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root).as_posix()
        if exclusion(relative):
            raise ValueError('Excluded component remains: ' + relative)
        if path.is_symlink():
            target = path.resolve(strict=True)
            if not target.is_relative_to(root):
                raise ValueError('Escaping packaged alias: ' + relative)
            if exclusion(target.relative_to(root).as_posix()):
                raise ValueError('Alias retains excluded component: ' + relative)
        elif path.is_file():
            for dependency in read_needed(path):
                if exclusion(dependency):
                    raise ValueError(f'Retained binary needs excluded family: {relative}: {dependency}')
                if dependency.startswith(('/System/Library/', '/usr/lib/')):
                    continue
                if not dependency.startswith(('@rpath/', '@loader_path/', '@executable_path/')):
                    raise ValueError(f'Outside or relative native dependency: {relative}: {dependency}')

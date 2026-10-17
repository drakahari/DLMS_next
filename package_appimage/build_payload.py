"""Freeze the normal AppImage payload with existing pinned project-local inputs.

This copies dependencies; it does not install or upgrade them. All output must be
new. The existing OCR and notice/source kits are required explicit inputs.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess


def main():
    p = argparse.ArgumentParser()
    for name in ('output', 'ocr-bundle', 'notices', 'distribution-kit'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--release', required=True)
    p.add_argument('--instrumented', action='store_true', help='Separate synthetic checkpoint build; never the normal artifact')
    p.add_argument('--host-platform', action='store_true', help='Use host Fontconfig/GBM with host rules/drivers')
    p.add_argument('--target', default='Fedora44 x86_64 AppImage')
    p.add_argument('--support', default='Personal-test Fedora44 x86_64 AppImage; public distribution not cleared')
    p.add_argument('--source-commit', help='Exact source identity for an isolated, verified build snapshot without Git history')
    p.add_argument('--source-tree-sha256', help='SHA-256 of the supplied file manifest when building an uncommitted review tree')
    a = p.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = a.output.absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError('Never overwrite a build directory')
    for value in (a.ocr_bundle, a.notices, a.distribution_kit):
        if not value.is_dir():
            raise FileNotFoundError(value)
    commit = a.source_commit or subprocess.check_output(
        (['git', '--git-dir=.dlms-git', '--work-tree=.'] if (root / '.dlms-git').is_dir() else ['git']) + ['rev-parse', 'HEAD'],
        cwd=root, text=True).strip()
    import re
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('Source identity must be an exact commit SHA')
    if a.source_tree_sha256 is not None and not re.fullmatch(r'[0-9a-f]{64}', a.source_tree_sha256):
        raise ValueError('Source tree identity must be a SHA-256 digest')
    # A missing native Qt dependency can make PyInstaller silently omit all
    # platform plugins after its isolated Qt info probe fails. Refuse before
    # producing an unusable artifact; this check creates no QApplication.
    from PySide6.QtCore import QLibraryInfo
    from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
    plugins = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath))
    for name in ('libqoffscreen.so', 'libqxcb.so', 'libqwayland.so'):
        if not (plugins / 'platforms' / name).is_file():
            raise FileNotFoundError(f'Required Linux Qt platform plugin: {name}')
    output.mkdir(mode=0o700)
    (output / 'tmp').mkdir(mode=0o700)
    info = dict(application_version='0.1.0-fedora-rc1', release=a.release,
                source_commit=commit, target=a.target, support=a.support)
    if a.source_tree_sha256 is not None:
        # Preserve the runtime's strict five-field identity contract. Additional
        # provenance belongs in a separate build record, not privileged metadata.
        info['support'] += f' Uncommitted review tree SHA-256: {a.source_tree_sha256}; source_commit is its base.'
        if len(info['support']) >= 512:
            raise ValueError('Review support text exceeds the runtime identity limit')
        (output / 'review-tree.json').write_text(json.dumps(dict(
            baseline_commit=commit, source_dirty=True,
            source_tree_sha256=a.source_tree_sha256), indent=2) + '\n')
    (output / 'build-info.json').write_text(json.dumps(info, indent=2) + '\n')
    env = dict(os.environ, DLMS_DESKTOP_BUILD_INSTRUMENTED='1' if a.instrumented else '0',
               DLMS_DESKTOP_HOST_PLATFORM_LIBS='1' if a.host_platform else '0',
               DLMS_DESKTOP_HOST_PLATFORM_REPORT=str(output / 'host-platform.json'),
               DLMS_DESKTOP_MINIMAL_BUNDLE='1',
               DLMS_DESKTOP_MINIMAL_REPORT=str(output / 'pruned.json'),
               DLMS_TESSERACT_BUNDLE_ROOT=str(a.ocr_bundle.absolute()),
               DLMS_DESKTOP_BUILD_INFO=str(output / 'build-info.json'),
               DLMS_DESKTOP_NOTICE_ROOT=str(a.notices.absolute()),
               DLMS_DESKTOP_DISTRIBUTION_ROOT=str(a.distribution_kit.absolute()),
               XDG_CACHE_HOME=str(output / 'cache'), TMPDIR=str(output / 'tmp'))
    import sys
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--clean', '--noconfirm',
                    '--distpath', str(output / 'dist'), '--workpath', str(output / 'work'),
                    'package_fedora/DLMS-Desktop.spec'], cwd=root, env=env, check=True)
    if a.host_platform:
        from package_linux.host_platform import verify_payload
        verify_payload(output / 'dist' / ('DLMS-Desktop-Instrumented' if a.instrumented else 'DLMS-Desktop'))
    if a.instrumented:
        return  # Supplementary test payload has no install/release entry point.
    subprocess.run([sys.executable, '-m', 'package_fedora.finalize_candidate',
                    '--dist', str(output / 'dist'), '--distribution-root',
                    str(a.distribution_kit.absolute())], cwd=root, env=env, check=True)


if __name__ == '__main__':
    main()

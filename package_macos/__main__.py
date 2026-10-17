"""Finder/source entry and explicit owned-worker dispatch for macOS only."""
import argparse
import os
import platform
import sys


def main(argv=None):
    if sys.platform != 'darwin' or platform.machine() != 'arm64':
        raise RuntimeError('This private Desktop candidate requires Apple Silicon macOS')
    import package_macos
    package_macos.ACTIVE = True
    from desktop.macos_paths import prepare_root
    from desktop.package_entry import _seal_private_descriptors
    _seal_private_descriptors()
    args = list(sys.argv[1:] if argv is None else argv)
    args = [arg for arg in args if not arg.startswith('-psn_')]
    if args[:1] == ['--desktop-worker']:
        if len(args) < 2 or args[1] not in {'backend', 'adopt', 'maintenance', 'removal'}:
            raise ValueError('Unknown Mac Desktop worker')
        if not os.environ.get('DLMS_MACOS_DATA_ROOT'):
            raise ValueError('Mac Desktop worker requires its explicit scoped data root')
        root = prepare_root(os.environ['DLMS_MACOS_DATA_ROOT'], create=False)
        role = args[1]
        required = {'backend': 'DLMS_DESKTOP_PARENT_PID', 'adopt': 'DLMS_DESKTOP_ADOPT_OWNER_SECRET',
                    'maintenance': 'DLMS_DESKTOP_MAINT_OWNER_SECRET', 'removal': 'DLMS_DESKTOP_REMOVE_OWNER_SECRET'}[role]
        if not os.environ.get(required):
            raise ValueError('Mac Desktop worker has no owning launcher context')
        os.environ['DLMS_DESKTOP_DATA_ROOT'] = str(root)
        os.environ['DLMS_DESKTOP_ROOT_KIND'] = 'macos-candidate'
        sys.argv = [sys.argv[0], *args[2:]]
        from importlib import import_module
        return int(import_module('desktop.' + role).main() or 0)
    parser = argparse.ArgumentParser(description='Private DLMS Desktop Apple Silicon candidate')
    parser.add_argument('--profile', default='walkthrough')
    parser.add_argument('--data-root', help='new or previously marked Mac candidate root; no data adoption')
    parser.add_argument('--capture-window-events', action='store_true')
    selected = parser.parse_args(args)
    import re
    if re.fullmatch(r'[a-z][a-z0-9_-]{0,31}', selected.profile) is None:
        parser.error('Invalid profile name')
    root = prepare_root(selected.data_root)
    os.environ['DLMS_MACOS_DATA_ROOT'] = str(root)
    os.environ['DLMS_DESKTOP_DATA_ROOT'] = str(root)
    os.environ['DLMS_DESKTOP_ROOT_KIND'] = 'macos-candidate'
    for key in tuple(os.environ):
        if key == 'DLMS_DESKTOP_AUTOMATED' or key.startswith('DLMS_DESKTOP_TEST_'):
            os.environ.pop(key, None)
    from desktop.__main__ import main as desktop_main
    options = ['--profile', selected.profile]
    if selected.capture_window_events:
        options.append('--capture-window-events')
    return desktop_main(options)


if __name__ == '__main__':
    raise SystemExit(main())

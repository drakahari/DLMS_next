"""Separate synthetic native-control check executable. Never the normal entry."""
import argparse
import os
from pathlib import Path
import re
import sys


def _check_profile(value):
    if not isinstance(value, str) or not re.fullmatch(r'wvfollowup[a-z0-9_-]{1,22}', value):
        raise ValueError('Instrumented checks require a distinct wvfollowup-prefixed synthetic profile')


def _check_data_root(value):
    from package_windows.entry import root_path
    root = root_path(value)
    if root.name != 'data' or root.parent.name != 'windows-native' or root.parent.parent.name != '.gate1':
        raise ValueError('Instrumented checks require a marked project-local .gate1/windows-native/data root')
    return root


def _worker():
    # This separate artifact alone enables the existing synthetic adoption
    # driver's exact-parent/time fallback. Normal packages always strip it.
    for key in tuple(os.environ):
        if key == 'DLMS_DESKTOP_AUTOMATED' or key.startswith('DLMS_DESKTOP_TEST_'):
            os.environ.pop(key, None)
    if len(sys.argv) < 3 or sys.argv[2] not in {'backend', 'adopt', 'maintenance', 'removal'}:
        raise ValueError('Unknown instrumented Windows Desktop worker')
    role, arguments = sys.argv[2], sys.argv[3:]
    from desktop.windows_processes import bootstrap
    bootstrap()  # Unchanged parent birth/SID/image, pipe and Job release gate.
    _check_data_root(os.environ['DLMS_DESKTOP_DATA_ROOT'])
    if role == 'backend':
        profile = os.environ.get('DLMS_DESKTOP_PROFILE_NAME')
    else:
        if arguments.count('--profile') != 1 or any(item.startswith('--profile=') for item in arguments):
            raise ValueError('Instrumented workers require one explicit synthetic profile')
        offset = arguments.index('--profile') + 1
        profile = arguments[offset] if offset < len(arguments) else None
    _check_profile(profile)
    if role == 'adopt':
        os.environ['DLMS_DESKTOP_AUTOMATED'] = '1'
    sys.argv = [sys.argv[0], *arguments]
    from importlib import import_module
    return import_module('desktop.' + role).main()


def main():
    import package_windows_webview2
    package_windows_webview2.ACTIVE = True
    # Child workers keep the exact authenticated normal bootstrap; no check
    # argument is accepted as a substitute for its inherited owner handle.
    if sys.argv[1:2] == ['--desktop-worker']:
        return _worker()
    parser = argparse.ArgumentParser(description='INSTRUMENTED synthetic WebView2 native checks only')
    parser.add_argument('--native-check', choices=('menu', 'backup', 'locations', 'exports', 'ai'), required=True)
    parser.add_argument('--data-root', required=True)
    parser.add_argument('--profile', required=True)
    parser.add_argument('--output', required=True)
    args, extra = parser.parse_known_args()
    _check_profile(args.profile)
    root = _check_data_root(args.data_root)
    # Require the task-local layout as well as the normal marker/private ACL;
    # this entry cannot select the normal installation's default data root.
    output = Path(args.output)
    from desktop.windows_files import assert_path, owned
    assert_path(output)
    output = output.resolve()
    if not output.is_relative_to(root.parent) or output.is_relative_to(root):
        raise ValueError('Check output must be a separate project-local windows-native evidence directory')
    owned(output.parent, private=True)
    log = output.with_name(output.name + '-entry.log')
    assert_path(log, leaf=True)
    descriptor = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_BINARY, 0o600)
    os.set_inheritable(descriptor, False)
    stream = os.fdopen(descriptor, 'w', encoding='utf-8', errors='backslashreplace', buffering=1)
    sys.stdout = sys.stderr = stream
    print('INSTRUMENTED synthetic native-control check; not normal-package or physical acceptance.')
    os.environ['DLMS_DESKTOP_DATA_ROOT'] = str(root)
    os.environ['DLMS_DESKTOP_ROOT_KIND'] = 'windows-candidate'
    os.environ.pop('PYTHONHOME', None)
    os.environ.pop('PYTHONPATH', None)
    from desktop.windows_processes import own_launcher
    own_launcher()
    sys.argv = [sys.argv[0], '--profile', args.profile, '--output', str(output), *extra]
    if args.native_check == 'menu':
        from tests.webview2.gui_native_followup import main as check
    elif args.native_check == 'locations':
        from tests.webview2.gui_file_locations import main as check
    elif args.native_check == 'exports':
        from tests.webview2.gui_export_locations import main as check
    elif args.native_check == 'ai':
        from tests.webview2.gui_ai_handoff import main as check
    else:
        from tests.webview2.gui_backup_followup import main as check
    return check()


def _report_error(error, *, notify=None):
    """Windowed PyInstaller may have no usable stderr before the private log.

    Never turn a safe startup refusal into a second unhandled traceback. The
    normal application entry is separate and unchanged.
    """
    import traceback
    try:
        if sys.stderr is not None:
            sys.stderr.write(traceback.format_exc())
            sys.stderr.flush()
            return
    except (OSError, ValueError, AttributeError):
        pass
    if notify is None:
        import ctypes
        notify = lambda message: ctypes.windll.user32.MessageBoxW(
            None, message, 'DLMS Desktop instrumented check stopped', 0x10)
    notify('The separate instrumented test was stopped.\n\n'
           + type(error).__name__ + ': ' + str(error)[:1200])


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        _report_error(error)
        raise SystemExit(2)

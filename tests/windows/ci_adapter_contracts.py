"""Run existing native contracts with ordinary-user fixture ownership in CI.

The elevated hosted Windows runner may default new objects to Administrators,
whereas Desktop deliberately accepts only the actual user SID as owner. Keep
that runtime refusal unchanged. Change only this pytest process's default owner
(not privileges, DACLs, account policy or existing files), then restore it.

TOKEN_OWNER: https://learn.microsoft.com/windows/win32/api/winnt/ns-winnt-token_owner
"""
from contextlib import contextmanager
import os
from pathlib import Path
import tempfile


SELECTION = (
    'tests/windows/test_native.py',
    'tests/windows/test_reserved_paths.py',
    'tests/windows/test_restore_connection.py',
    'tests/webview2/test_ai_contract.py',
    'tests/webview2/test_backup_chooser.py',
)


@contextmanager
def ordinary_fixture_owner():
    if (os.name != 'nt' or os.environ.get('GITHUB_ACTIONS') != 'true'
            or os.environ.get('RUNNER_OS') != 'Windows'):
        raise RuntimeError('This fixture setup is only for hosted Windows CI')
    import ctypes as c
    from ctypes import wintypes as w
    from desktop import windows_files as files
    from desktop.windows_processes import (
        a, api, checked, close, current, open_token, sid_text, token_info,
    )

    class Owner(c.Structure):
        _fields_ = [('sid', w.LPVOID)]

    setter = api(a, 'SetTokenInformation', w.BOOL, w.HANDLE, c.c_int,
                 w.LPVOID, w.DWORD)
    token = w.HANDLE()
    # TOKEN_QUERY | TOKEN_ADJUST_DEFAULT; do not enable any privilege.
    checked(open_token(current(), 0x8 | 0x80, c.byref(token)))

    def query(kind):
        size = w.DWORD()
        token_info(token, kind, None, 0, c.byref(size))
        if not size.value:
            raise RuntimeError('Token ownership information is unavailable')
        buffer = c.create_string_buffer(size.value)
        checked(token_info(token, kind, buffer, size, c.byref(size)))
        return buffer

    changed = False
    try:
        original = query(4)  # TokenOwner: retain its embedded SID until restore.
        user = query(1)      # TokenUser starts with the user's SID pointer.
        old = c.cast(original, c.POINTER(Owner)).contents
        desired = Owner(c.cast(user, c.POINTER(w.LPVOID))[0])
        old_sid, user_sid = sid_text(old.sid), sid_text(desired.sid)
        print(f'CI fixture token owner={old_sid}; user={user_sid}', flush=True)
        with tempfile.TemporaryDirectory(prefix='dlms-ci-owner-') as directory:
            probe = Path(directory) / 'before.txt'
            probe.write_bytes(b'synthetic owner verification')
            if old_sid != user_sid:
                # Diagnose only the known hosted-runner case. Any other token
                # layout remains a refusal, not an excuse to relax ownership.
                if old_sid != 'S-1-5-32-544':
                    raise RuntimeError('Unexpected hosted-runner default owner')
                try:
                    files.owned(probe)
                except ValueError as error:
                    if str(error) != 'Windows object is owned by another account':
                        raise
                else:
                    raise AssertionError('Group-owned fixture unexpectedly accepted')
                checked(setter(token, 4, c.byref(desired), c.sizeof(desired)))
                changed = True
            current_owner = query(4)
            if sid_text(c.cast(current_owner, c.POINTER(Owner)).contents.sid) != user_sid:
                raise AssertionError('Fixture default owner did not become the user')
            after = Path(directory) / 'after.txt'
            after.write_bytes(b'synthetic ordinary-user fixture')
            files.owned(after)
            # The old object must still be refused after the setup: we changed
            # creation defaults, not the runtime check or an existing owner.
            if changed:
                try:
                    files.owned(probe)
                except ValueError as error:
                    if str(error) != 'Windows object is owned by another account':
                        raise
                else:
                    raise AssertionError('Existing group ownership was weakened')
            print('CI ordinary-user fixture setup verified; runtime refusals retained', flush=True)
            yield
    finally:
        try:
            if changed:
                checked(setter(token, 4, c.byref(old), c.sizeof(old)))
                restored = query(4)
                if sid_text(c.cast(restored, c.POINTER(Owner)).contents.sid) != old_sid:
                    raise AssertionError('Original fixture token owner was not restored')
        finally:
            close(token)


def main():
    import pytest
    with ordinary_fixture_owner():
        return pytest.main(['-q', '-p', 'no:cacheprovider', *SELECTION])


if __name__ == '__main__':
    raise SystemExit(main())

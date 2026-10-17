"""Native Darwin contracts; runnable with stdlib unittest before Qt is installed."""
from __future__ import annotations

import ctypes
import errno
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from desktop import macos_processes as native


@unittest.skipUnless(sys.platform == 'darwin', 'requires native macOS process APIs')
class DarwinProcessTests(unittest.TestCase):
    def start(self, code='import time; time.sleep(30)', *, nonce=None, **kwargs):
        process = subprocess.Popen([sys.executable, '-c', code],
            env=dict(os.environ, DLMS_DESKTOP_NONCE=nonce or secrets.token_hex(32)),
            start_new_session=True, **kwargs)
        self.addCleanup(self.stop, process)
        return process

    @staticmethod
    def stop(process):
        if process.poll() is None:
            process.kill()
        process.wait(timeout=4)

    @staticmethod
    def live(pid):
        try:
            return native.identity(pid)['status'] != 5
        except ProcessLookupError:
            return False

    def bind_or_skip(self, endpoint, address):
        try:
            endpoint.bind(address)
        except PermissionError as exc:
            if exc.errno != errno.EPERM:
                raise
            self.skipTest('execution sandbox denies native socket bind; rerun in normal Terminal')

    def test_exact_identity_and_kernel_arguments(self):
        nonce = secrets.token_hex(32)
        process = self.start(nonce=nonce)
        before = native.identity(process.pid)
        args, environment = native.arguments_environment(process.pid)
        self.assertEqual(before['pid'], process.pid)
        self.assertEqual(before['uid'], os.getuid())
        self.assertEqual(before['group'], process.pid)
        self.assertIn('-c', args)
        self.assertIn(('DLMS_DESKTOP_NONCE=' + nonce).encode(), environment)
        self.assertTrue(native._same_birth(before, native.identity(process.pid)))

    def test_stale_birth_cannot_signal(self):
        process = self.start()
        before = native.identity(process.pid)
        before['unique'] += 1
        self.assertFalse(native.signal_identity(before, signal.SIGKILL))
        self.assertIsNone(process.poll())

    def test_kernel_rejects_stale_pid_generation(self):
        process = self.start()
        before = native.identity(process.pid)
        token = (ctypes.c_uint32 * 8)()
        token[5] = before['pid']
        token[7] = before['version'] + 1
        result = native._library().proc_signal_with_audittoken(token, signal.SIGKILL)
        self.assertEqual(result, errno.ESRCH)
        self.assertIsNone(process.poll())
        self.assertTrue(native.signal_identity(before, signal.SIGTERM))
        self.assertEqual(process.wait(timeout=4), -signal.SIGTERM)

    def test_owned_helpers_reaped_but_same_group_without_nonce_survives(self):
        nonce = secrets.token_hex(32)
        code = '''import json,os,subprocess,sys,time
owned=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])
env=dict(os.environ);env.pop('DLMS_DESKTOP_NONCE',None)
foreign=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],env=env)
print(json.dumps([owned.pid,foreign.pid]),flush=True)
time.sleep(30)
'''
        process = self.start(code, nonce=nonce, stdout=subprocess.PIPE, text=True)
        owned_pid, foreign_pid = json.loads(process.stdout.readline())
        foreign_identity = native.identity(foreign_pid)
        def clean_foreign():
            try:
                native.signal_identity(foreign_identity, signal.SIGKILL)
            except ProcessLookupError:
                pass
        self.addCleanup(clean_foreign)
        self.assertEqual(native.reap(process.pid, nonce), [])
        process.wait(timeout=4)
        self.assertFalse(self.live(owned_pid))
        self.assertTrue(self.live(foreign_pid))
        process.stdout.close()

    def test_helpers_reaped_after_leader_crash(self):
        nonce = secrets.token_hex(32)
        code = '''import os,subprocess,sys,time
child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])
print(child.pid,flush=True)
time.sleep(30)
'''
        process = self.start(code, nonce=nonce, stdout=subprocess.PIPE, text=True)
        child_pid = int(process.stdout.readline())
        process.kill()
        process.wait(timeout=4)
        self.assertEqual(native.reap(process.pid, nonce), [])
        self.assertFalse(self.live(child_pid))
        process.stdout.close()

    def test_pipe_and_bound_socket_handoff_are_same_and_not_further_inherited(self):
        read_fd, write_fd = os.pipe()
        self.addCleanup(os.close, read_fd)
        self.addCleanup(os.close, write_fd)
        bound = socket.socket()
        self.addCleanup(bound.close)
        self.bind_or_skip(bound, ('127.0.0.1', 0))
        bound.listen()
        code = f'''import json,os,socket
from desktop.macos_processes import seal_private_descriptors
seal_private_descriptors()
s=socket.socket(fileno={bound.fileno()})
print(json.dumps([s.getsockname(),os.get_inheritable({read_fd}),os.get_inheritable(s.fileno())]),flush=True)
'''
        process = native.spawn([sys.executable, '-c', code], bound=bound,
            pass_fds=(read_fd, bound.fileno()), close_fds=True,
            stdout=subprocess.PIPE, text=True)
        result = json.loads(process.communicate(timeout=5)[0])
        self.assertEqual(process.returncode, 0)
        self.assertEqual(tuple(result[0]), bound.getsockname())
        self.assertEqual(result[1:], [False, False])

    def test_external_exec_cannot_inherit_private_descriptor(self):
        read_fd, write_fd = os.pipe()
        self.addCleanup(os.close, read_fd)
        self.addCleanup(os.close, write_fd)
        os.set_inheritable(read_fd, True)
        native.seal_private_descriptors()
        self.assertFalse(os.get_inheritable(read_fd))
        code = f'''import os
try:os.fstat({read_fd});print('inherited')
except OSError:print('closed')
'''
        result = subprocess.run([sys.executable, '-c', code], close_fds=False,
                                capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip(), 'closed')

    def test_parent_pipe_eof_cleans_owned_helpers_and_exits(self):
        nonce = secrets.token_hex(32)
        read_fd, write_fd = os.pipe()
        self.addCleanup(os.close, read_fd)
        code = f'''import os,subprocess,sys
from desktop.macos_processes import seal_private_descriptors,parent_lost
seal_private_descriptors()
child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])
print(child.pid,flush=True)
os.read({read_fd},1)
parent_lost()
'''
        process = self.start(code, nonce=nonce, pass_fds=(read_fd,), stdout=subprocess.PIPE, text=True)
        child_pid = int(process.stdout.readline())
        os.close(write_fd)
        self.assertEqual(process.wait(timeout=5), 70)
        self.assertFalse(self.live(child_pid))
        process.stdout.close()

    def test_wrong_nonce_cannot_claim_group(self):
        process = self.start()
        self.assertEqual(native.reap(process.pid, secrets.token_hex(32)), [])
        self.assertIsNone(process.poll())

    def test_term_resistant_owned_process_is_escalated(self):
        nonce = secrets.token_hex(32)
        process = self.start("import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);print('ready',flush=True);time.sleep(30)",
                             nonce=nonce, stdout=subprocess.PIPE, text=True)
        self.assertEqual(process.stdout.readline().strip(), 'ready')
        self.assertEqual(native.reap(process.pid, nonce), [])
        self.assertEqual(process.wait(timeout=3), -signal.SIGKILL)
        process.stdout.close()

    def test_instance_socket_is_short_private_and_profile_specific(self):
        first = Path(native.instance_socket_name(Path('/very/' + 'long/' * 50 + 'profile')))
        second = native.instance_socket_name(Path('/different/profile'))
        self.assertLess(len(os.fsencode(first)), 104)
        self.assertNotEqual(str(first), second)
        self.assertEqual(first.parent.stat().st_uid, os.getuid())
        self.assertEqual(first.parent.stat().st_mode & 0o077, 0)
        with socket.socket(socket.AF_UNIX) as endpoint:
            self.bind_or_skip(endpoint, str(first))
        first.unlink()

    def test_duplicate_descriptor_requires_birth_owner_mode_and_exact_launch(self):
        from desktop import ownership
        process = self.start("import time;print('ready',flush=True);time.sleep(30)", stdout=subprocess.PIPE, text=True)
        self.assertEqual(process.stdout.readline().strip(), 'ready')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            descriptor = root / 'instance-owner.json'
            value = {'pid': process.pid, 'start_ticks': native.identity(process.pid)['start'],
                     'name': 'test', 'secret': 'a' * 64}
            descriptor.write_text(json.dumps(value))
            descriptor.chmod(0o600)
            arguments = [sys.executable, '-m', 'package_macos', '--profile', 'test', '--data-root', str(root)]
            with patch.object(ownership, 'AREA', root), patch.object(ownership, 'FROZEN', False), patch.object(native, 'arguments_environment', return_value=(arguments, [])):
                self.assertEqual(ownership.verified_instance(descriptor, 'test'), 'a' * 64)
                self.assertIsNone(ownership.verified_instance(descriptor, 'wrong'))
                descriptor.chmod(0o644)
                self.assertIsNone(ownership.verified_instance(descriptor, 'test'))
                descriptor.chmod(0o600)
                value['start_ticks'] += 1
                descriptor.write_text(json.dumps(value))
                self.assertIsNone(ownership.verified_instance(descriptor, 'test'))
        process.stdout.close()

    def test_only_exact_launcher_arguments_match(self):
        root = Path('/private/tmp/dlms process contract')
        good = [sys.executable, '-m', 'package_macos', '--profile', 'test', '--data-root', str(root)]
        self.assertTrue(native.launch_matches(good, 'test', root, frozen=False))
        for extra in (['--profile', 'test'], ['--data-root', str(root)], ['--desktop-worker', 'backend']):
            self.assertFalse(native.launch_matches(good + extra, 'test', root, frozen=False))
        self.assertFalse(native.launch_matches(good, 'other', root, frozen=False))


if __name__ == '__main__':
    unittest.main()

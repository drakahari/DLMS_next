"""Native bounded signature/metadata controls; no LaunchServices calls."""
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
import unittest

from tools import macos_test_wrapper as tool


@unittest.skipUnless(os.uname().sysname == 'Darwin', 'macOS signature controls')
class VerifiedWrapperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp(prefix='dlms-wrapper-regression-', dir=Path.home()/'.cache'))
        cls.app = cls.work/'Synthetic.app'
        (cls.app/'Contents/MacOS').mkdir(parents=True)
        (cls.app/'Contents/Info.plist').write_bytes(plistlib.dumps(dict(
            CFBundleExecutable='Synthetic', CFBundleIdentifier='io.github.drakahari.SyntheticWrapperControl',
            CFBundlePackageType='APPL', CFBundleVersion='1')))
        source = cls.work/'synthetic.c'; source.write_text('int main(void) { return 0; }\n')
        tool.run(['/usr/bin/clang', '-arch', 'arm64', source, '-o', cls.app/'Contents/MacOS/Synthetic'])
        tool.run(['/usr/bin/codesign','--sign','-','--timestamp=none',cls.app])
        cls.root = cls.work/'data'; cls.root.mkdir(mode=0o700)
        (cls.root/'.dlms-macos-preview.json').write_text(json.dumps(dict(kind='dlms-desktop-macos-preview',version=1)))
        cls.record = tool.stage(cls.app, cls.root, 'sixcontrol', cls.work/'staged')
        cls.wrapper = Path(cls.record['wrapper'])
        cls.results = []

    @classmethod
    def tearDownClass(cls):
        (cls.work/'REGRESSION_RESULT.json').write_text(json.dumps(cls.results,indent=2)+'\n')
        print('Preserved native wrapper regression evidence: '+str(cls.work), flush=True)

    def test_valid_gate_calls_only_expected_opener(self):
        calls=[]
        tool.checked_open(self.record, opener=calls.append)
        self.assertEqual(calls,[['/usr/bin/open',str(self.wrapper)]])
        self.results.append(dict(test=self.id(),opener_calls=1,real_open=False,pass_=True))

    def test_finder_metadata_reproduces_failure_and_never_opens(self):
        copy = self.work/'Invalid Finder metadata.app'
        shutil.copytree(self.wrapper, copy, symlinks=True)
        # Synthetic quarantine marker bytes; never remove or alter this attribute.
        quarantine=b'0081;00000000;DLMS-wrapper-regression;synthetic'
        tool.set_attribute(copy,'com.apple.quarantine',quarantine)
        tool.set_attribute(copy,'com.apple.FinderInfo',bytes([1])+bytes(31))
        calls=[]
        with self.assertRaises(subprocess.CalledProcessError):
            tool.checked_open(self.record,copy,opener=calls.append)
        self.assertEqual(calls,[])
        # Same verifier used by the genuine gate failed before its sole opener.
        # Do not execute a quarantined control: that is a separate OS approval
        # boundary. A different fresh, non-quarantined metadata-only copy tests
        # native fail-closed behavior, without dialogs or LaunchServices.
        native_copy=self.work/'Native invalid metadata.app'
        shutil.copytree(self.wrapper,native_copy,symlinks=True)
        tool.set_attribute(native_copy,'com.apple.FinderInfo',bytes([1])+bytes(31))
        native=subprocess.run([str(native_copy/'Contents/MacOS/VerifiedLauncher'),'--verify-only'],capture_output=True,timeout=15)
        self.assertEqual(native.returncode,1)
        self.assertIn(b'Finder information',native.stderr)
        self.assertEqual(tool.get_attribute(copy,'com.apple.quarantine'),quarantine)
        failure=subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(copy)],capture_output=True,text=True)
        self.assertIn('Finder information',failure.stderr)
        self.results.append(dict(test=self.id(),strict_status=failure.returncode,stderr=failure.stderr,
                                 native_status=native.returncode,opener_calls=0,quarantine_preserved=True,pass_=True))

    def test_correct_only_a_fresh_copy_before_signing_preserves_quarantine(self):
        copy=self.work/'Fresh corrected control.app'
        shutil.copytree(self.wrapper,copy,symlinks=True)
        tool.set_attribute(copy,'com.apple.FinderInfo',bytes([1])+bytes(31))
        quarantine=b'0081;00000000;DLMS-wrapper-regression;synthetic'
        tool.set_attribute(copy,'com.apple.quarantine',quarantine)
        before=tool.metadata(copy)
        tool.remove_attribute(copy,'com.apple.FinderInfo')
        tool.run(['/usr/bin/codesign','--force','--sign','-','--timestamp=none',copy])
        tool.verify(copy)
        self.assertEqual(tool.get_attribute(copy,'com.apple.quarantine'),quarantine)
        self.results.append(dict(test=self.id(),removed=[dict(path='',attribute='com.apple.FinderInfo',bytes_hex=before['']['com.apple.FinderInfo'])],quarantine_preserved=True,pass_=True))

    def test_second_verification_failure_prevents_opener(self):
        calls=[]; verified=[]
        def verifier(path):
            verified.append(str(path))
            if len(verified)==2: raise subprocess.CalledProcessError(1,['codesign'])
        with self.assertRaises(subprocess.CalledProcessError):
            tool.checked_open(self.record,opener=calls.append,verifier=verifier)
        self.assertEqual(calls,[]);self.assertEqual(len(verified),2)
        self.results.append(dict(test=self.id(),opener_calls=0,pass_=True))

    def test_payload_and_wrapper_inventory_changes_prevent_open(self):
        for key in ('wrapper_inventory','payload_inventory'):
            changed=dict(self.record);changed[key]={};calls=[]
            with self.assertRaises(ValueError):tool.checked_open(changed,opener=calls.append)
            self.assertEqual(calls,[])
        self.results.append(dict(test=self.id(),opener_calls=0,pass_=True))

    def test_wrong_payload_root_or_profile_is_refused(self):
        for key in ('app','data_root','profile'):
            changed=dict(self.record)
            if key=='app':
                # Another valid signed app is not an acceptable substitute.
                other=self.work/'Other valid.app';shutil.copytree(self.app,other,symlinks=True)
                changed[key]=str(other)
            else:changed[key]='unexpected'
            calls=[]
            with self.assertRaises(ValueError):tool.checked_open(changed,opener=calls.append)
            self.assertEqual(calls,[])
        self.results.append(dict(test=self.id(),opener_calls=0,pass_=True))


if __name__ == '__main__': unittest.main()

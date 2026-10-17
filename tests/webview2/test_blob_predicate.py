"""Pure managed URI/path predicate checks; reflection only, no Form/browser."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
HOST = ROOT/'.gate1/windows-native/webview2-host-candidate-01/payload/DLMS-WebView2-Host.exe'
# Fresh canonical Windows host, independently inventoried against the pinned SDK.
HOST_SHA256 = '0bd83204ebe28390c40e8d6687182bdd3a3f845590957c4c97a1779c817ded2a'


@unittest.skipUnless(os.name == 'nt' and HOST.exists(), 'Exact reviewed canonical host01 required')
class BlobPredicateTests(unittest.TestCase):
    def test_native_path_reserved_stems_in_leaf_and_ancestors(self):
        self.assertEqual(hashlib.sha256(HOST.read_bytes()).hexdigest(), HOST_SHA256)
        shell = shutil.which('pwsh')
        self.assertIsNotNone(shell)
        reserved = ['CON', 'PRN', 'AUX', 'NUL'] + [prefix+suffix for prefix in ('COM', 'LPT')
                   for suffix in (*map(str, range(1, 10)), '¹', '²', '³')]
        bad_names = [variant for stem in reserved for variant in (stem, stem.lower()+'.txt', stem+' .txt', ' '+stem+' .txt')]
        denied = [path for name in bad_names for path in ('C:/synthetic/'+name, 'C:/synthetic/'+name+'/leaf.txt')]
        allowed = ['C:/synthetic/'+name for name in ('CONSOLE.txt', 'COM10.txt', 'LPT0.txt',
                   'COM¹0.txt', 'CONx .txt', 'COM 1.txt', '.CON', 'normal 日本語.txt')]
        allowed += ['C:/synthetic/CONSOLE.txt/leaf.txt', 'C:/synthetic/COM10/leaf.txt']
        values = denied+allowed
        script = ("$ErrorActionPreference='Stop';$a=[Reflection.Assembly]::LoadFrom('"+
                  str(HOST).replace("'", "''")+"');"
                  "$m=$a.GetType('DesktopRenderer').GetMethod('NativePath',[Reflection.BindingFlags]'Static,NonPublic');"
                  "$cases=[Console]::In.ReadToEnd()|ConvertFrom-Json;"
                  "$rows=foreach($item in $cases){try{$null=$m.Invoke($null,[object[]]@([string]$item));$true}catch{$cause=$_.Exception;while($cause.InnerException){$cause=$cause.InnerException};if($cause.GetType().FullName -ne 'System.InvalidOperationException' -or $cause.Message -ne 'Ambiguous native path component refused'){throw};$false}};"
                  "$rows|ConvertTo-Json -Compress")
        run = subprocess.run([shell, '-NoProfile', '-NonInteractive', '-Command', script],
                             input=json.dumps(values), text=True, capture_output=True, timeout=20, check=True)
        self.assertEqual(json.loads(run.stdout), [False]*len(denied)+[True]*len(allowed))

    def test_canonical_download_origin_only(self):
        self.assertEqual(hashlib.sha256(HOST.read_bytes()).hexdigest(), HOST_SHA256)
        shell = shutil.which('pwsh')
        self.assertIsNotNone(shell, 'Existing native PowerShell7 required; no prerequisite installed')
        origin, uuid = 'http://127.0.0.1:9001', '12345678-1234-1234-1234-123456789abc'
        good = f'blob:{origin}/{uuid}'
        values = [good, good.replace(':9001/', ':9002/'), good.replace('blob:http:', 'blob:https:'),
                  f'blob:null/{uuid}', 'data:text/plain,x',
                  good.replace('127.0.0.1', 'user:pass@127.0.0.1'), good+'?x=1', good+'#x',
                  f'blob:{origin}//{uuid}', good[:-3]+'ABC', good.replace('blob:', 'BLOB:'),
                  f'blob:{origin}/no-uuid', f'blob:http://127.0.0.1.evil.invalid:9001/{uuid}']
        script = ("$ErrorActionPreference='Stop';$a=[Reflection.Assembly]::LoadFrom('"+
                  str(HOST).replace("'", "''")+"');"
                  "$m=$a.GetType('DesktopRenderer').GetMethod('BlobDownloadUri',[Reflection.BindingFlags]'Static,NonPublic');"
                  "$cases=[Console]::In.ReadToEnd()|ConvertFrom-Json;"
                  "$rows=foreach($item in $cases){$m.Invoke($null,[object[]]@([string]$item.uri,[string]$item.origin))};"
                  "$rows|ConvertTo-Json -Compress")
        run = subprocess.run([shell, '-NoProfile', '-NonInteractive', '-Command', script],
                             input=json.dumps([{'uri': value, 'origin': origin} for value in values]),
                             text=True, capture_output=True, timeout=20, check=True)
        self.assertEqual(json.loads(run.stdout), [True]+[False]*(len(values)-1))


if __name__ == '__main__': unittest.main()

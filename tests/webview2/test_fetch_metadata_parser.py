"""Native console parser checks; no browser, network, or application profiles."""
import json
import os
from pathlib import Path
import subprocess

import pytest


@pytest.mark.skipif(os.name != "nt", reason="Windows C# metadata parser")
def test_native_metadata_scanner(tmp_path):
    root = Path(__file__).resolve().parents[2]
    compiler = Path("C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe")
    if not compiler.is_file():
        pytest.skip("The existing native .NET Framework compiler is unavailable")
    executable = tmp_path / "FetchMetadataTests.exe"
    compiled = subprocess.run(
        [str(compiler), "/nologo", "/target:exe", "/platform:x64", "/optimize+",
         f"/out:{executable}", "/reference:System.dll", "/reference:System.Core.dll",
         "/reference:System.Web.Extensions.dll",
         str(root / "windows_webview2/FetchMetadata.cs"),
         str(root / "tests/webview2/FetchMetadataTests.cs")],
        capture_output=True, text=True, timeout=30,
    )
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    checked = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
    assert checked.returncode == 0, checked.stdout + checked.stderr
    receipt = json.loads(checked.stdout)
    assert receipt["passed"] and receipt["tests"] >= 35
    assert receipt["large_envelope_chars"] > 16 * 1024 * 1024
    assert receipt["allocated_bytes"] < 1024 * 1024
    assert not receipt["body_values_logged"]
    assert not receipt["native_or_normal_acceptance"]

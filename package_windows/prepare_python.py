"""Private CPython build interpreter; never changes host Python/PATH/registry."""
from pathlib import Path
import base64
import hashlib
import gzip
import json
import urllib.request
import zipfile

PACKAGE_URL = "https://api.nuget.org/v3-flatcontainer/python/3.14.7/python.3.14.7.nupkg"
CATALOG_URL = "https://api.nuget.org/v3/catalog0/data/2026.08.05.12.47.10/python.3.14.7.json"
PUBLISHER_SHA512 = "MX3tQ1/8rOfHRN/xsJPEkESz7ALdq1dhR16E+bmFrqKCkXF+09QsiwHW3ZOq9uqTQ0STwYgt92UIU9E6mMKTgg=="

def verify_package(payload, metadata):
    if (metadata.get("id") != "python" or metadata.get("version") != "3.14.7"
            or metadata.get("authors") != "Python Software Foundation"
            or metadata.get("packageHashAlgorithm") != "SHA512"
            or metadata.get("packageSize") != len(payload)
            or metadata.get("packageHash") != PUBLISHER_SHA512):
        raise ValueError("Unexpected CPython publisher metadata")
    expected = base64.b64decode(PUBLISHER_SHA512, validate=True).hex()
    if hashlib.sha512(payload).hexdigest() != expected:
        raise ValueError("CPython NuGet package digest mismatch")
    return expected

def main():
    root = Path(__file__).resolve().parents[1] / ".gate1/windows-native/inputs"
    root.mkdir(parents=True,exist_ok=True)
    url = PACKAGE_URL
    package = root / "python.3.14.7.nupkg"
    if not package.exists():
        with urllib.request.urlopen(url, timeout=60) as response:
            package.write_bytes(response.read())
    # NuGet publishes the package hash in its catalog, not at a .sha512 sidecar.
    with urllib.request.urlopen(CATALOG_URL, timeout=30) as response:
        raw = response.read()
    metadata = json.loads(gzip.decompress(raw) if raw.startswith(b"\x1f\x8b") else raw)
    payload = package.read_bytes()
    expected = verify_package(payload, metadata)
    target = root / "python314"
    if target.exists():
        raise FileExistsError("Keep the existing interpreter input")
    with zipfile.ZipFile(package) as archive:
        for entry in archive.infolist():
            path = Path(entry.filename)
            if path.is_absolute() or ".." in path.parts or ":" in entry.filename:
                raise ValueError("Unexpected CPython archive path")
        archive.extractall(target)
    (root / "python-provenance.json").write_text(json.dumps({"url":url,"version":"3.14.7", "sha512":expected,
        "catalog_url":CATALOG_URL, "publisher":metadata["authors"],
        "sha256":hashlib.sha256(payload).hexdigest(),"bytes":len(payload)},indent=2)+"\n")
    (root / "python-publisher.json").write_text(json.dumps(metadata, indent=2)+"\n")
    print("Prepared project-local CPython 3.14.7", hashlib.sha256(payload).hexdigest())

if __name__ == "__main__":
    main()

"""Materialize reviewed native OCR pins without running package scripts."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".gate1/windows-native"

def main():
    lock = json.loads((ROOT / "package_windows/ocr-lock.json").read_text())
    packages = WORK / "native-packages"
    packages.mkdir(exist_ok=True)
    sources = []
    for item in lock["packages"]:
        url = item["url"]
        if not url.startswith(("https://conda.anaconda.org/conda-forge/win-64/",
                               "https://conda.anaconda.org/conda-forge/noarch/")):
            raise ValueError("OCR package escaped the reviewed native channel")
        archive = packages / url.rsplit("/", 1)[-1]
        if not archive.exists():
            with urllib.request.urlopen(url, timeout=120) as response, archive.open("xb") as target:
                shutil.copyfileobj(response, target)
        with archive.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != item["sha256"]:
                raise ValueError(f"Native package digest mismatch: {archive.name}")
        target = packages / item["name"]
        if not target.exists():
            subprocess.run([str(WORK / "inputs/micromamba.exe"), "package", "extract", str(archive), str(target)], check=True)
        sources.append(target)
    # Select by PE imports, preserving exactly one unambiguous byte sequence
    # per DLL name. No PATH/system Tesseract fallback is used.
    import pefile
    available = {}
    for root in sources:
        for path in root.rglob("*.dll"):
            key = path.name.lower()
            if key in available and available[key].read_bytes() != path.read_bytes():
                raise ValueError(f"Ambiguous OCR native library: {key}")
            available[key] = path
    tesseract = packages / "tesseract/Library/bin/tesseract.exe"
    if not tesseract.is_file():
        raise ValueError("Native Tesseract executable is unavailable")
    bundle = WORK / "ocr-bundle-final"
    if bundle.exists():
        raise FileExistsError("Preserve the existing OCR bundle")
    binary = bundle / "bin"
    binary.mkdir(parents=True)
    queue, copied = [tesseract], set()
    system = Path(__import__("os").environ["SystemRoot"]) / "System32"
    while queue:
        path = queue.pop()
        if path.name.lower() in copied:
            continue
        copied.add(path.name.lower())
        shutil.copy2(path, binary / path.name)
        with pefile.PE(str(path)) as pe:
            if pe.FILE_HEADER.Machine != 0x8664:
                raise ValueError("OCR input is not Windows x86-64")
            for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
                name = entry.dll.decode("ascii").lower()
                if name in available:
                    queue.append(available[name])
                elif name.startswith(("api-ms-win-", "ext-ms-win-")) or (system / name).is_file():
                    continue
                else:
                    raise ValueError(f"Unresolved OCR DLL: {name}")
    data_roots = [p.parent for p in (packages / "tesseract").rglob("eng.traineddata")]
    if len(data_roots) != 1:
        raise ValueError("Ambiguous English OCR data")
    data = bundle / "tessdata"
    (data / "configs").mkdir(parents=True)
    shutil.copy2(data_roots[0] / "eng.traineddata", data / "eng.traineddata")
    # conda-forge supplies trained data but omits this one-line Tesseract
    # configuration. Keep it as reviewed input, rather than a host fallback.
    shutil.copy2(ROOT / "package_windows/ocr-tsv.txt", data / "configs/tsv")
    licenses = bundle / "licenses"
    licenses.mkdir()
    for source in sources:
        origin = source / "info/licenses"
        if origin.is_dir():
            shutil.copytree(origin, licenses / source.name)
    # Use the captured preparer's authoritative, hash-pinned license texts.
    import sys
    sys.path.insert(0, str(ROOT))
    from tools.prepare_ocr_bundle import OFFICIAL_LICENSES
    for key, value in OFFICIAL_LICENSES.items():
        with urllib.request.urlopen(value["url"], timeout=30) as response:
            payload = response.read(128 * 1024)
        if hashlib.sha256(payload).hexdigest() != value["sha256"]:
            raise ValueError("OCR license digest mismatch")
        (licenses / (key + "-LICENSE.txt")).write_bytes(payload)
    from tools.pyinstaller_ocr import validate_tesseract_bundle
    validate_tesseract_bundle(bundle)
    subprocess.run([str(binary / "tesseract.exe"), "--version"], check=True)
    inventory = [{"path": str(p.relative_to(bundle)).replace("\\", "/"),
                  "sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "bytes": p.stat().st_size}
                 for p in sorted(bundle.rglob("*")) if p.is_file()]
    (WORK / "ocr-inventory.json").write_text(json.dumps(inventory, indent=2) + "\n")

if __name__ == "__main__":
    main()

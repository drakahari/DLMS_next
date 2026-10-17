"""Download build inputs into ignored storage; never install host software.

Downloads use anonymous HTTPS, not Git Credential Manager. The acquisition
record retains exact URLs and digests; execution is a separate reviewed step.
"""
from pathlib import Path
import hashlib
import json
import urllib.request
import urllib.parse

ROOT = Path(__file__).resolve().parents[1] / ".gate1/windows-native/inputs"

def fetch(url, name, expected):
    target = ROOT / name
    if target.exists():
        raise FileExistsError(f"Preserve existing acquisition: {target}")
    with urllib.request.urlopen(url, timeout=90) as response, target.open("xb") as output:
        final = urllib.parse.urlsplit(response.url)._replace(query="", fragment="").geturl()
        while block := response.read(1024 * 1024):
            output.write(block)
    with target.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    if digest!=expected:raise ValueError(f'Pinned input digest mismatch: {name}')
    return {"url": url, "resolved_url": final, "file": name, "bytes": target.stat().st_size,"sha256":digest}

def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    rows = []
    rows.append(fetch("https://github.com/jrsoftware/issrc/releases/download/is-7_1_0/innosetup-7.1.0-x64.exe", "innosetup-7.1.0-x64.exe",
                      '0362a383ed217d4c4239b5933866dd96d3eb2102737da92f80f6057a4b40df2f'))
    with urllib.request.urlopen("https://api.anaconda.org/package/conda-forge/micromamba", timeout=30) as response:
        metadata = json.load(response)
    choices = [x for x in metadata["files"] if x["basename"]=='win-64/micromamba-2.9.0-0.tar.bz2'
               and "main" in x.get("labels", [])]
    if len(choices)!=1:raise ValueError('Pinned micromamba publisher record unavailable')
    selected=choices[0]
    row = fetch("https://conda.anaconda.org/conda-forge/" + selected["basename"], Path(selected["basename"]).name,
                '97a336f4ab794bd96a6a4da5e6ed63e75a1d31830414a182419b23d3b36f3fe0')
    if row["sha256"] != selected["sha256"]:
        raise ValueError("Micromamba does not match publisher metadata")
    row["publisher_sha256"] = selected["sha256"]
    rows.append(row)
    (ROOT / "acquisition.json").write_text(json.dumps(rows, indent=2) + "\n")
    print(json.dumps(rows, indent=2))

if __name__ == "__main__":
    main()

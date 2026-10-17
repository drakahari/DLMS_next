"""Create bounded malformed imports from the accepted synthetic portable fixtures."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import stat
import zipfile

from desktop.isolation import AREA


def copy_zip(source: Path, target: Path, *, drop=(), alter=None, extra=None) -> None:
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as output:
        for info in original.infolist():
            if info.filename in drop:
                continue
            data = original.read(info.filename)
            if alter and info.filename in alter:
                data = alter[info.filename](data)
            output.writestr(info, data)
        if extra:
            for name, data in extra.items():
                output.writestr(name, data)


def main() -> int:
    root = AREA / "fixtures/data-safety-invalid"
    root.mkdir(parents=True, exist_ok=True)
    ordinary = AREA / "fixtures/closure-portable-media.zip"
    pack = AREA / "fixtures/closure-pack-datasets.zip"
    with zipfile.ZipFile(ordinary) as archive:
        asset = next(name for name in archive.namelist() if name.startswith("assets/") and not name.endswith("/"))
    values = {}
    valid = ordinary.read_bytes()
    (root / "ordinary-truncated.zip").write_bytes(valid[:-22])
    copy_zip(ordinary, root / "ordinary-invalid-manifest.zip",
             alter={"dlms-quiz-bundle.json": lambda _: b"{}"})
    copy_zip(ordinary, root / "ordinary-unsafe-path.zip", extra={"../escape.txt": b"synthetic"})
    copy_zip(ordinary, root / "ordinary-missing-media.zip", drop={asset})
    copy_zip(ordinary, root / "ordinary-inconsistent-media.zip", alter={asset: lambda value: value + b"changed"})
    with zipfile.ZipFile(pack) as archive:
        pack_manifest = next(name for name in archive.namelist() if name.endswith("/manifest.json"))
    copy_zip(pack, root / "pack-missing-manifest.zip", drop={pack_manifest})
    link = zipfile.ZipInfo("DLMS_Study_closure_datasets/unsafe-link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(pack) as original, zipfile.ZipFile(root / "pack-unsafe-link.zip", "w", zipfile.ZIP_DEFLATED) as output:
        for info in original.infolist():
            output.writestr(info, original.read(info.filename))
        output.writestr(link, "../escape")
    for path in sorted(root.glob("*.zip")):
        assert path.stat().st_size < 4 * 1024 * 1024
        values[path.name] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}
    (root / "inventory.json").write_text(json.dumps(values, indent=2) + "\n")
    print(json.dumps(values, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

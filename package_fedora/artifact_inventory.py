"""Read-only SHA-256 inventory for an extracted one-folder artifact."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    if not root.is_dir() or args.output.resolve().is_relative_to(root):
        raise ValueError("Inventory output must be outside the package")
    entries = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            if not path.resolve().is_relative_to(root):
                raise ValueError(f"Package symlink escapes payload: {path}")
            entries.append({"path": path.relative_to(root).as_posix(),
                            "kind": "symlink", "target": os.readlink(path), "bytes": 0})
        elif path.is_file():
            entries.append({"path": path.relative_to(root).as_posix(), "kind": "file",
                            "bytes": path.stat().st_size, "sha256": sha256(path)})
    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    result = {"root": str(root), "files": len(entries),
              "total_file_bytes": sum(entry["bytes"] for entry in entries),
              "manifest_sha256": hashlib.sha256(canonical).hexdigest(),
              "entries": entries}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "entries"}, indent=2))


if __name__ == "__main__":
    main()

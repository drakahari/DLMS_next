"""Keep an immutable, verified synthetic profile copy outside a destructive target."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil

from desktop.isolation import AREA, profile_paths
from desktop.maintenance import _file_inventory, _directory_inventory


def inventory(root: Path) -> dict[str, str]:
    return _file_inventory(root)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--label", default="before")
    args = parser.parse_args()
    source = profile_paths(args.profile, create=False)["root"]
    before = inventory(source)
    before_directories = _directory_inventory(source)
    if not args.label.replace("-", "").isalnum():
        raise ValueError("Retained-copy label must contain only letters, digits or hyphens")
    target = AREA / "retained" / f"{args.profile}-{args.label}"
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"Verified recovery copy already exists: {target}")
    shutil.copytree(source, target, symlinks=True)
    after = inventory(target)
    if before != after or before_directories != _directory_inventory(target) or before != inventory(source):
        raise RuntimeError("Retained synthetic recovery copy differs")
    report = target.parent / f"{args.profile}-{args.label}-inventory.json"
    report.write_text(json.dumps(after, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"profile": args.profile, "files": len(after), "retained": str(target)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

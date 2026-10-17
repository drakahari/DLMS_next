"""Mark one project-local synthetic root for the Fedora package acceptance."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    project = Path(__file__).resolve().parent.parent
    allowed = (project / ".gate1" / "packaging").resolve()
    requested = args.root.absolute()
    if not requested.is_relative_to(allowed) or requested == allowed:
        raise ValueError("Disposable package data root must be under this project's ignored .gate1/packaging area")
    for component in (requested, *requested.parents):
        if component == allowed.parent:
            break
        if component.is_symlink():
            raise ValueError("Disposable package root contains a symlink")
    requested.mkdir(mode=0o700, parents=True, exist_ok=True)
    marker = requested / ".dlms-desktop-disposable.json"
    if marker.exists() or marker.is_symlink():
        raise FileExistsError("Disposable marker already exists; preserve this root")
    fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump({"kind": "dlms-desktop-fedora-package-feasibility", "version": 1}, stream)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    print(requested)


if __name__ == "__main__":
    main()

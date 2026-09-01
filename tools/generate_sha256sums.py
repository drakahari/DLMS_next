"""Generate a portable SHA256SUMS.txt manifest for staged release artifacts."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Write SHA256 checksums for final DLMS release files."
    )
    parser.add_argument("artifacts", nargs="+", type=Path, help="files to include")
    parser.add_argument(
        "--output", type=Path, default=Path("SHA256SUMS.txt"), help="manifest path"
    )
    args = parser.parse_args()

    output = args.output.resolve()
    artifacts = []
    for artifact in args.artifacts:
        resolved = artifact.resolve()
        if resolved == output:
            parser.error("the checksum manifest cannot be an input artifact")
        if not resolved.is_file():
            parser.error(f"artifact is not a file: {artifact}")
        artifacts.append(resolved)

    if len(set(artifacts)) != len(artifacts):
        parser.error("each artifact must be listed only once")
    if len({path.name for path in artifacts}) != len(artifacts):
        parser.error("artifact filenames must be unique")

    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{sha256_file(path)}  {path.name}" for path in sorted(artifacts, key=lambda p: p.name)]
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

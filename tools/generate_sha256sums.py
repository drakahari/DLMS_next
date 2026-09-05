"""Validate and checksum the canonical final DLMS release package set."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from verify_release_artifact import release_version
from verify_release_package import expected_packages, verify_release_package


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
    parser.add_argument(
        "--source-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root containing app.py and release_assets",
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
    if {path.parent for path in artifacts} != {output.parent}:
        parser.error(
            "all final packages and SHA256SUMS.txt must use one canonical directory"
        )

    source_root = args.source_root.resolve()
    version = release_version(source_root)
    expected_names = set(expected_packages(version))
    actual_names = {path.name for path in artifacts}
    if actual_names != expected_names:
        missing = ", ".join(sorted(expected_names - actual_names))
        extra = ", ".join(sorted(actual_names - expected_names))
        details = []
        if missing:
            details.append(f"missing: {missing}")
        if extra:
            details.append(f"unexpected: {extra}")
        parser.error(
            "checksums require the exact canonical final package set ("
            + "; ".join(details)
            + ")"
        )
    for artifact in artifacts:
        errors = verify_release_package(artifact, source_root)
        if errors:
            parser.error(
                f"final package {artifact.name} failed validation: "
                + "; ".join(errors)
            )

    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{sha256_file(path)}  {path.name}" for path in sorted(artifacts, key=lambda p: p.name)]
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

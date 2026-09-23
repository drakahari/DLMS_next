"""Accept actual GitHub release downloads using the existing package gates."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import uuid

from verify_release_artifact import release_version, sha256_file, verify_checksum
from verify_release_package import (
    clean_extract_and_smoke, expected_packages, verify_release_package,
)

ROOT = Path(__file__).resolve().parents[1]


def tagged_source(repository: Path, tag: str, destination: Path) -> str:
    """Read only the verifier's inputs from a local tag; never check it out."""
    commit = subprocess.check_output(
        ["git", "-C", str(repository), "rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}"],
        stderr=subprocess.PIPE, text=True,
    ).strip()
    for name in ("app.py", "release_assets/README.txt", "release_assets/sample_quiz.txt"):
        payload = subprocess.check_output(
            ["git", "-C", str(repository), "show", f"{commit}:{name}"],
            stderr=subprocess.PIPE,
        )
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    if release_version(destination) != tag.removeprefix("v"):
        raise ValueError("Local release tag APP_VERSION does not match requested tag")
    return commit


def download(repo: str, tag: str, name: str, destination: Path) -> None:
    environment = os.environ.copy()
    environment.update(GH_HOST="github.com", GH_PROMPT_DISABLED="1")
    subprocess.run(
        ["gh", "release", "download", tag, "--repo", f"github.com/{repo}",
         "--pattern", name, "--dir", str(destination)],
        env=environment, check=True, capture_output=True, timeout=600,
    )
    if not (destination / name).is_file():
        raise ValueError(f"Release download did not produce {name}")


def accept(args) -> tuple[dict, Path]:
    now = datetime.now(timezone.utc)
    output = (args.output_dir or ROOT / "build/downloaded-release" / args.tag /
              args.asset / (now.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])).resolve()
    # Exclusive creation protects both completed and failed acceptance evidence.
    output.mkdir(parents=True, exist_ok=False)
    record = {
        "schema_version": 1, "repository": args.repo, "release_tag": args.tag,
        "release_url": f"https://github.com/{args.repo}/releases/tag/{args.tag}",
        "asset_name": args.asset, "asset_sha256": None,
        "timestamp_utc": now.isoformat(), "source_tag_commit": None,
        "checksum_manifest_sha256": None, "checksum_manifest_result": "NOT_RUN",
        "package_verification_result": "NOT_RUN",
        "native_smoke_result": "NOT_RUN", "native_smoke_requested": args.smoke,
        "automated_acceptance": "FAILED", "manual_platform_check": "REQUIRED",
        "errors": [],
    }
    stage = "release source"
    try:
        with tempfile.TemporaryDirectory(prefix="dlms-download-source-") as temporary:
            source = Path(temporary)
            record["source_tag_commit"] = tagged_source(args.source_root, args.tag, source)
            stage = "asset download"
            download(args.repo, args.tag, args.asset, output)
            package = output / args.asset
            record["asset_sha256"] = sha256_file(package)
            stage = "checksum manifest download"
            download(args.repo, args.tag, "SHA256SUMS.txt", output)
            stage = "checksum_manifest_result"
            manifest = output / "SHA256SUMS.txt"
            record["checksum_manifest_sha256"] = sha256_file(manifest)
            errors = verify_checksum(package, manifest)
            if errors:
                raise ValueError("; ".join(errors))
            record[stage] = "PASS"
            stage = "package_verification_result"
            errors = verify_release_package(package, source)
            if errors:
                raise ValueError("; ".join(errors))
            record[stage] = "PASS"
            if args.smoke:
                stage = "native_smoke_result"
                errors = clean_extract_and_smoke(package, source)
                if errors:
                    raise ValueError("; ".join(errors))
                record[stage] = "PASS"
            record["automated_acceptance"] = "PASSED"
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        if stage in record:
            record[stage] = "FAIL"
        # Do not persist CLI stderr: it can include authentication diagnostics.
        record["errors"].append(f"{stage}: {exc}")
    record["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    evidence = output / "acceptance.json"
    with evidence.open("x", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2)
        handle.write("\n")
    return record, evidence


def report(record, evidence):
    return ("DLMS DOWNLOADED RELEASE ACCEPTANCE\n"
            f"Tag: {record['release_tag']}\nAsset: {record['asset_name']}\n"
            f"Checksum: {record['checksum_manifest_result']}\n"
            f"Package verification: {record['package_verification_result']}\n"
            f"Native smoke: {record['native_smoke_result']}\n"
            f"Automated acceptance: {record['automated_acceptance']}\n"
            "Manual platform check: REQUIRED\n"
            f"Evidence: {evidence}")


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--repo", required=True, help="GitHub OWNER/REPO")
    result.add_argument("--tag", required=True, help="explicit release tag, e.g. v3.2.1")
    result.add_argument("--asset", required=True, help="one canonical final package filename")
    result.add_argument("--source-root", type=Path, default=ROOT,
                        help="local repository containing the trusted release tag")
    result.add_argument("--output-dir", type=Path, help="new directory; never overwritten")
    result.add_argument("--smoke", action="store_true",
                        help="also clean-extract and launch on the matching native host")
    return result


def main(argv=None):
    argument_parser = parser()
    args = argument_parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", args.repo):
        argument_parser.error("--repo must be OWNER/REPO on github.com")
    if not re.fullmatch(r"v\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?", args.tag):
        argument_parser.error("--tag must be an explicit version tag such as v3.2.1")
    if args.asset not in expected_packages(args.tag[1:]):
        argument_parser.error("--asset must be a supported final package for --tag")
    try:
        record, evidence = accept(args)
    except OSError as exc:
        print(f"DLMS DOWNLOADED RELEASE ACCEPTANCE FAILED: {exc}", file=sys.stderr)
        return 1
    print(report(record, evidence))
    for error in record["errors"]:
        print(f"ERROR: {error}", file=sys.stderr)
    return 0 if record["automated_acceptance"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())

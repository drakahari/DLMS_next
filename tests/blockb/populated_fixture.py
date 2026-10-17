"""Create a synthetic portable archive with recovery, Review and credentials."""
from __future__ import annotations

import argparse
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import uuid

from desktop.backend import acquire_writer_lock
from desktop.isolation import PROJECT, isolated_environment, profile_paths
from desktop.profile_state import read_manifest


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", required=True)
    p.add_argument("--backup-only", action="store_true")
    args = p.parse_args()
    paths = profile_paths(args.profile)
    manifest = read_manifest(paths, args.profile)
    env = isolated_environment(paths)
    env.update(PYTHONPATH=os.pathsep.join((str(PROJECT), str(PROJECT))),
               PYTHONNOUSERSITE="1", DLMS_DESKTOP_PROFILE_NAME=args.profile,
               DLMS_DESKTOP_PORT=str(manifest["port"]), DLMS_DESKTOP_NONCE="0" * 32)
    os.environ.clear(); os.environ.update(env)
    lock = acquire_writer_lock(paths["root"] / "backend-writer.lock")
    try:
        sys.path.insert(0, str(PROJECT))
        import app
        from dlms.services import certifications as cert
        from PIL import Image
        def request(action, data, **kw):
            with app.get_db() as conn:
                state = cert.state(conn.cursor())
            return dict(request_id=uuid.uuid4().hex, action=action, data=data, **state, **kw)
        if not args.backup_only:
            image = BytesIO(); Image.new("RGB", (80, 80), "white").save(image, "PNG")
            with app.get_db() as conn:
                cid = cert.apply(conn, request("certification", dict(name="Synthetic credential",
                    issuer="Example issuer", earned="2025-06-01")), {"badge": image.getvalue()})["id"]
            with app.get_db() as conn:
                cycle = cert.detail(conn.cursor(), cid)["cycles"][0]["id"]
            with app.get_db() as conn:
                tid = cert.apply(conn, request("training", dict(name="Synthetic workshop",
                    completed="2026-09-01", hours=8)))["id"]
            with app.get_db() as conn:
                aid = cert.apply(conn, request("allocation", dict(hours=6, submitted=5, accepted=3),
                    cycle_id=cycle, training_id=tid))["id"]
        archive, manifest_data = app._create_dlms_backup("blockb-populated-synthetic")
        with app.get_db() as conn:
            counts = {name: conn.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
                      for name in ("attempts", "certifications", "certification_training", "certification_attachments")}
        report = {"archive": str(archive), "counts": counts,
                  "archive_files": manifest_data.get("file_count")}
        (paths["root"] / "blockb-populated-fixture.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
    finally:
        lock.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

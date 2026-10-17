"""Small Desktop acceptance records and read-only status for existing request IDs."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import threading

from .isolation import assert_safe_leaf
from .profile_state import atomic_json, read_manifest
from .recovery import canonical, digest, fsync_directory, RecoveryFailure

MAX_RECORDS = 256
MAX_BODY = 128 * 1024
KINDS = {
    "study_mistakes": "/api/quiz-composer/study-mistakes/create",
    "review_save": "/api/review-marks/save",
    "review_generate": "/api/review-marks/generate",
}
IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{16,100}\Z")


class PendingRequests:
    def __init__(self, paths, name, app, gate: threading.RLock):
        self.paths, self.name, self.app, self.gate = paths, name, app, gate
        self.root = paths["root"] / "pending-requests"
        if self.root.is_symlink() or (self.root.exists() and not self.root.is_dir()):
            raise RecoveryFailure("Desktop pending-request directory is unsafe", 500)
        self.root.mkdir(mode=0o700, exist_ok=True)
        # On a first launch the origin manifest is published only after
        # authenticated readiness. There cannot yet be accepted records.
        if read_manifest(paths, name) is not None:
            self.validate_all()
        elif list(self.root.iterdir()):
            raise RecoveryFailure("Request evidence exists without Desktop identity", 500)

    def context(self):
        manifest = read_manifest(self.paths, self.name)
        if manifest is None:
            raise RecoveryFailure("Desktop profile identity is unavailable", 503)
        return {"profile_uuid": manifest["uuid"], "epoch": manifest["epoch"]}

    def _require_context(self, requested):
        if not isinstance(requested, dict) or requested != self.context():
            raise RecoveryFailure("Request belongs to another Desktop dataset; evidence was not replayed", 409, "stale_dataset")

    def _parts(self, envelope):
        if not isinstance(envelope, dict) or set(envelope) != {"kind", "payload", "context"}:
            raise RecoveryFailure("Invalid Desktop request envelope", 400)
        kind, payload = envelope["kind"], envelope["payload"]
        if kind not in KINDS or not isinstance(payload, dict):
            raise RecoveryFailure("Unsupported Desktop request", 400)
        identifier = payload.get("request_id")
        if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier):
            raise RecoveryFailure("Invalid immutable request ID", 400)
        self._require_context(envelope["context"])
        return kind, payload, identifier

    def _path(self, kind, identifier):
        return self.root / f"{kind}-{hashlib.sha256(identifier.encode()).hexdigest()}.json"

    def _record(self, kind, payload, identifier, context):
        value = {"version": 1, "kind": kind, "id": identifier,
                 "payload": payload, "payload_hash": digest(payload), "context": context}
        value["record_hash"] = digest(value)
        return value

    def _read(self, path):
        assert_safe_leaf(path)
        if path.stat().st_size > MAX_BODY:
            raise RecoveryFailure("Desktop request record is oversized", 500)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if (not isinstance(value, dict) or set(value) != {"version", "kind", "id", "payload",
                    "payload_hash", "context", "record_hash"} or value["version"] != 1
                    or value["kind"] not in KINDS or not IDENTIFIER.fullmatch(value["id"])
                    or self._path(value["kind"], value["id"]) != path
                    or digest(value["payload"]) != value["payload_hash"]
                    or digest({k: v for k, v in value.items() if k != "record_hash"}) != value["record_hash"]):
                raise ValueError("invalid record")
            return value
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise RecoveryFailure(f"Desktop request record needs inspection: {path.name}", 500) from exc

    def validate_all(self):
        with self.gate:
            files = list(self.root.glob("*.json"))
            if len(files) > MAX_RECORDS:
                raise RecoveryFailure("Too many pending Desktop requests", 500)
            context = self.context()
            for path in files:
                value = self._read(path)
                if value["context"] != context:
                    raise RecoveryFailure("Pending Desktop request belongs to another dataset; inspect its evidence", 500)

    def list_records(self):
        with self.gate:
            self.validate_all()
            return [{"kind": item["kind"], "payload": item["payload"],
                     "payload_hash": item["payload_hash"], "context": item["context"]}
                    for item in (self._read(path) for path in sorted(self.root.glob("*.json")))]

    def envelope(self, record):
        return {"kind": record["kind"], "payload": record["payload"], "context": record["context"]}

    def count(self):
        return len(list(self.root.glob("*.json")))

    def _source_journals(self):
        root = Path(self.app._quiz_publication_staging_root())
        if root.is_symlink() or (root.exists() and not root.is_dir()):
            return True
        return bool(list(root.glob("publication_*.json*"))) if root.exists() else False

    def status(self, envelope):
        kind, payload, identifier = self._parts(envelope)
        conn = self.app.get_db()
        try:
            if kind == "study_mistakes":
                from dlms.services import study_mistakes as mistakes
                expected = mistakes.digest(payload)
                row = conn.execute("SELECT * FROM study_mistake_actions WHERE request_id=?", (identifier,)).fetchone()
                generation = mistakes.state(conn.cursor())
            else:
                from dlms.services import exam_plans
                expected = exam_plans.digest(payload)
                row = conn.execute("SELECT * FROM review_mark_actions WHERE request_id=?", (identifier,)).fetchone()
                review_state = conn.execute("SELECT generation,revision FROM review_mark_state WHERE id=1").fetchone()
                generation = review_state["generation"]
            if row is None:
                if self._source_journals():
                    return {"state": "unknown", "request_id": identifier}
                if generation != payload.get("generation"):
                    return {"state": "stale", "request_id": identifier}
                if kind == "study_mistakes":
                    try:
                        current = mistakes.pool(conn.cursor(), mistakes.scope(**payload["scope"]), self.app._study_mistake_options())
                        if current["fingerprint"] != payload.get("fingerprint"):
                            return {"state": "stale", "request_id": identifier}
                    except (ValueError, TypeError, KeyError):
                        return {"state": "stale", "request_id": identifier}
                elif review_state["revision"] != payload.get("revision"):
                    return {"state": "stale", "request_id": identifier}
                return {"state": "absent", "request_id": identifier}
            row = dict(row)
            if row["input_hash"] != expected or row["generation"] != payload.get("generation"):
                return {"state": "stale", "request_id": identifier}
            state = row["state"]
            if kind == "study_mistakes" and state == "published":
                url = mistakes.destination(row, self.app._study_mistake_options())
                return {"state": "committed", "request_id": identifier, "url": url} if url else {"state": "unknown", "request_id": identifier}
            if kind == "review_save" and state == "done":
                return {"state": "committed", "request_id": identifier, "result": json.loads(row["result_json"])}
            if kind == "review_generate" and state == "published":
                from dlms.services import exam_plans
                # Status is read-only. _exam_plan_options also loads portal
                # config, and that loader may create or repair a file.
                registry = self.app.load_registry()
                entry = next((item for item in registry if item.get("id") == row["quiz_id"] and item.get("html") == row["html"]), None)
                url = exam_plans.valid_link(entry, data_folder=self.app.DATA_FOLDER,
                                            quiz_folder=self.app.QUIZ_FOLDER,
                                            artifact_names=self.app._quiz_artifact_names) if entry else None
                return {"state": "committed", "request_id": identifier, "url": url} if url else {"state": "unknown", "request_id": identifier}
            if state == "retryable":
                if generation != row["generation"]:
                    return {"state": "stale", "request_id": identifier}
                if kind != "study_mistakes" and review_state["revision"] != payload.get("revision"):
                    return {"state": "stale", "request_id": identifier}
                return {"state": "retryable", "request_id": identifier}
            if state in {"reserved", "committed", "pending"}:
                return {"state": "pending", "request_id": identifier,
                        "detail": "Original request has an unfinished server action; restart recovery before retrying"}
            return {"state": "unknown", "request_id": identifier}
        finally:
            conn.close()

    def accept(self, envelope):
        kind, payload, identifier = self._parts(envelope)
        record = self._record(kind, payload, identifier, envelope["context"])
        if len(canonical(record).encode()) > MAX_BODY:
            raise RecoveryFailure("Desktop request is too large", 413)
        with self.gate:
            path = self._path(kind, identifier)
            assert_safe_leaf(path)
            if path.exists():
                if self._read(path) != record:
                    raise RecoveryFailure("Request ID was already used with different content", 409)
            else:
                if self.count() >= MAX_RECORDS:
                    raise RecoveryFailure("Desktop request recovery storage is full", 507)
                atomic_json(path, record)
            return KINDS[kind], record

    def acknowledge(self, envelope):
        kind, payload, identifier = self._parts(envelope)
        with self.gate:
            path = self._path(kind, identifier)
            assert_safe_leaf(path)
            if not path.exists():
                return {"ok": True, "already_cleared": True}
            record = self._read(path)
            if record["payload"] != payload or record["context"] != envelope["context"]:
                raise RecoveryFailure("Request acknowledgment has different content", 409)
            status = self.status(envelope)
            if status["state"] != "committed":
                raise RecoveryFailure("Request result is not committed; evidence was retained", 409)
            try:
                if (os.environ.get("DLMS_DESKTOP_AUTOMATED") == "1"
                        and os.environ.get("DLMS_DESKTOP_TEST_FAIL_REQUEST_CLEANUP") == "1"):
                    raise OSError("Synthetic Desktop request cleanup failure")
                path.unlink()
                fsync_directory(self.root)
            except OSError as exc:
                raise RecoveryFailure("Request saved, but recovery cleanup failed; keep this evidence", 500) from exc
            return {"ok": True, "result": status}

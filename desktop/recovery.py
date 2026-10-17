"""Bounded, Desktop-only durable handoff for Study events and Exam attempts.

The accepted file is the recovery authority. Chromium storage is a convenience,
not the crash-durability boundary. This module changes no application schema.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import threading

from .isolation import assert_safe_leaf
from .profile_state import atomic_json, read_manifest

MAX_BODY = 768 * 1024
MAX_RECORDS = 256
IDENTIFIER = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")


class RecoveryFailure(Exception):
    def __init__(self, message: str, status: int = 409, code: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def fsync_directory(path: Path) -> None:
    if os.name == "nt":
        from .platform_files import sync_directory
        return sync_directory(path)
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class DurableActions:
    def __init__(self, paths: dict[str, Path], name: str, app):
        self.paths = paths
        self.name = name
        self.app = app
        self.lock = threading.RLock()
        self.root = paths["root"] / "durable-actions"
        if self.root.is_symlink() or (self.root.exists() and not self.root.is_dir()):
            raise RecoveryFailure("Desktop recovery directory is unsafe", 500)
        self.root.mkdir(mode=0o700, exist_ok=True)
        self.quarantine = paths["root"] / "durable-actions-quarantine"
        self.warnings: list[str] = []

    def _manifest(self):
        manifest = read_manifest(self.paths, self.name)
        if manifest is None:
            raise RecoveryFailure("Desktop profile identity is not published", 503)
        return manifest

    def _path(self, kind: str, identifier: str) -> Path:
        # Hash instead of placing browser-controlled identity in a filename.
        return self.root / f"{kind}-{hashlib.sha256(identifier.encode()).hexdigest()}.json"

    def _identity(self, kind, payload):
        if kind not in {"study", "exam"} or not isinstance(payload, dict):
            raise RecoveryFailure("Only Study and Exam actions are accepted", 400)
        identifier = payload.get("eventId" if kind == "study" else "attemptId")
        if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier):
            raise RecoveryFailure("Invalid immutable action identity", 400)
        quiz_id = payload.get("quizId")
        if isinstance(quiz_id, bool) or not isinstance(quiz_id, int) or quiz_id <= 0:
            raise RecoveryFailure("Invalid quiz identity", 400)
        if kind == "study" and payload.get("contract") != 2:
            raise RecoveryFailure("Only current Study response contracts are accepted", 400)
        if kind == "exam" and payload.get("mode") != "Exam":
            raise RecoveryFailure("Only Exam attempts are accepted", 400)
        return identifier, quiz_id

    def _source(self, cur, quiz_id, fingerprint):
        entry = self.app._quiz_registry_entry(self.app.load_registry(), quiz_id)
        if entry is None:
            raise RecoveryFailure("Quiz is no longer available", 409)
        try:
            self.app._generated_practice_lifecycle._verify_artifact(
                entry, quiz_id, fingerprint, data_folder=self.app.DATA_FOLDER,
                quiz_artifact_names=self.app._quiz_artifact_names,
            )
        except (ValueError, OSError, UnicodeError) as exc:
            raise RecoveryFailure(str(exc), 409) from exc
        revision = self.app._study_service.assessment_revision(cur, quiz_id)
        return revision

    def _validated_exam(self, cur, payload):
        return self.app._validate_attempt_payload(cur, payload)

    @staticmethod
    def _exam_summary_matches(row, payload):
        """Reject obvious reused-ID conflicts before classifying uncertainty."""
        return (row["quiz_id"], row["score"], row["total"], row["percent"],
                row["started_at"], row["completed_at"], row["time_remaining"], row["mode"]) == (
                    payload.get("quizId"), payload.get("score"), payload.get("total"),
                    payload.get("percent"), payload.get("startedAt"), payload.get("completedAt"),
                    payload.get("timeRemaining"), payload.get("mode"))

    def accept(self, request: dict) -> tuple[dict, int]:
        if not isinstance(request, dict) or set(request) != {"kind", "payload", "fingerprint"}:
            raise RecoveryFailure("Invalid Desktop action envelope", 400)
        kind, payload, fingerprint = request["kind"], request["payload"], request["fingerprint"]
        identifier, quiz_id = self._identity(kind, payload)
        if not isinstance(fingerprint, str) or not fingerprint.startswith("sha256:") or len(fingerprint) != 71:
            raise RecoveryFailure("Quiz page identity is missing", 400)
        with self.lock:
            manifest = self._manifest()
            path = self._path(kind, identifier)
            assert_safe_leaf(path)
            if path.exists():
                record = self._read(path)
                if (record["kind"] != kind or record["id"] != identifier
                        or record["payload"] != payload or record["fingerprint"] != fingerprint):
                    raise RecoveryFailure("Action identity already has different content", 409)
                return self._apply(path, record, manifest)
            if len(list(self.root.glob("*.json"))) >= MAX_RECORDS:
                raise RecoveryFailure("Desktop recovery storage is full; action was not retained", 507)
            conn = self.app.get_db()
            try:
                cur = conn.cursor()
                # A cleaned journal is not proof that this identity is unused.
                # Reconcile against the application's durable result first.
                if kind == "study":
                    prior = {"kind": kind, "id": identifier, "payload": payload}
                    if self._already_committed(conn, prior):
                        return {"ok": True, "event_id": identifier, "already_recorded": True}, 200
                else:
                    columns = {row[1] for row in cur.execute("PRAGMA table_info(attempts)")}
                    identity_col = "attempt_id" if "attempt_id" in columns else "id"
                    exists = cur.execute(
                        f"SELECT quiz_id,score,total,percent,started_at,completed_at,time_remaining,mode "
                        f"FROM attempts WHERE CAST({identity_col} AS TEXT)=?",
                        (identifier,),
                    ).fetchone()
                    if exists:
                        if not self._exam_summary_matches(exists, payload):
                            raise RecoveryFailure("Committed Exam identity has different content", 409)
                        try:
                            validated_prior = self._validated_exam(cur, payload)
                        except self.app._study_service.LearningPayloadError as exc:
                            raise RecoveryFailure(
                                "An Exam result with this ID exists, but the current quiz cannot verify it. Check History before retrying.",
                                409, "exam_existing_unverifiable",
                            ) from exc
                        prior = {"kind": kind, "id": identifier, "validated_exam": validated_prior}
                        if self._already_committed(conn, prior):
                            return {"ok": True, "attempt_id": identifier, "already_recorded": True}, 200
                revision = self._source(cur, quiz_id, fingerprint)
                if kind == "study" and payload.get("assessmentRevision") != revision:
                    raise RecoveryFailure("Study source revision changed; reload before saving", 409)
                if kind == "study":
                    try:
                        self.app._study_service.owned(cur, payload)
                    except self.app._study_service.LearningPayloadError as exc:
                        raise RecoveryFailure(f"Study action is stale; no action was retained: {exc}", 409) from exc
                if kind == "exam":
                    try:
                        validated = self._validated_exam(cur, payload)
                    except self.app._study_service.LearningPayloadError as exc:
                        raise RecoveryFailure(
                            "This Exam attempt was not confirmed as retained or saved. Its current source or request content could not be verified. Check History for this attempt before trying again.",
                            409, "exam_validation_unconfirmed",
                        ) from exc
                else:
                    validated = None
            finally:
                conn.close()
            record = {"version": 1, "kind": kind, "id": identifier,
                      "profile_uuid": manifest["uuid"], "epoch": manifest["epoch"],
                      "fingerprint": fingerprint, "assessment_revision": revision,
                      "payload": payload, "validated_exam": validated, "payload_hash": digest(payload)}
            record["record_hash"] = digest(record)
            try:
                if len(canonical(record).encode()) > MAX_BODY:
                    raise RecoveryFailure("Action exceeds Desktop recovery limit", 413)
                if os.environ.get("DLMS_DESKTOP_TEST_FAIL_ACTION_ACCEPT") == "1":
                    raise OSError("Synthetic recovery storage failure before acceptance")
                atomic_json(path, record)  # fsync file, atomic replace, fsync directory
            except OSError as exc:
                raise RecoveryFailure("Recovery storage unavailable; action was not retained", 507) from exc
            self._pause_for_test("accepted", identifier)
            return self._apply(path, record, manifest)

    def _read(self, path: Path) -> dict:
        assert_safe_leaf(path)
        try:
            if path.stat().st_size > MAX_BODY:
                raise ValueError("oversize")
            record = json.loads(path.read_text(encoding="utf-8"))
            if (not isinstance(record, dict) or set(record) != {"version", "kind", "id", "profile_uuid", "epoch",
                    "fingerprint", "assessment_revision", "payload", "validated_exam", "payload_hash", "record_hash"}
                    or record["version"] != 1 or digest(record["payload"]) != record["payload_hash"]
                    or digest({key: value for key, value in record.items() if key != "record_hash"}) != record["record_hash"]):
                raise ValueError("invalid record")
            payload_id, _ = self._identity(record["kind"], record["payload"])
            if payload_id != record["id"]:
                raise ValueError("payload and record identities differ")
            if self._path(record["kind"], record["id"]) != path:
                raise ValueError("filename and identity differ")
            return record
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise RecoveryFailure(f"Recovery record needs inspection: {path.name}", 500) from exc

    def _quarantine(self, path: Path, reason: str):
        if self.quarantine.is_symlink() or (self.quarantine.exists() and not self.quarantine.is_dir()):
            raise RecoveryFailure("Desktop recovery quarantine is unsafe", 500)
        self.quarantine.mkdir(mode=0o700, exist_ok=True)
        destination = self.quarantine / path.name
        if destination.exists() or destination.is_symlink():
            raise RecoveryFailure("Existing quarantine file needs inspection", 500)
        path.rename(destination)
        fsync_directory(self.root)
        fsync_directory(self.quarantine)
        self.warnings.append(f"Quarantined {path.name}: {reason}")

    def _already_committed(self, conn, record):
        cur = conn.cursor()
        if record["kind"] == "study":
            row = cur.execute("SELECT payload_json FROM study_responses WHERE event_id=?", (record["id"],)).fetchone()
            if row is None:
                return False
            payload = record["payload"]
            normalized = {key: payload.get(key) for key in ("quizId", "sessionId", "eventId", "sequence", "questionOrdinal", "questionType", "wasCorrect", "selected", "assessmentRevision")}
            normalized["kind"] = payload.get("kind", "response")
            if row[0] != self.app._study_service.encode(normalized):
                raise RecoveryFailure("Committed Study identity has different content", 409)
            return True
        columns = {row[1] for row in cur.execute("PRAGMA table_info(attempts)")}
        identity_col = "attempt_id" if "attempt_id" in columns else "id"
        existing = cur.execute(f"SELECT 1 FROM attempts WHERE CAST({identity_col} AS TEXT)=?", (record["id"],)).fetchone()
        if existing is None:
            return False
        if not self.app._attempt_retry_matches_existing(cur, record["validated_exam"], columns):
            raise RecoveryFailure("Committed Exam identity has different content", 409)
        return True

    def _apply(self, path: Path, record: dict, manifest: dict) -> tuple[dict, int]:
        kind, identifier = record["kind"], record["id"]
        if record["profile_uuid"] != manifest["uuid"] or record["epoch"] != manifest["epoch"]:
            self._quarantine(path, "profile or epoch mismatch")
            raise RecoveryFailure("Action belongs to a different profile epoch; evidence was quarantined", 409)
        conn = self.app.get_db()
        try:
            if self._already_committed(conn, record):
                result = {"ok": True, "event_id" if kind == "study" else "attempt_id": identifier,
                          "already_recorded": True}
            else:
                cur = conn.cursor()
                try:
                    revision = self._source(cur, record["payload"]["quizId"], record["fingerprint"])
                except RecoveryFailure as exc:
                    self._quarantine(path, str(exc))
                    raise
                if revision != record["assessment_revision"]:
                    self._quarantine(path, "assessment revision changed")
                    raise RecoveryFailure("Quiz source changed; accepted action was quarantined", 409)
                try:
                    if kind == "study":
                        result, status = self.app._persist_study_response(conn, cur, record["payload"])
                        if status != 200 or result.get("ok") is not True:
                            raise RecoveryFailure("Study action was retained but could not be committed", 409)
                    else:
                        conn.execute("BEGIN IMMEDIATE")
                        result = self.app._attempt_service.persist_attempt(
                            conn, cur, record["payload"],
                            validate_attempt_payload=self.app._validate_attempt_payload,
                            attempt_retry_matches_existing=self.app._attempt_retry_matches_existing,
                            record_learning_event=self.app._record_learning_event,
                            json_module=json, print_message=print,
                        )
                except self.app._study_service.LearningPayloadError as exc:
                    conn.rollback()
                    self._quarantine(path, f"stale or invalid accepted action: {exc}")
                    raise RecoveryFailure("Accepted action became stale; evidence was quarantined", 409) from exc
                except Exception:
                    conn.rollback()
                    raise
            self._pause_for_test("committed", identifier)
        except RecoveryFailure:
            raise
        except Exception as exc:
            conn.rollback()
            self.warnings.append(f"Accepted {kind} action {identifier} is awaiting commit: {type(exc).__name__}")
            return {"ok": False, "retained": True, "error": "Action retained for recovery; application save is not yet confirmed."}, 202
        finally:
            conn.close()
        try:
            if os.environ.get("DLMS_DESKTOP_TEST_FAIL_ACTION_CLEANUP") == "1":
                raise OSError("Synthetic recovery cleanup failure")
            path.unlink()
            fsync_directory(self.root)
        except OSError:
            result["cleanup_pending"] = True
            self.warnings.append(f"Committed {kind} action {identifier} remains in recovery storage; cleanup pending")
        return result, 200

    def reconcile(self):
        with self.lock:
            files = sorted(self.root.glob("*.json"))
            if len(files) > MAX_RECORDS:
                raise RecoveryFailure("Too many accepted actions; inspect the profile before launch", 500)
            manifest = read_manifest(self.paths, self.name)
            if files and manifest is None:
                raise RecoveryFailure("Accepted actions exist without profile identity", 500)
            records = [(path, self._read(path)) for path in files]
            # One Study session's original sequence is the replay order.
            records.sort(key=lambda item: (0, str(item[1]["payload"].get("sessionId", "")),
                                           item[1]["payload"].get("sequence", 0))
                         if item[1]["kind"] == "study" else (1, "", 0))
            for path, record in records:
                try:
                    self._apply(path, record, manifest)
                except RecoveryFailure as exc:
                    self.warnings.append(str(exc))

    def pending_summary(self):
        with self.lock:
            quarantined = len(list(self.quarantine.glob("*.json"))) if self.quarantine.is_dir() else 0
            warnings = self.warnings[-4:]
            if quarantined:
                warnings = [*warnings, f"{quarantined} quarantined action(s) need manual inspection"]
            return {"count": len(list(self.root.glob("*.json"))),
                    "warnings": warnings}

    def _pause_for_test(self, phase: str, identifier: str):
        if (os.environ.get("DLMS_DESKTOP_AUTOMATED") != "1"
                or os.environ.get("DLMS_DESKTOP_TEST_PAUSE_PHASE") != phase):
            return
        marker = self.paths["root"] / f"recovery-pause-{phase}.json"
        atomic_json(marker, {"phase": phase, "id": identifier})
        # Only the exact automated process can be terminated by the driver;
        # it deliberately never reaches a timeout that could fake durability.
        import time
        while not (self.paths["root"] / "recovery-pause-release").exists():
            time.sleep(0.05)

"""Temporary screenshot OCR staging and cooperative cancellation services."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import threading
import time
from typing import Any, Callable, Iterable

from dlms.persistence import json_files


OCR_SCREENSHOT_MAX_FILES = 25
OCR_SCREENSHOT_MAX_FILE_BYTES = 16 * 1024 * 1024
OCR_SCREENSHOT_MAX_BATCH_BYTES = 64 * 1024 * 1024
OCR_SCREENSHOT_MAX_PIXELS = 40_000_000
OCR_SCREENSHOT_MAX_SIDE = 12_000
OCR_SCREENSHOT_STALE_SECONDS = 7 * 24 * 60 * 60
OCR_SCREENSHOT_ALLOWED_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp"})
OCR_SCREENSHOT_TASK_MARKER = ".dlms-ocr-screenshot-task.json"
_OPAQUE_ID_RE = re.compile(r"^[A-Za-z0-9]{12,40}$")


class OCRScreenshotBatchError(ValueError):
    """Raised when a screenshot batch cannot safely be staged."""


class OCRTaskBusyError(RuntimeError):
    """Raised when another request already owns the task's OCR process slot."""


class OCRTaskCancellationRegistry:
    """Runtime-only cancellation signals for bounded, request-owned OCR children."""

    def __init__(self):
        self._lock = threading.RLock()
        self._entries: dict[str, dict[str, Any]] = {}

    @contextmanager
    def active(self, task_id: str):
        with self._lock:
            entry = self._entries.setdefault(task_id, {"active": 0, "cancelled": False})
            if entry["active"]:
                raise OCRTaskBusyError("Screenshot OCR is already active for this task.")
            entry["active"] = 1
        try:
            yield lambda: self.cancel_requested(task_id)
        finally:
            with self._lock:
                entry = self._entries.get(task_id)
                if entry is not None:
                    entry["active"] = max(0, int(entry["active"]) - 1)
                    if not entry["active"] and not entry["cancelled"]:
                        self._entries.pop(task_id, None)

    def request_cancel(self, task_id: str) -> bool:
        with self._lock:
            entry = self._entries.setdefault(task_id, {"active": 0, "cancelled": False})
            entry["cancelled"] = True
            return bool(entry["active"])

    def cancel_requested(self, task_id: str) -> bool:
        with self._lock:
            return bool(self._entries.get(task_id, {}).get("cancelled"))

    def clear(self, task_id: str) -> None:
        with self._lock:
            self._entries.pop(task_id, None)


def _safe_id(value: Any) -> str:
    value = str(value or "")
    if not _OPAQUE_ID_RE.fullmatch(value):
        raise ValueError("Invalid screenshot OCR task identity.")
    return value


def _task_path(staging_root: str | os.PathLike[str], task_id: str) -> Path:
    root = Path(staging_root).resolve()
    candidate = (root / _safe_id(task_id)).resolve()
    if candidate.parent != root:
        raise ValueError("Screenshot OCR staging path is unsafe.")
    return candidate


def _display_name(filename: Any, index: int) -> str:
    value = str(filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    value = "".join(character for character in value if ord(character) >= 32 and ord(character) != 127)
    return value.strip()[:160] or f"Screenshot {index}"


def stage_screenshot_batch(
    staging_root: str | os.PathLike[str],
    task_id: str,
    uploads: Iterable[Any],
    *,
    store_validated_upload: Callable[..., dict[str, Any]],
    atomic_write_json: Callable[..., Any] | None = None,
    now: Callable[[], datetime] | None = None,
) -> list[dict[str, Any]]:
    """Validate/re-encode an ordered screenshot batch into an opaque task folder."""

    uploads = list(uploads)
    if not uploads:
        raise OCRScreenshotBatchError("Choose at least one screenshot to import.")
    if len(uploads) > OCR_SCREENSHOT_MAX_FILES:
        raise OCRScreenshotBatchError(
            f"Choose no more than {OCR_SCREENSHOT_MAX_FILES} screenshots per batch."
        )
    atomic_write_json = atomic_write_json or json_files._atomic_write_json
    now = now or (lambda: datetime.now(timezone.utc))
    root = Path(staging_root)
    root.mkdir(parents=True, exist_ok=True)
    task_path = _task_path(root, task_id)
    task_path.mkdir(mode=0o700, exist_ok=False)
    sources: list[dict[str, Any]] = []
    aggregate_bytes = 0
    hashes: dict[str, str] = {}
    try:
        marker = {
            "kind": "dlms-ocr-screenshot-task",
            "task_id": task_id,
            "created_at": now().isoformat(),
        }
        atomic_write_json(task_path / OCR_SCREENSHOT_TASK_MARKER, marker, ensure_ascii=False, expected_type=dict)
        for index, upload in enumerate(uploads, 1):
            source_id = hashlib.sha256(f"{task_id}:{index}".encode("ascii")).hexdigest()[:20]
            source = {
                "id": source_id,
                "index": index,
                "original_name": _display_name(getattr(upload, "filename", ""), index),
                "status": "pending",
            }
            consumed = 0
            try:
                stored = store_validated_upload(
                    upload,
                    str(task_path),
                    source_id,
                    max_bytes=OCR_SCREENSHOT_MAX_FILE_BYTES,
                    max_pixels=OCR_SCREENSHOT_MAX_PIXELS,
                    max_side=OCR_SCREENSHOT_MAX_SIDE,
                )
                consumed = int(stored["consumed_bytes"])
                file_path = task_path / str(stored["filename"])
                digest = hashlib.sha256(file_path.read_bytes()).hexdigest()
                source.update(
                    {
                        "filename": file_path.name,
                        "mime_type": str(stored["mime_type"]),
                        "width": int(stored["width"]),
                        "height": int(stored["height"]),
                        "size_bytes": consumed,
                        "sha256": digest,
                        "duplicate_of": hashes.get(digest),
                    }
                )
                hashes.setdefault(digest, source_id)
            except OCRScreenshotBatchError:
                raise
            except Exception as exc:
                public_error = (
                    str(exc)
                    if isinstance(exc, ValueError)
                    else "Screenshot validation failed."
                )
                source.update(
                    {
                        "status": "validation_failed",
                        "error": public_error or "Screenshot validation failed.",
                    }
                )
                consumed = int(getattr(upload, "_dlms_consumed_bytes", 0) or 0)
            aggregate_bytes += consumed
            if aggregate_bytes > OCR_SCREENSHOT_MAX_BATCH_BYTES:
                raise OCRScreenshotBatchError(
                    "The screenshot batch exceeds the 64 MiB aggregate limit."
                )
            sources.append(source)
        return sources
    except Exception:
        shutil.rmtree(task_path, ignore_errors=True)
        raise


def _validated_marker(task_path: Path, task_id: str) -> dict[str, Any]:
    marker_path = task_path / OCR_SCREENSHOT_TASK_MARKER
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise FileNotFoundError("Screenshot OCR staging is unavailable.") from exc
    if marker.get("kind") != "dlms-ocr-screenshot-task" or marker.get("task_id") != task_id:
        raise FileNotFoundError("Screenshot OCR staging is unavailable.")
    return marker


def staged_source_path(
    staging_root: str | os.PathLike[str], task_id: str, source: dict[str, Any]
) -> Path:
    task_path = _task_path(staging_root, task_id)
    _validated_marker(task_path, task_id)
    source_id = _safe_id(source.get("id"))
    filename = str(source.get("filename") or "")
    suffix = Path(filename).suffix.lower()
    if suffix not in OCR_SCREENSHOT_ALLOWED_EXTENSIONS or filename != f"{source_id}{suffix}":
        raise FileNotFoundError("Screenshot preview is unavailable.")
    candidate = (task_path / filename).resolve()
    if candidate.parent != task_path or not candidate.is_file() or candidate.is_symlink():
        raise FileNotFoundError("Screenshot preview is unavailable.")
    return candidate


def cleanup_screenshot_task(staging_root: str | os.PathLike[str], task_id: str) -> bool:
    task_path = _task_path(staging_root, task_id)
    try:
        _validated_marker(task_path, task_id)
    except FileNotFoundError:
        return False
    shutil.rmtree(task_path)
    return True


def prune_stale_screenshot_tasks(
    staging_root: str | os.PathLike[str],
    *,
    now: Callable[[], float] | None = None,
    stale_seconds: int = OCR_SCREENSHOT_STALE_SECONDS,
    max_entries: int = 200,
) -> int:
    """Remove only explicitly marked, abandoned Image OCR staging directories."""

    now = now or time.time
    root = Path(staging_root)
    if not root.is_dir() or root.is_symlink():
        return 0
    removed = 0
    for entry in list(root.iterdir())[:max_entries]:
        if not entry.is_dir() or entry.is_symlink() or not _OPAQUE_ID_RE.fullmatch(entry.name):
            continue
        try:
            _validated_marker(entry, entry.name)
            age = now() - entry.stat().st_mtime
            if age >= stale_seconds:
                shutil.rmtree(entry)
                removed += 1
        except (FileNotFoundError, OSError, ValueError):
            continue
    return removed

"""Bounded, all-or-nothing downloads of ordinary bundles or bundle collections.

Collections are an export envelope, not a new accepted import format. Source
identities belong in its inventory; each inner ZIP declares its portable format version.
"""

import hashlib
from contextlib import contextmanager
import json
import os
import re
import shutil
import tempfile
import threading
import zipfile
from pathlib import Path

from dlms.services import portable_quiz_bundles as bundles


MAX_SELECTION = 1_000
MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024
# Each of two jobs holds at most one bounded quiz in memory. Prepared ZIPs,
# final parts and the envelope each have a 512 MiB disk budget (1.5 GiB/job).
_EXPORT_SLOTS = threading.BoundedSemaphore(2)


class ExportSelectionError(bundles.PortableQuizBundleError):
    """A public, deliberately bounded diagnostic (never a raw exception)."""
    def __init__(self, message, report=None):
        super().__init__(message)
        self.report = report


class ExportBusyError(RuntimeError):
    pass


@contextmanager
def preflight_admission():
    """Bound inspection-only requests using the same export work allowance."""
    if not _EXPORT_SLOTS.acquire(blocking=False):
        raise ExportBusyError("Two exports are already running. Keep your selection and try again when they finish.")
    try:
        yield
    finally:
        _EXPORT_SLOTS.release()


class ExportDownload:
    def __init__(self, temporary, path, filename):
        self.temporary = temporary
        self.path = Path(path)
        self.filename = filename
        self.closed = False

    def close(self):
        if not self.closed:
            self.closed = True
            try:
                self.temporary.cleanup()
            finally:
                _EXPORT_SLOTS.release()


def _manifest_bytes(manifest):
    return (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _public_reason(exc):
    # Do not return raw matching text, unknown JSON keys, paths or tracebacks.
    text = str(exc)
    for needle, reason in (
        ("hotspot", "Image hotspot targets are not supported by this portable format. Transfer the original content pack or use a full-data backup; no questions were converted."),
        ("media", "Check the question image: it is unavailable, unsafe or too large."),
        ("asset", "Check the question image or quiz logo: it is missing, unsafe or too large."),
        ("logo", "Check the quiz logo: it is missing or unsafe."),
        ("JSON boolean", "A choice has an invalid correct-answer flag."),
        ("at least one correct", "The question needs at least one marked correct answer."),
        ("label", "Check choice labels and their order; use supported labels and separate choice identities."),
        ("matching", "Check matching pairs, direction and round size."),
        ("limit", "This quiz exceeds a portable content or media limit; use a full backup."),
        ("MiB", "This quiz exceeds a portable size limit; use a full backup."),
        ("source question number", "The stored source question number must be a positive integer."),
        ("source", "Check the question's source details and URL."),
        ("empty", "A required question or choice field is empty."),
        ("non-empty", "A required question or choice field is empty."),
    ):
        if needle in text:
            return reason
    return "Check the question structure, choices and required fields in the quiz editor."


def _fits(manifest):
    quizzes = manifest["quizzes"]
    payload = _manifest_bytes(manifest)
    assets = [a for q in quizzes for a in q["assets"]]
    # Exact ZIP_STORED size: fixed headers + ASCII generated member names.
    members = [(bundles.PORTABLE_QUIZ_BUNDLE_MANIFEST, len(payload))] + [
        (a["path"], a["size"]) for a in assets
    ]
    zip_bytes = 22 + sum(size + 76 + 2 * len(name.encode("utf-8")) for name, size in members)
    return (
        len(quizzes) <= bundles.PORTABLE_QUIZ_BUNDLE_MAX_QUIZZES
        and sum(len(q["questions"]) for q in quizzes) <= bundles.PORTABLE_QUIZ_BUNDLE_MAX_TOTAL_QUESTIONS
        and len(payload) <= bundles._MAX_MANIFEST_BYTES
        and len(members) <= bundles.PORTABLE_QUIZ_BUNDLE_MAX_FILES
        and sum(size for _, size in members) <= bundles.PORTABLE_QUIZ_BUNDLE_MAX_UNCOMPRESSED_BYTES
        and zip_bytes <= bundles.PORTABLE_QUIZ_BUNDLE_UPLOAD_MAX_BYTES
    )


def build_export_download(cur, registry, selected_ids, *, staging_folder,
                          build_single, inspect_bundle, preflight=None):
    """Prepare all content under one SQLite snapshot, then publish one download.

    build_single writes a bounded one-quiz ZIP to the supplied path. Completed
    parts are inspected by the unchanged archive security boundary. Unique job
    directories and a process-local concurrency bound prevent collisions.
    """
    selected = []
    for raw in selected_ids:
        if not re.fullmatch(r"[0-9]{1,18}", str(raw)) or int(raw) <= 0:
            raise ExportSelectionError("The selection contains an invalid quiz ID. Review the selection.")
        value = int(raw)
        if value not in selected:
            selected.append(value)
        if len(selected) > MAX_SELECTION:
            raise ExportSelectionError("Select at most 1,000 source quizzes per download; export the rest separately.")
    if not selected:
        raise ExportSelectionError("Select at least one source quiz to download.")
    if not _EXPORT_SLOTS.acquire(blocking=False):
        raise ExportBusyError("Two exports are already running. Keep your selection and try again when they finish.")
    temporary = None
    try:
        os.makedirs(staging_folder, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="export-", dir=staging_folder)
        root = Path(temporary.name)
        if not cur.connection.in_transaction:
            cur.execute("BEGIN")
        if preflight:
            report = preflight(cur, registry, selected)
            if report['blocked_quizzes']:
                raise ExportSelectionError(f"{report['blocked_quizzes']} selected quizzes are blocked. No quizzes were exported; your selection is retained.", report)
        catalog = bundles.portable_quiz_export_catalog(cur, registry)["quizzes"]
        available = {q["quiz_id"] for q in catalog}
        missing = [i for i in selected if i not in available]
        if missing:
            raise ExportSelectionError(f"Quiz ID {missing[0]} is unavailable or not an exportable source. No quizzes were exported.")
        wanted = set(selected)
        ordered = [q for q in catalog if q["quiz_id"] in wanted]
        prepared = []
        total_bytes = 0
        for ordinal, item in enumerate(ordered, 1):
            path = root / f"source-{ordinal:06d}.zip"
            try:
                _, single_filename, manifest = build_single(cur, registry, [item["quiz_id"]], path)
                inspect_bundle(path)
            except ValueError as exc:
                match = re.search(r"question (\d+)", str(exc), re.IGNORECASE)
                position = f", question {match.group(1)}" if match else ""
                raise ExportSelectionError(
                    f"{str(item['title'])[:240]} (quiz ID {item['quiz_id']}){position}: {_public_reason(exc)} No quizzes were exported."
                ) from exc
            total_bytes += path.stat().st_size
            if total_bytes > MAX_DOWNLOAD_BYTES:
                raise ExportSelectionError("Selection exceeds the 512 MiB download budget. Select fewer quizzes; no partial export was created.")
            prepared.append((item, path))
        base = {k: v for k, v in manifest.items() if k != "quizzes"}
        del manifest
        inventory = {"format": "dlms-quiz-bundle-collection", "version": 1,
                     "instructions": "Extract this collection. Import each listed ZIP separately using Quiz Bundles → Validate and Preview.",
                     "compatibility": "Format 2 requires a DLMS receiver with preservation-format-2 support. Older applications reject it. Extract the collection and import each inner bundle separately.",
                     "selected_quiz_count": len(ordered), "bundles": []}
        parts = []
        def write_part(group):
            filename = f"DLMS-Quiz-Bundle-part-{len(parts) + 1:03d}.zip"
            path = root / filename
            part_manifest = bundles.validate_portable_quiz_bundle_manifest({**base, "quizzes": [r[1] for r in group]})
            with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as output:
                output.writestr(bundles.PORTABLE_QUIZ_BUNDLE_MANIFEST, _manifest_bytes(part_manifest))
                for _, _, source, mapping in group:
                    with zipfile.ZipFile(source) as archive:
                        for original, target in mapping.items():
                            with archive.open(original) as src, output.open(target, "w") as dst:
                                shutil.copyfileobj(src, dst, 1024 * 1024)
            if path.stat().st_size > bundles.PORTABLE_QUIZ_BUNDLE_UPLOAD_MAX_BYTES:
                raise ExportSelectionError("A bundle exceeds 128 MiB. Select fewer quizzes.")
            inspect_bundle(path)
            parts.append(path)
            inventory["bundles"].append({"filename": filename, "quiz_count": len(group),
                "sha256": _file_hash(path), "quizzes": [
                    {"source_quiz_id": r[0]["quiz_id"], "bundle_id": r[1]["bundle_id"],
                     "title": r[0]["title"], "folder": r[0]["folder"], "question_count": len(r[1]["questions"])} for r in group]})
        # Keep only one part's metadata in memory. Prepared sources are private
        # disk snapshots, not another read of changing database/media content.
        group = []
        for ordinal, (item, source) in enumerate(prepared, 1):
            with zipfile.ZipFile(source) as archive:
                quiz = json.loads(archive.read(bundles.PORTABLE_QUIZ_BUNDLE_MANIFEST))["quizzes"][0]
            new_id, old_id = f"quiz-{ordinal:03d}", quiz["bundle_id"]
            quiz["bundle_id"] = new_id
            mapping = {a["path"]: a["path"].replace(f"assets/{old_id}/", f"assets/{new_id}/", 1) for a in quiz["assets"]}
            for asset in quiz["assets"]:
                asset["path"] = mapping[asset["path"]]
            for media in [quiz, *(q["media"] for q in quiz["questions"])]:
                field = "logo" if media is quiz else "image_url"
                ref = media.get(field)
                if ref:
                    original = ref.removeprefix(bundles.PORTABLE_QUIZ_BUNDLE_ASSET_REF_PREFIX)
                    media[field] = bundles.PORTABLE_QUIZ_BUNDLE_ASSET_REF_PREFIX + mapping[original]
            record = (item, quiz, source, mapping)
            if not _fits({**base, "quizzes": [r[1] for r in [*group, record]]}):
                if group:
                    write_part(group)
                    group = []
                if not _fits({**base, "quizzes": [quiz]}):
                    raise ExportSelectionError(f"Quiz ID {item['quiz_id']} exceeds the ordinary bundle budgets. Use a full backup.")
            group.append(record)
        write_part(group)
        if len(parts) == 1:
            return ExportDownload(temporary, parts[0], single_filename)
        if sum(p.stat().st_size for p in parts) > MAX_DOWNLOAD_BYTES:
            raise ExportSelectionError("Selection exceeds the 512 MiB collection budget. Select fewer quizzes.")
        collection = root / "DLMS-Quiz-Bundle-Collection.zip"
        with zipfile.ZipFile(collection, "w", zipfile.ZIP_STORED) as archive:
            archive.writestr("inventory.json", _manifest_bytes(inventory))
            archive.writestr("READ-ME.txt", inventory["instructions"] + "\n" + inventory["compatibility"] + "\n")
            for part in parts:
                archive.write(part, part.name)
        if collection.stat().st_size > MAX_DOWNLOAD_BYTES:
            raise ExportSelectionError("Selection exceeds the 512 MiB collection budget. Select fewer quizzes.")
        return ExportDownload(temporary, collection, collection.name)
    except BaseException:
        try:
            if temporary is not None:
                temporary.cleanup()
        finally:
            _EXPORT_SLOTS.release()
        raise


def _file_hash(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

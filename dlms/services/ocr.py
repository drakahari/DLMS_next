"""Bounded local OCR runtime detection and observation extraction.

This module deliberately stops at normalized OCR observations.  Question-layout
inference and product workflows belong to later DLMS-119 segments.
"""

from __future__ import annotations

import csv
import io
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


OCR_ENGINE = "tesseract"
OCR_DEFAULT_LANGUAGE = "eng"
OCR_DEFAULT_TIMEOUT_SECONDS = 30.0
OCR_MAX_TSV_BYTES = 8 * 1024 * 1024
OCR_MAX_OBSERVATIONS = 25_000
OCR_TERMINATE_GRACE_SECONDS = 1.0


class OCRError(RuntimeError):
    """Base class for bounded OCR failures."""


class OCRUnavailableError(OCRError):
    """Raised when a trusted OCR runtime cannot be resolved."""


class OCRTimeoutError(OCRError):
    """Raised when OCR exceeds its configured time limit."""


class OCRCancelledError(OCRError):
    """Raised when a caller requests cancellation."""


class OCRProcessError(OCRError):
    """Raised when the OCR engine exits unsuccessfully."""


class OCROutputLimitError(OCRError):
    """Raised when the OCR engine produces more output than permitted."""


class OCRTSVError(OCRError):
    """Raised when OCR TSV cannot be validated safely."""


@dataclass(frozen=True)
class OCRRuntime:
    executable: Path
    tessdata_dir: Path
    version: str
    bundled: bool


@dataclass(frozen=True)
class OCRBoundingBox:
    left: int
    top: int
    width: int
    height: int


@dataclass(frozen=True)
class OCRObservation:
    source_id: str
    page_index: int
    source_width: int
    source_height: int
    text: str
    bounding_box: OCRBoundingBox
    confidence: float
    block_id: int
    paragraph_id: int
    line_id: int
    engine: str
    engine_version: str


def _frozen_resource_root() -> Path | None:
    root = getattr(sys, "_MEIPASS", None)
    return Path(root).resolve() if root else None


def _validate_runtime_paths(executable: Path, tessdata_dir: Path) -> None:
    if not executable.is_absolute() or not executable.is_file():
        raise OCRUnavailableError("The configured Tesseract executable is unavailable.")
    if not os.access(executable, os.X_OK):
        raise OCRUnavailableError("The configured Tesseract executable is not executable.")
    if not tessdata_dir.is_absolute() or not tessdata_dir.is_dir():
        raise OCRUnavailableError("The configured Tesseract language-data directory is unavailable.")
    if not (tessdata_dir / f"{OCR_DEFAULT_LANGUAGE}.traineddata").is_file():
        raise OCRUnavailableError("English Tesseract language data is unavailable.")
    if not (tessdata_dir / "configs" / "tsv").is_file():
        raise OCRUnavailableError("Tesseract TSV configuration data is unavailable.")


def _restricted_environment(tessdata_dir: Path) -> dict[str, str]:
    allowed = (
        "SYSTEMROOT",
        "WINDIR",
        "LD_LIBRARY_PATH",
        "DYLD_LIBRARY_PATH",
        "TMP",
        "TEMP",
        "TMPDIR",
    )
    environment = {name: os.environ[name] for name in allowed if os.environ.get(name)}
    environment.update(
        {
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "TESSDATA_PREFIX": str(tessdata_dir),
        }
    )
    return environment


def _read_engine_version(executable: Path, tessdata_dir: Path) -> str:
    try:
        completed = subprocess.run(
            [str(executable), "--version"],
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=_restricted_environment(tessdata_dir),
            timeout=5.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OCRUnavailableError("Tesseract version detection failed.") from exc
    output = completed.stdout[:4096].decode("utf-8", errors="replace").strip()
    if completed.returncode != 0 or not output:
        raise OCRUnavailableError("Tesseract version detection failed.")
    first_line = output.splitlines()[0].strip()
    if not first_line.lower().startswith("tesseract "):
        raise OCRUnavailableError("The configured executable is not a recognized Tesseract runtime.")
    return first_line.removeprefix("tesseract ").strip()


def resolve_tesseract_runtime(
    *,
    executable: str | os.PathLike[str] | None = None,
    tessdata_dir: str | os.PathLike[str] | None = None,
    frozen_root: str | os.PathLike[str] | None = None,
) -> OCRRuntime:
    """Resolve a trusted Tesseract runtime.

    Frozen applications require their bundled runtime and never fall back to
    ``PATH``.  Source/development mode may use explicit configuration or a
    feature-detected system installation.
    """

    detected_frozen_root = Path(frozen_root).resolve() if frozen_root else _frozen_resource_root()
    bundled = detected_frozen_root is not None
    if bundled:
        suffix = ".exe" if sys.platform == "win32" else ""
        bundle_root = detected_frozen_root / "ocr" / "tesseract"
        resolved_executable = bundle_root / "bin" / f"tesseract{suffix}"
        resolved_tessdata = bundle_root / "tessdata"
    else:
        configured_executable = executable or os.environ.get("DLMS_TESSERACT_EXECUTABLE")
        configured_tessdata = tessdata_dir or os.environ.get("DLMS_TESSDATA_PREFIX")
        discovered = str(configured_executable or shutil.which("tesseract") or "")
        if not discovered:
            raise OCRUnavailableError("Tesseract is not available.")
        resolved_executable = Path(discovered).expanduser().resolve()
        if configured_tessdata:
            resolved_tessdata = Path(configured_tessdata).expanduser().resolve()
        else:
            candidates = (
                Path("/usr/share/tesseract/tessdata"),
                Path("/usr/share/tessdata"),
                resolved_executable.parent / "tessdata",
                resolved_executable.parent.parent / "share" / "tessdata",
                resolved_executable.parent.parent / "share" / "tesseract-ocr" / "5" / "tessdata",
            )
            resolved_tessdata = next(
                (candidate.resolve() for candidate in candidates if (candidate / "eng.traineddata").is_file()),
                Path("/nonexistent-dlms-tessdata"),
            )

    _validate_runtime_paths(resolved_executable, resolved_tessdata)
    return OCRRuntime(
        executable=resolved_executable,
        tessdata_dir=resolved_tessdata,
        version=_read_engine_version(resolved_executable, resolved_tessdata),
        bundled=bundled,
    )


def detect_tesseract_runtime(**kwargs) -> OCRRuntime | None:
    """Return runtime diagnostics when OCR is available, otherwise ``None``."""

    try:
        return resolve_tesseract_runtime(**kwargs)
    except OCRUnavailableError:
        return None


def parse_tesseract_tsv(
    payload: bytes,
    *,
    source_id: str,
    page_index: int,
    source_width: int,
    source_height: int,
    engine_version: str,
    max_observations: int = OCR_MAX_OBSERVATIONS,
) -> tuple[OCRObservation, ...]:
    """Validate Tesseract TSV and return word-level observations."""

    if len(payload) > OCR_MAX_TSV_BYTES:
        raise OCROutputLimitError("OCR TSV exceeded the configured output limit.")
    if not isinstance(source_id, str) or not source_id or len(source_id) > 200:
        raise OCRTSVError("OCR source identity is invalid.")
    if not isinstance(page_index, int) or page_index < 0:
        raise OCRTSVError("OCR page index is invalid.")
    if not isinstance(source_width, int) or not isinstance(source_height, int):
        raise OCRTSVError("OCR source dimensions are invalid.")
    if source_width <= 0 or source_height <= 0:
        raise OCRTSVError("OCR source dimensions are invalid.")

    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise OCRTSVError("OCR TSV is not valid UTF-8.") from exc
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    required = {
        "level",
        "page_num",
        "block_num",
        "par_num",
        "line_num",
        "left",
        "top",
        "width",
        "height",
        "conf",
        "text",
    }
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise OCRTSVError("OCR TSV is missing required columns.")

    observations: list[OCRObservation] = []
    try:
        for row in reader:
            if int(row["level"]) != 5:
                continue
            word = str(row.get("text") or "").strip()
            if not word:
                continue
            left = int(row["left"])
            top = int(row["top"])
            width = int(row["width"])
            height = int(row["height"])
            confidence = float(row["conf"])
            block_id = int(row["block_num"])
            paragraph_id = int(row["par_num"])
            line_id = int(row["line_num"])
            if min(left, top, width, height, block_id, paragraph_id, line_id) < 0:
                raise ValueError
            if width == 0 or height == 0 or left + width > source_width or top + height > source_height:
                raise ValueError
            if not -1.0 <= confidence <= 100.0:
                raise ValueError
            observations.append(
                OCRObservation(
                    source_id=source_id,
                    page_index=page_index,
                    source_width=source_width,
                    source_height=source_height,
                    text=word,
                    bounding_box=OCRBoundingBox(left, top, width, height),
                    confidence=confidence,
                    block_id=block_id,
                    paragraph_id=paragraph_id,
                    line_id=line_id,
                    engine=OCR_ENGINE,
                    engine_version=engine_version,
                )
            )
            if len(observations) > max_observations:
                raise OCROutputLimitError("OCR TSV contains too many observations.")
    except (KeyError, TypeError, ValueError) as exc:
        raise OCRTSVError("OCR TSV contains an invalid observation.") from exc
    return tuple(observations)


def _stop_process(process: subprocess.Popen, grace_seconds: float) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=grace_seconds)


def recognize_image_bytes(
    image_bytes: bytes,
    *,
    source_id: str,
    source_width: int,
    source_height: int,
    page_index: int = 0,
    runtime: OCRRuntime | None = None,
    timeout_seconds: float = OCR_DEFAULT_TIMEOUT_SECONDS,
    cancel_requested: Callable[[], bool] | None = None,
    max_output_bytes: int = OCR_MAX_TSV_BYTES,
    image_suffix: str = ".png",
) -> tuple[OCRObservation, ...]:
    """Run bounded OCR over bytes staged under a service-owned filename."""

    if not isinstance(image_bytes, bytes) or not image_bytes:
        raise OCRError("OCR image input is empty.")
    if len(image_bytes) > 64 * 1024 * 1024:
        raise OCRError("OCR image input exceeds the service limit.")
    if timeout_seconds <= 0:
        raise ValueError("OCR timeout must be positive.")
    image_suffix = str(image_suffix or "").lower()
    if image_suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise ValueError("OCR image suffix is unsupported.")
    runtime = runtime or resolve_tesseract_runtime()
    environment = _restricted_environment(runtime.tessdata_dir)

    with tempfile.TemporaryDirectory(prefix="dlms-ocr-") as temp_dir:
        image_path = Path(temp_dir) / f"input-image{image_suffix}"
        image_path.write_bytes(image_bytes)
        with tempfile.TemporaryFile(mode="w+b") as output, tempfile.TemporaryFile(
            mode="w+b"
        ) as diagnostics:
            try:
                process = subprocess.Popen(
                    [
                        str(runtime.executable),
                        str(image_path),
                        "stdout",
                        "-l",
                        OCR_DEFAULT_LANGUAGE,
                        "--psm",
                        "6",
                        "tsv",
                    ],
                    shell=False,
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=diagnostics,
                    env=environment,
                )
            except OSError as exc:
                raise OCRProcessError("Tesseract could not be started.") from exc

            started = time.monotonic()
            try:
                while process.poll() is None:
                    if cancel_requested is not None and cancel_requested():
                        _stop_process(process, OCR_TERMINATE_GRACE_SECONDS)
                        raise OCRCancelledError("OCR was cancelled.")
                    if time.monotonic() - started >= timeout_seconds:
                        _stop_process(process, OCR_TERMINATE_GRACE_SECONDS)
                        raise OCRTimeoutError("OCR exceeded the configured time limit.")
                    if output.tell() > max_output_bytes or diagnostics.tell() > max_output_bytes:
                        _stop_process(process, OCR_TERMINATE_GRACE_SECONDS)
                        raise OCROutputLimitError("OCR output exceeded the configured limit.")
                    time.sleep(0.025)
                diagnostics.seek(0, os.SEEK_END)
                if diagnostics.tell() > max_output_bytes:
                    raise OCROutputLimitError("OCR diagnostic output exceeded the configured limit.")
                if process.returncode != 0:
                    raise OCRProcessError(
                        f"Tesseract exited unsuccessfully (status {process.returncode})."
                    )
                output.seek(0, os.SEEK_END)
                if output.tell() > max_output_bytes:
                    raise OCROutputLimitError("OCR TSV exceeded the configured output limit.")
                output.seek(0)
                payload = output.read(max_output_bytes + 1)
            finally:
                if process.poll() is None:
                    _stop_process(process, OCR_TERMINATE_GRACE_SECONDS)

    return parse_tesseract_tsv(
        payload,
        source_id=source_id,
        page_index=page_index,
        source_width=source_width,
        source_height=source_height,
        engine_version=runtime.version,
    )

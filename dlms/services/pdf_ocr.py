"""Selective scanned-PDF OCR preflight, staging, and rasterization.

The existing Smart PDF parser remains authoritative for selectable text.  This
module only identifies pages that may benefit from OCR and renders explicitly
selected pages into bounded, task-owned PNG files for the shared OCR service.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import shutil
import time
from typing import Any, Callable, Iterable

from PIL import Image

from dlms.persistence import json_files


PDF_OCR_MAX_SELECTED_PAGES = 25
PDF_OCR_TARGET_DPI = 300
PDF_OCR_MAX_PIXELS = 40_000_000
PDF_OCR_MAX_SIDE = 12_000
PDF_OCR_STALE_SECONDS = 7 * 24 * 60 * 60
PDF_OCR_TASK_MARKER = ".dlms-ocr-pdf-task.json"
PDF_OCR_SOURCE_FILENAME = "source.pdf"
PDF_OCR_LOW_USEFUL_CHARACTERS = 40
PDF_OCR_USABLE_CHARACTERS = 80
PDF_OCR_MIN_SUBSTANTIVE_LINES = 2
_OPAQUE_ID_RE = re.compile(r"^[A-Za-z0-9]{12,40}$")
_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


class PDFOCRTaskError(ValueError):
    """Raised when a PDF OCR task or page selection is unsafe."""


class PDFOCRUnavailableError(RuntimeError):
    """Raised when the optional PDFium raster runtime is unavailable."""


def _safe_task_id(value: Any) -> str:
    value = str(value or "")
    if not _OPAQUE_ID_RE.fullmatch(value):
        raise PDFOCRTaskError("Invalid PDF OCR task identity.")
    return value


def _task_path(staging_root: str | os.PathLike[str], task_id: str) -> Path:
    root = Path(staging_root).resolve()
    candidate = (root / _safe_task_id(task_id)).resolve()
    if candidate.parent != root:
        raise PDFOCRTaskError("PDF OCR staging path is unsafe.")
    return candidate


def _normalized_page_lines(page: dict[str, Any]) -> list[str]:
    raw_lines = page.get("lines") if isinstance(page, dict) else []
    if not isinstance(raw_lines, list):
        return []
    return [re.sub(r"\s+", " ", str(line or "")).strip() for line in raw_lines]


def analyze_page_text_usefulness(page: dict[str, Any]) -> dict[str, Any]:
    """Classify extracted page text using conservative, explainable signals."""

    lines = [line for line in _normalized_page_lines(page) if line]
    text = "\n".join(lines)
    useful_characters = sum(1 for character in text if character.isalnum())
    alphabetic_characters = sum(1 for character in text if character.isalpha())
    substantive_lines = [
        line
        for line in lines
        if len([character for character in line if character.isalnum()]) >= 12
        and len(_WORD_RE.findall(line)) >= 2
    ]
    alphabetic_ratio = (
        alphabetic_characters / useful_characters if useful_characters else 0.0
    )
    normalized_lines = [line.casefold() for line in lines]
    unique_ratio = (
        len(set(normalized_lines)) / len(normalized_lines) if normalized_lines else 0.0
    )

    reasons: list[str] = []
    if useful_characters < PDF_OCR_LOW_USEFUL_CHARACTERS:
        reasons.append("fewer than 40 useful characters")
    if len(substantive_lines) < PDF_OCR_MIN_SUBSTANTIVE_LINES:
        reasons.append("fewer than two substantive lines")
    if useful_characters and alphabetic_ratio < 0.25:
        reasons.append("mostly non-alphabetic extraction")
    if len(lines) >= 4 and unique_ratio < 0.35:
        reasons.append("implausibly repetitive extraction")

    has_images = bool(page.get("has_images"))
    is_empty_blank = useful_characters == 0 and not has_images
    clearly_low = bool(reasons) and not is_empty_blank and (
        useful_characters < PDF_OCR_LOW_USEFUL_CHARACTERS
        or len(substantive_lines) < PDF_OCR_MIN_SUBSTANTIVE_LINES
        or alphabetic_ratio < 0.25
        or unique_ratio < 0.35
    )
    clearly_usable = (
        useful_characters >= PDF_OCR_USABLE_CHARACTERS
        and len(substantive_lines) >= PDF_OCR_MIN_SUBSTANTIVE_LINES
        and alphabetic_ratio >= 0.35
        and unique_ratio >= 0.35
    )
    if is_empty_blank:
        classification = "blank"
        reasons = ["blank page without selectable text or raster images"]
    elif clearly_usable:
        classification = "usable"
        reasons = ["usable selectable text"]
    elif clearly_low:
        classification = "low"
    else:
        classification = "ambiguous"
        reasons = ["limited selectable text may be incomplete"]

    return {
        "page": int(page.get("page") or 0),
        "classification": classification,
        "ocr_candidate": classification in {"low", "ambiguous"},
        "useful_characters": useful_characters,
        "substantive_lines": len(substantive_lines),
        "alphabetic_ratio": round(alphabetic_ratio, 3),
        "has_images": has_images,
        "reason": "; ".join(reasons),
    }


def analyze_pdf_text_usefulness(pages: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [analyze_page_text_usefulness(page) for page in pages]


def validate_selected_pages(
    values: Iterable[Any], candidate_pages: Iterable[Any], *, max_pages: int = PDF_OCR_MAX_SELECTED_PAGES
) -> list[int]:
    candidates = {int(value) for value in candidate_pages}
    selected: list[int] = []
    for value in values:
        try:
            page_number = int(value)
        except (TypeError, ValueError) as exc:
            raise PDFOCRTaskError("An OCR page selection is invalid.") from exc
        if page_number not in candidates:
            raise PDFOCRTaskError(
                f"PDF page {page_number} is not eligible for selective OCR."
            )
        if page_number not in selected:
            selected.append(page_number)
    if not selected:
        raise PDFOCRTaskError("Select at least one eligible PDF page to OCR.")
    if len(selected) > max_pages:
        raise PDFOCRTaskError(
            f"Select no more than {max_pages} PDF pages for OCR per import."
        )
    return sorted(selected)


def stage_pdf_ocr_task(
    staging_root: str | os.PathLike[str],
    task_id: str,
    pdf_path: str | os.PathLike[str],
    *,
    atomic_write_json: Callable[..., Any] | None = None,
    now: Callable[[], datetime] | None = None,
) -> Path:
    """Copy one validated upload into an explicitly marked OCR task folder."""

    atomic_write_json = atomic_write_json or json_files._atomic_write_json
    now = now or (lambda: datetime.now(timezone.utc))
    root = Path(staging_root)
    root.mkdir(parents=True, exist_ok=True)
    task_path = _task_path(root, task_id)
    task_path.mkdir(mode=0o700, exist_ok=False)
    try:
        marker = {
            "kind": "dlms-ocr-pdf-task",
            "task_id": task_id,
            "created_at": now().isoformat(),
        }
        atomic_write_json(
            task_path / PDF_OCR_TASK_MARKER,
            marker,
            ensure_ascii=False,
            expected_type=dict,
        )
        source = task_path / PDF_OCR_SOURCE_FILENAME
        shutil.copy2(Path(pdf_path), source)
        return source
    except Exception:
        shutil.rmtree(task_path, ignore_errors=True)
        raise


def _validated_marker(task_path: Path, task_id: str) -> dict[str, Any]:
    try:
        marker = json.loads((task_path / PDF_OCR_TASK_MARKER).read_text("utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise FileNotFoundError("PDF OCR staging is unavailable.") from exc
    if marker.get("kind") != "dlms-ocr-pdf-task" or marker.get("task_id") != task_id:
        raise FileNotFoundError("PDF OCR staging is unavailable.")
    return marker


def staged_pdf_path(staging_root: str | os.PathLike[str], task_id: str) -> Path:
    task_path = _task_path(staging_root, task_id)
    _validated_marker(task_path, task_id)
    candidate = (task_path / PDF_OCR_SOURCE_FILENAME).resolve()
    if candidate.parent != task_path or not candidate.is_file() or candidate.is_symlink():
        raise FileNotFoundError("PDF OCR source is unavailable.")
    return candidate


def staged_page_path(
    staging_root: str | os.PathLike[str], task_id: str, page_number: int
) -> Path:
    task_path = _task_path(staging_root, task_id)
    _validated_marker(task_path, task_id)
    try:
        page_number = int(page_number)
    except (TypeError, ValueError) as exc:
        raise FileNotFoundError("PDF OCR page preview is unavailable.") from exc
    if page_number < 1:
        raise FileNotFoundError("PDF OCR page preview is unavailable.")
    candidate = (task_path / f"page-{page_number:04d}.png").resolve()
    if candidate.parent != task_path or not candidate.is_file() or candidate.is_symlink():
        raise FileNotFoundError("PDF OCR page preview is unavailable.")
    return candidate


def staged_region_path(
    staging_root: str | os.PathLike[str], task_id: str, source_id: str
) -> Path:
    task_path = _task_path(staging_root, task_id)
    _validated_marker(task_path, task_id)
    source_id = _safe_task_id(source_id)
    candidate = (task_path / f"region-{source_id}.png").resolve()
    if candidate.parent != task_path or not candidate.is_file() or candidate.is_symlink():
        raise FileNotFoundError("PDF OCR region preview is unavailable.")
    return candidate


def _bounded_render_scale(width_points: float, height_points: float) -> float:
    if width_points <= 0 or height_points <= 0:
        raise PDFOCRTaskError("The selected PDF page has invalid dimensions.")
    desired = PDF_OCR_TARGET_DPI / 72.0
    side_scale = min(PDF_OCR_MAX_SIDE / width_points, PDF_OCR_MAX_SIDE / height_points)
    pixel_scale = math.sqrt(PDF_OCR_MAX_PIXELS / (width_points * height_points))
    scale = min(desired, side_scale, pixel_scale)
    if not math.isfinite(scale) or scale <= 0:
        raise PDFOCRTaskError("The selected PDF page cannot be rendered safely.")
    return scale


def render_pdf_page(
    staging_root: str | os.PathLike[str],
    task_id: str,
    page_number: int,
    *,
    render_lock: Any,
    cancel_requested: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Render one selected page under the caller-owned PDFium lock."""

    cancel_requested = cancel_requested or (lambda: False)
    if cancel_requested():
        raise InterruptedError("PDF OCR was cancelled.")
    source = staged_pdf_path(staging_root, task_id)
    task_path = source.parent
    try:
        import pypdfium2 as pdfium
    except Exception as exc:
        raise PDFOCRUnavailableError(
            "Selective scanned-PDF OCR requires the bundled PDFium runtime."
        ) from exc

    temporary = task_path / f".page-{int(page_number):04d}.rendering.png"
    destination = task_path / f"page-{int(page_number):04d}.png"
    try:
        with render_lock:
            if cancel_requested():
                raise InterruptedError("PDF OCR was cancelled.")
            document = pdfium.PdfDocument(str(source))
            try:
                index = int(page_number) - 1
                if index < 0 or index >= len(document):
                    raise PDFOCRTaskError("The selected PDF page is out of range.")
                page = document[index]
                try:
                    width_points, height_points = page.get_size()
                    scale = _bounded_render_scale(width_points, height_points)
                    bitmap = page.render(scale=scale)
                    try:
                        image = bitmap.to_pil().convert("RGB")
                    finally:
                        bitmap.close()
                finally:
                    page.close()
            finally:
                document.close()
        if cancel_requested():
            raise InterruptedError("PDF OCR was cancelled.")
        width, height = image.size
        if (
            width > PDF_OCR_MAX_SIDE
            or height > PDF_OCR_MAX_SIDE
            or width * height > PDF_OCR_MAX_PIXELS
        ):
            raise PDFOCRTaskError("The rendered PDF page exceeds OCR image limits.")
        image.save(temporary, format="PNG", optimize=False)
        os.replace(temporary, destination)
        return {
            "page": int(page_number),
            "filename": destination.name,
            "mime_type": "image/png",
            "width": width,
            "height": height,
            "dpi": round(scale * 72.0, 1),
        }
    finally:
        try:
            temporary.unlink()
        except OSError:
            pass


def render_pdf_region(
    staging_root: str | os.PathLike[str],
    task_id: str,
    source_id: str,
    page_number: int,
    bbox: dict[str, Any],
    *,
    render_lock: Any,
    cancel_requested: Callable[[], bool] | None = None,
    padding_points: float = 6.0,
) -> dict[str, Any]:
    """Render one validated PDF-space raster union, never the complete page."""
    cancel_requested = cancel_requested or (lambda: False)
    if cancel_requested():
        raise InterruptedError("PDF OCR was cancelled.")
    source = staged_pdf_path(staging_root, task_id)
    task_path = source.parent
    source_id = _safe_task_id(source_id)
    try:
        import pypdfium2 as pdfium
    except Exception as exc:
        raise PDFOCRUnavailableError(
            "Targeted PDF OCR requires the bundled PDFium runtime."
        ) from exc

    temporary = task_path / f".region-{source_id}.rendering.png"
    destination = task_path / f"region-{source_id}.png"
    try:
        with render_lock:
            if cancel_requested():
                raise InterruptedError("PDF OCR was cancelled.")
            document = pdfium.PdfDocument(str(source))
            try:
                index = int(page_number) - 1
                if index < 0 or index >= len(document):
                    raise PDFOCRTaskError("The targeted PDF page is out of range.")
                page = document[index]
                try:
                    page_width, page_height = page.get_size()
                    try:
                        left = float(bbox["left"])
                        bottom = float(bbox["bottom"])
                        right = float(bbox["right"])
                        top = float(bbox["top"])
                    except (KeyError, TypeError, ValueError) as exc:
                        raise PDFOCRTaskError(
                            "The targeted PDF raster bounds are invalid."
                        ) from exc
                    values = (left, bottom, right, top, page_width, page_height)
                    if not all(math.isfinite(value) for value in values):
                        raise PDFOCRTaskError(
                            "The targeted PDF raster bounds are invalid."
                        )
                    left = max(0.0, left - padding_points)
                    bottom = max(0.0, bottom - padding_points)
                    right = min(page_width, right + padding_points)
                    top = min(page_height, top + padding_points)
                    if not (left < right and bottom < top):
                        raise PDFOCRTaskError(
                            "The targeted PDF raster bounds are outside the page."
                        )
                    region_width = right - left
                    region_height = top - bottom
                    scale = _bounded_render_scale(region_width, region_height)
                    crop = (
                        left,
                        bottom,
                        page_width - right,
                        page_height - top,
                    )
                    bitmap = page.render(scale=scale, crop=crop)
                    try:
                        image = bitmap.to_pil().convert("RGB")
                    finally:
                        bitmap.close()
                finally:
                    page.close()
            finally:
                document.close()
        if cancel_requested():
            raise InterruptedError("PDF OCR was cancelled.")
        width, height = image.size
        if (
            width > PDF_OCR_MAX_SIDE
            or height > PDF_OCR_MAX_SIDE
            or width * height > PDF_OCR_MAX_PIXELS
        ):
            raise PDFOCRTaskError("The targeted PDF raster exceeds OCR image limits.")
        image.save(temporary, format="PNG", optimize=False)
        os.replace(temporary, destination)
        return {
            "page": int(page_number),
            "filename": destination.name,
            "mime_type": "image/png",
            "width": width,
            "height": height,
            "dpi": round(scale * 72.0, 1),
            "bbox": {"left": left, "bottom": bottom, "right": right, "top": top},
        }
    finally:
        try:
            temporary.unlink()
        except OSError:
            pass


def cleanup_pdf_ocr_task(staging_root: str | os.PathLike[str], task_id: str) -> bool:
    task_path = _task_path(staging_root, task_id)
    try:
        _validated_marker(task_path, task_id)
    except FileNotFoundError:
        return False
    shutil.rmtree(task_path)
    return True


def prune_stale_pdf_ocr_tasks(
    staging_root: str | os.PathLike[str],
    *,
    now: Callable[[], float] | None = None,
    stale_seconds: int = PDF_OCR_STALE_SECONDS,
    max_entries: int = 200,
) -> int:
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
            if now() - entry.stat().st_mtime >= stale_seconds:
                shutil.rmtree(entry)
                removed += 1
        except (FileNotFoundError, OSError, ValueError):
            continue
    return removed

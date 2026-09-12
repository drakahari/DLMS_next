"""Shared PyInstaller resource contract for the optional Tesseract runtime."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def tesseract_bundle_paths(root, *, platform_name: str | None = None):
    """Return the required paths for one target-native OCR bundle."""
    root = Path(root).expanduser().resolve()
    platform_name = str(platform_name or sys.platform).casefold()
    windows = platform_name in {"win32", "windows"}
    executable = root / "bin" / ("tesseract.exe" if windows else "tesseract")
    return {
        "executable": executable,
        "eng_traineddata": root / "tessdata" / "eng.traineddata",
        "tsv_config": root / "tessdata" / "configs" / "tsv",
        "tesseract_license": root / "licenses" / "tesseract-LICENSE.txt",
        "tessdata_license": root / "licenses" / "tessdata-LICENSE.txt",
        "leptonica_license": root / "licenses" / "leptonica-LICENSE.txt",
    }


def validate_tesseract_bundle(root, *, platform_name: str | None = None):
    """Validate and return the authoritative frozen OCR bundle paths."""
    paths = tesseract_bundle_paths(root, platform_name=platform_name)
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise ValueError("Incomplete Tesseract bundle: " + ", ".join(missing))
    empty = [str(path) for path in paths.values() if path.stat().st_size == 0]
    if empty:
        raise ValueError("Empty Tesseract bundle resource: " + ", ".join(empty))
    target = str(platform_name or sys.platform).casefold()
    if target not in {"win32", "windows"} and not os.access(
        paths["executable"], os.X_OK
    ):
        raise ValueError("Bundled Tesseract executable is not executable")
    return paths


def collect_tesseract_bundle(*, required: bool = False):
    """Return ``(binaries, datas)`` for a prepared native Tesseract bundle.

    Release builders provide a platform-native directory through
    ``DLMS_TESSERACT_BUNDLE_ROOT``.  The repository does not commit platform
    executables or language models.
    """

    configured = os.environ.get("DLMS_TESSERACT_BUNDLE_ROOT")
    if not configured:
        if required:
            raise ValueError("DLMS_TESSERACT_BUNDLE_ROOT is required for the OCR probe")
        return [], []

    root = Path(configured).expanduser().resolve()
    paths = validate_tesseract_bundle(root)
    executable = paths["executable"]
    tessdata = root / "tessdata"
    licenses = root / "licenses"

    bundled_native_libraries = sorted(
        path
        for path in executable.parent.iterdir()
        if path.is_file()
        and path != executable
        and (
            path.suffix.casefold() in {".dll", ".dylib"}
            or ".so" in path.name.casefold()
        )
    )
    binaries = [(str(executable), "ocr/tesseract/bin")]
    binaries.extend(
        (str(library), "ocr/tesseract/bin")
        for library in bundled_native_libraries
    )
    datas = [
        (str(tessdata / "eng.traineddata"), "ocr/tesseract/tessdata"),
        (str(tessdata / "configs" / "tsv"), "ocr/tesseract/tessdata/configs"),
        (str(licenses), "ocr/tesseract/licenses"),
    ]
    return binaries, datas

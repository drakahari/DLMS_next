"""Shared PyInstaller resource contract for the optional Tesseract runtime."""

from __future__ import annotations

import os
import sys
from pathlib import Path


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
    executable_name = "tesseract.exe" if sys.platform == "win32" else "tesseract"
    executable = root / "bin" / executable_name
    tessdata = root / "tessdata"
    licenses = root / "licenses"
    required_paths = (
        executable,
        tessdata / "eng.traineddata",
        tessdata / "configs" / "tsv",
        licenses / "tesseract-LICENSE.txt",
        licenses / "tessdata-LICENSE.txt",
        licenses / "leptonica-LICENSE.txt",
    )
    missing = [str(path) for path in required_paths if not path.is_file()]
    if missing:
        raise ValueError("Incomplete Tesseract bundle: " + ", ".join(missing))
    empty = [str(path) for path in required_paths if path.stat().st_size == 0]
    if empty:
        raise ValueError("Empty Tesseract bundle resource: " + ", ".join(empty))
    if os.name != "nt" and not os.access(executable, os.X_OK):
        raise ValueError("Bundled Tesseract executable is not executable")

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

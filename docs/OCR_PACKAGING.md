# DLMS OCR runtime, source setup, and packaging contract

DLMS-119 uses Tesseract 5 through the bounded service in
`dlms/services/ocr.py`. Tesseract is a native executable, not a Python package.
`pypdfium2` provides selected-page PDF rasterization and remains a normal,
locked Python dependency. Question-layout inference stays outside the OCR
engine service.

OCR is optional. When it is unavailable, normal selectable-text Smart PDF and
glossary imports remain available; only screenshot OCR and selective
scanned-page OCR are disabled.

## Source/development runtime

Source mode resolves Tesseract in this order:

1. the `executable=` service argument;
2. `DLMS_TESSERACT_EXECUTABLE`;
3. `tesseract` discovered on `PATH`.

English trained data is resolved from the `tessdata_dir=` service argument,
then `DLMS_TESSDATA_PREFIX`, then known system locations relative to the
executable and common Linux installation paths. DLMS validates
`eng.traineddata` and `configs/tsv` before enabling OCR. It sets the standard
`TESSDATA_PREFIX` only for the restricted Tesseract child process; setting
`TESSDATA_PREFIX` alone does not configure DLMS discovery.

Restart a running DLMS development server after installing Tesseract or
changing either `DLMS_TESSERACT_*` variable. No network download or first-use
model installation occurs.

### Ubuntu 24.04

Ubuntu 24.04 provides Tesseract 5 through `tesseract-ocr` and English trained
data through `tesseract-ocr-eng`:

```bash
sudo apt update
sudo apt install --yes tesseract-ocr tesseract-ocr-eng
```

The package manager supplies Leptonica, `libtesseract`, and the standard TSV
configuration as dependencies; `libtesseract-dev` is not required. DLMS does
not currently use orientation/script detection, so a separate OSD package is
not required for its OCR workflows.

Verify the complete source-mode contract from the repository root:

```bash
command -v tesseract
tesseract --version
tesseract --list-langs
test -r /usr/share/tesseract-ocr/5/tessdata/eng.traineddata
test -r /usr/share/tesseract-ocr/5/tessdata/configs/tsv
tesseract tests/fixtures/ocr/dlms-question.png stdout -l eng --psm 6 tsv | sed -n '1,12p'
.venv/bin/python -c "from dlms.services.ocr import diagnose_tesseract_runtime as d; x=d(); print(x.mode, x.reason, x.runtime.version if x.runtime else x.guidance); raise SystemExit(not x.available)"
```

No environment variable is normally needed on Ubuntu 24.04. For a nonstandard
installation, use the directory that directly contains `eng.traineddata`:

```bash
export DLMS_TESSERACT_EXECUTABLE=/absolute/path/to/tesseract
export DLMS_TESSDATA_PREFIX=/absolute/path/to/tessdata
```

These overrides can be temporary for manual testing. Persist them only when the
development machine intentionally keeps Tesseract outside its package-manager
locations.

### Other source-development platforms

- **Fedora:** `sudo dnf install tesseract tesseract-langpack-eng`
- **Arch/Omarchy:** `sudo pacman -S tesseract tesseract-data-eng`
- **macOS with Homebrew:** `brew install tesseract` (the formula includes
  English and OSD data). Homebrew's standard `bin` and `share/tessdata`
  locations are discovered automatically when Homebrew is on `PATH`; use the
  two `DLMS_TESSERACT_*` overrides above for a nonstandard prefix.
- **Windows source development:** install a trusted Tesseract 5 distribution
  that includes English data and `tessdata\configs\tsv`, then set
  `DLMS_TESSERACT_EXECUTABLE` to the absolute `tesseract.exe` path and
  `DLMS_TESSDATA_PREFIX` to its `tessdata` directory before starting DLMS.

These are source-development prerequisites, not instructions for users of an
official OCR-enabled frozen DLMS package.

## Frozen/official package runtime

A frozen DLMS process accepts OCR only from
`<frozen-resource-root>/ocr/tesseract/`. It never falls back to `PATH`, source
environment overrides, or a system Tesseract. This makes the release artifact
self-contained and ensures that a different host installation cannot silently
change OCR behavior.

Native builders prepare a platform-specific directory and set
`DLMS_TESSERACT_BUNDLE_ROOT`. Its required layout is:

```text
bin/tesseract[.exe]
bin/[platform-native dependent libraries, when not resolved by the build host]
tessdata/eng.traineddata
tessdata/configs/tsv
licenses/tesseract-LICENSE.txt
licenses/tessdata-LICENSE.txt
licenses/leptonica-LICENSE.txt
```

`DLMS.spec` includes this runtime when the variable is set. The stricter
`DLMS-OCR-Probe.spec` requires it and produces a frozen executable that checks
version detection, timeout termination, cancellation termination, TSV output,
and OCR of the repository-created probe fixture. Missing executable, English
data, TSV config, or required license files is a build-contract failure.

`pypdfium2>=5.13.0,<6` is declared in `requirements.txt` and version 5.13.0 is
locked in `requirements-lock.txt`, which was exercised with Python 3.14.7 on
the current Fedora validation host. The canonical PyInstaller manifest includes
`pypdfium2`, `pypdfium2_raw`, its native PDFium library, and installed package
license metadata. Every target still needs its own native rasterization smoke;
one operating system cannot prove another target's binary compatibility.

## OCR-specific native release gate

Fedora x86-64 is the only frozen OCR target proven during DLMS-119 repository
implementation. Ubuntu, Omarchy/Arch, Windows 11 x86-64, and macOS ARM64 remain
target-native release gates. Do not advertise OCR in a platform package until
that exact native artifact proves all of the following:

- the native build succeeds;
- bundled Tesseract and its dependent libraries are present;
- `eng.traineddata` and `configs/tsv` are present;
- PDFium and its license metadata are present;
- Tesseract, tessdata, and Leptonica licenses are present;
- screenshot OCR succeeds without a system Tesseract;
- selected scanned-PDF rasterization and OCR succeed;
- timeout and cancellation terminate the bundled process;
- frozen resource/archive inspection passes.

The general native release procedure remains in
`docs/RELEASE_VERIFICATION.md`.

## Smart PDF compatibility

Smart PDF question banks save list-capable `correct_answers` values. At
load/conversion boundaries, legacy scalar `correct` values remain supported and
are normalized in memory without rewriting existing user files.

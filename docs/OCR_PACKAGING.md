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
bin/tesseract (Linux/macOS)
bin/tesseract.exe (Windows)
bin/[platform-native dependent libraries, when not resolved by the build host]
tessdata/eng.traineddata
tessdata/configs/tsv
licenses/tesseract-LICENSE.txt
licenses/tessdata-LICENSE.txt
licenses/leptonica-LICENSE.txt
```

### Prepare the native bundle

`tools/prepare_ocr_bundle.py` is the authoritative preparation and validation
helper. It discovers the current platform's package-manager layout, copies only
the required files into a new bundle, validates the result through the same
contract used by `DLMS.spec`, and prints the environment command for the build.
It intentionally has no cross-target mode. The default output is
repository-local but ignored:

```bash
python tools/prepare_ocr_bundle.py
python tools/prepare_ocr_bundle.py --output .ocr-bundle --validate-only
export DLMS_TESSERACT_BUNDLE_ROOT="$PWD/.ocr-bundle"
```

Preparation is atomic and refuses to replace an existing directory. Remove an
old local bundle deliberately before preparing a new one, or use
`--validate-only` to check it. A custom output inside the checkout must already
be ignored by Git; an output outside the checkout is also supported. The helper
never changes source package files and copies adjacent `.dll`, `.dylib`, or
`.so` files when the native installation places them beside Tesseract.

Install the native packages first, then prepare on that same target:

- **Ubuntu 24.04 and 26.04:**

  ```bash
  sudo apt update
  sudo apt install --yes tesseract-ocr tesseract-ocr-eng
  python tools/prepare_ocr_bundle.py
  ```

  The helper recognizes both `liblept5` and `libleptonica6` copyright paths.

- **Fedora 44:**

  ```bash
  sudo dnf install -y tesseract tesseract-langpack-eng
  python tools/prepare_ocr_bundle.py
  ```

  Fedora does not expose a separate English tessdata license in the validated
  layout. The helper may reuse the packaged Tesseract license for tessdata only
  when its bytes match the pinned official tessdata license exactly.

- **Omarchy/Arch:**

  ```bash
  sudo pacman -S --needed tesseract tesseract-data-eng
  python tools/prepare_ocr_bundle.py --download-missing-licenses
  ```

  The validated Arch package exposes the Leptonica license but not a Tesseract
  license. The opt-in flag obtains the missing official license once and caches
  the checksum-verified text for later preparations.

- **macOS Apple Silicon with Homebrew:**

  ```bash
  brew install tesseract
  python tools/prepare_ocr_bundle.py --download-missing-licenses
  ```

  Homebrew prefixes are queried rather than version-coded. The packaged
  Tesseract license is used. If the Leptonica prefix has no license file, the
  helper downloads and caches the actual pinned Leptonica license; it never
  substitutes the Tesseract license for Leptonica.

- **Windows 11 PowerShell:** validate the known-good local bundle directly:

  ```powershell
  python tools\prepare_ocr_bundle.py --output .ocr-bundle --validate-only
  $env:DLMS_TESSERACT_BUNDLE_ROOT = (Resolve-Path .ocr-bundle).Path
  ```

  To prepare from another trusted native installation, give explicit paths;
  the helper intentionally does not assume a particular third-party installer:

  ```powershell
  python tools\prepare_ocr_bundle.py --output .ocr-bundle `
    --tesseract-executable C:\path\to\tesseract.exe `
    --tessdata-dir C:\path\to\tessdata `
    --tesseract-license C:\path\to\tesseract-LICENSE.txt `
    --tessdata-license C:\path\to\tessdata-LICENSE.txt `
    --leptonica-license C:\path\to\leptonica-LICENSE.txt
  $env:DLMS_TESSERACT_BUNDLE_ROOT = (Resolve-Path .ocr-bundle).Path
  ```

Explicit source overrides are also available on Unix for nonstandard package
layouts. Run `python tools/prepare_ocr_bundle.py --help` for the complete list.

### License handling

An explicit CLI license path is authoritative when supplied. Otherwise,
package-manager license files are preferred, followed by an existing local
cache. `--download-missing-licenses` is opt-in and downloads only a missing
license from immutable upstream commits. Every download is bounded and checked
against a pinned SHA-256 before it enters the cache or bundle:

- `tesseract-ocr/tesseract` 5.5.0 `LICENSE` at source commit
  `64eab6c457b2337dd690746a5fde5c222b40d5f8`;
- `tesseract-ocr/tessdata` 4.1.0 `LICENSE` at source commit
  `4767ea922bcc460e70b87b1d303ebdfed0897da8`;
- `DanBloomberg/leptonica` 1.85.0 `leptonica-license.txt` at source commit
  `63aef18d98432b8582a1565e241f7bd2ee9cc8d9`.

The cache defaults to the platform user cache and can be overridden with
`--license-cache` or `DLMS_OCR_LICENSE_CACHE`. This avoids a network request on
every build without committing third-party license files, executables, or
trained models. Missing, empty, or checksum-mismatched licenses fail clearly;
placeholder files are never generated. Review and update the pinned source and
checksum deliberately if a future native dependency changes its licensing.

### Canonical frozen build and strict probe

`DLMS.spec` includes the bundle whenever `DLMS_TESSERACT_BUNDLE_ROOT` is set.
`DLMS-OCR-Probe.spec` is the strict pre-build gate: it refuses to build without
a complete bundle. Build and run it before the application in the same native
environment:

```bash
export DLMS_TESSERACT_BUNDLE_ROOT="$PWD/.ocr-bundle"
python -m PyInstaller --clean --noconfirm DLMS-OCR-Probe.spec
./dist/DLMS-OCR-Probe
python -m PyInstaller --clean --noconfirm DLMS.spec
```

```powershell
$env:DLMS_TESSERACT_BUNDLE_ROOT = (Resolve-Path .ocr-bundle).Path
python -m PyInstaller --clean --noconfirm DLMS-OCR-Probe.spec
.\dist\DLMS-OCR-Probe.exe
python -m PyInstaller --clean --noconfirm DLMS.spec
```

The frozen probe requires bundled Tesseract 5 and checks frozen resource
discovery, version detection, timeout termination, cancellation termination,
TSV output, and OCR of the repository-created fixture. Missing executable,
English data, TSV config, required licenses, or bundled discovery is a hard
failure. This gate prevents an intended OCR-enabled release build from silently
continuing without its OCR bundle.

The bundle must match the build target. Do not reuse a bundle prepared for
another operating system or architecture. PyInstaller analyzes the staged
Tesseract executable's native dependencies; libraries supplied alongside the
executable are also included by the shared bundle collector.

`pypdfium2>=5.13.0,<6` is declared in `requirements.txt` and version 5.13.0 is
locked in `requirements-lock.txt`, which was exercised with Python 3.14.7 on
the current Fedora validation host. The canonical PyInstaller manifest includes
`pypdfium2`, `pypdfium2_raw`, its native PDFium library, and installed package
license metadata. Every target still needs its own native rasterization smoke;
one operating system cannot prove another target's binary compatibility.

## OCR-specific native release gate

The DLMS 3.1.0 native artifacts have completed build and smoke verification on
Fedora 44 x86-64, Ubuntu 24.04 x86-64, Ubuntu 26.04 x86-64, Omarchy Quattro
x86-64, Windows 11 x86-64, and macOS Apple Silicon arm64. This does not waive
the gate for future builds: each rebuilt native artifact must pass it again.

Do not advertise OCR in any platform package until that exact native artifact
proves all of the following:

- the native build succeeds;
- bundled Tesseract and its dependent libraries are present;
- `eng.traineddata` and `configs/tsv` are present;
- PDFium and its license metadata are present;
- Tesseract, tessdata, and Leptonica licenses are present;
- screenshot OCR succeeds without a system Tesseract;
- selected scanned-PDF rasterization and OCR succeed;
- timeout and cancellation terminate the bundled process;
- frozen resource/archive inspection passes.

Perform the final OCR smoke on a clean target machine that has no system
Tesseract available. On Linux, `command -v tesseract` must return no executable;
on Windows, `Get-Command tesseract.exe -ErrorAction SilentlyContinue` must return
nothing. Then launch the staged/final DLMS artifact and verify both workflows:

1. Import a repository-created neutral screenshot fixture, wait for local OCR,
   compare the draft with its preview, and reach Review & Repair.
2. Import the scanned-PDF regression fixture, select a low-text page for OCR,
   and verify PDFium rasterization, OCR, preview, and Review & Repair.
3. Confirm the OCR availability UI identifies bundled Tesseract and does not
   ask for a system installation.

A successful OCR run under these conditions is the proof that the packaged
application is using its bundle. Installing Tesseract to make a frozen artifact
pass invalidates this check; fix the staged bundle or build instead.

The general native release procedure remains in
`docs/RELEASE_VERIFICATION.md`.

## Smart PDF compatibility

Smart PDF question banks save list-capable `correct_answers` values. At
load/conversion boundaries, legacy scalar `correct` values remain supported and
are normalized in memory without rewriting existing user files.

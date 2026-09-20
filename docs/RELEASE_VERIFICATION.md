# Native Release Verification

This is the canonical native-artifact and final-distributable verification
procedure for a DLMS release. Run it from the same clean checkout used to build
and stage the release. It is deliberately small: it verifies the exact archives
being published and requires real native UAT where desktop behavior cannot be
established from another operating system.

For 3.2.0, follow the [final release checklist](releases/3.2.0-RELEASE-CHECKLIST.md).
Every public native package must be rebuilt from the exact final frozen release
commit after the final source/documentation changes are committed. Earlier
3.2.0 builds and their hashes are not final release artifacts, including builds
that predate the Content Packs metric-card CSS fix. Create each final user-facing
package on its named native host; the assembly host only verifies and collects
the unchanged finished archives.

`tools/verify_release_artifact.py` never imports `app.py`. Structural and
checksum checks are therefore safe to run from a development checkout without
creating or selecting normal DLMS user data. Its optional native smoke test sets
`QUIZAPP_DATA_DIR` to a temporary directory and verifies that DLMS initializes
only that controlled data root. The smoke client retains the HTML-created DLMS
session and CSRF cookies, then sends the session-bound CSRF token with matching
same-origin request headers for **Shutdown DLMS**; it does not bypass the
application security boundary.

Filename, checksum, PE/ELF/Mach-O architecture, macOS bundle-structure, and
bundle-metadata checks are portable and run consistently on every host. POSIX
execute permission is checked from explicit mode bits when the verifier runs on
Linux or macOS. A Windows filesystem cannot faithfully represent those bits, so
cross-host Windows verification still performs the portable structural checks
and leaves executable-permission enforcement to the required native Linux or
macOS verification run. The extracted macOS executable is checked during its
native smoke test. `--smoke` remains restricted to the matching target operating
system and architecture.

## Recommended: one-command native release

After the owner freezes a reviewed commit containing DLMS-124/136, activate the
native build environment (`requirements-build.txt`) and run:

```text
python tools/build_native_release.py --target fedora44-x86_64 --expected-commit FULL_40_CHARACTER_RELEASE_COMMIT --expected-version 3.2.0
```

Replace the SHA placeholder with the independently agreed frozen commit, not a
moving branch name. Targets are `fedora44-x86_64`, `ubuntu24.04-x86_64`,
`ubuntu26.04-x86_64`, `omarchy-quattro-x86_64`, `windows11-x86_64`, and
`macos-arm64`. Use the same command in PowerShell on Windows. The native OS and
architecture gate is mandatory. Fedora/Ubuntu ID and version are checked against
`os-release`; Omarchy requires an Arch/Omarchy host, and selecting that target
also asserts that the operator has confirmed the Quattro environment. The
acceptance record includes host/distribution metadata. This does not cross-compile, commit, tag or publish anything.

By default, the command validates the existing `.ocr-bundle`. Use `--ocr-bundle
PATH` to select another native bundle. `--prepare-ocr` prepares a **new** bundle
using the existing preparation helper; it accepts that helper's
`--tesseract-executable`, `--tessdata-dir`, three `--*-license` options and
`--license-cache`. Network license retrieval is opt-in with
`--prepare-ocr --download-missing-licenses`. Native Tesseract installation,
licenses and a working locked Python environment remain prerequisites; the
command does not install system packages or Python dependencies.

The command checks a clean tracked/untracked source tree, exact commit and
APP_VERSION, native host, port 9001 and dependency consistency. It prepares or
validates OCR, builds/runs the frozen OCR probe, builds the application, stages
the canonical native artifact, verifies it and runs native smoke. It then uses
`package_release.py` to create and verify the final package and smoke its exact
clean-extracted executable. Both smoke paths compare the running
`X-DLMS-Version` response header with expected APP_VERSION; a missing header,
stale binary or mismatch fails qualification. Existing filename and macOS
bundle-version checks remain active. Structural-only verification is not a
runtime-version qualification.

Every run creates fresh task-owned PyInstaller **work, dist and cache** paths;
probe and application work/dist paths are separate. Repository `build/` and
`dist/` are never used as native inputs or recursively deleted. `--clean` alone
is not a clean-build guarantee. All task-owned intermediates are removed on
success or failure. Port conflicts fail before building; no existing server is
terminated for you.

On success, a new directory appears at
`build/native-release/<version>/<target>/<full-commit>/` containing the final
package, `SHA256SUMS.txt` and `acceptance.json`. The terminal prints target,
version, commit, package path and SHA-256 under `DLMS NATIVE RELEASE ACCEPTED`.
Use `--output-dir PATH` for a different **nonexistent** acceptance directory,
outside the source tree or under an ignored build directory. Existing output
is never overwritten. Failure exits nonzero, identifies the failing stage, and
publishes no acceptance directory. Native smoke still captures bounded launch
diagnostics. Source cleanliness/version/commit are checked again before final
promotion. This is automation of build gates, not a substitute for desktop,
OCR-workflow or platform-specific UAT below.

macOS still uses native `ditto`; final ZIP roots remain `DLMS.app`, `README.txt`
and `sample_quiz.txt`. The other platform package layouts are unchanged.
Published 3.2.0 packages and the historical frozen tag are not replaced by this
change. Older binaries without the runtime header cannot pass the strengthened
smoke gate; use tools from their historical release if reproducing that release.

## Manual component reference

The steps below remain useful for diagnosing individual stages. For a qualified
new release use the orchestrator above. If invoking PyInstaller manually, pass
new empty `--workpath` and `--distpath` directories for each build and stage only
from those directories; never rely on `--clean` with an old `dist/` tree.

### Manual build prerequisites

1. Create a clean environment from `requirements-lock.txt`, then install
   `requirements-build.txt`.
2. Install the target's native Tesseract packages and prepare or validate the
   ignored `.ocr-bundle` with `tools/prepare_ocr_bundle.py`, following
   `docs/OCR_PACKAGING.md`. Set the printed absolute
   `DLMS_TESSERACT_BUNDLE_ROOT` value in the build shell.
3. Build and run `DLMS-OCR-Probe.spec`. This strict frozen gate fails rather
   than silently producing an intended OCR release without its bundled runtime.
4. Run the focused release tests and the full isolated pytest and unittest
   suites, compilation, and `git diff --check`.
5. Build natively with `python -m PyInstaller --clean --noconfirm --workpath NEW_EMPTY_WORK_DIR --distpath NEW_EMPTY_DIST_DIR DLMS.spec`.
   PyInstaller does not cross-build Windows, Linux, or macOS artifacts.
6. Stage only the verified native input in `releases/`, using the name below. Do not
   stage `build/`, `dist/`, user data, logs, databases, or virtual environments.

## OCR-specific native gate

OCR-enabled release artifacts have an additional platform-native gate described
in `docs/OCR_PACKAGING.md`. The DLMS 3.1.0 native artifacts have completed
build and smoke verification on Fedora 44 x86-64, Ubuntu 24.04 x86-64, Ubuntu
26.04 x86-64, Omarchy Quattro x86-64, Windows 11 x86-64, and macOS Apple
Silicon arm64. Future rebuilds must repeat the target-native gate.

For each target, use `tools/prepare_ocr_bundle.py` to stage and validate a
platform-native Tesseract bundle, set the absolute
`DLMS_TESSERACT_BUNDLE_ROOT` path in the same shell that runs PyInstaller,
build and run the strict `DLMS-OCR-Probe.spec`, then build the canonical spec.
Verify that the exact artifact contains the executable, native dependencies,
English tessdata, TSV config, PDFium, and required licenses. Then prove
screenshot OCR, scanned-PDF OCR, timeout/cancellation, and no dependence on a
system Tesseract. Run the final OCR smoke on a clean machine where
`command -v tesseract` (Linux) or
`Get-Command tesseract.exe -ErrorAction SilentlyContinue` (Windows) finds no
system executable. Do not infer cross-platform OCR support from another target.

## Windows 11 x86_64

Build with native 64-bit Windows Python. Stage:

```powershell
Copy-Item dist\DLMS.exe releases\DLMS-3.2.0-windows11-x86_64.exe
python tools\verify_release_artifact.py windows-x86_64 releases\DLMS-3.2.0-windows11-x86_64.exe --smoke
```

The generic PyInstaller output name `dist\DLMS.exe` is an intermediate build
name only. Copying it to the stable native-input name is required; the final ZIP
later contains exactly `DLMS-3.2.0-windows11-x86_64.exe` inside the matching
versioned wrapper. The command validates the PE architecture, native-input name, controlled data-root
initialization, server availability, root/static/Help/Settings/Library routes,
clean Shutdown DLMS, and a successful restart.

After a successful protected `POST /api/shutdown`, the current Windows
PyInstaller/SIGINT shutdown path may report exit code `2`. The verifier accepts
that code only for this acknowledged Windows shutdown; startup exits, rejected
shutdown requests, timeouts, and every other unexpected nonzero exit remain
failures.

Native UAT still required: launch the staged `.exe` through the normal Explorer
path, accept or document any Windows security prompt, confirm the browser UI
opens, open Help, Settings, and Quiz Library, and inspect the displayed data
directory in Settings. It should be `%APPDATA%\DLMS` unless an explicit
`QUIZAPP_DATA_DIR` override was used. Exercise a representative existing quiz
in Study and Exam mode, then use **Shutdown DLMS**.

## Linux x86_64

Build each Linux artifact with native x86_64 Python on the operating system
named in its filename. Stage each build under its exact final name, make it
executable, and run the same internal `linux-x86_64` verification target:

```bash
cp dist/DLMS releases/DLMS-3.2.0-fedora44-x86_64
chmod +x releases/DLMS-3.2.0-fedora44-x86_64
python tools/verify_release_artifact.py linux-x86_64 releases/DLMS-3.2.0-fedora44-x86_64 --smoke

cp dist/DLMS releases/DLMS-3.2.0-ubuntu24.04-x86_64
chmod +x releases/DLMS-3.2.0-ubuntu24.04-x86_64
python tools/verify_release_artifact.py linux-x86_64 releases/DLMS-3.2.0-ubuntu24.04-x86_64 --smoke

cp dist/DLMS releases/DLMS-3.2.0-ubuntu26.04-x86_64
chmod +x releases/DLMS-3.2.0-ubuntu26.04-x86_64
python tools/verify_release_artifact.py linux-x86_64 releases/DLMS-3.2.0-ubuntu26.04-x86_64 --smoke

cp dist/DLMS releases/DLMS-3.2.0-omarchy-quattro-x86_64
chmod +x releases/DLMS-3.2.0-omarchy-quattro-x86_64
python tools/verify_release_artifact.py linux-x86_64 releases/DLMS-3.2.0-omarchy-quattro-x86_64 --smoke
```

Native UAT still required: launch the staged file from the intended desktop
environment, confirm the browser UI opens, visit Help, Settings, and Quiz
Library, run a representative existing quiz in Study and Exam mode, and shut it
down from the UI. In Settings, confirm the data directory is
`$XDG_DATA_HOME/DLMS`, or `~/.local/share/DLMS` when `XDG_DATA_HOME` is unset,
unless explicitly overridden.

## macOS Apple Silicon

Build with native `arm64` Python on an Apple Silicon Mac. Stage only the
application bundle ZIP:

```bash
python -c "import platform; assert platform.machine() == 'arm64', platform.machine()"
python -m PyInstaller --clean --noconfirm DLMS.spec
mkdir -p releases
ditto -c -k --sequesterRsrc --keepParent dist/DLMS.app releases/DLMS-3.2.0-macos-arm64.zip
python tools/verify_release_artifact.py macos-arm64 releases/DLMS-3.2.0-macos-arm64.zip --smoke
```

The verifier requires exactly one top-level `DLMS.app`, validates
`Contents/Info.plist` and `Contents/MacOS/DLMS`, confirms the executable is
arm64 Mach-O, rejects common runtime-data entries, then runs the controlled
start/route/shutdown/restart smoke test against the bundled executable. For the
smoke launch it extracts the ZIP with macOS `ditto`, preserving the framework
symlinks and metadata that Python ZIP extraction cannot faithfully restore. It
also removes shell Python-launcher overrides so the app uses its embedded
PyInstaller runtime, like a Finder launch. If startup fails, the verifier prints
the captured packaged-launch diagnostic tail.

Native UAT still required: extract the staged ZIP, drag `DLMS.app` to
`/Applications`, and launch it through Finder. Verify the documented Gatekeeper
first-run experience; the application is intentionally unsigned and not
notarized. Confirm the browser UI opens, Help, Settings, and Quiz Library work,
an existing quiz works in Study and Exam mode, and **Shutdown DLMS** exits it.
Settings should show `~/Library/Application Support/DLMS` unless explicitly
overridden.

## Intel macOS

Intel macOS is not a default release target. Only publish
`DLMS-3.2.0-macos-x86_64.zip` after building with native `x86_64` macOS
Python and completing the same command/UAT flow with `macos-x86_64`. Do not
label the Apple Silicon archive as Intel-compatible.

## Final downloadable packages

### Native build machine: package one finished target

After the canonical native artifact passes its preceding structural check,
native smoke, and UAT, package it on that same host with the authoritative
end-user files in `release_assets/`. Use a **different** output directory from
the native artifact. The following examples also clean-extract and smoke the
completed final archive before it is made visible in the output directory.

Run the matching command on each Linux build host:

```bash
python tools/package_release.py \
  --target fedora44-x86_64 \
  --artifact releases/DLMS-3.2.0-fedora44-x86_64 \
  --output-dir release-packages \
  --smoke

python tools/package_release.py \
  --target ubuntu24.04-x86_64 \
  --artifact releases/DLMS-3.2.0-ubuntu24.04-x86_64 \
  --output-dir release-packages \
  --smoke

python tools/package_release.py \
  --target ubuntu26.04-x86_64 \
  --artifact releases/DLMS-3.2.0-ubuntu26.04-x86_64 \
  --output-dir release-packages \
  --smoke

python tools/package_release.py \
  --target omarchy-quattro-x86_64 \
  --artifact releases/DLMS-3.2.0-omarchy-quattro-x86_64 \
  --output-dir release-packages \
  --smoke
```

```powershell
python tools\package_release.py `
  --target windows11-x86_64 `
  --artifact releases\DLMS-3.2.0-windows11-x86_64.exe `
  --output-dir release-packages `
  --smoke
```

```bash
python tools/package_release.py \
  --target macos-arm64 \
  --artifact releases/DLMS-3.2.0-macos-arm64.zip \
  --output-dir release-packages \
  --smoke
```

The single-target helper enforces the target's canonical native-input and final
package names, validates the native artifact, creates the final package in a
temporary directory, adds the two authoritative release assets, validates the
finished package, and, with `--smoke`, clean-extracts and launches that package
through the existing native smoke verifier. It moves the package to the output
directory only after every requested gate passes. It then prints the SHA-256 of
the exact completed archive; it never reports an intermediate artifact hash as
the release-package hash. A failed validation or smoke does not publish a
partial final package. The helper does not build or modify an executable.

Record the printed hash with the transfer notes. It can be recomputed before
and after transfer with `sha256sum <package>` on Linux,
`shasum -a 256 <package>` on macOS, or
`Get-FileHash <package> -Algorithm SHA256` in PowerShell. The bytes and digest
must remain unchanged.

### Coordinated all-six compatibility mode

The existing coordinated mode remains available when all six verified native
inputs have already been collected in one staging directory:

```bash
python tools/package_release.py \
  releases \
  build/release-packages/3.2.0
```

This mode validates all six native inputs before writing anything. It refuses
to use the staging directory as its output or overwrite an existing final
package. It assembles and structurally validates all output in a temporary
directory before publishing the six archives to the requested output directory.
Because one host cannot natively smoke all three operating-system families,
each final archive still requires `verify_release_package.py --smoke` on its
matching host. These outputs are the one canonical final distributable set; do
not create a second upload archive by hand.

The final archives and their exact payload layouts are platform-specific:

```text
DLMS-3.2.0-fedora44-x86_64.tar.gz
└── DLMS-3.2.0-fedora44-x86_64/
    ├── DLMS-3.2.0-fedora44-x86_64
    ├── README.txt
    └── sample_quiz.txt

DLMS-3.2.0-ubuntu24.04-x86_64.tar.gz
└── DLMS-3.2.0-ubuntu24.04-x86_64/
    ├── DLMS-3.2.0-ubuntu24.04-x86_64
    ├── README.txt
    └── sample_quiz.txt

DLMS-3.2.0-ubuntu26.04-x86_64.tar.gz
└── DLMS-3.2.0-ubuntu26.04-x86_64/
    ├── DLMS-3.2.0-ubuntu26.04-x86_64
    ├── README.txt
    └── sample_quiz.txt

DLMS-3.2.0-windows11-x86_64.zip
└── DLMS-3.2.0-windows11-x86_64/
    ├── DLMS-3.2.0-windows11-x86_64.exe
    ├── README.txt
    └── sample_quiz.txt

DLMS-3.2.0-macos-arm64.zip
├── DLMS.app/
├── README.txt
└── sample_quiz.txt

DLMS-3.2.0-omarchy-quattro-x86_64.tar.gz
└── DLMS-3.2.0-omarchy-quattro-x86_64/
    ├── DLMS-3.2.0-omarchy-quattro-x86_64
    ├── README.txt
    └── sample_quiz.txt
```

Linux executables are written to the tar archives with mode `0755`; release
documents use `0644`. The package verifier requires at least one execute bit on
each archived Linux executable, independent of the verifier host filesystem.

The staged macOS native input remains a `ditto` ZIP containing one root-level
`DLMS.app`. The packaging helper copies that verified ZIP, then appends the two
authoritative release documents at the archive root. It does not materialize or
renest the app, does not add a versioned wrapper, and retains the existing app
member data and ZIP metadata. The final-package verifier requires exactly
`DLMS.app`, `README.txt`, and `sample_quiz.txt` at the root, requires both
documents to match their tracked sources under the text comparison described
below, and rechecks arm64 Mach-O, bundle identifier/version metadata,
executable mode, resources, safe unique paths, and content exclusions.

`tools/verify_release_package.py` requires every package's documents to match
the tracked sources. For `README.txt` and `sample_quiz.txt` only, it canonicalizes
CRLF and lone CR newlines to LF before comparing; every other textual byte must
still match. Executable and other binary comparisons remain byte-exact. Linux
and Windows packages may contain only the three listed files in their versioned
wrapper. The macOS package may contain only root-level `DLMS.app`, `README.txt`,
and `sample_quiz.txt` (plus associated `__MACOSX` metadata when present). It
rejects unsafe, duplicate, and case-colliding paths and common
development/runtime content such as `build/`, `dist/`, virtual environments,
`__pycache__/`, databases, logs, backups, and uploads.

## Clean-extract and smoke the exact final distributables

Portable member inspection is necessary but is not the final gate. Single-target
packaging with `--smoke` performs this gate before publishing the final file.
The commands below are the equivalent explicit verification and may be used to
repeat the check or to validate packages produced by coordinated all-six mode.
They first check the archive contract, extract into a new temporary directory,
recheck the resulting filesystem layout and executable, and only then run the
existing isolated start/routes/shutdown/restart smoke against the extracted
executable. Set `PACKAGE_DIR` to the final-package directory on each native host.

Run the four Linux packages on their individually named systems:

```bash
python tools/verify_release_package.py "$PACKAGE_DIR/DLMS-3.2.0-fedora44-x86_64.tar.gz" --smoke
python tools/verify_release_package.py "$PACKAGE_DIR/DLMS-3.2.0-ubuntu24.04-x86_64.tar.gz" --smoke
python tools/verify_release_package.py "$PACKAGE_DIR/DLMS-3.2.0-ubuntu26.04-x86_64.tar.gz" --smoke
python tools/verify_release_package.py "$PACKAGE_DIR/DLMS-3.2.0-omarchy-quattro-x86_64.tar.gz" --smoke
```

Each Linux run uses the exact final `.tar.gz`, requires the matching versioned
wrapper, executable, `README.txt`, and `sample_quiz.txt`, preserves an execute
bit, reconfirms x86-64 ELF after extraction, and launches that extracted file.

Run the Windows package on native 64-bit Windows:

```powershell
python tools\verify_release_package.py "$env:PACKAGE_DIR\DLMS-3.2.0-windows11-x86_64.zip" --smoke
```

The Windows flow uses PowerShell `Expand-Archive`, requires the exact versioned
wrapper and stable-named `DLMS-3.2.0-windows11-x86_64.exe`, requires the two
release documents, reconfirms x86-64 PE after extraction, and launches the
extracted `.exe`. A stray `DLMS.exe`, obsolete platform name, second executable,
or incorrect wrapper is a failure. SmartScreen or Smart App Control warnings
remain expected normal-user UAT for this unsigned independent application; they
are not structural validation failures.

Run the macOS package on Apple Silicon macOS:

```bash
python tools/verify_release_package.py "$PACKAGE_DIR/DLMS-3.2.0-macos-arm64.zip" --smoke
```

The macOS flow uses `ditto -x -k`, requires `<temp>/DLMS.app` with no versioned
wrapper, requires `<temp>/README.txt` and `<temp>/sample_quiz.txt` to match the
tracked release assets, reconfirms the executable bit, arm64 Mach-O, bundle
identifier and version metadata, resources, and archived bundle symlinks, then
launches `<temp>/DLMS.app/Contents/MacOS/DLMS`.

The final archive that passes this gate is the file that must be transferred,
checksummed, and uploaded. Native inputs remain clearly separated in `releases`;
final distributables remain in `release-packages`. Never substitute a
smoke-tested native input for a later repackaged upload, or repackage a passing
final archive.

The canonical release handoff is therefore:

1. Build the native artifact on the named platform.
2. Verify that native input structurally and with its isolated native smoke.
3. On that native host, create the one canonical final release archive with
   single-target mode and `--smoke`.
4. Record the SHA-256 printed only after that exact final archive passes its
   platform-specific layout, clean-extraction, and native smoke gates.
5. Transfer that unchanged finished package to the release assembly machine and
   compare its SHA-256 with the native-host value.
6. After all six finished packages arrive, generate and validate the combined
   `SHA256SUMS.txt` from those exact files. Intermediate native artifacts are not
   needed on the assembly machine.
7. Upload those unchanged archives and `SHA256SUMS.txt`.
8. Download each published asset once.
9. Compare its SHA-256 to the pre-upload validated value.
10. When the bytes match exactly, do not repeat the native smoke merely because
    GitHub hosted the file.

## Final checksums and upload set

On the release assembly machine, collect only the six exact final archives that
passed their native clean-extraction smoke. Verify each transferred file against
the SHA-256 reported by its native host. Then generate the authoritative
combined manifest. The checksum helper derives the canonical six filenames from
the repository release version, requires exactly that set, structurally
validates each file again, and hashes those same bytes; it does not need the
intermediate native artifacts:

```bash
PACKAGE_DIR="$PWD/build/release-packages/3.2.0"
python tools/generate_sha256sums.py --output "$PACKAGE_DIR/SHA256SUMS.txt" \
  "$PACKAGE_DIR/DLMS-3.2.0-fedora44-x86_64.tar.gz" \
  "$PACKAGE_DIR/DLMS-3.2.0-ubuntu24.04-x86_64.tar.gz" \
  "$PACKAGE_DIR/DLMS-3.2.0-ubuntu26.04-x86_64.tar.gz" \
  "$PACKAGE_DIR/DLMS-3.2.0-windows11-x86_64.zip" \
  "$PACKAGE_DIR/DLMS-3.2.0-macos-arm64.zip" \
  "$PACKAGE_DIR/DLMS-3.2.0-omarchy-quattro-x86_64.tar.gz"
```

The helper sorts entries by basename and writes conventional
`<sha256>  <filename>` lines. It rejects missing, obsolete RC, stale generic, or
unexpected package names and must not receive raw binaries, GitHub source
archives, or `SHA256SUMS.txt` itself. Verify package contents, the exact six-file
set, and every checksum:

```bash
PACKAGE_DIR="$PWD/build/release-packages/3.2.0"
python tools/verify_release_package.py --complete-set \
  --checksums "$PACKAGE_DIR/SHA256SUMS.txt" \
  "$PACKAGE_DIR/DLMS-3.2.0-fedora44-x86_64.tar.gz" \
  "$PACKAGE_DIR/DLMS-3.2.0-ubuntu24.04-x86_64.tar.gz" \
  "$PACKAGE_DIR/DLMS-3.2.0-ubuntu26.04-x86_64.tar.gz" \
  "$PACKAGE_DIR/DLMS-3.2.0-windows11-x86_64.zip" \
  "$PACKAGE_DIR/DLMS-3.2.0-macos-arm64.zip" \
  "$PACKAGE_DIR/DLMS-3.2.0-omarchy-quattro-x86_64.tar.gz"
(cd "$PACKAGE_DIR" && sha256sum --check SHA256SUMS.txt)
```

Upload exactly these seven manually prepared assets:

1. `DLMS-3.2.0-fedora44-x86_64.tar.gz`
2. `DLMS-3.2.0-ubuntu24.04-x86_64.tar.gz`
3. `DLMS-3.2.0-ubuntu26.04-x86_64.tar.gz`
4. `DLMS-3.2.0-windows11-x86_64.zip`
5. `DLMS-3.2.0-macos-arm64.zip`
6. `DLMS-3.2.0-omarchy-quattro-x86_64.tar.gz`
7. `SHA256SUMS.txt`

GitHub automatically supplies repository source ZIP and tarball links. Do not
create or upload `DLMS-3.2.0-source.zip` or another manual source archive.

## Post-upload byte verification and normal-user UAT

DLMS-137 makes this the final acceptance gate for each uploaded package, on a
draft release or after publication. With GitHub CLI (`gh`) installed and access
to the release (authenticate for private/draft releases), run:

```text
python tools/accept_downloaded_release.py --repo drakahari/DLMS_next --tag v3.2.0 --asset DLMS-3.2.0-macos-arm64.zip
python tools/accept_downloaded_release.py --repo drakahari/DLMS_next --tag v3.2.0 --asset DLMS-3.2.0-windows11-x86_64.zip
```

Repeat for all six final package names. The tool downloads the exact named asset
and `SHA256SUMS.txt` from the same explicit GitHub release, checks the published
checksum, and calls the existing package verifier. It never uploads or changes
a release. The trusted local release tag must already exist; `--source-root`
can select another local repository containing it. Only `app.py` and the two
support documents are read from that tag into temporary verifier inputs, without
switching branches. This avoids comparing older packages with newer support
documents. The tag's APP_VERSION must match the requested version.

Downloads and `acceptance.json` are retained under a unique ignored
`build/downloaded-release/<tag>/<asset>/<run>/` directory. `--output-dir PATH`
selects an explicit **new** directory; existing directories/records are refused.
Temporary source inputs are cleaned. Failures produce a nonzero exit and failed
JSON evidence; invalid arguments or an unwritable/existing output directory fail
before evidence can be created. Failed downloads may leave partial files in
that failed run directory; never use them for manual acceptance.

Evidence includes repository/tag, local tag commit, asset and manifest hashes,
UTC timestamps, checksum/package/native-smoke results, and automated
`PASSED`/`FAILED` status. Manual platform acceptance always remains `REQUIRED`.
An automated pass without `--smoke` proves checksum and package structure only.
Compare the downloaded hash with the native build's acceptance record as well:
agreement with a manifest hosted alongside the package alone is not independent
proof of build provenance. The local tag is a trusted prerequisite, not a remote
tag-authenticity check.

`--smoke` additionally delegates to the existing clean-extraction/native-smoke
verifier on the matching native host, including runtime version verification.
Wrong-host and smoke failures fail acceptance; they are never silently skipped.
No OS security settings are changed. Older releases such as the original 3.2.0
may lack the runtime-version header required by the current smoke gate. Their
checksum/structure acceptance still works; use their recorded native UAT and
the manual checks below rather than weakening the current smoke gate. Identical
bytes with existing native qualification need not be smoked again solely
because they were downloaded.

**Manual macOS acceptance:** use the actual browser-downloaded release ZIP
(verify its hash against the accepted asset), extract with Finder, and confirm
root-level `DLMS.app`, `README.txt` and `sample_quiz.txt`. Move the app to
`/Applications`, attempt first launch, and record the unsigned/unnotarized
Gatekeeper behavior. Verify the release README's Control-click/Open or
Privacy & Security → Open Anyway workflow where the OS offers it. Confirm DLMS
runs afterward, opens its UI, shuts down and restarts normally. Record OS version,
warnings and outcome separately alongside the JSON evidence.

**Manual Windows acceptance:** use the actual browser-downloaded ZIP (verify
its hash), extract with Explorer, and launch the executable in the versioned
folder. Record any unsigned-app SmartScreen or Smart App Control warning. Verify
the README's user-approval path where offered, then confirm normal DLMS operation,
shutdown and restart. If policy blocks launch without an approval path, record
that result; do not disable protection to obtain a pass.

CLI downloads/native smoke do not establish browser download-origin marking or
first-launch warning behavior. A CLI download that launches without a warning
does not complete either manual check. Do not remove quarantine attributes,
unblock files programmatically, or bypass Gatekeeper, SmartScreen or Smart App
Control. No tool result claims the manual checks passed. If draft assets change,
rerun acceptance against the final published bytes.

For the target platform's expected normal data location without starting DLMS:

```bash
python tools/verify_release_artifact.py macos-arm64 --print-expected-data-dir
```

The verifier complements, but cannot replace, native UAT. It deliberately does
not sign, notarize, publish, upload, or create installers; those are outside the
current DLMS packaging model. macOS ZIP contents can be directly enumerated for
runtime-data exclusions. Windows and Linux are intentionally one-file
PyInstaller executables inside their final packages, so their embedded
PyInstaller payload is not treated as a generic archive. Their release guard is
the canonical-spec hygiene test, native-input validation, final-package
inspection, clean extraction, native-header/checksum checks, and isolated native
smoke from the extracted final distributable.

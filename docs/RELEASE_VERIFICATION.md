# Native Release Verification

This is the canonical native-artifact and final-distributable verification
procedure for a DLMS release. Run it from the same clean checkout used to build
and stage the release. It is deliberately small: it verifies the exact archives
being published and requires real native UAT where desktop behavior cannot be
established from another operating system.

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

## Before every target build

1. Create a clean environment from `requirements-lock.txt`, then install
   `requirements-build.txt`.
2. Run the focused release tests and the full isolated pytest and unittest
   suites, compilation, and `git diff --check`.
3. Build natively with `python -m PyInstaller --clean --noconfirm DLMS.spec`.
   PyInstaller does not cross-build Windows, Linux, or macOS artifacts.
4. Stage only the verified native input in `releases/`, using the name below. Do not
   stage `build/`, `dist/`, user data, logs, databases, or virtual environments.

## Windows 11 x86_64

Build with native 64-bit Windows Python. Stage:

```powershell
Copy-Item dist\DLMS.exe releases\DLMS-3.0.2-windows11-x86_64.exe
python tools\verify_release_artifact.py windows-x86_64 releases\DLMS-3.0.2-windows11-x86_64.exe --smoke
```

The generic PyInstaller output name `dist\DLMS.exe` is an intermediate build
name only. Copying it to the stable native-input name is required; the final ZIP
later contains exactly `DLMS-3.0.2-windows11-x86_64.exe` inside the matching
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
cp dist/DLMS releases/DLMS-3.0.2-fedora44-x86_64
chmod +x releases/DLMS-3.0.2-fedora44-x86_64
python tools/verify_release_artifact.py linux-x86_64 releases/DLMS-3.0.2-fedora44-x86_64 --smoke

cp dist/DLMS releases/DLMS-3.0.2-ubuntu24.04-x86_64
chmod +x releases/DLMS-3.0.2-ubuntu24.04-x86_64
python tools/verify_release_artifact.py linux-x86_64 releases/DLMS-3.0.2-ubuntu24.04-x86_64 --smoke

cp dist/DLMS releases/DLMS-3.0.2-ubuntu26.04-x86_64
chmod +x releases/DLMS-3.0.2-ubuntu26.04-x86_64
python tools/verify_release_artifact.py linux-x86_64 releases/DLMS-3.0.2-ubuntu26.04-x86_64 --smoke

cp dist/DLMS releases/DLMS-3.0.2-omarchy-quattro-x86_64
chmod +x releases/DLMS-3.0.2-omarchy-quattro-x86_64
python tools/verify_release_artifact.py linux-x86_64 releases/DLMS-3.0.2-omarchy-quattro-x86_64 --smoke
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
ditto -c -k --sequesterRsrc --keepParent dist/DLMS.app releases/DLMS-3.0.2-macos-arm64.zip
python tools/verify_release_artifact.py macos-arm64 releases/DLMS-3.0.2-macos-arm64.zip --smoke
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
`DLMS-3.0.2-macos-x86_64.zip` after building with native `x86_64` macOS
Python and completing the same command/UAT flow with `macos-x86_64`. Do not
label the Apple Silicon archive as Intel-compatible.

## Final downloadable packages

Native build artifacts remain read-only after they pass the preceding structural
checks, smoke test, and UAT. Package them with the authoritative end-user files
in `release_assets/` by writing to a **different** output directory:

```bash
python tools/package_release.py \
  /home/drak/DLMS_builds/DLMS-3.0.2 \
  /home/drak/DLMS_builds/DLMS-3.0.2-packages
```

The helper validates all six native inputs before writing anything. It refuses
to use the staging directory as its output or overwrite an existing final
package. It assembles and structurally validates all output in a temporary
directory before publishing the six archives to the requested output directory.
It does not build or modify an executable. These outputs are the one canonical
final distributable set; do not create a second upload archive by hand.

The final archives and their exact payload layouts are platform-specific:

```text
DLMS-3.0.2-fedora44-x86_64.tar.gz
└── DLMS-3.0.2-fedora44-x86_64/
    ├── DLMS-3.0.2-fedora44-x86_64
    ├── README.txt
    └── sample_quiz.txt

DLMS-3.0.2-ubuntu24.04-x86_64.tar.gz
└── DLMS-3.0.2-ubuntu24.04-x86_64/
    ├── DLMS-3.0.2-ubuntu24.04-x86_64
    ├── README.txt
    └── sample_quiz.txt

DLMS-3.0.2-ubuntu26.04-x86_64.tar.gz
└── DLMS-3.0.2-ubuntu26.04-x86_64/
    ├── DLMS-3.0.2-ubuntu26.04-x86_64
    ├── README.txt
    └── sample_quiz.txt

DLMS-3.0.2-windows11-x86_64.zip
└── DLMS-3.0.2-windows11-x86_64/
    ├── DLMS-3.0.2-windows11-x86_64.exe
    ├── README.txt
    └── sample_quiz.txt

DLMS-3.0.2-macos-arm64.zip
└── DLMS.app/

DLMS-3.0.2-omarchy-quattro-x86_64.tar.gz
└── DLMS-3.0.2-omarchy-quattro-x86_64/
    ├── DLMS-3.0.2-omarchy-quattro-x86_64
    ├── README.txt
    └── sample_quiz.txt
```

Linux executables are written to the tar archives with mode `0755`; release
documents use `0644`. The package verifier requires at least one execute bit on
each archived Linux executable, independent of the verifier host filesystem.

The staged macOS input is already the final native `ditto` ZIP containing one
root-level `DLMS.app`. The packaging helper promotes that ZIP byte-for-byte; it
does not rewrite members or add a versioned wrapper, `README.txt`, or
`sample_quiz.txt`. Exact-byte promotion preserves Unix modes, symbolic links,
resource-fork/AppleDouble metadata, timestamps, compression, and ZIP extra
fields without materializing the bundle on a non-macOS filesystem. The final
package verifier requires the app-only root layout and rechecks arm64 Mach-O,
bundle identifier/version metadata, executable mode, resources, safe unique
paths, and content exclusions.

`tools/verify_release_package.py` requires Linux and Windows package documents
to match the tracked sources byte-for-byte. Those packages may contain only the
three listed files in their versioned wrapper. The macOS package may contain
only root-level `DLMS.app` (plus associated `__MACOSX` metadata when present).
It rejects unsafe, duplicate, and case-colliding paths and common
development/runtime content such as `build/`, `dist/`, virtual environments,
`__pycache__/`, databases, logs, backups, and uploads.

## Clean-extract and smoke the exact final distributables

Portable member inspection is necessary but is not the final gate. Return each
archive from `DLMS-3.0.2-packages` to its named native build host and run
`verify_release_package.py --smoke` against that exact file. The command first
checks the archive contract, extracts into a new temporary directory, rechecks
the resulting filesystem layout and executable, and only then runs the existing
isolated start/routes/shutdown/restart smoke against the extracted executable.
Set `PACKAGE_DIR` to that final-package directory on each host before running
the commands below.

Run the four Linux packages on their individually named systems:

```bash
python tools/verify_release_package.py "$PACKAGE_DIR/DLMS-3.0.2-fedora44-x86_64.tar.gz" --smoke
python tools/verify_release_package.py "$PACKAGE_DIR/DLMS-3.0.2-ubuntu24.04-x86_64.tar.gz" --smoke
python tools/verify_release_package.py "$PACKAGE_DIR/DLMS-3.0.2-ubuntu26.04-x86_64.tar.gz" --smoke
python tools/verify_release_package.py "$PACKAGE_DIR/DLMS-3.0.2-omarchy-quattro-x86_64.tar.gz" --smoke
```

Each Linux run uses the exact final `.tar.gz`, requires the matching versioned
wrapper, executable, `README.txt`, and `sample_quiz.txt`, preserves an execute
bit, reconfirms x86-64 ELF after extraction, and launches that extracted file.

Run the Windows package on native 64-bit Windows:

```powershell
python tools\verify_release_package.py "$env:PACKAGE_DIR\DLMS-3.0.2-windows11-x86_64.zip" --smoke
```

The Windows flow uses PowerShell `Expand-Archive`, requires the exact versioned
wrapper and stable-named `DLMS-3.0.2-windows11-x86_64.exe`, requires the two
release documents, reconfirms x86-64 PE after extraction, and launches the
extracted `.exe`. A stray `DLMS.exe`, obsolete platform name, second executable,
or incorrect wrapper is a failure. SmartScreen or Smart App Control warnings
remain expected normal-user UAT for this unsigned independent application; they
are not structural validation failures.

Run the macOS package on Apple Silicon macOS:

```bash
python tools/verify_release_package.py "$PACKAGE_DIR/DLMS-3.0.2-macos-arm64.zip" --smoke
```

The macOS flow uses `ditto -x -k`, requires `<temp>/DLMS.app` with no versioned
wrapper, reconfirms the executable bit, arm64 Mach-O, bundle identifier and
version metadata, resources, and archived bundle symlinks, then launches
`<temp>/DLMS.app/Contents/MacOS/DLMS`. `README.txt` and `sample_quiz.txt` are not
part of the macOS archive contract.

The final archive that passes this gate is the artifact that must be checksummed
and uploaded. Native inputs remain clearly separated in `DLMS-3.0.2`; final
distributables remain in `DLMS-3.0.2-packages`. Never substitute a smoke-tested
native input for a later repackaged upload, or repackage a passing final archive.

The canonical release handoff is therefore:

1. Build the native artifact on the named platform.
2. Verify that native input structurally and with its isolated native smoke.
3. Create the one canonical final release archive in the package directory.
4. Clean-extract that exact final archive.
5. Verify its platform-specific top-level layout and names.
6. Smoke-test the executable or app from that clean extraction.
7. After all six native confirmations, compute SHA-256 from those exact final
   package-directory files.
8. Upload those unchanged archives and `SHA256SUMS.txt`.
9. Download each published asset once.
10. Compare its SHA-256 to the pre-upload validated value.
11. When the bytes match exactly, do not repeat the native smoke merely because
    GitHub hosted the file.

## Final checksums and upload set

Generate the checksum manifest only after all six exact final archives have
passed their native clean-extraction smoke. The checksum helper derives the
canonical six filenames from the repository release version, requires exactly
that set, structurally validates each file again, and hashes those same bytes:

```bash
PACKAGE_DIR=/home/drak/DLMS_builds/DLMS-3.0.2-packages
python tools/generate_sha256sums.py --output "$PACKAGE_DIR/SHA256SUMS.txt" \
  "$PACKAGE_DIR/DLMS-3.0.2-fedora44-x86_64.tar.gz" \
  "$PACKAGE_DIR/DLMS-3.0.2-ubuntu24.04-x86_64.tar.gz" \
  "$PACKAGE_DIR/DLMS-3.0.2-ubuntu26.04-x86_64.tar.gz" \
  "$PACKAGE_DIR/DLMS-3.0.2-windows11-x86_64.zip" \
  "$PACKAGE_DIR/DLMS-3.0.2-macos-arm64.zip" \
  "$PACKAGE_DIR/DLMS-3.0.2-omarchy-quattro-x86_64.tar.gz"
```

The helper sorts entries by basename and writes conventional
`<sha256>  <filename>` lines. It rejects missing, obsolete RC, stale generic, or
unexpected package names and must not receive raw binaries, GitHub source
archives, or `SHA256SUMS.txt` itself. Verify package contents, the exact six-file
set, and every checksum:

```bash
PACKAGE_DIR=/home/drak/DLMS_builds/DLMS-3.0.2-packages
python tools/verify_release_package.py --complete-set \
  --checksums "$PACKAGE_DIR/SHA256SUMS.txt" \
  "$PACKAGE_DIR/DLMS-3.0.2-fedora44-x86_64.tar.gz" \
  "$PACKAGE_DIR/DLMS-3.0.2-ubuntu24.04-x86_64.tar.gz" \
  "$PACKAGE_DIR/DLMS-3.0.2-ubuntu26.04-x86_64.tar.gz" \
  "$PACKAGE_DIR/DLMS-3.0.2-windows11-x86_64.zip" \
  "$PACKAGE_DIR/DLMS-3.0.2-macos-arm64.zip" \
  "$PACKAGE_DIR/DLMS-3.0.2-omarchy-quattro-x86_64.tar.gz"
(cd "$PACKAGE_DIR" && sha256sum --check SHA256SUMS.txt)
```

Upload exactly these seven manually prepared assets:

1. `DLMS-3.0.2-fedora44-x86_64.tar.gz`
2. `DLMS-3.0.2-ubuntu24.04-x86_64.tar.gz`
3. `DLMS-3.0.2-ubuntu26.04-x86_64.tar.gz`
4. `DLMS-3.0.2-windows11-x86_64.zip`
5. `DLMS-3.0.2-macos-arm64.zip`
6. `DLMS-3.0.2-omarchy-quattro-x86_64.tar.gz`
7. `SHA256SUMS.txt`

GitHub automatically supplies repository source ZIP and tarball links. Do not
create or upload `DLMS-3.0.2-source.zip` or another manual source archive.

## Post-upload byte verification and normal-user UAT

Download each published platform asset and the published `SHA256SUMS.txt` once
into a clean directory. Recompute each download's SHA-256 and compare it with
the corresponding pre-upload value. This establishes that GitHub is serving the
exact final archive that passed structural, clean-extraction, and native smoke
validation. If the bytes match, do not repeat the full native smoke solely
because the file was downloaded from GitHub.

On Windows, additionally use Explorer to extract the published ZIP, confirm the
versioned package folder and exact stable-named executable, and exercise the
documented SmartScreen or Smart App Control first-run path. On macOS, use Finder
to extract the published ZIP, confirm `DLMS.app` appears directly at the
extraction root, drag or move it to `/Applications`, and exercise the documented
Gatekeeper first-launch path. These are normal-user UAT checks separate from the
automated structural and server smoke tests.

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

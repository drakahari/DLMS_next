# Native Release Verification

This is the canonical native-artifact verification procedure for a DLMS
release. Run it from the same clean checkout used to build and stage the final
artifacts. It is deliberately small: it verifies the files being published and
requires real native UAT where desktop behavior cannot be established from
another operating system.

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
4. Stage only the final artifact in `releases/`, using the name below. Do not
   stage `build/`, `dist/`, user data, logs, databases, or virtual environments.

## Windows 11 x86_64

Build with native 64-bit Windows Python. Stage:

```powershell
Copy-Item dist\DLMS.exe releases\DLMS-3.0.2-windows11-x86_64.exe
python tools\verify_release_artifact.py windows-x86_64 releases\DLMS-3.0.2-windows11-x86_64.exe --smoke
```

The command validates the PE architecture, final name, controlled data-root
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
package. It assembles and validates all output in a temporary directory before
publishing the six archives to the requested output directory. It does not
build or modify an executable.

The final archives and their exact payload layouts are:

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
└── DLMS-3.0.2-macos-arm64/
    ├── DLMS.app/
    ├── README.txt
    └── sample_quiz.txt

DLMS-3.0.2-omarchy-quattro-x86_64.tar.gz
└── DLMS-3.0.2-omarchy-quattro-x86_64/
    ├── DLMS-3.0.2-omarchy-quattro-x86_64
    ├── README.txt
    └── sample_quiz.txt
```

Linux executables are written to the tar archives with mode `0755`; release
documents use `0644`. The package verifier requires at least one execute bit on
each archived Linux executable, independent of the verifier host filesystem.

The staged macOS input is already a native `ditto` ZIP containing one
`DLMS.app`. On the Framework Desktop, the packaging helper copies its ZIP
entries directly into the package wrapper without extracting the bundle. It
preserves each entry's bytes, Unix mode, symbolic-link representation,
timestamps, compression choice, and ZIP extra fields; AppleDouble/resource-fork
entries are moved under the matching wrapper when present. The helper does not
alter `DLMS.app`. The package verifier then rechecks the wrapper, arm64 Mach-O,
bundle version metadata, executable mode, required documents, and content
exclusions. This archive-to-archive method avoids restoring a POSIX app bundle
through a Linux filesystem or Python extraction.

`tools/verify_release_package.py` requires the package documents to match the
tracked sources byte-for-byte. Linux and Windows packages may contain only the
three listed files. The macOS package may contain only the two documents and
the `DLMS.app` bundle (plus associated `__MACOSX` metadata when present). It
rejects unsafe paths and common development/runtime content such as `build/`,
`dist/`, virtual environments, `__pycache__/`, databases, logs, backups, and
uploads.

## Final checksums and upload set

Generate the checksum manifest only after all six final archives exist:

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
`<sha256>  <filename>` lines. It must not receive raw binaries, GitHub source
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

For the target platform's expected normal data location without starting DLMS:

```bash
python tools/verify_release_artifact.py macos-arm64 --print-expected-data-dir
```

The verifier complements, but cannot replace, native UAT. It deliberately does
not sign, notarize, publish, upload, or create installers; those are outside the
current DLMS packaging model. macOS ZIP contents can be directly enumerated for
runtime-data exclusions. Windows and Linux are intentionally one-file PyInstaller
artifacts, so their embedded payload is not treated as a generic archive: their
release guard is the canonical-spec hygiene test, final artifact inspection,
native-header/checksum checks, and the isolated native smoke test.

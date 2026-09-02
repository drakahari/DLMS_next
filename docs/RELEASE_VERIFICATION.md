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
only that controlled data root.

## Before every target build

1. Create a clean environment from `requirements-lock.txt`, then install
   `requirements-build.txt`.
2. Run the focused release tests and the full isolated pytest and unittest
   suites, compilation, and `git diff --check`.
3. Build natively with `python -m PyInstaller --clean --noconfirm DLMS.spec`.
   PyInstaller does not cross-build Windows, Linux, or macOS artifacts.
4. Stage only the final artifact in `releases/`, using the name below. Do not
   stage `build/`, `dist/`, user data, logs, databases, or virtual environments.

## Windows x86_64

Build with native 64-bit Windows Python. Stage:

```powershell
Copy-Item dist\DLMS.exe releases\DLMS-3.0.2-RC4-windows-x86_64.exe
python tools\verify_release_artifact.py windows-x86_64 releases\DLMS-3.0.2-RC4-windows-x86_64.exe --smoke
```

The command validates the PE architecture, final name, controlled data-root
initialization, server availability, root/static/Help/Settings/Library routes,
clean Shutdown DLMS, and a successful restart.

Native UAT still required: launch the staged `.exe` through the normal Explorer
path, accept or document any Windows security prompt, confirm the browser UI
opens, open Help, Settings, and Quiz Library, and inspect the displayed data
directory in Settings. It should be `%APPDATA%\DLMS` unless an explicit
`QUIZAPP_DATA_DIR` override was used. Exercise a representative existing quiz
in Study and Exam mode, then use **Shutdown DLMS**.

## Linux x86_64

Build with native x86_64 Linux Python. Stage and make the final executable
executable:

```bash
cp dist/DLMS releases/DLMS-3.0.2-RC4-linux-x86_64
chmod +x releases/DLMS-3.0.2-RC4-linux-x86_64
python tools/verify_release_artifact.py linux-x86_64 releases/DLMS-3.0.2-RC4-linux-x86_64 --smoke
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
ditto -c -k --sequesterRsrc --keepParent dist/DLMS.app releases/DLMS-3.0.2-RC4-macos-arm64.zip
python tools/verify_release_artifact.py macos-arm64 releases/DLMS-3.0.2-RC4-macos-arm64.zip --smoke
```

The verifier requires exactly one top-level `DLMS.app`, validates
`Contents/Info.plist` and `Contents/MacOS/DLMS`, confirms the executable is
arm64 Mach-O, rejects common runtime-data entries, then runs the controlled
start/route/shutdown/restart smoke test against the bundled executable.

Native UAT still required: extract the staged ZIP, drag `DLMS.app` to
`/Applications`, and launch it through Finder. Verify the documented Gatekeeper
first-run experience; the application is intentionally unsigned and not
notarized. Confirm the browser UI opens, Help, Settings, and Quiz Library work,
an existing quiz works in Study and Exam mode, and **Shutdown DLMS** exits it.
Settings should show `~/Library/Application Support/DLMS` unless explicitly
overridden.

## Intel macOS

Intel macOS is not a default release target. Only publish
`DLMS-3.0.2-RC4-macos-x86_64.zip` after building with native `x86_64` macOS
Python and completing the same command/UAT flow with `macos-x86_64`. Do not
label the Apple Silicon archive as Intel-compatible.

## Final staged release set

After each supported target passes its native smoke test and UAT, generate one
manifest from the exact staged files:

```bash
python tools/generate_sha256sums.py --output releases/SHA256SUMS.txt releases/DLMS-3.0.2-RC4-*
```

Re-run structural/checksum verification against the final manifest before
uploading. The commands are portable Python; use the platform path syntax from
the sections above:

```bash
python tools/verify_release_artifact.py windows-x86_64 releases/DLMS-3.0.2-RC4-windows-x86_64.exe --checksums releases/SHA256SUMS.txt
python tools/verify_release_artifact.py linux-x86_64 releases/DLMS-3.0.2-RC4-linux-x86_64 --checksums releases/SHA256SUMS.txt
python tools/verify_release_artifact.py macos-arm64 releases/DLMS-3.0.2-RC4-macos-arm64.zip --checksums releases/SHA256SUMS.txt
```

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

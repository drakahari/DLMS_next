# Experimental Linux desktop AppImage and native icons

DLMS-144 adds an **experimental, optional Linux desktop package**. The six-target
native release matrix is unchanged. Fedora, Ubuntu and Omarchy native binaries
and their tar.gz packages remain required and are the supported server/headless
distribution path. An AppImage is not a universal-Linux compatibility claim.

The AppImage contains the existing target-native PyInstaller one-file executable,
its bundled Tesseract/English data and PDFium, plus an AppRun launcher, desktop
entry, icon and the existing support documents. It introduces no new application
runtime or data format. Double-clicking it dispatches DLMS's normal browser UI;
it is not a separate native window shell. Startup options pass through unchanged.
Data remains outside the image: normally `$XDG_DATA_HOME/DLMS` or
`~/.local/share/DLMS`, with the existing `QUIZAPP_DATA_DIR` override available.

## Build

Use the existing locked native build environment and prepared `.ocr-bundle`.
Additional build tools are `desktop-file-validate` (desktop-file-utils), an
official x86_64 `appimagetool` AppImage and its matching type-2 runtime. Supply
local SHA-256-pinned files; the builder never downloads tools or runtimes.
Pillow, already a DLMS dependency, generates icon formats from existing artwork.

The local evaluation used these official downloads (the `continuous` URLs can
change; verify the pins and retain the matching files for repeat builds):

| Input | SHA-256 |
|---|---|
| [appimagetool-x86_64.AppImage](https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage) | `a6d71e2b6cd66f8e8d16c37ad164658985e0cf5fcaa950c90a482890cb9d13e0` |
| [runtime-x86_64](https://github.com/AppImage/type2-runtime/releases/download/continuous/runtime-x86_64) | `1cc49bcf1e2ccd593c379adb17c9f85a36d619088296504de95b1d06215aebbf` |

Place them under ignored `build/appimage-tools/` and make appimagetool executable.
From the repository root, the exact evaluation command is:

```sh
.venv-build/bin/python tools/build_appimage.py \
  --target fedora44-x86_64 --expected-version 3.2.0 --candidate \
  --appimagetool build/appimage-tools/appimagetool-x86_64.AppImage \
  --appimagetool-sha256 a6d71e2b6cd66f8e8d16c37ad164658985e0cf5fcaa950c90a482890cb9d13e0 \
  --runtime-file build/appimage-tools/runtime-x86_64 \
  --runtime-sha256 1cc49bcf1e2ccd593c379adb17c9f85a36d619088296504de95b1d06215aebbf \
  --output-dir build/appimage-evaluation/fedora44-candidate
```

The destination must not exist. Use a new directory for each attempt. For frozen
source, replace `--candidate` with `--expected-commit FULL_40_CHARACTER_SHA`;
the existing native source preflight checks commit, clean tree and version before
and after the build. `--candidate` explicitly allows uncommitted evaluation work
and records `frozen_source: false`; it does not qualify a release. APP_VERSION is
read from source and is not changed by this tool.

The target can also be `ubuntu24.04-x86_64`, `ubuntu26.04-x86_64` or
`omarchy-quattro-x86_64`, on the corresponding native host. The filename retains
that provenance: `DLMS-VERSION-TARGET.AppImage`. Build reproducibility here means
pinned inputs and repeatable gates; byte-identical PyInstaller outputs are not
claimed.

The builder composes `build_native_release.py` clean work/dist/cache creation,
the frozen OCR probe and existing runtime-version/CSRF shutdown/restart smoke.
It verifies the AppDir, desktop entry, icon links, and exact executable hash again
after extracting the assembled AppImage. Only successful runs publish the new
output directory with the image, `SHA256SUMS.txt` and `evaluation.json`. Temporary
build/extraction/smoke directories are removed. Existing build outputs and native
release artifacts are never overwritten. The canonical six-package checksum and
download-acceptance workflows are unchanged; experimental AppImages have their
own evaluation records and are not implicitly included in that release set.

## Runtime evaluation

Default build smoke uses FUSE. On a host without usable FUSE, `--smoke-mode extract`
uses the runtime's `--appimage-extract-and-run` fallback and records that narrower
result. Successful fallback testing does not establish double-click/FUSE behavior.
Temporary storage must have enough space and allow executable files; wrapping a
one-file application entails both AppImage and PyInstaller extraction overhead.

Run the additional real HTTP workflow probe against the resulting trusted image:

```sh
.venv-build/bin/python tools/verify_appimage_runtime.py \
  build/appimage-evaluation/fedora44-candidate/DLMS-3.2.0-fedora44-x86_64.AppImage \
  --expected-version 3.2.0 --lan \
  --report build/appimage-evaluation/fedora44-candidate/runtime-uat.json
```

The report path must be new. The probe uses synthetic content and temporary data;
it checks extraction fallback, screenshot OCR, scanned-PDF rendering/OCR, browser
URL dispatch and restoration of the host library path through a recording stub,
and external data-root ownership. `--lan`
additionally binds briefly to `0.0.0.0` with `--no-browser` and probes via loopback.
This is not a remote-client/firewall test. No real browser or desktop settings are
changed. Port 9001 must be free; existing servers are never stopped for the test.
The LAN check requires the desktop-only HTTP shutdown action to be denied, then
terminates its own test server. Desktop checks still require normal HTTP shutdown.

## Desktop integration and icons

The AppDir includes `dlms.desktop`, `dlms.png`, `.DirIcon`, and standard
`usr/share/applications` / `usr/share/icons/hicolor/256x256/apps` links. The desktop
entry passes `desktop-file-validate`. AppImage-compatible desktop integration
tools can use this metadata. Running an AppImage does **not** automatically install
a menu entry; this workflow deliberately does not alter the user's desktop.

For manual menu integration, first place the executable at a stable path. Use a
per-user desktop entry in `~/.local/share/applications/` with `Type=Application`,
`Name=DLMS`, `Terminal=false`, `Categories=Education;`, and `Exec` pointing to the
absolute executable path (properly quoted if it contains spaces). Set `Icon` to
the absolute extracted `dlms.png` path, or install that PNG in the user's hicolor
icon theme and use `Icon=dlms`. These same conventions work for the existing Linux
native binary; ELF files do not carry Windows-style Explorer icon resources.
Do not point a launcher at a temporary AppImage mount/extraction directory.
No automatic menu installation or removal is performed or claimed validated here.

DLMS-145 keeps **one artwork source**, `static/favicon.ico`. Despite its historical
extension, that file contains a 1024×1024 PNG. macOS already passes it to PyInstaller
for the app-bundle icon; that behavior is preserved. Windows previously omitted
the EXE `icon` argument entirely. `tools/native_icons.py` now creates a real ICO
with 16/24/32/48/64/128/256-pixel entries in PyInstaller's work directory, and
`DLMS.spec` supplies it on Windows. AppImage PNGs are derived from the same source.
No duplicate artwork or generated icon binaries are tracked.

A Windows native rebuild must confirm the embedded icon in Explorer and a fresh
shortcut. Existing executables are not changed; stale Explorer icon caches can
require a new filename/shortcut or shell refresh during evaluation. The browser
window and console retain their host application's identity. macOS still requires
its normal bundle/Finder/Dock smoke on a native rebuild.

## Compatibility decision and remaining matrix

Keep AppImage **experimental/optional**. A Fedora-built payload retains its glibc
and system-library baseline; the AppImage runtime does not make it runnable on
older distributions. Before offering a shared Linux-desktop artifact, build on
the oldest supported baseline (Ubuntu 24.04) and test those exact bytes on all
four distributions. Never relabel a Fedora build as an Ubuntu-compatible build.

| Host | Required desktop acceptance |
|---|---|
| Fedora 44 | FUSE and extraction fallback; OCR/PDFium; shutdown/restart; actual file-manager launch and menu integration |
| Omarchy Quattro | Same exact candidate bytes; compositor/file-manager launch, browser dispatch, OCR/PDFium and lifecycle |
| Ubuntu 24.04 | Oldest proposed build baseline; FUSE availability, system dependencies and all runtime gates |
| Ubuntu 26.04 | Same candidate bytes; FUSE, browser/menu behavior and all runtime gates |

Cross-distribution and real graphical-shell acceptance remain mandatory before
promotion to an official additional package. Server/headless distribution stays
on the existing native binary/tar.gz strategy regardless of this decision.

### Browser environment portability fix

Cross-distribution testing by the maintainer found the same Ubuntu 24.04-built
image worked on Ubuntu 24.04, Fedora 44 and Ubuntu 26.04. On Omarchy Quattro the
server worked with `--no-browser`, but automatic browser dispatch failed with a
host shell `rl_print_keybinding` symbol error. The prior recording-stub probe
checked dispatch only; it did not detect inherited library paths.

Frozen Linux browser launches now use a child-only environment: restore
`LD_LIBRARY_PATH_ORIG` (or unset `LD_LIBRARY_PATH`), exclude PyInstaller/AppDir
paths from the restored path, executable search path and preload/audit entries,
and retain other host entries. DLMS's environment, including bundled OCR library
paths, is never changed. `BROWSER` overrides are tried before `xdg-open`,
`gio open` and `sensible-browser`. Source runs, Windows and macOS retain their
existing browser handling. See [PyInstaller's external-program guidance](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html#launching-external-programs-from-the-frozen-application).

Rebuild on Ubuntu 24.04 using the build command above with
`--target ubuntu24.04-x86_64` and a **new** output directory, then transfer those
exact new bytes to Omarchy and the other three distributions. Existing images
do not contain the fix. With port 9001 free, retest on Omarchy:

```sh
chmod +x ./DLMS-3.2.0-ubuntu24.04-x86_64.AppImage
./DLMS-3.2.0-ubuntu24.04-x86_64.AppImage --browser
```

Confirm the actual default browser opens, no shell symbol errors appear, OCR
still works, and shutdown/restart succeeds. After closing that instance, also
test `--no-browser` and manually open `http://127.0.0.1:9001`. Where the development
environment is available, run `tools/verify_appimage_runtime.py` as above against
the rebuilt image with a new report path. Its host-library sentinel now detects
this leakage automatically. This implementation fix does not substitute for the
Omarchy graphical retest or promote AppImage out of experimental status.

### Original Fedora evaluation evidence

On Fedora 44 x86_64, the uncommitted-source 3.2.0 evaluation produced
`build/appimage-evaluation/fedora44-candidate/DLMS-3.2.0-fedora44-x86_64.AppImage`
(49,809,912 bytes), SHA-256
`39da5dfcfcc59834c7e4d63c415998b58029553a22a62949789f87fd5617b218`.
This is a development candidate, **not a replacement for any 3.2.0 release asset**.

Passed: desktop-file validation; extracted layout/payload hash; FUSE startup,
runtime version and two clean lifecycle runs; extraction fallback and restart;
bundled Tesseract 5.5.3 including timeout/cancellation probe; real screenshot OCR;
PDFium rendering plus OCR of a synthetic scanned PDF; browser URL dispatch using
a stub; LAN arguments with browser suppression and expected shutdown denial;
external data-root ownership; unchanged image hash after runtime checks.

Local evidence: `evaluation.json` and `runtime-uat-4.json` beside the candidate.
Earlier runtime probe records are retained as failed attempts: the synthetic PDF
first needed its resolution matched to the 300-DPI renderer, and the probe then
needed to expect the existing LAN shutdown denial. No application change was
made to obtain the passing result. At that point, actual graphical
browser/file-manager/menu integration, Omarchy, both Ubuntu hosts, and
Windows/macOS native icon checks were unverified. See the later portability
finding above. No native six-target package or published artifact was changed.

### Browser-fix regression evidence

The strengthened runtime probe rejects the original Fedora candidate for leaking
the bundled library path (`fedora44-candidate/browser-leak-regression.json`).
A fresh isolated Fedora candidate in
`build/appimage-evaluation/browser-environment-fix/` passes FUSE build smoke,
extraction/restart, host browser-library restoration, screenshot OCR, PDFium/OCR,
LAN browser suppression, shutdown policy and external data-root checks. Its
`evaluation.json` and `runtime-uat.json` record the results. Browser dispatch uses
a shell stub, not a real graphical browser; Ubuntu rebuild and Omarchy graphical
acceptance remain required. No existing image was overwritten.

References: [AppDir specification](https://docs.appimage.org/reference/appdir.html),
[AppImage compatibility guidance](https://docs.appimage.org/introduction/concepts.html),
[local runtime pinning](https://github.com/AppImage/appimagetool#usage),
[PyInstaller icon options](https://pyinstaller.org/en/stable/usage.html#cmdoption-i).

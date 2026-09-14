# 2. Installation and First Launch

For ordinary use, install the native DLMS package built for your operating
system. The native package contains the local application and its OCR runtime;
you do not need Python, a separate database server, or a system Tesseract
installation.

This chapter documents DLMS 3.2.0. If you are running the source code for
development or evaluation instead, see [Running from source](#running-from-source)
near the end of this chapter.

## Choose the correct package

DLMS native packages are target-specific. Download the package whose name
matches your system from the project's Releases page.

| Platform | Package |
| --- | --- |
| Fedora 44, x86-64 | `DLMS-3.2.0-fedora44-x86_64.tar.gz` |
| Ubuntu 24.04, x86-64 | `DLMS-3.2.0-ubuntu24.04-x86_64.tar.gz` |
| Ubuntu 26.04, x86-64 | `DLMS-3.2.0-ubuntu26.04-x86_64.tar.gz` |
| Omarchy Quattro, x86-64 | `DLMS-3.2.0-omarchy-quattro-x86_64.tar.gz` |
| Windows 11, x86-64 | `DLMS-3.2.0-windows11-x86_64.zip` |
| macOS Apple Silicon, arm64 | `DLMS-3.2.0-macos-arm64.zip` |

The Linux packages are built and tested separately for their named
distributions; one Linux archive is not a universal build. The documented
macOS package is for Apple Silicon, not Intel.

Each final package includes the native application, `README.txt`, and
`sample_quiz.txt`. Verify the downloaded archive against the published
`SHA256SUMS.txt` before bypassing an operating-system warning or transferring
the package between computers.

## Install on Linux

1. Extract the `.tar.gz` archive with your file manager or archive tool.
2. Open a terminal in the extracted, versioned package directory.
3. Run the executable for that package. For example:

   ```text
   ./DLMS-3.2.0-fedora44-x86_64
   ```

The archive preserves the executable permission. If another transfer method
removed it, restore it for the extracted DLMS executable with `chmod +x`, then
try again. Do not substitute a package built for a different Linux target.

## Install on Windows 11

1. Extract the ZIP archive; do not run the application from inside the ZIP.
2. Open the extracted, versioned package folder.
3. Double-click `DLMS-3.2.0-windows11-x86_64.exe`.

The current Windows package is unsigned. Microsoft Defender SmartScreen may
therefore warn on first launch. First confirm that the archive came from the
official DLMS release and matches its published SHA-256 checksum. You can then
use **More info** and **Run anyway** if Windows offers those choices.

## Install on macOS Apple Silicon

The macOS ZIP contains `DLMS.app`, `README.txt`, and `sample_quiz.txt` directly
at the archive root. There is no extra versioned wrapper around the app.

1. Extract `DLMS-3.2.0-macos-arm64.zip`.
2. Drag `DLMS.app` into `/Applications`.
3. In Finder or Applications, Control-click `DLMS.app`, choose **Open**, and
   confirm the first launch.

The current app is not Developer ID-signed or notarized. If macOS blocks it and
the Control-click choice is unavailable, try opening it once and then use
**System Settings → Privacy & Security → Open Anyway**. Only use that approval
after checking the download source and published SHA-256.

Removing quarantine is a fallback, not a normal installation step. If the
standard choices remain unavailable after verification, the current release
guidance permits this targeted command:

```text
xattr -dr com.apple.quarantine /Applications/DLMS.app
```

It applies to that copied application bundle only.

## What happens on first launch

DLMS creates or opens its application-data directory, starts a local application
process, and normally opens your default browser after the local server is
ready. No sign-in or first-run account setup is required.

The normal local address is:

```text
http://127.0.0.1:9001/
```

The page you see is the Dashboard. A new installation will naturally have
little or no history, so some recommendations and learning summaries will be
empty until you create or import material and save answers. You can begin with
**Build Quiz**, an installed **Study Pack**, or the included
`sample_quiz.txt`. The next chapter explains the common interface without
requiring you to learn every feature first.

## Where DLMS keeps your data

DLMS keeps active user data outside the downloaded or installed application
package. The default locations are:

| Platform | Default application-data directory |
| --- | --- |
| Linux | `$XDG_DATA_HOME/DLMS`, or `~/.local/share/DLMS` when `XDG_DATA_HOME` is not set |
| Windows | `%APPDATA%\DLMS` |
| macOS | `~/Library/Application Support/DLMS` |

This directory contains the persistent DLMS workspace, including quizzes,
settings, results, installed content, and related local data. Moving or
replacing the application package does not by itself replace this data.

Some interrupted-quiz checkpoints and a small number of interface preferences
are stored by the browser. A checkpoint marked **This browser** is available
only in that browser profile; it is not the same as the durable History stored
by DLMS. The interface chapter introduces this distinction, and the quiz-taking
chapter will explain recovery in detail.

Use **Settings → Backup & Restore** to create a portable backup, and keep an
important backup somewhere outside the live DLMS data directory. Back up before
moving to another computer, resetting data, or making a significant upgrade.

## OCR in native packages

The native packages include the validated local components used for screenshot
OCR and selected scanned-PDF OCR. OCR runs on the computer hosting DLMS; it is
not sent to a cloud OCR service.

If an OCR-dependent workflow is unavailable, DLMS labels it as unavailable.
Normal selectable-text PDF import remains available without OCR. In a packaged
release, do not install system Tesseract as a workaround for a missing bundled
runtime; record the package and platform and report the packaging problem.

OCR extracts draft text, not guaranteed answers. Imported OCR material still
goes through Review & Repair before publication.

## Local desktop mode and LAN/server mode

DLMS starts in local desktop mode by default. It listens only on the loopback
interface, so another computer cannot reach it merely because both computers
are on the same network.

LAN/server mode is an explicit advanced choice. Starting DLMS with a
non-loopback bind such as `--host 0.0.0.0` allows other devices to use the host
computer's printed LAN address. `0.0.0.0` is a bind setting, not an address to
enter into a browser.

DLMS does not provide account authentication or TLS for LAN/server mode. Use it
only on a trusted, appropriately firewalled local network, and never expose the
DLMS port directly to the public internet. All connected browsers act on the
same single-user DLMS data. Interrupted recovery checkpoints remain local to
each browser profile, so two clients can show different **This browser** Resume
items even while they share quiz data, History, and server-derived study
recommendations.

## Stop DLMS safely

In normal local desktop mode, use **Shutdown DLMS** when you want to stop the
application immediately. Closing a browser tab or window is not an unconditional
shutdown command.

If optional browser-presence shutdown is enabled under **Settings →
Application Lifecycle**, closing the final DLMS browser page in an eligible
loopback-only session may stop the local process after a grace period of about
five minutes. Reopening a DLMS page during that period keeps the application
running. Do not rely on this behavior when the setting is disabled.

In LAN/server mode, in-app shutdown, browser/API shutdown, and automatic
browser-presence shutdown are unavailable. Closing client browser windows does
not stop the server. Stop the DLMS process or service from the host
computer—for example, from the terminal, service manager, or process manager
that started it.

## Upgrade an existing installation

Before a significant upgrade, create a DLMS backup and copy it outside the live
data directory. Then stop the existing DLMS process, download and verify the
correct new package, and install or extract it using the platform steps above.
The new application continues to use the platform's normal DLMS data directory;
do not move the old data into the downloaded package directory.

You normally do not need to run **Rebuild All Quiz Pages** after an update. It
is an occasional maintenance and recovery tool for refreshing derived quiz
pages when DLMS specifically instructs you to use it or when existing pages
appear stale or inconsistent with the current interface.

## Running from source

Running from source is primarily for contributors and advanced users. It
requires a supported Python environment and the repository's locked
dependencies. Source mode uses the same local browser interface and default
data location, but OCR-dependent workflows require a complete local Tesseract 5
installation with English language data and the TSV configuration.

Follow the [repository README](../../README.md) for the current source setup.
Do not follow the maintainer-only frozen OCR bundle, native probe, or release
packaging procedures merely to use DLMS from source.

## First-launch troubleshooting

### The browser did not open automatically

Automatic launch may be disabled, may be unavailable in a headless or SSH
session, or may fail even though DLMS started successfully. For a normal local
launch, open `http://127.0.0.1:9001/` yourself. A source or terminal launch also
prints its access address. Browser-launch detection does not silently change a
local launch into LAN/server mode.

If the address does not load, confirm that the DLMS process is still running and
that startup did not report an error.

### DLMS appears to be already running

Open `http://127.0.0.1:9001/` first. If the Dashboard responds, reconnect to
that already-running process instead of starting a second copy. If the address
does not respond, return to the original terminal or process manager, confirm
that the prior process has stopped, and then launch DLMS again.

### The operating system blocks the first launch

Use the verified Windows SmartScreen or macOS Gatekeeper steps earlier in this
chapter. Do not bypass a warning until you have confirmed the download source
and SHA-256 checksum. Linux users should confirm that they selected the correct
target package and that the extracted executable retained its execute
permission.

### OCR is unavailable

Selectable-text PDF import should remain usable. In a native package, note the
exact platform package and report the missing OCR runtime rather than trying to
repair the frozen application with a system Tesseract install. Source users
should follow the source OCR setup referenced by the repository README and
restart DLMS after correcting that optional dependency.

Continue with [Interface and Navigation](03-interface-and-navigation.md) once
the Dashboard opens.

# DLMS – Digital Learning & Management System

**Current release: DLMS 3.0.2 RC4**

👉 Download packaged releases from the [Releases page](../../releases).

DLMS is a self-hosted quiz and learning application designed for study, practice,
and exam preparation. It supports both **Study Mode** and **Exam Mode**, detailed
attempt history, confidence analysis, and Anki export for long-term retention.

## Why DLMS Exists

DLMS was created to address a gap between simple quiz tools and full-scale learning
management systems. Many existing solutions are either too limited for serious
study or too complex, restrictive, or heavyweight for individual learners,
educators, and IT professionals.

DLMS is designed to be local, transparent, and learner-focused. It gives users full
control over their content, data, and study workflow without requiring cloud
accounts, subscriptions, or external services. By running entirely on the user’s
system as a local web application, DLMS prioritizes privacy, reliability, and
portability.

For users who prefer deeper system integration, DLMS can also be enabled as a
systemd service (this is what I do).

The project emphasizes learning effectiveness, not just assessment. Features like
Study Mode, confidence analysis, Learning Intelligence, attempt history, and Anki
export are intended to help users identify weak areas, reinforce understanding,
and retain knowledge over time—especially in certification, technical training,
and self-directed study scenarios.

DLMS exists because effective learning tools should be:

* Powerful without being bloated
* Flexible without being fragile
* Private by default
* Open for inspection, improvement, and reuse

DLMS runs as a **local web application**.

---

## 🚀 How to Use DLMS (Important)

After starting DLMS, use:

👉 **[http://127.0.0.1:9001/](http://127.0.0.1:9001/)**

This is the main interface for the application.

In an interactive desktop session, DLMS normally opens this address in the default
browser after the local server is ready. In a headless or SSH session it prints the
address but does not open a browser. See [Browser launch and server options](#browser-launch-and-server-options)
for explicit controls.

The browser is DLMS's interface, not the application process itself. Closing the
browser tab or window does not shut down DLMS; the local process continues running.
To return to an instance that is still running, reopen a browser and visit
**[http://127.0.0.1:9001/](http://127.0.0.1:9001/)** instead of starting another
server copy. When you are finished, use **Shutdown DLMS** in the application
sidebar and confirm the prompt to fully exit. After shutdown, launch DLMS normally
the next time you want to use it.

---

## ✨ Key Features

* Study Mode and Exam Mode
* Manual, pasted-text, file, matching, image, and Smart PDF quiz builders
* Reusable Study Packs, including guided AI Study Pack ZIP validation and install
* IT, Law, Medical, and other study-area workflows
* Attempt History, Analytics, and Learning Intelligence review planning
* Confidence analysis (optional)
* Anki export and printable physical flashcards
* Backups, restore validation, and configurable themes/navigation

---

## 🧠 Study Mode & Learning Tools

Study Mode is designed to help users learn and reinforce concepts rather than
simulate a timed exam. Users can review questions, analyze confidence levels, and
focus on missed material.

(See screenshots below. No logos or quiz questions/answers are provided.)

### Study Mode Examples

![Study Mode Example 1](docs/screenshots/SS1.png)
![Study Mode Example 2](docs/screenshots/SS2.png)


## 🧩 Anki Integration

DLMS supports exporting missed questions to Anki, a proven spaced-repetition
learning system. This allows users to turn weak areas into targeted study decks
for long-term retention.

---


### Anki Export Examples

![Anki Export Example 1](docs/screenshots/anki1.png)
![Anki Export Example 2](docs/screenshots/anki2.png)

---



## 🖥️ Running DLMS

### From a packaged release (recommended)

On Windows or Linux, download the matching release artifact, run the DLMS
executable, and allow it to open the browser. You can also open
**[http://127.0.0.1:9001/](http://127.0.0.1:9001/)** yourself after DLMS starts.

#### macOS on Apple Silicon

1. Download and extract `DLMS-3.0.2-RC4-macos-arm64.zip` from **Releases**.
2. Drag `DLMS.app` into `/Applications`.
3. Open DLMS from Finder or Applications. DLMS starts locally and normally opens
   its browser interface automatically.
4. Because this release is not signed with an Apple Developer ID and is not
   notarized, Gatekeeper may block the first launch. Where available, Control-click
   `DLMS.app`, choose **Open**, then confirm **Open**. Otherwise try opening the app
   once, then use **System Settings → Privacy & Security → Open Anyway** and confirm
   the launch.

Removing the quarantine attribute is not part of the normal installation. If the
two Gatekeeper choices above are unavailable, first verify the ZIP against the
release `SHA256SUMS.txt`, then use this targeted troubleshooting fallback:

```bash
xattr -dr com.apple.quarantine /Applications/DLMS.app
```

The documented macOS package is built for Apple Silicon (`arm64`). An Intel
(`x86_64`) package should be published only when it has been built with an Intel
Python environment and smoke-tested on Intel macOS; the Apple Silicon ZIP is not
an Intel build.

### From source (advanced users)

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-lock.txt
python app.py
```

On Windows, activate the environment with `.venv\Scripts\activate`.

`requirements-lock.txt` records the dependency set used for the verified 3.0.2 RC4
environment. Contributors who intentionally need compatible dependency updates can
instead install the supported ranges in `requirements.txt`, run the full test suite,
and then deliberately refresh the lock file.

### Building release binaries

Build on each target operating system from a clean checkout and isolated virtual
environment:

```bash
python -m pip install -r requirements-build.txt
pyinstaller --clean --noconfirm DLMS.spec
```

`DLMS.spec` is the canonical platform-aware build manifest. Windows and Linux
retain one-file executables. On macOS it creates a windowed, onedir-style native
`dist/DLMS.app` bundle; the executable and its dependencies live inside the app
bundle. Its only local data inputs are `static/` and `init.sql`; databases,
settings, backups, logs, caches, tests, development directories, and per-user
runtime data are not build inputs. Inspect the resulting `dist/` artifact and
perform the release smoke tests before distribution.

Build natively for each target architecture; PyInstaller does not produce
cross-platform binaries. Stage the final artifacts with these names:

* Windows: `DLMS-3.0.2-RC4-windows-x86_64.exe`
* Linux: `DLMS-3.0.2-RC4-linux-x86_64`
* macOS Apple Silicon: `DLMS-3.0.2-RC4-macos-arm64.zip`

For the Apple Silicon build, use a native `arm64` Python environment on an Apple
Silicon Mac, verify its architecture, build the canonical spec, and archive only
the application bundle:

```bash
python -c "import platform; assert platform.machine() == 'arm64', platform.machine()"
python -m pip install -r requirements-build.txt
python -m PyInstaller --clean --noconfirm DLMS.spec
test -d dist/DLMS.app
mkdir -p releases
ditto -c -k --sequesterRsrc --keepParent dist/DLMS.app releases/DLMS-3.0.2-RC4-macos-arm64.zip
```

The ZIP should expose one top-level `DLMS.app`. The bundle contains
`Contents/Info.plist`, `Contents/MacOS/DLMS`, and its packaged resources and
frameworks. Do not include the `build/` directory, runtime data, or an additional
raw DLMS executable in the release ZIP. If an Intel build is intentionally
produced and tested from an `x86_64` Python environment, use the distinct name
`DLMS-3.0.2-RC4-macos-x86_64.zip`.

After staging the final binaries/packages in `releases/`, generate the shared
checksum manifest from the same checkout:

```bash
python tools/generate_sha256sums.py --output releases/SHA256SUMS.txt releases/DLMS-3.0.2-RC4-*
```

The user-facing release name is `DLMS 3.0.2 RC4`; the matching Git tag convention
is `v3.0.2-rc.4`.

### Native artifact verification

Follow [the native release-verification procedure](docs/RELEASE_VERIFICATION.md)
for every staged Windows, Linux, and Apple Silicon macOS artifact. It provides a
small structural/checksum verifier and a native start, route, Shutdown DLMS, and
restart smoke test that uses a temporary controlled data directory. Native UAT on
each target OS remains required for desktop launch, security prompts, browser
behavior, and the representative quiz workflow; the procedure distinguishes those
steps explicitly. It does not add signing, notarization, installers, publishing,
or CI release automation.

### Browser launch and server options

Browser launch and network binding are separate choices:

* With no browser flag, DLMS opens a browser in an interactive Windows, macOS, or
  Linux graphical desktop session. It skips automatic launch for SSH/headless
  sessions. Headless/server detection controls automatic browser launch only; it
  does not change the network bind address.
* `python app.py --browser` forces a launch attempt even when a desktop session is
  not detected.
* `python app.py --no-browser` always suppresses automatic launch.
* `DLMS_NO_BROWSER=1` also suppresses launch. The values `true`, `yes`, and `on`
  are accepted case-insensitively. This setting and `--no-browser` take precedence
  over `--browser`.
* DLMS always defaults to `127.0.0.1:9001`, including in headless and SSH sessions.
  `--host HOST` (or `--host=HOST`) changes only the bind address.

This separation is intentional. Do not change or rely on headless detection to
make DLMS LAN-accessible; request a non-loopback bind explicitly when that is the
intended deployment.

#### Intentional LAN or server access

To accept connections through the host's network interfaces, start DLMS
explicitly with `--host 0.0.0.0`:

```bash
python app.py --host 0.0.0.0
```

For a packaged Linux executable installed as `/usr/local/bin/DLMS`, a systemd
service should use the equivalent explicit argument:

```ini
[Service]
ExecStart=/usr/local/bin/DLMS --host 0.0.0.0
```

After starting the service, verify the listening address and port with:

```bash
ss -ltnp | grep ':9001'
```

Use the server's actual LAN address, such as `http://192.168.1.25:9001`, from
another device. `0.0.0.0` is a bind address, not a browser destination.

**Security:** Binding to `0.0.0.0` exposes DLMS to devices that can reach the host
and port. DLMS has no user authentication, so use a non-loopback bind only on a
trusted LAN, restrict access with host/network firewall rules as appropriate, and
do not expose it directly to the public internet.

---

## 📂 Data & Configuration

On first run, DLMS creates its data directory in your user profile and initializes
its database and configuration files automatically.

No external database or web server is required.

---

## 📘 Question & Answer Formatting (Important)

DLMS relies on a clear and consistent question format in order to correctly parse
quiz content. Each question **must include an explicit answer line** so the system
knows which option or options are correct.

### ✅ Required Answer Line

Every question must end with **one** of the following:

* `Suggested Answer: X`
* `Correct Answer: X`

Where `X` is:

* A single letter (e.g., `A`)
* Multiple letters for multi-answer questions (e.g., `AC`)

Both formats are treated identically by DLMS.

---

### 🧪 Example: Single-Answer Question

```
1. Which component is responsible for providing electrical power to a computer system?

A. Motherboard
B. Power supply
C. CPU
D. Hard drive

Suggested Answer: B
```

---

### 🧪 Example: Multi-Answer Question

```
2. Which of the following are common operating system functions?
(Choose two.)

A. Memory management
B. Power distribution
C. Process scheduling
D. Monitor calibration
E. File system management

Correct Answer: AC
```

---

### 🧪 Example: Alternate Accepted Format

```
3. What does DNS primarily resolve?

A. MAC addresses to IP addresses
B. IP addresses to hostnames
C. Hostnames to IP addresses
D. Ports to services

Correct Answer: C
```

`Suggested Answer:` and `Correct Answer:` are interchangeable.

---

### ⚠️ Formatting Notes & Best Practices

* Answer letters must match the choices exactly
* Do **not** include punctuation or words in the answer line

  * ❌ `Correct Answer: A, C`
  * ❌ `Suggested Answer: A and C`
  * ✅ `Correct Answer: AC`
* Question numbers are optional but recommended
* Blank lines between questions are allowed
* Extra whitespace is ignored safely

---

### 🧠 Tip for Pasted Questions

If you are pasting questions from PDFs, documents, or study guides, DLMS includes
regex-based parsing tools to help clean and normalize formatting before upload.
Use these tools carefully to ensure answer lines remain intact.

---

## 🧹 Removing DLMS & Cleaning Up Files

DLMS does not install system-wide dependencies or background services by default.
Removing the application is straightforward.

### 🪟 Windows Cleanup

1. Close DLMS and stop the application
2. Delete the DLMS executable
3. Remove the application data directory:

```
C:\Users\<YourUsername>\AppData\Roaming\DLMS
```

(Optional) If you ran development or test builds, you may also remove:

```
C:\Users\<YourUsername>\AppData\Local\Temp\_MEI*
```

These temporary folders are created by PyInstaller and are safe to delete.

---

### 🍎 macOS Cleanup

1. Quit DLMS.
2. Remove `/Applications/DLMS.app`.
3. Remove the application data directory if you also want to delete saved DLMS
   content and settings:

```text
~/Library/Application Support/DLMS
```

Removing the app does not automatically remove this per-user data directory.

---

### 🐧 Linux Cleanup

1. Stop DLMS if it is running
2. Remove the DLMS binary or source directory
3. Remove the application data directory:

```
~/.local/share/DLMS
```

(Optional) If you enabled DLMS as a systemd service, disable and remove it:

```bash
sudo systemctl stop DLMS
sudo systemctl disable DLMS
sudo rm /etc/systemd/system/DLMS.service
sudo systemctl daemon-reload
```

No additional cleanup is required. DLMS leaves no background services or hidden
files once removed.

---

## Release checklist

1. Synchronize the release number in `app.py`, this README, and user-facing Help
   text; confirm database and backup format versions are changed only when their
   formats actually change.
2. Review top-level and Help documentation against the release source, including
   startup flags, data locations, and changed workflows.
3. Create a clean environment from `requirements-lock.txt`; run targeted tests,
   the full isolated test suite, Python compilation, and `git diff --check`.
4. Build each supported platform artifact from `requirements-build.txt` with the
   canonical `DLMS.spec`. Follow
   [Native Release Verification](docs/RELEASE_VERIFICATION.md) on each target OS:
   stage the prescribed name, run artifact structure/architecture validation and
   the controlled native start/route/shutdown/restart smoke test, then complete
   the required desktop UAT. On macOS, verify that the result is `dist/DLMS.app`,
   ZIP that bundle with `ditto`, and confirm the archive has no separate raw
   executable. Do not imply Intel macOS support without a native Intel build and
   UAT.
5. Review `git status` and package source from tracked files, for example with
   `git archive --format=zip --output releases/DLMS-3.0.2-RC4-source.zip HEAD`. Inspect
   the archive to confirm it contains required application assets and excludes
   `.git`, virtual environments, caches, databases, logs, and local build output.
6. Generate `releases/SHA256SUMS.txt` from the final staged binaries/packages with
   `python tools/generate_sha256sums.py --output releases/SHA256SUMS.txt releases/DLMS-3.0.2-RC4-*`.
   Re-run the artifact verifier with `--checksums releases/SHA256SUMS.txt` for
   every staged native artifact before upload.

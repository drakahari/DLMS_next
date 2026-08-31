# DLMS – Digital Learning & Management System

**Current release: DLMS 3.0.2**

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

### From a prebuilt binary (recommended)

1. Download the appropriate binary for your operating system from **Releases**
2. Run the DLMS executable
3. Allow DLMS to open the browser, or go to **[http://127.0.0.1:9001/](http://127.0.0.1:9001/)**

### From source (advanced users)

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-lock.txt
python app.py
```

On Windows, activate the environment with `.venv\Scripts\activate`.

`requirements-lock.txt` records the dependency set used for the verified 3.0.2
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

`DLMS.spec` is the canonical one-file build manifest. Its only local data inputs
are `static/` and `init.sql`; databases, settings, backups, logs, caches, tests,
development directories, and per-user runtime data are not build inputs. Inspect
the resulting `dist/` artifact and perform the release smoke tests before
distribution.

### Browser launch and server options

Browser launch and network binding are separate choices:

* With no browser flag, DLMS opens a browser in an interactive Windows, macOS, or
  Linux graphical desktop session. It skips automatic launch for SSH/headless
  sessions.
* `python app.py --browser` forces a launch attempt even when a desktop session is
  not detected.
* `python app.py --no-browser` always suppresses automatic launch.
* `DLMS_NO_BROWSER=1` also suppresses launch. The values `true`, `yes`, and `on`
  are accepted case-insensitively. This setting and `--no-browser` take precedence
  over `--browser`.
* DLMS binds to `127.0.0.1` by default. `--host HOST` (or `--host=HOST`) changes
  only the bind address. Binding to `0.0.0.0` makes the service reachable through
  an appropriate local network address; it does not make `0.0.0.0` a browser URL.

DLMS has no user authentication. Use a non-loopback bind only on a trusted LAN and
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
4. Build each supported platform artifact from `requirements-build.txt` with
   `pyinstaller --clean --noconfirm DLMS.spec`, inspect the artifact contents, then
   smoke-test startup, browser/no-browser operation, static assets, quiz creation,
   and backup/restore.
5. Review `git status` and package source from tracked files, for example with
   `git archive --format=zip --output releases/DLMS-3.0.2-source.zip HEAD`. Inspect
   the archive to confirm it contains required application assets and excludes
   `.git`, virtual environments, caches, databases, logs, and local build output.

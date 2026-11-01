# 🖥️ DLMS Desktop 3.3.1 Preview 1 — Windows 11 x86_64

Your quizzes, study history, certifications and flashcards in a dedicated application
window. **Local** manages a separate profile on this computer; **Server** connects
to an existing DLMS deployment and uses its data. Neither mode automatically copies
or synchronizes another edition's Local data. No hosted server is needed for Local use.

**This is a prerelease.** The accepted binaries retain their `candidate` filenames
and bundled prepublication wording; this page describes their published Preview 1 status.

## 🛠️ What this maintenance preview includes

The shared app is aligned at **3.3.1**, including hotspot rebuild/Study Resume fixes,
selected-question Anki and AI handoff corrections, Marked navigation, import/restore
hardening, later Avery/Return fixes and in-app certificate PDF/image viewing.
These improve existing learning workflows; they do not introduce the entire DLMS feature set.
The accepted Windows Preview 2.2 installer improvements and their source supplement are retained.

## ⬇️ Download and prerequisites

[**Download Windows Setup.exe**](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.1-preview1-windows/DLMS-Desktop-WebView2-Windows-x86_64-windows-331-preview1-candidate-Setup.exe)

Requires **Windows 11 x86_64**, **.NET Framework 4.8** and a **protected machine-wide
WebView2 Evergreen Runtime 155.0.4283.45 or newer**. Setup installs neither prerequisite;
per-user/AppData-only WebView2 runtimes are unsupported.

Close an existing Desktop session, verify the download, and use the per-user
installer and its Start menu shortcut. Local data is created by normal first launch;
no manual profile setup is needed. Keep OS protections enabled and stop on policy blocks.

## 🧪 Preview limits

Native automated build/renderer/OCR/lifecycle evidence is retained. **Setup was
compiled and automatically checked, not executed** in this qualification. Installed
Start-menu, manual Server/Save-Cancel, physical printing and other unperformed checks
are not claimed as passed. The installer is unsigned; the opening instructions are
not a claim of installation acceptance.

## 💾 Existing data and Server use

Back up and retain the old payload before an update. Keep edition/profile data roots
separate and use supported import/restore rather than sharing a live directory.
For complete corrected Server behavior, use **original DLMS 3.3.1**, or the documented
matching shared baseline. Updating Desktop Local does not update an older server.
No new schema/portable-format migration is introduced from 3.3.0. DLMS has no built-in
server account login or TLS; do not expose its port directly to the public Internet.

## 📚 Start here

- [User manual](https://github.com/drakahari/DLMS_next/blob/main/docs/user-manual/README.md) — installation, learning workflows and backups.
- [DLMS front page](https://github.com/drakahari/DLMS_next#readme) — features, edition comparison and quick start.
- [DLMS 3.3 overview](https://www.youtube.com/watch?v=axmym1glqD8) — Study, practice, Exam Plans and certification tracking.
- [Desktop walkthrough](https://www.youtube.com/watch?v=mPGNbPy56X8) — Local and Server modes demonstrated on Linux, not Windows/Mac acceptance evidence.
- [Mark questions for practice and Anki](https://www.youtube.com/watch?v=hya5DsFD3Sc) — reuse selected questions outside the original quiz.
- [Back up, restore and understand rollback](https://www.youtube.com/watch?v=eNSfwEzA1Bc) — protect existing data before an update.
- [More public feature walkthroughs](https://github.com/drakahari/DLMS_next/blob/main/docs/demo-video/series/README.md#public-walkthroughs) — import, Study recovery, Exam Plans, certifications and printable cards.

[SHA-256 checksums](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.1-preview1-windows/SHA256SUMS.txt) · [detailed qualification](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.1-preview1-windows/QUALIFICATION.md) · [release/source guide](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.1-preview1-windows/RELEASE_GUIDE.md)

Ordinary users need their app download, not the large source archives. Matching
notices, required sources and build/replacement materials are available in this
release and must accompany applicable redistribution. Checksums verify bytes, not publisher identity.

<details>
<summary>Source and technical records</summary>

Binary source: `f507b64e9366cfd36a536d1112a5279ff28cb27d`. Platform supplements/source snapshot identities remain as recorded; no binary was rebuilt for this description refresh.
See [source identity](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.1-preview1-windows/SOURCE_IDENTITY.json) and [exact asset inventory](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.1-preview1-windows/RELEASE_ASSETS.json).

</details>

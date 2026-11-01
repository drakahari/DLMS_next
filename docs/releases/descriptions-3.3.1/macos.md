# 🖥️ DLMS Desktop 3.3.1 Preview 1 — Apple Silicon Mac

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
Accepted Mac printing/packaging behavior is retained.

## ⬇️ Download and open

[**Download the Apple Silicon DMG**](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.1-preview1-macos/DLMS-Desktop-3.3.1-macos-arm64-preview1-candidate.dmg)

Open the DMG, copy **DLMS Desktop.app** to Applications, and open the copied app in
Finder. This is separate from the original browser edition's DLMS.app ZIP.

**Apple Silicon only.** Automated evidence is from **macOS 26.6.2**; Intel Macs and
other macOS versions are not newly qualified. The app is ad hoc signed, **without
Developer ID or notarization**. Use only the offered individual-app **System Settings
→ Privacy & Security → Open Anyway** approval for a trusted, checksum-verified download.
Stop on malware, damage, policy blocks or unavailable approval. Never remove quarantine
or disable Gatekeeper.

## 🧪 Preview limits

Native automated build/OCR/HTTP/lifecycle, DMG structure and strict signature checks
are retained. **Manual Mac acceptance remains untested** and the provenance record's
`qualified=false` remains unchanged. No physical printing or downloaded/quarantined
first-launch acceptance is newly claimed.

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

[SHA-256 checksums](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.1-preview1-macos/SHA256SUMS.txt) · [detailed qualification](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.1-preview1-macos/QUALIFICATION.md) · [release/source guide](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.1-preview1-macos/RELEASE_GUIDE.md)

Ordinary users need their app download, not the large source archives. Matching
notices, required sources and build/replacement materials are available in this
release and must accompany applicable redistribution. Checksums verify bytes, not publisher identity.

<details>
<summary>Source and technical records</summary>

Binary source: `f507b64e9366cfd36a536d1112a5279ff28cb27d`. Platform supplements/source snapshot identities remain as recorded; no binary was rebuilt for this description refresh.
See [source identity](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.1-preview1-macos/SOURCE_IDENTITY.json) and [exact asset inventory](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.1-preview1-macos/RELEASE_ASSETS.json).

</details>

# 🚀 DLMS 3.3.1 — your learning, on your computer

Turn your notes, PDFs, screenshots and question banks into quizzes, focused review
and flashcards. **Original DLMS 3.3.1 is the stable browser edition:** the app runs
locally and opens your preferred browser. No cloud deployment or hosted account is required.

## 🛠️ What changes in 3.3.1

This is a maintenance release. Study/Exam modes, Learning Intelligence, Study Packs,
certification/training records, Anki and portable backups are established capabilities;
they are not all new in 3.3.1. Compared with published 3.3.0, this release brings together:

- Repair hotspot import/rebuild and preserve Study Resume when rebuilt content is unchanged.
- Correct selected-question Anki exports, Marked navigation and selected-question AI copying/browser handoff.
- Harden import/restore handling and incorporate later Avery layout, printing and Return fixes.
- Display supported certificate PDFs/images inside DLMS, with PDF page navigation and a separate Download action.

Original packages also refresh bundled guidance. Original Windows uses the serviced
Windows 11 UCRT rather than bundling a System32 copy. No new schema or portable-format
migration is introduced from 3.3.0.

## ⬇️ Pick one app package

| Your system | Download |
| --- | --- |
| Fedora 44 x86_64 | [App package](https://github.com/drakahari/DLMS_next/releases/download/v3.3.1/DLMS-3.3.1-fedora44-x86_64.tar.gz) |
| Ubuntu 24.04 x86_64 | [App package](https://github.com/drakahari/DLMS_next/releases/download/v3.3.1/DLMS-3.3.1-ubuntu24.04-x86_64.tar.gz) |
| Ubuntu 26.04 x86_64 | [App package](https://github.com/drakahari/DLMS_next/releases/download/v3.3.1/DLMS-3.3.1-ubuntu26.04-x86_64.tar.gz) |
| Windows 11 x86_64 | [App package](https://github.com/drakahari/DLMS_next/releases/download/v3.3.1/DLMS-3.3.1-windows11-x86_64.zip) |
| Apple Silicon Mac arm64 | [App package](https://github.com/drakahari/DLMS_next/releases/download/v3.3.1/DLMS-3.3.1-macos-arm64.zip) |

Extract first, then run the DLMS executable; on Mac open **DLMS.app**. The original
Mac ZIP has DLMS.app, README.txt and sample_quiz.txt at its root. The browser normally
opens at http://127.0.0.1:9001/. Try the included sample quiz, then Study Mode.

## 💾 Existing data and platform limits

Back up through **Settings → Backup & Restore**, keep the archive outside live data,
retain the previous payload and stop the old app before an update. Editions have
separate live data roots; use explicit supported import/restore to transfer data.
A new executable does not undo an older data migration.

All five native builders passed; this is not full manual acceptance on every OS.
Ubuntu 24.04 PDF Download remains untested; its extra Firefox-exit helper timeout
is a cleanup limitation, not an established application defect. Ubuntu 26.04 and
Mac manual acceptance remain untested. Mac automated evidence is from Apple Silicon
macOS 26.6.2. Mac is ad hoc signed without Developer ID/notarization; Linux/Windows
packages are unsigned. Use only offered OS approval for a trusted download; stop
on malware/damage/policy blocks, and never remove quarantine or disable protections.

## 📚 Start here

- [User manual](https://github.com/drakahari/DLMS_next/blob/main/docs/user-manual/README.md) — installation, learning workflows and backups.
- [DLMS front page](https://github.com/drakahari/DLMS_next#readme) — features, edition comparison and quick start.
- [DLMS 3.3 overview](https://www.youtube.com/watch?v=axmym1glqD8) — Study, practice, Exam Plans and certification tracking.
- [Desktop walkthrough](https://www.youtube.com/watch?v=mPGNbPy56X8) — the optional Desktop edition's Local/Server modes, demonstrated on Linux.
- [Mark questions for practice and Anki](https://www.youtube.com/watch?v=hya5DsFD3Sc) — reuse selected questions outside the original quiz.
- [Back up, restore and understand rollback](https://www.youtube.com/watch?v=eNSfwEzA1Bc) — protect existing data before an update.
- [More public feature walkthroughs](https://github.com/drakahari/DLMS_next/blob/main/docs/demo-video/series/README.md#public-walkthroughs) — import, Study recovery, Exam Plans, certifications and printable cards.

[SHA-256 checksums](https://github.com/drakahari/DLMS_next/releases/download/v3.3.1/SHA256SUMS.txt) · [detailed qualification](https://github.com/drakahari/DLMS_next/releases/download/v3.3.1/QUALIFICATION.md) · [release/source guide](https://github.com/drakahari/DLMS_next/releases/download/v3.3.1/RELEASE_GUIDE.md)

Ordinary users need their app download, not the large source archives. Matching
notices, required sources and build/replacement materials are available in this
release and must accompany applicable redistribution. Checksums verify bytes, not publisher identity.

<details>
<summary>Source and technical records</summary>

Binary source: `79e42531d37b78fc806628e0ba989da13d9ed5ea`. The frozen tag CI retains outdated documentation assertions; corrected expectations passed in the separate publication PR #35 without changing packaged source.
See [source identity](https://github.com/drakahari/DLMS_next/releases/download/v3.3.1/SOURCE_IDENTITY.json) and [exact asset inventory](https://github.com/drakahari/DLMS_next/releases/download/v3.3.1/RELEASE_ASSETS.json).

</details>

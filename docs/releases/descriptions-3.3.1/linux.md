# 🖥️ DLMS Desktop 3.3.1 Preview 1 — Linux x86_64

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
Accepted Linux printing/packaging behavior is retained.

## ⬇️ Download and open

[**Download the Linux AppImage**](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.1-preview1-linux/DLMS-Desktop-3.3.1-preview1-candidate-linux-x86_64.AppImage)

Make the AppImage executable and open it. Normal mounting needs **FUSE**; the
[opening guide](https://github.com/drakahari/DLMS_next/blob/main/docs/choose-your-dlms.md#open-desktop-on-linux)
also documents the supported extracted AppRun option. Keep Chromium sandboxing
enabled and do not run as root.

The separate [managed payload](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.1-preview1-linux/DLMS-Desktop-3.3.1-preview1-candidate-managed-linux-x86_64.tar.zst)
is for its existing launcher/profile contract. It is not a drop-in AppImage upgrade;
preserve an existing managed installation's data root and launcher.

## 🧪 Preview limits

Fedora AppImage/extraction and managed synthetic-profile evidence is retained.
Owner Omarchy confirmation covers extracted AppRun Server-mode PDF display,
both-page navigation, exact-byte PDF Download and image viewing against the matching
synthetic server. Cancel remains unverified; omitted checks remain not tested,
and a host-wide helper audit was unavailable. This does not qualify every Linux
distribution, every Local workflow or physical printing. The AppImage is unsigned.

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
- [Overview video — currently private](https://www.youtube.com/watch?v=nrUz3umt8vk) — the established 3.2 tour currently requires owner-granted YouTube access; use the manual or public Desktop walkthrough meanwhile.
- [Desktop walkthrough](https://www.youtube.com/watch?v=mPGNbPy56X8) — Local and Server modes demonstrated on Linux, not Windows/Mac acceptance evidence.

[SHA-256 checksums](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.1-preview1-linux/SHA256SUMS.txt) · [detailed qualification](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.1-preview1-linux/QUALIFICATION.md) · [release/source guide](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.1-preview1-linux/RELEASE_GUIDE.md)

Ordinary users need their app download, not the large source archives. Matching
notices, required sources and build/replacement materials are available in this
release and must accompany applicable redistribution. Checksums verify bytes, not publisher identity.

<details>
<summary>Source and technical records</summary>

Binary source: `f507b64e9366cfd36a536d1112a5279ff28cb27d`. Platform supplements/source snapshot identities remain as recorded; no binary was rebuilt for this description refresh.
See [source identity](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.1-preview1-linux/SOURCE_IDENTITY.json) and [exact asset inventory](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.1-preview1-linux/RELEASE_ASSETS.json).

</details>

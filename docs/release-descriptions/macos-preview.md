# DLMS Desktop 3.3.0 Preview 1 — macOS Apple Silicon

**[Download the Apple Silicon Mac DMG](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.0-preview1-macos/DLMS-Desktop-3.3.0-macos-arm64-preview1.dmg)**

For ordinary use, download this DMG only. You do not need Python or source archives. **Apple Silicon only; qualified on macOS 26.6.2.** Intel Macs and other macOS versions are not qualified. This preview is **ad hoc signed, without Developer ID or notarization**.

**Desktop preview, not the stable release.** Both Desktop and the [original stable browser-based DLMS 3.3.0](https://github.com/drakahari/DLMS_next/releases/tag/v3.3.0) can run locally. Desktop opens its own window: choose **Local** for this computer or **Server** to connect to an existing DLMS server you choose. The editions do not automatically share or synchronize data.

## Install and open

1. Open the DMG and copy **DLMS Desktop.app** to a location you choose. Use a separate folder if another DLMS app is already there.
2. Double-click the copied app in Finder.
3. If macOS says it cannot verify the app, choose **Done**, then **System Settings → Privacy & Security → Open Anyway** for this app. Confirm **Open Anyway** (or **Open**) and authenticate personally with your existing password or Touch ID.

The normal per-app flow was verified on the quarantined preview. If approval is unavailable or macOS reports malware or damage, stop; do not disable Gatekeeper or remove quarantine. Managed Macs may prohibit approval. [Apple's opening instructions](https://support.apple.com/en-us/102445). [Checksums](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.0-preview1-macos/SHA256SUMS) detect a mismatched download but do not independently establish publisher identity.

Start in Local mode to create or import learning material, then choose Study or Exam. Choose Server only to connect to an existing deployment.

<details>
<summary><strong>Technical details and preview limitations</strong></summary>

### Local, Server and data boundaries

DLMS Local and Server modes are enabled, including file selection, TXT/PDF/image imports, OCR, Study, exports and native backup/restore/reset. Local and Server keep separate storage, origins, credentials and privileges. A Server outage does not silently switch to Local. AI handoff opens the normal default browser/profile without automatic paste or submission. The geometric replacement badge used in that preview is included.

The app uses a new, separately marked `~/Library/Application Support/DLMS Desktop Preview` namespace and profile `default`. Existing Candidate, Personal and legacy data is not automatically discovered, adopted, migrated or deleted. Server connections use the server you choose. A first connection may require a macOS access prompt and a retry.

### Selected-file protection

Explicit page-owned file consent, exact origin/path checks, pinned descriptors and content-integrity verification remain enabled. Detected changes fail closed. A malicious native process already running as the same user can clear macOS immutable flags and potentially change bytes after verification; that threat is outside this preview's guarantee. These snapshots are **not Linux-equivalent irrevocable sealing**. Ordinary Server navigation or answers that do not select local files are separate from this selected-file boundary.

### Qualification limits

Completed Mac Local and synthetic Server validation and owner walkthrough evidence are reused with their original scope. Focused public packaging checks covered the single app/icon, arm64 payload, strict ad hoc signatures, bundled OCR/PDFium and the actual quarantined Finder/Cmd-Q/reopen flow. The download check used a task-owned loopback HTTP server; it does not claim Safari/GitHub end-to-end or another Mac's acceptance. Full Server Study/Exam, long-duration use and other native platforms are not inferred from these checks.

There is no Developer ID signature or notarization. This is an explicitly limited **prerelease**, not a stable/latest release. Both existing non-browser CI runs and the Desktop Linux/Windows adapter contract checks passed for this source commit. Review [PR #15](https://github.com/drakahari/DLMS_next/pull/15) for the exact checks and scoped implementation; no broad local tests or build were repeated for publication preparation.

</details>

<details>
<summary><strong>Developers, licensing, source and verification</strong></summary>

Ordinary users do not need these companions to run the DMG. Anyone redistributing the binary must preserve its applicable notices and corresponding-source materials. All application, source/notices archives and provenance downloads remain unchanged.

Application source commit: [`9d3d1b608d99dc633345ad2f5103645f1d6093b5`](https://github.com/drakahari/DLMS_next/commit/9d3d1b608d99dc633345ad2f5103645f1d6093b5).

The DMG and all source/notices archives are the unchanged verified artifacts. The original build/export records its base plus working-tree snapshot; [the commit-to-artifact record](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.0-preview1-macos/COMMIT_SOURCE_MATCH.json) confirms all 1,504 archived application-source files and 432 runtime-source files match the final source commit. No private Git history was merged.

- [Notices and dependency/source correspondence](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.0-preview1-macos/DLMS-Desktop-3.3.0-macos-preview1-notices.tar.zst)
- [Exact application source](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.0-preview1-macos/DLMS-Desktop-3.3.0-macos-preview1-source-application.tar.zst)
- [Mac native producer sources, formulas, patches and English OCR model](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.0-preview1-macos/DLMS-Desktop-3.3.0-macos-preview1-source-native.tar.zst)
- [Wheel-native correspondence and separate FFmpeg 7.1.5 source/configuration](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.0-preview1-macos/DLMS-Desktop-3.3.0-macos-preview1-source-wheel-native.tar.zst)
- [Matching Python dependency source companion](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.0-preview1-macos/DLMS-Desktop-3.3.0-preview1-source-python.tar.zst)
- [Complete matching Qt/PySide source companion](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.0-preview1-macos/DLMS-Desktop-3.3.0-preview1-source-qt-pyside.tar)
- [Redistribution and license details](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.0-preview1-macos/REDISTRIBUTION.md) · [Build and compatible library-replacement instructions](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.0-preview1-macos/BUILD_AND_REPLACEMENT.md) · [Source index](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.0-preview1-macos/SOURCE_INDEX.json)

These are Mac-specific bindings, not substituted Linux or Windows binary-license mappings. Source supersets do not imply every upstream component is shipped. No publisher private key is required to rebuild or ad hoc sign your own compatible replacement copy.

### Additional provenance

- [APPLICATION_SOURCE_MANIFEST.json](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.0-preview1-macos/APPLICATION_SOURCE_MANIFEST.json)
- [APP_MANIFEST.json](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.0-preview1-macos/APP_MANIFEST.json)
- [BUILD_PROVENANCE.json](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.0-preview1-macos/BUILD_PROVENANCE.json)
- [QT_EXCLUSIONS.json](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.0-preview1-macos/QT_EXCLUSIONS.json)
- [RUNTIME_SOURCE_MATCH.json](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.0-preview1-macos/RUNTIME_SOURCE_MATCH.json)

</details>

Artwork history: this release text describes its already-built geometric badge.
Current source restores the original round blue icon, identified by the owner as
AI-generated; see desktop_assets/ICON_PROVENANCE.md for its distinct rights status.
No previously published artifact is changed by this source update.

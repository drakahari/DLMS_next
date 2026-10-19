# DLMS Desktop 3.3.0 Preview 1 — Windows 11 x86-64

**[Download the Windows installer (.exe)](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.0-preview1-windows/DLMS-Desktop-3.3.0-preview1-windows11-x86_64-Setup.exe)**

For ordinary use, download this installer only. You do not need Python or source archives. **Requires Windows 11 x86-64, .NET Framework 4.8 and a protected machine-wide Microsoft WebView2 Evergreen Runtime 155.0.4283.45 or newer.** Setup does not install prerequisites; per-user/AppData-only WebView2 runtimes are unsupported.

**Desktop preview, not the stable release.** Both Desktop and the [original stable browser-based DLMS 3.3.0](https://github.com/drakahari/DLMS_next/releases/tag/v3.3.0) can run locally. Desktop opens its own window: choose **Local** for this computer or **Server** to connect to an existing DLMS server you choose. The editions do not automatically share or synchronize data.

## Install and open

1. Run `DLMS-Desktop-3.3.0-preview1-windows11-x86_64-Setup.exe`. It installs for your user account.
2. The installer is **unsigned**, so Windows may display a security warning. Proceed only if you trust the download and Windows allows it; do not disable protections to install it. [Checksums](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.0-preview1-windows/SHA256SUMS.txt) can detect a mismatched file but do not independently identify the publisher.
3. Finish setup, then open **DLMS Desktop** from the Start menu. Its menu folder retains the compatibility name **DLMS Desktop WebView2 Candidate**. The optional desktop shortcut and post-install launch are initially unchecked.

Start in Local mode to create or import learning material, then choose Study or Exam. Server mode uses the configured server's data instead of your Local profile.

<details>
<summary><strong>Technical details and preview limitations</strong></summary>

### Changes and data

Startup accepts exact supported built-in component metadata retained after Evergreen updates, including references to an older Runtime that is absent, without resetting the profile. Origin, certificate, sandbox, process ownership and extension safeguards remain enabled.

Updates preserve validated `--profile <name>` arguments from the Start menu shortcut. A selected optional desktop shortcut retains its separate profile; unsupported or unsafe shortcut state stops setup rather than selecting default.

Local and Server stay separate. Data remains outside application payloads and is preserved during update/uninstall; previous payload versions remain on update.

Legacy Candidate installation/menu/data names are retained for compatibility.

Desktop shortcut and post-install launch are optional and unchecked.

### Preview limitations

Deep custom browser-data paths can fail native startup. Use the ordinary default location or a short explicit root; the measured 195/115 UTF16-unit examples do not establish a universal length threshold. Unknown/future/foreign component state and unsafe Runtime installations still fail closed.

The absent-version validation used synthetic profiles whose persisted metadata named an actually absent Runtime version. No machine Runtime was uninstalled or serviced for that test. Automated checks do not establish long-duration graphics or physical focus acceptance.

</details>

<details>
<summary><strong>Developers, licensing, source and verification</strong></summary>

The installer already includes license/notice texts. All required source and notice archives are also provided under Assets for license compliance, rebuilding and compatible library replacement; they are not extra runtime downloads.

`SOURCE_MATERIALS.json` indexes the original runtime source companions.

`FINAL_DISTRIBUTION.json` additionally binds the unchanged runtime, revised installer and final installer-source supplement. See `REDISTRIBUTION.md`, `BUILD_AND_REPLACEMENT.md` and `INSTALLER_SOURCE_SUPPLEMENT.md`. Anyone redistributing the binary must preserve the applicable notices and accompanying source obligations. The geometric replacement badge used in that preview is MIT-licensed.

The files below are available for verification, licensing, redistribution and rebuilding. Ordinary users do not need to download them to run the installer; the system prerequisites above still apply. Preserve all applicable source/notices and the final installer supplement when redistributing the binary. No release assets are changed by this description refresh.

- [BUILD_AND_REPLACEMENT.md](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.0-preview1-windows/BUILD_AND_REPLACEMENT.md)
- [DLMS-Desktop-3.3.0-windows-preview1-notices.zip](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.0-preview1-windows/DLMS-Desktop-3.3.0-windows-preview1-notices.zip)
- [DLMS-Desktop-3.3.0-windows-preview1-shared-source-python.tar.zst](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.0-preview1-windows/DLMS-Desktop-3.3.0-windows-preview1-shared-source-python.tar.zst)
- [DLMS-Desktop-3.3.0-windows-preview1-shared-source-qt-pyside.tar](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.0-preview1-windows/DLMS-Desktop-3.3.0-windows-preview1-shared-source-qt-pyside.tar)
- [DLMS-Desktop-3.3.0-windows-preview1-source-application.zip](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.0-preview1-windows/DLMS-Desktop-3.3.0-windows-preview1-source-application.zip)
- [DLMS-Desktop-3.3.0-windows-preview1-source-final-installer.zip](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.0-preview1-windows/DLMS-Desktop-3.3.0-windows-preview1-source-final-installer.zip)
- [DLMS-Desktop-3.3.0-windows-preview1-source-installer.tar.gz](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.0-preview1-windows/DLMS-Desktop-3.3.0-windows-preview1-source-installer.tar.gz)
- [DLMS-Desktop-3.3.0-windows-preview1-source-native.zip](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.0-preview1-windows/DLMS-Desktop-3.3.0-windows-preview1-source-native.zip)
- [DLMS-Desktop-3.3.0-windows-preview1-source-python-extras.zip](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.0-preview1-windows/DLMS-Desktop-3.3.0-windows-preview1-source-python-extras.zip)
- [FINAL_DISTRIBUTION.json](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.0-preview1-windows/FINAL_DISTRIBUTION.json)
- [INSTALLER_SOURCE_SUPPLEMENT.md](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.0-preview1-windows/INSTALLER_SOURCE_SUPPLEMENT.md)
- [payload-inventory.json](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.0-preview1-windows/payload-inventory.json)
- [Python-3.14.7.tar.xz](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.0-preview1-windows/Python-3.14.7.tar.xz)
- [REDISTRIBUTION.md](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.0-preview1-windows/REDISTRIBUTION.md)
- [SHA256SUMS.txt](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.0-preview1-windows/SHA256SUMS.txt)
- [SOURCE_MATERIALS.json](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.0-preview1-windows/SOURCE_MATERIALS.json)

</details>

Artwork history: this release text describes its already-built geometric badge.
Current source restores the original round blue icon, identified by the owner as
AI-generated and separately authorized for use/redistribution. See
`desktop_assets/ICON_PROVENANCE.md`; existing artifacts are not changed.

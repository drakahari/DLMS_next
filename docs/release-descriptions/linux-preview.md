# DLMS Desktop 3.3.0 Preview 1 — Linux x86_64

**[Download the Linux AppImage](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.0-preview1/DLMS-Desktop-3.3.0-preview1-linux-x86_64.AppImage)**

For ordinary use, download this AppImage only. You do not need Python or source archives. **Normal mounting requires FUSE.** The exact preview was tested on Fedora 44/COSMIC Wayland; native Ubuntu and Omarchy acceptance is pending. The file is **unsigned**; keep Chromium sandboxing enabled.

**Desktop preview, not the stable release.** Both Desktop and the [original stable browser-based DLMS 3.3.0](https://github.com/drakahari/DLMS_next/releases/tag/v3.3.0) can run locally. Desktop opens its own window: choose **Local** for this computer or **Server** to connect to an existing DLMS server you choose. The editions do not automatically share or synchronize data.

## Open the AppImage

1. Save it in a folder you want to keep, then open a terminal in that folder.
2. Make it executable and launch a named preview profile:

```sh
chmod u+x DLMS-Desktop-3.3.0-preview1-linux-x86_64.AppImage
./DLMS-Desktop-3.3.0-preview1-linux-x86_64.AppImage --profile preview01
```

No mandatory installation or desktop integration is needed. Local data persists outside the AppImage. Create or import learning material, then choose Study or Exam.

### Alternative installation

- If FUSE is unavailable, explicitly extract and run the same AppImage: `APPIMAGE_EXTRACT_AND_RUN=1 ./DLMS-Desktop-3.3.0-preview1-linux-x86_64.AppImage --profile preview01`. Keep sandboxing enabled.
- [The .tar.zst one-folder bundle](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.0-preview1/DLMS-Desktop-3.3.0-preview1-linux-x86_64.tar.zst) is an alternative for the optional Fedora per-user installation/manual-maintenance manager. Extract into a new folder and keep the full bundle together. Its installer previews locations and requires confirmation; it never installs automatically.

<details>
<summary><strong>Technical details and preview limitations</strong></summary>

**Tested:** exact normal AppImage on Fedora44/COSMIC Wayland: launch,
relocation/reopen, quiz/Study persistence, bundled PDF/PNG OCR, backup output,
duplicate exclusion and owned cleanup. Normal tar manager/launcher/reopen passed
in synthetic Fedora homes and Ubuntu24.04 userspace. Synthetic Server
navigation/outage/isolation passed. Container results are not native Ubuntu
qualification. **Exact-preview native Ubuntu and Omarchy acceptance is pending.**
New physical chooser/keyboard, accessibility, printing and power-loss acceptance
is not claimed. Known limits include occasional `.txt.txt` export suffixes,
roughly5–6s Mix entry, and portal/VM graphics diagnostics.

Close the app and keep a verified compatible backup before replacing its file.
Retain the previous executable. Executable rollback cannot undo later data or an
incompatible schema. Backup restore is explicit; quiz export transfers selected
content and is not a full backup.

Profiles and origins persist outside the AppImage under `${XDG_DATA_HOME:-$HOME/.local/share}/dlms-desktop-appimage-test/`. Server connects only to a deployment you explicitly configure; there is no automatic synchronization or adoption of another application's profiles. Synthetic Server evidence is not general production acceptance.

</details>

<details>
<summary><strong>Developers, licensing, source and verification</strong></summary>

Checksums below detect file mismatches, not independent publisher identity. Ordinary users need only the AppImage (or the alternative tar bundle), not the source companions.

**Source and notices:** MIT application/original badge; third-party terms remain
applicable. Deliver the notices archive and all five source companions alongside
both binaries. They include Qt/PySide, native/Python and AppImage runtime sources,
patches, notices and build/library-replacement instructions. This technical
material is not legal certification. See the public build documentation and
bundled `THIRD-PARTY-NOTICES.txt`.

Build identity: main `86b04e4d5a0658a7dd39ce6c7e2d9a0582ee32fd` plus the supplied
packaging overlay. Source PR#13 commit
`c6f3be7f54c9e7da761795ef275aaadb2be1776f` contains identical build/test inputs
plus later build documentation; About retains the original build identity.

[Linux build, notices and compatible replacement guide](https://github.com/drakahari/DLMS_next/blob/main/docs/linux-desktop-preview-build.md).

- [DLMS-Desktop-3.3.0-preview1-notices.tar.zst](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.0-preview1/DLMS-Desktop-3.3.0-preview1-notices.tar.zst)
- [DLMS-Desktop-3.3.0-preview1-source-appimage-runtime.tar.zst](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.0-preview1/DLMS-Desktop-3.3.0-preview1-source-appimage-runtime.tar.zst)
- [DLMS-Desktop-3.3.0-preview1-source-application.tar.zst](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.0-preview1/DLMS-Desktop-3.3.0-preview1-source-application.tar.zst)
- [DLMS-Desktop-3.3.0-preview1-source-native.tar.zst](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.0-preview1/DLMS-Desktop-3.3.0-preview1-source-native.tar.zst)
- [DLMS-Desktop-3.3.0-preview1-source-python.tar.zst](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.0-preview1/DLMS-Desktop-3.3.0-preview1-source-python.tar.zst)
- [DLMS-Desktop-3.3.0-preview1-source-qt-pyside.tar](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.0-preview1/DLMS-Desktop-3.3.0-preview1-source-qt-pyside.tar)

## SHA-256 — all eight assets

```text
47f1164a762cb4336ad3f8fa69e3914f6d04547b058b0193b50c3ec929d0e03c  DLMS-Desktop-3.3.0-preview1-notices.tar.zst
25b94c37be7bf97d085051976d3ad1f3720f9e9704320ae77eef30424caefb94  DLMS-Desktop-3.3.0-preview1-source-appimage-runtime.tar.zst
12a30fce149714f8f352fbb326c8d95fe04db1bb52f65d5311cbfec529400909  DLMS-Desktop-3.3.0-preview1-source-application.tar.zst
28e1043e31599a4611ee22f8492cbe84b9c2e42cfac2e1cc6d62e3fb8ac4fd46  DLMS-Desktop-3.3.0-preview1-source-native.tar.zst
40d78ccaad2cb0aadcca96f7f9cfeff06cba11e2de794ec45146954190b141f1  DLMS-Desktop-3.3.0-preview1-source-python.tar.zst
2d5f30392243200188b7df70563ba9d40e9847d695c979f628e38543d9d6ff73  DLMS-Desktop-3.3.0-preview1-source-qt-pyside.tar
f1693fcc751685d8811c9067f29f25bc677de7676d6e9abf1050bbc3e049c579  DLMS-Desktop-3.3.0-preview1-linux-x86_64.AppImage
a54a658ef66909a3d25ee64cfe80ce42e521a3e54e87198961581c3f696106ef  DLMS-Desktop-3.3.0-preview1-linux-x86_64.tar.zst
```

</details>

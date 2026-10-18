# Proposed Desktop release-description refresh

These three files are replacement **release descriptions for owner review**, not new downloads or changes to application packages. README and the edition guide use the same app choices and opening steps. No live release has been edited.

| Existing release | Proposed replacement body | Current published body SHA-256 |
| --- | --- | --- |
| [DLMS Desktop 3.3.0 Preview 1 - Windows 11 x86-64](https://github.com/drakahari/DLMS_next/releases/tag/desktop-v3.3.0-preview1-windows) | [windows-preview.md](windows-preview.md) | `38c5275f18b187e30b848d23239e6c8c9791513b1dd6c5be574a92d0aa76f235` |
| [DLMS Desktop 3.3.0 Preview 1 — Linux x86_64](https://github.com/drakahari/DLMS_next/releases/tag/desktop-v3.3.0-preview1) | [linux-preview.md](linux-preview.md) | `7692972e9aa329dc62ae2cc27799a771ec4f619464127a456b7e41cd4b9960b3` |
| [DLMS Desktop 3.3.0 Preview 1 — macOS Apple Silicon](https://github.com/drakahari/DLMS_next/releases/tag/desktop-v3.3.0-preview1-macos) | [macos-preview.md](macos-preview.md) | `f1d89e787e8b6e2f9a230d4e9b916091f1c3d83ba0e3d02d36903ba48db0acc1` |

One later approval can authorize replacing **only the bodies** of these three existing Desktop releases with the reviewed Markdown files. Before editing, compare the live description with the recorded body hash and stop for unexpected changes. Keep titles, tags, prerelease/latest flags and every asset unchanged. The original browser-based DLMS 3.3.0 release remains untouched.

Each proposed body puts the platform app and opening steps first, explicitly says ordinary users need only their app, and keeps source/notices/checksums/rebuilding information secondary. Technical qualification, runtime, signing, data separation and platform limitations remain in the clearly labeled details sections. All existing explicit public links and all published asset links are retained. The Linux tar bundle is an alternative installation, not the primary download.

Historical packaging records under `docs/windows-preview/`, `docs/macos-preview/` and `docs/linux-desktop-preview-build.md` remain unchanged. This documentation-only branch starts at current public main `a86bbb528f4b115bcbd50dce11538b0311081b03`. No application builds or application test suites are part of this change; verification checks Markdown links/anchors, published filenames, description consistency and documentation-only scope.

# Choose your DLMS

DLMS has two supported interface choices. Browser-based DLMS is **not
server-only**. Desktop is **not a replacement requirement** for existing users.
Both editions can run locally. Original DLMS **3.3.1 is stable**; Desktop **3.3.1 Preview 1** is available as
separate Linux, Windows and Apple Silicon Mac prereleases.

## Start with your use case

| What you want | Suggested choice | What it does |
| --- | --- | --- |
| Study locally with your preferred browser | Browser-based DLMS | Runs the application locally and opens its browser interface. |
| A dedicated application window without managing a separate local server | DLMS Desktop preview for your OS | Manages its Local backend and selected Desktop profile. |
| Host one dataset on a deliberately configured machine | Browser-based DLMS configured as a server | The server process owns that dataset; clients use its interface. |
| Connect to an existing DLMS deployment | Your browser, or compatible Desktop Server mode | Uses the deployed server's data, not a copy of your Local profile. |

Local quiz authoring, Study/Exam, history, supported PDF/image OCR and backup
workflows are designed for local/offline use when their runtime dependencies are
present. External AI handoff and intentional external links require connectivity.
A browser interface does not itself imply a cloud service or Internet dependency.

## Downloads: stable original and Desktop previews

Use the [current README download tables](../README.md#downloads) to choose one app
for your platform. Original **3.3.1** has native Fedora 44, Ubuntu 24.04/26.04 and
Windows 11 x86_64 packages, plus an Apple Silicon Mac ZIP. Desktop **3.3.1 Preview 1**
has a Linux x86_64 AppImage, Windows 11 x86_64 installer and Apple Silicon Mac DMG.
These are separate editions; Desktop is optional, not a required replacement.

| Edition | Current release, checksums and companions |
| --- | --- |
| Original 3.3.1 stable | [Five native app packages](https://github.com/drakahari/DLMS_next/releases/tag/v3.3.1) |
| Desktop 3.3.1 Preview 1 — Linux | [AppImage and managed payload](https://github.com/drakahari/DLMS_next/releases/tag/desktop-v3.3.1-preview1-linux) |
| Desktop 3.3.1 Preview 1 — Windows | [Setup.exe](https://github.com/drakahari/DLMS_next/releases/tag/desktop-v3.3.1-preview1-windows) |
| Desktop 3.3.1 Preview 1 — Mac | [DMG](https://github.com/drakahari/DLMS_next/releases/tag/desktop-v3.3.1-preview1-macos) |

Ordinary users need their app download, not Python, build tools or all source archives.
Retain the matching notices/source/replacement materials when redistributing.
Desktop retains candidate filenames and bundled prepublication wording; the release
pages establish its current Preview 1 status. Historical releases remain available.

### Open Desktop on Linux

Normal AppImage mounting requires FUSE. Save the AppImage somewhere you will keep it,
then make it executable and open it:

```sh
chmod u+x DLMS-Desktop-3.3.1-preview1-candidate-linux-x86_64.AppImage
./DLMS-Desktop-3.3.1-preview1-candidate-linux-x86_64.AppImage
```

If FUSE is unavailable, use the supported extracted launcher instead:

```sh
./DLMS-Desktop-3.3.1-preview1-candidate-linux-x86_64.AppImage --appimage-extract
./squashfs-root/AppRun
```

Extract into a fresh directory. Keep Chromium sandboxing enabled and do not run as
root. Fedora normal AppImage/extraction evidence is retained; owner Omarchy evidence
covers extracted AppRun **Server** PDF/image viewing and exact PDF Download, not all
Local workflows or all Linux distributions. Cancel remains unverified.

The separate managed `.tar.zst` payload uses a different launcher/profile contract.
It is not a drop-in replacement for an AppImage, or permission to overwrite an
existing managed installation. Preserve its data root and launcher when planning an update.

### Install and open Desktop on Windows

Requires Windows 11 x86_64, .NET Framework 4.8 and a **protected machine-wide WebView2
Evergreen Runtime 155.0.4283.45 or newer**. Setup installs neither prerequisite;
per-user/AppData-only WebView2 runtimes are unsupported.

Download the current release's Setup.exe, check its SHA-256, close any existing
Desktop session, and use the per-user installer. Its Start menu shortcut is the
normal launcher; no manual Local profile creation is needed. Keep OS protections
enabled and stop if policy blocks the unsigned installer. The current installer
was **compiled and automatically checked, not executed** in its qualification;
these opening steps are instructions, not a claim of installation acceptance.

### Install and open Desktop on Mac

Apple Silicon only. Open the DMG, copy **DLMS Desktop.app** to Applications, and
open the copied app in Finder. Automated evidence is from macOS **26.6.2**;
Intel Macs and other macOS versions are not newly qualified. Manual Mac acceptance
is untested; the provenance record retains `qualified=false`.

The app is ad hoc signed, without Developer ID or notarization. Use only the
individual-app **System Settings → Privacy & Security → Open Anyway** approval
when offered for a trusted, checksum-verified download. Stop if approval is
unavailable or macOS reports malware, damage or a policy block. Do not remove
quarantine or disable Gatekeeper. Managed Macs may prohibit approval.

Original Mac installation uses a ZIP containing **DLMS.app**, not the Desktop DMG.
See [original installation steps](user-manual/02-installation-and-first-launch.md).

## Local, Server and data ownership

- **Browser-based Local:** the local application owns its database and assets;
  your browser stores its browser session state.
- **Desktop Local:** the selected Desktop profile owns local quizzes, history,
  certifications, settings and recovery evidence. Desktop manages its backend.
- **Server access:** the configured server owns the displayed dataset and
  server-side Settings. Desktop Server mode does not gain Local maintenance
  privileges. An unreachable server must not silently show Local data instead.
- Switching Desktop modes does not copy, merge, synchronize, erase or replay data
  between datasets. Desktop Local crash-recovery guarantees do not automatically
  apply to a remote deployment or another deployed version.

For server access, authenticated HTTPS is recommended. A deliberately enabled
exact-origin private-HTTP connection has no HTTPS transport encryption; a private
address or a Tailscale subnet router does not prove the remaining LAN hop is
protected. The captured browser-based application has no application user-login
system. Do not expose it directly to the public Internet. Cross-origin login and
other server-version differences require explicit compatibility review.

## Where your data lives

Application files and writable data are separate. The current defaults are:

| Product/profile | Writable data location |
| --- | --- |
| Browser-based DLMS, Linux | `~/.local/share/DLMS` |
| Browser-based DLMS, Windows | `%APPDATA%\DLMS` |
| Browser-based DLMS, macOS | `~/Library/Application Support/DLMS` |
| Existing Linux Desktop per-user installation | `~/.local/share/dlms-desktop-pilot/profiles/<profile>/` (retained compatibility name; not silently renamed by consolidation) |
| Published Linux Desktop AppImage preview | `${XDG_DATA_HOME:-$HOME/.local/share}/dlms-desktop-appimage-test/profiles/<profile>/` (retained preview namespace; data persists outside the AppImage) |
| Published Windows Desktop preview | Windows LocalAppData Known Folder + `DLMSDesktop\WebView2Candidate\profiles\<profile>\` |
| Published Mac Desktop preview | `~/Library/Application Support/DLMS Desktop Preview/profiles/<profile>/` (default profile `default`; separate marked root) |
| Source/test Desktop runs | Explicit disposable project-local profiles; not the normal installed data root. |

The application identifies the active profile/server. Explicit data-root
configuration can change locations. Keep release-specific instructions and the
shown profile identity authoritative; do not manually point both editions at one
live data root. Replacing an executable is not a data migration.

## Backup versus quiz export

**A full backup** transfers the supported portable application dataset under the
backup contract. Use explicit export/import, check compatibility and destination,
and keep the original archive plus a recovery copy. Desktop import stages and
validates a private copy before confirmation; it does not adopt an existing live
browser-edition profile. Local browser state and Desktop request journals are not
cross-product synchronization material. A restored dataset must be reconciled
before old pending evidence can be reused.

**Quiz bundles, collections, Study Packs and text exports** transfer their
specified content; they are not interchangeable with full backups. A quiz export
is not a promise to include history, certifications, all settings or recovery
state. Use each supported importer rather than renaming a file or sending it to
an unrelated import route. Same-ID Study Pack replacement is intentionally not
supported in the captured application.

Do not share a live database between products or run two writers against a data
root. A successful import may create new identities where the portable format
requires remapping. Check the importer summary instead of assuming a byte-for-byte
clone. Before upgrading a schema or format, retain a verified compatible backup;
a previous executable alone does not guarantee rollback.

## 3.3.1 server compatibility and upgrade boundary

For complete corrected Server behavior use an original **3.3.1** server, or shared
source `f507b64e9366cfd36a536d1112a5279ff28cb27d`. Original binaries use
`79e42531d37b78fc806628e0ba989da13d9ed5ea`, with the same shared application behavior.
Desktop Local updates do not update a remote server. Older 3.3.0 deployments differ
by source; the later 5e5fa245 build still lacks the complete certificate/Avery
baseline. Older-client/new-server combinations are not newly qualified.

Schema 12, backup 1, portable quiz 2 (legacy 1 imports) and pack 1 remain unchanged;
no new migration is introduced from 3.3.0. Preserve a verified backup and old payload
before updating. Read the [current release guidance](releases/3.3.1.md) for the
precise qualification limits; unperformed checks are not passes or established defects.

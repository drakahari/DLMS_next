# Choose your DLMS

DLMS has two supported interface choices. Browser-based DLMS is **not
server-only**. Desktop is **not a replacement requirement** for existing users.
Both editions can run locally. The original browser-based 3.3.0 release is stable;
Desktop is available as separately published platform previews.

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

The [original browser-based DLMS 3.3.0 release](https://github.com/drakahari/DLMS_next/releases/tag/v3.3.0) remains the stable option. It runs locally in your browser and can also be intentionally hosted as a server. Desktop is an optional preview, not a required replacement.

For ordinary use, download only your platform's app. Sources and notices remain available for licensing, redistribution and rebuilding; they are not extra runtime downloads. See the [README download and opening steps](../README.md#download-dlms-desktop--previews).

| Edition | OS/architecture | Published download and qualification |
| --- | --- | --- |
| Browser-based DLMS 3.3.0 — stable | Fedora 44 x86_64 | [Original release](https://github.com/drakahari/DLMS_next/releases/tag/v3.3.0), `.tar.gz`; native builder and broader Fedora workflow evidence recorded. |
| Browser-based DLMS 3.3.0 — stable | Ubuntu 24.04 / 26.04 x86_64 | [Original release](https://github.com/drakahari/DLMS_next/releases/tag/v3.3.0), `.tar.gz`; native builders passed. Broader Ubuntu 24.04 packaged harness was canceled, not passed. |
| Browser-based DLMS 3.3.0 — stable | Windows 11 x86_64 | [Original release](https://github.com/drakahari/DLMS_next/releases/tag/v3.3.0), `.zip`; native builder evidence does not imply every workflow was qualified. |
| Browser-based DLMS 3.3.0 — stable | macOS Apple Silicon (not Intel) | [Original release](https://github.com/drakahari/DLMS_next/releases/tag/v3.3.0), `.zip` containing `DLMS.app`; no signing/notarization claim. |
| DLMS Desktop — Preview 1 | Linux x86_64 | [AppImage](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.0-preview1/DLMS-Desktop-3.3.0-preview1-linux-x86_64.AppImage); Ubuntu-24.04-compatible build, exact normal AppImage tested on Fedora 44/COSMIC Wayland. Native Ubuntu/Omarchy acceptance remains pending. The `.tar.zst` manager bundle is an [alternative installation](../README.md#alternative-linux-installation). Unsigned. |
| DLMS Desktop — Preview 1 | Windows 11 x86_64 | [Installer](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.0-preview1-windows/DLMS-Desktop-3.3.0-preview1-windows11-x86_64-Setup.exe); .NET Framework 4.8 and protected machine-wide WebView2 Evergreen 155.0.4283.45+ required. Setup installs neither prerequisite. Unsigned. |
| DLMS Desktop — Preview 1 | macOS 26.6.2 Apple Silicon | [DMG](https://github.com/drakahari/DLMS_next/releases/download/desktop-v3.3.0-preview1-macos/DLMS-Desktop-3.3.0-macos-arm64-preview1.dmg); qualified on this native baseline, not Intel or other macOS versions. Ad hoc signed, not Developer ID-signed or notarized; supported per-app approval verified. |

Read the [Windows](https://github.com/drakahari/DLMS_next/releases/tag/desktop-v3.3.0-preview1-windows), [Linux](https://github.com/drakahari/DLMS_next/releases/tag/desktop-v3.3.0-preview1) or [Mac](https://github.com/drakahari/DLMS_next/releases/tag/desktop-v3.3.0-preview1-macos) release details for prerequisites, checksums and technical limitations. Mac selected-file consent/origin/path/descriptor/hash checks remain enabled, but a malicious native process already running as the same user is outside the preview guarantee; immutable snapshots are not Linux-equivalent sealing. Ordinary non-file-upload Server workflows are distinct from that boundary.

The original stable downloads and release history remain available. Installing Desktop does not migrate another edition's data or qualify another OS/architecture. For the original edition's checksums, upgrade and rollback limits, read the [3.3.0 release notes](releases/3.3.0.md).

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

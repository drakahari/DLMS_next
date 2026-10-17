# Choose your DLMS

DLMS has two supported interface choices. Browser-based DLMS is **not
server-only**. Desktop is **not a replacement requirement** for existing users.
This guide separates published downloads from private candidates and plans.

## Start with your use case

| What you want | Suggested choice | What it does |
| --- | --- | --- |
| Study locally with your preferred browser | Browser-based DLMS | Runs the application locally and opens its browser interface. |
| A dedicated application window without managing a separate local server | DLMS Desktop, when qualified for your OS | Manages its Local backend and selected Desktop profile. |
| Host one dataset on a deliberately configured machine | Browser-based DLMS configured as a server | The server process owns that dataset; clients use its interface. |
| Connect to an existing DLMS deployment | Your browser, or compatible Desktop Server mode | Uses the deployed server's data, not a copy of your Local profile. |

Local quiz authoring, Study/Exam, history, supported PDF/image OCR and backup
workflows are designed for local/offline use when their runtime dependencies are
present. External AI handoff and intentional external links require connectivity.
A browser interface does not itself imply a cloud service or Internet dependency.

## Downloads: available, private and planned

The [published DLMS 3.3.0 release](https://github.com/drakahari/DLMS_next/releases/tag/v3.3.0)
contains **browser-based DLMS** packages. Keep using them if that interface suits
you. Their existing URLs and release history remain valid.

| Edition | OS/architecture | Format | Current status |
| --- | --- | --- | --- |
| Browser-based DLMS 3.3.0 | Fedora 44 x86_64 | `.tar.gz` | Published; native builder and broader Fedora workflow evidence recorded in release notes. |
| Browser-based DLMS 3.3.0 | Ubuntu 24.04 / 26.04 x86_64 | `.tar.gz` | Published; native builders passed. Broader Ubuntu 24.04 packaged harness was canceled, not passed. |
| Browser-based DLMS 3.3.0 | Windows 11 x86_64 | `.zip` | Published; native builder evidence does not imply every workflow was qualified. |
| Browser-based DLMS 3.3.0 | macOS arm64 | `.zip` application bundle | Published browser-based package, not macOS Desktop. No signing/notarization claim. |
| DLMS Desktop | Linux x86_64, Ubuntu-24.04-compatible build | AppImage and `.tar.zst` one-folder bundle | Private candidate. Evidence includes Fedora and Ubuntu-userspace checks plus bounded owner Omarchy observations; not universal Linux qualification. |
| DLMS Desktop | Windows 11 x86_64, WebView2 host | One-folder payload and per-user installer candidate | Private candidate17; native acceptance is limited to its recorded checks. |
| DLMS Desktop | macOS 26.6.2 arm64 | Private `.app`/DMG candidate | Bounded native and owner checks only; not a public download or general Mac qualification. Real-file uploads and signing/notarization remain unresolved. |

A private candidate is not a public download. Consolidation does not publish new
artifacts, qualify another OS/architecture, or replace an installed application.
For exact browser-edition limitations, checksums and setup, read the
[3.3.0 release notes](releases/3.3.0.md). Future public Desktop formats and support
labels require their own release approval.

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
| Linux Desktop AppImage candidate | `${XDG_DATA_HOME:-$HOME/.local/share}/dlms-desktop-appimage-test/profiles/<profile>/` (separate synthetic-test namespace) |
| Windows Desktop candidate | Windows LocalAppData Known Folder + `DLMSDesktop\WebView2Candidate\profiles\<profile>\` |
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

# Desktop hosts and the shared application

One root application (`app.py`, `dlms/`, `templates/`, `static/`, `init.sql`)
supports both browser-based DLMS and Desktop. Neither edition maintains a
second application copy. The public 3.3.0 release history is unchanged.

## Host boundaries

Linux uses Qt WebEngine. Windows candidate17 uses a C# WebView2 renderer with
Python backend ownership and Qt native controls. They share contracts, not an
assumption that renderer events or OS handles behave identically. The separate
Apple Silicon Qt candidate has bounded qualification on macOS 26.6.2 arm64; it
is not a generally qualified or notarized public Mac release. The browser-based
macOS release does not qualify Desktop.

Mac file snapshots currently use private immutable flags plus descriptor/hash
checks under a synthetic-data-only approval. A same-user process can clear the
flag; do not claim Linux's irrevocable sealing guarantee or approve production
file uploads from ordinary Server navigation passes. Local ad hoc signatures
are not Developer ID/notarization. The source includes the generic candidate
builder and synthetic checks, not private personal launchers/installation tools.

Application grading, answer identity, history, schema and portable formats are
canonical. Desktop adapters own stable local origins, authenticated loopback,
profile concurrency, native Settings, explicit file consent/sealed snapshots,
save journals, managed data transitions, process cleanup and external-browser
dispatch. Optional application hooks keep ordinary web defaults unchanged.

Local and Server use separate browser storage and datasets. Server pages receive
no Local tokens, native maintenance privileges or Local recovery journal access.
Root-mounted exact origins are supported; remote deployment/version compatibility
must be tested. Local recovery acknowledgments are not remote save guarantees.

Private HTTP is explicit opt-in, without transport encryption. A VPN subnet
router does not establish encryption on the final HTTP LAN hop. No automatic
copying, synchronization, server connection or data adoption is performed.

## Releases and maintenance

Record the application version, host/release identity, source commit and data
compatibility independently. Browser packages, Linux Desktop and Windows Desktop
may release independently. Preserve existing application IDs and data roots;
repository consolidation does not authorize renaming or migrating profiles.

Installer rollback remains conservative: an older executable cannot undo a
data migration or later writes. Preserve compatible verified backups. Read
[validation](desktop-validation.md) and [publication prerequisites](publication-prerequisites.md).

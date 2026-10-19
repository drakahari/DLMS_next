# Proposed Windows preview release text — approval required

**DLMS Desktop 3.3.0 Preview 1 for Windows 11 x86-64**

This unsigned prerelease packages the DLMS backend/web UI with the native
WebView2 Desktop host. It adds compatibility for retained component metadata
after Evergreen servicing, including references to an older Runtime that has
been removed, without deleting or resetting the profile. Exact origin,
certificate, sandbox, process ownership and extension checks remain enabled.

Requires .NET Framework 4.8 and an already installed, protected machine-wide
Microsoft WebView2 Evergreen Runtime 155.0.4283.45 or newer. Setup does not install
prerequisites. It is per-user and unsigned; Windows may display security warnings.
No signing certificate was purchased or generated.

Download the installer **and all accompanying notices/source files**. The cleared
geometric replacement badge used in that preview is MIT; dependency licenses and replacement/build instructions
remain applicable. Read SOURCE_MATERIALS.json and REDISTRIBUTION.md. Checksums
detect mismatches but are not an independent publisher signature.

Local and Server remain separate. Existing legacy Candidate installation/data
namespaces are retained for upgrade compatibility. Setup keeps prior version
payloads and external data; desktop shortcut and post-install launch are optional
and unchecked. Updates retain a supported named profile from the Start menu
shortcut (`--profile <name>`), after verifying its target and arguments. The
optional desktop shortcut retains its own selection when that task is selected;
otherwise the existing desktop link is left unchanged. Unsafe or
unsupported shortcut state stops setup with an actionable error; arbitrary
arguments are never replayed. No production server changes or data migration are
performed.

Known preview limitations: deep custom browser-data paths can fail native startup;
use the ordinary default data location or a short explicit root. The observed
195-character browser-storage failure and 115-character success do not define a
universal path-length threshold. Per-user/AppData-only WebView2 runtimes are
unsupported; a protected machine-wide Runtime is required. Unknown/future/foreign
component identities and unsafe installations still fail closed. Automated
startup/reopen evidence is not long-duration graphics or physical focus acceptance.

The absent-Runtime validation seeded persisted metadata naming an actually absent
version. It did **not** uninstall or service the machine's Runtime. Supplied
installer-source supplement/index describes the revised setup; the preserved
runtime's embedded source materials continue to identify its original build.

This text and the prepared artifacts need owner approval before any merge,
installation, tag, release upload or publication. This proposal does not claim
that those actions have occurred or that every future Runtime change is covered.

Artwork history: this release text describes its already-built geometric badge.
Current source restores the original round blue icon, identified by the owner as
AI-generated and separately authorized for use/redistribution. See
`desktop_assets/ICON_PROVENANCE.md`; existing artifacts are not changed.

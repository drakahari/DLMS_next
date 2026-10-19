> Unpublished focused Mac candidate `macos-focus-fix-20261019`.
> Exact source/handoff: `717dd01a5efa9c6cbc8f95f463e70714ec198597`;
> shared runtime correction: `c1268daaf8a1dab2919b912c117a1ac4f86ea6c6`.
> Uncommitted shared Qt Server focus correction, test tooling and packaging identity
> overlay are recorded separately.
> Bundle: `DLMS Desktop Focus Candidate.app`. During this task open only via
> the verified task wrapper with its fixed synthetic data-root/profile. The bare
> app retains the public Preview default directory; do not open against existing
> installed/personal storage. No installation/release is authorized. Ad hoc only,
> no Developer ID/notarization; downloaded/quarantined approval is unqualified for
> this artifact. Same-user malicious native processes remain outside the selected
> file snapshot guarantee. Historical Preview1 instructions below are reference,
> not this candidate's identity or qualification.

# Build and replace components of the Apple Silicon preview

Public base: `e084c04a2be7b1e5f593b12fc0f232b7d3c2c75b`, on
`feature/macos-desktop-public-preview`. The application companion is the exact
reviewed public source snapshot plus Mac changes, without private Git history.
APPLICATION_SOURCE_MANIFEST.json identifies every exported file. Build provenance
records the Git base and exact runtime snapshot; a working-tree snapshot is not
misrepresented as a pristine committed build.

Use Apple Silicon macOS with Xcode Command Line Tools and Python3.14.7. Recorded
native qualification is macOS26.6.2 arm64; no universal binary or other macOS-version
claim is made. Use a separate build environment from the pinned requirements in
package_macos. The original task reuses already verified offline wheels read-only;
BUILD_INPUTS.json binds the local wheelhouse, its hashes and interpreter. It is a
local build configuration, not a source-of-truth for recipient paths.

`python -m package_macos.build --app-only --inputs /absolute/BUILD_INPUTS.json`
builds under the task's private cache outside Documents FileProvider. Supply exact
source/notice materials there first; the builder refuses unresolved source or
changed wheel/material hashes. Consult package_macos/native_materials.py and
preview_materials.py for the source index format and bounded collection steps.
The retained Homebrew formulas describe the producer build settings and patches.
Source archives are inert until a recipient deliberately builds them. No source
acquisition helper installs packages or executes downloaded scripts.

The spec produces **one** user-facing `DLMS Desktop.app`, including the cleared
Mac icon, native Cocoa integration, Qt WebEngine, PDFium and bundled OCR resources.
Normal Finder launch uses `~/Library/Application Support/DLMS Desktop Preview`,
profile `default`, with a preview-specific marker. It does not adopt the private
Candidate's default/Personal/Walkthrough directories. `--data-root` and `--profile`
remain supported for explicit separate roots and named profiles. Unmarked or
unsafe existing roots fail closed. Data stays outside the application bundle.

To replace compatible Qt/PySide or native libraries, work on a separate copy and
rebuild from the supplied sources with matching ABI/architecture and required
features. Use the original dependencies' build instructions plus the retained
producer formulas/patches. Keep WebEngine's matching resources/helper and the
library set together. Preserve licenses and update your own inventories/hashes.
You may ad hoc sign your changed copy with
`codesign --force --deep --sign - "/path/to/your/DLMS Desktop.app"`, then verify
with `codesign --verify --deep --strict "/path/to/your/DLMS Desktop.app"`.
This creates your own integrity signature; it neither retains a publisher's
signature nor notarizes the result. Never alter a running payload or forge the
original artifact manifest. The original hashes are expected to change.

No publisher key is needed for library replacement/debugging. Existing schema
and saved-data compatibility still apply when changing application versions.
Do not disable Gatekeeper, strip quarantine, weaken browser sandboxing or modify
installed dependencies to make a replacement launch. Follow the supported
per-app approval flow only when macOS offers it; stop for a malware/damage
warning or an unavailable approval path.

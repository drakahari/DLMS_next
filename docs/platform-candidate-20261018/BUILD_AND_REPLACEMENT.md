# Source, build and replacement instructions

Obtain the matching source companions listed in SOURCE_MATERIALS.json alongside
the two binary formats, then verify their SHA-256 values. They contain no Git
history, personal data, private operational reports or signing keys. Sources are
provided directly; this release does not rely on an unspecified future offer.

## Application and payload

The application source archive is a direct export of commit
4b50e2b3fb39dd478d355bf785b319805579076c. Its runtime matches
bfdffb720f743e9d720cd07292ec7e1ec325e059; the four additional files are
reviewed quality reports. Extract the exact named application archive listed in
SOURCE_MATERIALS.json, enter DLMS-source, and use it directly. No packaging patch
is required or supplied for this candidate. Do not apply the historical Preview1
overlay. Historical dependency companion filenames are intentionally unchanged
because their verified bytes and dependency pins are unchanged.

Use package_linux/Containerfile.ubuntu24, its pinned base-image digest,
package_linux/native-inputs.json and package_fedora/requirements-build-lock.txt.
The native companion contains exact Python 3.14.7, Tesseract 5.5.3 and Leptonica
1.87.0 input archives and all Ubuntu-native source versions/patches. Package
copyrights and EXACT_INPUTS.json distinguish build-environment packages from
actual bundled native files. Use `dpkg-source -x package.dsc` for each Ubuntu
source package and its retained debian/rules/build dependencies. No binary
reproducibility claim is made for a contemporary apt mirror: use the recorded
versions and source patches, not an unreviewed broad dependency upgrade.

The Qt/PySide source companion contains the verified official 6.11.2 source
releases and their standard CMake/PySide build instructions. Configure shared
Qt with WebEngine/Widgets/SVG/printing and required QML/native support; keep the
package_fedora/minimal_bundle.py exclusions. Preserve WebEngine's sandbox and
its required helper/resources. Use the sources' Qt and PySide instructions to
build replacements; compiler choices may produce different bytes. A replacement
must be ABI-compatible, not merely have the same filename/version string.

The Python companion provides retained matching package source archives and
Pillow dependency-source/recipe evidence. Exact wheel notices accompany the
payload. Preserve upstream notices/exception terms in rebuilds.

Prepare an OCR bundle and notice kit as described in package_linux/freeze_ubuntu.sh
and package_appimage/build_payload.py. The source companion includes the current packaging modules and public recipes
in docs/linux-desktop-preview-build.md. That document records the historical
Preview1 build; for this candidate use the exact source identity above directly
and omit its historical overlay step. Supply new output directories and the
exact source identity. Never build into a profile or installed version directory.

## Compatible shared-library replacement

The tar payload is an ordinary one-folder distribution. Make a separate copy,
replace a library with an ABI-compatible rebuilt version, preserve notices,
and rebuild the artifact/inventory. Do not edit a running/installed payload.
The bundled manager's `prepare-variant` accepts an owner-modified copy and makes
a distinct offline variant with fresh integrity metadata. It does not require
publisher signing credentials. Run `./Install-DLMS-Desktop prepare-variant --help`
for its explicit base-inventory, modified-payload, new release and output inputs.
Use an entirely separate output and back up compatible data before manual update.
Its hashes detect substitutions; they are not a prohibition on modified libraries.
An older executable is not a data rollback after incompatible changes or later
writes. Do not alter receipts/locks or bypass a refusal to force rollback.

For AppImage, extract the payload, make the compatible replacement and rebuild
using package_appimage/build.py. New runtime bytes require a new matching
appimage-info/runtime-input identity: do not patch a mounted image or lie about
its digest. No vendor secret or production signing key is required to rebuild.

## AppImage runtime/static libfuse replacement

The AppImage source companion includes type2-runtime commit
8f39b89e2ac31e1640b3d3f7e9a5108e6ce805fa, its complete Makefile/scripts, the
upstream libfuse mount patch, all six library input archives, and Alpine aports
commit b82a90a26fc0965ffd03cca90dfb1daed17101cc with build recipes/patches.
The producer build log confirms Alpine 3.21 image digest
ce64758a109eb420d874a118f87920e625e12d3634e03b4a5573fd9f6e5d3507 and exact
library versions. Source archive digests match pinned upstream/Alpine recipes.
Use the included BUILD.md, scripts/docker/Dockerfile,
scripts/common/install-dependencies.sh and scripts/build-runtime.sh; build a
modified libfuse and relink the MIT runtime with that library. A reproducible
build may need the recorded Alpine package revisions rather than today's mirror.
Use the new runtime hash in a separate AppImage build-input JSON and rebuild
with package_appimage/build.py. This provides the source/application/build route
for modifying the statically linked LGPL library, not only a link to its license.

## Publisher verification

No paid signing certificate is required by this preview's Linux packaging.
SHA256SUMS detects mismatched bytes. Obtain it through the owner's authentic
GitHub release channel; a checksum copied with a substituted binary does not
independently authenticate a publisher. No signing key, automatic downloader or
background updater is included. Publication remains a separate owner decision.

## Safety candidate 2026-10-18

This candidate uses shared runtime bfdffb720f743e9d720cd07292ec7e1ec325e059 and exact source commit 4b50e2b3fb39dd478d355bf785b319805579076c. The only changes beyond the runtime baseline are four reviewed quality reports. The refreshed application-source archive is a direct git archive of that commit and needs no packaging patch. All dependency/source companions retain their verified Preview1 bytes and filenames. Use the included source tree and current locks for replacement; do not apply the historical Preview1 overlay again. The artifact is a private review candidate, not a published release.

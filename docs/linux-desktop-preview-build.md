# Building and replacing the Linux Desktop preview

## Scope and exact source identity

DLMS Desktop 3.3.0 Preview 1 is a **prerelease**, not a replacement for the
existing browser-based DLMS 3.3.0 downloads. Source and binary publication are
separate approvals. No release, automatic updater or installed replacement is
performed by the build commands below.

The prepared binaries were built from consolidated main
`86b04e4d5a0658a7dd39ce6c7e2d9a0582ee32fd` plus the five-file packaging overlay
supplied as `linux-preview-packaging.patch` in the application-source companion.
Its SHA-256 is
`165dfb96baa40ed4762dff46b7481c1739b3d7c9deee3d7d68e2988fdf1d9d23`.
The recorded build-input file-manifest SHA-256 is
`06f87097c597bcc62db24dd4c9f758aa87d9eb9333ea17c2f936b5038da90875`.
The release identity is `linux-330-preview1-20261017`; the application version
is `3.3.0`. About accurately records the base commit and review-tree identity.
It must not be relabeled as a pristine build of a later documentation commit.
The five changed build/test files in this source PR are byte-identical to that
overlay. This document was added afterward; it is not an embedded runtime input.

The overlay validates release names before freezing, reads the shared application
version without initializing a profile, validates preview notice/source manifests,
and provides the correct notice entry point. It changes no application behavior,
dependency pin, schema, portable format, recovery protocol or server header.

## Required delivery and provenance

Deliver **both binaries and all six companions** together. The notice archive's
`distribution-kit/SOURCE_MATERIALS.json` binds the five source companions; its
`MANIFEST.json` binds the notice texts. Notices cover exact wheel files, Ubuntu
copyrights, Qt/PySide, Chromium, OCR and the AppImage runtime. Third-party terms
remain applicable alongside the MIT application code. Technical
source correspondence is not legal certification or a bit-reproducibility claim.

| Companion | Contents |
| --- | --- |
| `DLMS-Desktop-3.3.0-preview1-notices.tar.zst` | Verified distribution-kit, notices, native mapping, source index, redistribution and replacement instructions |
| `DLMS-Desktop-3.3.0-preview1-source-application.tar.zst` | Main export, packaging patch and build/replacement instructions; no private Git history |
| `DLMS-Desktop-3.3.0-preview1-source-native.tar.zst` | Python/Tesseract/Leptonica inputs plus exact 75 Ubuntu source packages, descriptors and patches for 94 binary packages mapped to 111 bundled native files |
| `DLMS-Desktop-3.3.0-preview1-source-python.tar.zst` | Matching Python package sources and Pillow dependency-source/recipe evidence |
| `DLMS-Desktop-3.3.0-preview1-source-qt-pyside.tar` | Official Qt and PySide 6.11.2 source archives |
| `DLMS-Desktop-3.3.0-preview1-source-appimage-runtime.tar.zst` | Pinned runtime, six static-library inputs, libfuse mount patch, Alpine recipes and producer provenance |

Verify downloaded files using checksums obtained from the trusted release page.
Checksums detect mismatches; these unsigned files do not establish an independent
publisher identity. Do not distribute private profiles, logs, backups, source
history, signing keys or operational reports with the package.

## Build inputs and environment

Use an **isolated x86_64 Ubuntu 24.04 build environment**, not the host's Python,
glibc or a running installation. The initial environment is described by
`package_linux/Containerfile.ubuntu24`, base image
`docker.io/library/ubuntu@sha256:f610ab94648195aa356059f5b41d6085c9d4d903c072430cdd1af7bdb646106b`.
The actual cached producer image was
`sha256:0cbc551e1b75bcd723ebd97289691eac0cf5ee8bd858f129c53cc912ec01ed27`;
that is provenance, not a promise that this private image is downloadable.
The legacy `Containerfile.qt-runtime-layer` references a local historical image;
use the self-contained `Containerfile.ubuntu24` for a fresh environment instead.

`package_linux/native-inputs.json` pins Python 3.14.7, Tesseract 5.5.3 and
Leptonica 1.87.0 archives and SHA-256 values. Copy those three files and
`package_fedora/requirements-build-lock.txt` into a new container build context:

```sh
# Run from the reviewed source tree; inputs/ contains the verified native archives.
set -eu
buildroot=$(mktemp -d "${TMPDIR:-/tmp}/dlms-preview-build.XXXXXXXX")
mkdir "$buildroot/context"
cp package_linux/Containerfile.ubuntu24 "$buildroot/context/Containerfile"
cp package_fedora/requirements-build-lock.txt "$buildroot/context/"
cp inputs/Python-3.14.7.tar.xz inputs/tesseract-5.5.3.tar.gz \
   inputs/leptonica-1.87.0.tar.gz "$buildroot/context/"
podman build -t localhost/dlms-preview-build -f "$buildroot/context/Containerfile" \
  "$buildroot/context"
```

This does not install host packages or require sudo. Rootless Podman (or an
independently qualified equivalent) is a build prerequisite. Contemporary apt
mirrors and build compilers can produce different bytes. For exact source/version
replacement use the supplied `.dsc`, original archives, Ubuntu patches and
`debian/rules`; run `dpkg-source -x package.dsc` and satisfy its declared build
dependencies. The preview does not claim bit-reproducible apt, wheels or vendor Qt.

Active pins include PySide/Qt 6.11.2, pypdf 6.20.1, pypdfium2 5.14.0 (PDFium
156.0.8076.0), Werkzeug 3.1.9, Waitress 3.0.2, pip 26.2 and PyInstaller 6.22.2.
The cached producer image's old freeze list reported PDFium 5.13.0; the actual
build installed the verified 5.14.0 wheel (SHA-256
`11f281613fa22313d9c7ab89947665e84eccf8ebe40e1198a84a88352305648d`).
A fresh build must use the **current lock**, not that stale freeze list.

## Preparing explicit inputs without a private checkout

Extract companions into a new working directory, after verification. The native
archive has `native-build-sources/` and `ubuntu-sources/`; the notices archive
has `distribution-kit/`. The application archive has `DLMS-source/` and the
packaging patch at the archive root. If using the baseline application archive,
run `cd DLMS-source`, then
`git apply --check --whitespace=error-all ../linux-preview-packaging.patch` and
`git apply ../linux-preview-packaging.patch`. Do not apply it again to a source
tree already containing these five changes.

Prepare a writable build copy of the reviewed source as `/work` in the container.
No profile or installation may be mounted there. Supply these explicit directories:

- `/work/distribution-kit`: the verified extracted notice archive's
  `distribution-kit`. `python -c 'from pathlib import Path; from
  package_fedora.assemble_distribution import verify_materials;
  verify_materials(Path("distribution-kit"))'` verifies its exact contents when
  run as a single-line command from the source root.
- `/work/notices`: copy `ubuntu/`, `common-licenses/`, `wheels/` and
  `EXACT_INPUTS.json` from that same kit into a fresh directory, with an
  `INVENTORY.json` identifying that mapping (recipe below). These are the existing
  build's native/wheel notice inputs, not reports from a developer home.
- `/work/old-ocr/tessdata`: English language data plus `configs/tsv`.
  `/work/old-ocr/licenses`: Tesseract, tessdata and Leptonica license texts.
  These are non-executable data/notice inputs. For an identical-data rebuild,
  copy them from the verified preview tar's `_internal/ocr/tesseract/` directory;
  **do not reuse its native executable**. The supplied Containerfile rebuilds
  Tesseract/Leptonica from source under `/opt/ocr` and `/opt/lept`.
  English data SHA-256 is
  `7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2`;
  `configs/tsv` contains `tessedit_create_tsv 1` and a newline. The Apache-2.0
  data notices remain supplied. Alternatively use official Tesseract tessdata,
  verify/record the chosen revision and digest, and identify it as a new build.

The companion `BUILD_AND_REPLACEMENT.md` gives the source/replacement overview;
its phrase “materials recipes” refers to these public recipes and the build
modules, not to unavailable private preparation scripts. Reusing the supplied
verified notice kit avoids needing private scripts to reconstruct it.

For example, the following uses the public source checkout and verified assets
in an explicitly chosen directory. It copies build inputs into a fresh task
container; it mounts neither HOME nor an installation/profile. It requires the
`buildroot` and image prepared above. Set `assets` to your verified download
folder; no scanning of other folders is performed.

```sh
set -eu
assets=/absolute/path/to/verified-preview-assets
source_commit=$(git rev-parse HEAD)
mkdir "$buildroot/work" "$buildroot/materials" "$buildroot/release"
git archive HEAD | tar -xf - -C "$buildroot/work"
tar --zstd -xf "$assets/DLMS-Desktop-3.3.0-preview1-notices.tar.zst" \
  -C "$buildroot/materials"
tar --zstd -xf "$assets/DLMS-Desktop-3.3.0-preview1-linux-x86_64.tar.zst" \
  -C "$buildroot/release"
cp -R "$buildroot/materials/distribution-kit" "$buildroot/work/distribution-kit"
mkdir "$buildroot/work/notices" "$buildroot/work/old-ocr"
for entry in ubuntu common-licenses wheels EXACT_INPUTS.json; do
  cp -R "$buildroot/materials/distribution-kit/$entry" "$buildroot/work/notices/"
done
printf '%s\n' '{"scope":"Exact native and wheel build notices; see EXACT_INPUTS.json","source":"EXACT_INPUTS.json","status":"Technical inventory, not legal certification"}' \
  > "$buildroot/work/notices/INVENTORY.json"
cp -R "$buildroot/release/DLMS-Desktop/_internal/ocr/tesseract/tessdata" \
  "$buildroot/work/old-ocr/"
cp -R "$buildroot/release/DLMS-Desktop/_internal/ocr/tesseract/licenses" \
  "$buildroot/work/old-ocr/"
build_container=$(podman create --network none --entrypoint /bin/sh \
  localhost/dlms-preview-build -c '
    set -eu
    cd /work
    python -c "from pathlib import Path; from package_fedora.assemble_distribution import verify_materials; verify_materials(Path(\"distribution-kit\"))"
    python -m pip check
    python -B tools/check_release_dependencies.py
    export DLMS_DESKTOP_PREVIEW_SUPPORT="Linux x86_64 preview; qualification recorded separately."
    sh package_linux/freeze_ubuntu.sh linux-330-preview1-rebuild "$1"
  ' build "$source_commit")
podman cp "$buildroot/work/." "$build_container:/work/"
podman start --attach "$build_container"
podman cp "$build_container:/work/out" "$buildroot/results"
```

Keep failed containers/output for diagnosis; do not copy production profiles into
them or replace host libraries. The command runs the following existing build
sequence inside the container, with `/work/out` initially nonexistent:

```sh
set -eu
cd /work
python -m pip check
python -B tools/check_release_dependencies.py
export DLMS_DESKTOP_PREVIEW_SUPPORT='Linux x86_64 preview; qualification recorded separately.'
sh package_linux/freeze_ubuntu.sh linux-330-preview1-rebuild SOURCE_COMMIT
```

Replace `SOURCE_COMMIT` with the exact 40-character commit of the source being
built. A modified uncommitted tree also requires its own file-manifest SHA-256
as the third argument; do not reuse the prepared preview's manifest for changed
inputs. `freeze_ubuntu.sh` performs minimal exclusions, host-platform pruning,
normal freezing, embedded-source checks and the Ubuntu-24 ABI floor check.
It leaves one shared payload at `/work/out/normal-build/dist/DLMS-Desktop`.
Keep Chromium sandboxing and the Qt WebEngine helper/resources enabled. Host
Fontconfig and GBM remain host requirements; do not reinsert incompatible bundled
copies or disable acceleration globally to hide a driver warning.

## Two formats from one payload

Create the tar in a new output path from that distribution directory. Include
`candidate.json` for the bundled manual manager, and preserve executable modes.
For the AppImage use `python -m package_appimage.build --help`, with the **same**
payload, a new AppDir, a new output file and the exact tool/runtime files pinned
by `package_appimage/inputs.json`. Its official URLs/asset IDs and digests are
recorded there; the builder refuses mismatched tooling and existing outputs.
No implicit “latest” download, signing key or automatic desktop integration is
needed. For example, with verified tooling under `/inputs`:

```sh
cd /work/out/normal-build/dist
test ! -e /work/out/DLMS-Desktop-rebuild.tar.zst
tar --zstd -cf /work/out/DLMS-Desktop-rebuild.tar.zst DLMS-Desktop candidate.json
cd /work
python -m package_appimage.build \
  --payload /work/out/normal-build/dist/DLMS-Desktop \
  --appdir /work/out/rebuild.AppDir --output /work/out/DLMS-Desktop-rebuild.AppImage \
  --tool /inputs/appimagetool-x86_64.AppImage --runtime /inputs/runtime-x86_64 \
  --inputs package_appimage/inputs.json
```

For library replacement, rebuild the matching shared Qt/PySide/native component
from the supplied sources, preserve notices and test ABI compatibility in a
**separate payload copy**. The bundled manager's `prepare-variant --help` explains
fresh owner-modified inventories without publisher keys. Never alter a running
payload or forge its inventory. For static AppImage libfuse replacement, follow
the supplied runtime Makefile, Dockerfile and build scripts, retained mount patch
and Alpine recipe commit. Relink the runtime with the modified library, create
new input hashes and rebuild using `--inputs` with that new matching JSON.
Checksums do not forbid library replacement or debugging modified libraries.
An older executable cannot undo incompatible schemas or later data writes.

## Reused validation and qualification

No application/dependency input changed during this preparation. Reused local
packaging verification: **63 passed** in
`tests/package/test_preview_materials.py`, `tests/distribution/test_materials.py`
and `tests/package/test_installation_manager.py`. Completed normal AppImage checks
on Fedora 44/COSMIC Wayland covered launch, moved filename/path, reopen with
quiz/Study/origin persistence, bundled PDF/PNG OCR, backup output, duplicate
exclusion and owned cleanup. The normal tar's manager/launcher/reopen passed in
synthetic homes on Fedora and Ubuntu 24.04 userspace. Synthetic Server
navigation/outage/isolation checks remain distinct from owner-operated servers.

Ubuntu checks used a container and Fedora kernel; **native Ubuntu and this exact
preview's native Omarchy acceptance remain pending**. Source/instrumented recovery
evidence is not a new native-button or physical-keyboard acceptance. Screen-reader,
physical printing, power-loss, real disk exhaustion and other-platform Desktop
qualification are not established. No full-parity or universal-Linux claim is made.
Windows/macOS public binaries remain deferred for their specific runtime/update,
upload-protection and native signing/qualification decisions.

Artwork update: current source restores the owner-identified AI-generated round blue
icon. See desktop_assets/ICON_PROVENANCE.md for established provenance, owner redistribution permission and unknown
generation details; the former geometric badge MIT statement must not be applied
to the restored image. Existing published artifacts and their notices are unchanged.

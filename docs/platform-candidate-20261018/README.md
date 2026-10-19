# Pinned Linux safety candidate and platform handoffs

Private review candidate `linux-330-safety-20261018`, application 3.3.0. No release asset, tag, merge or installation is performed by this preparation. Existing Preview1 remains unchanged. The bounded Fedora workflow audit is complete; this is compact build qualification, not a reopened audit.

- **Shared runtime:** `bfdffb720f743e9d720cd07292ec7e1ec325e059`.
- **Exact complete build source/documentation commit:** `4b50e2b3fb39dd478d355bf785b319805579076c` on `docs/workflow-recovery-audit-20261018`.
- [Draft documentation PR #21](https://github.com/drakahari/DLMS_next/pull/21): exact approved four-report patch `808aaf49aa0307eb29fe7efb794ecb5659a8330b48a9d93d94aeb3298b5db6b0`; push CI39170427754 and PR CI39170431062 passed. These runs execute non-browser tests; do not call them a fresh Firefox run.
- **Preparation branch:** `build/linux-safety-candidate-20261018`; record its exact fetched head. Its later additions are these handoff/build documents, manifests and unchanged copied synthetic fixtures only, and are not claimed as embedded build inputs.
- One Ubuntu24.04-compatible frozen payload, normal non-instrumented executable, two formats. Runtime, dependency pins, recovery contracts and host Fontconfig/GBM policy are unchanged. AppImage standalone storage remains separate from installed DLMS.

## Read and transfer

[Omarchy exact-artifact instructions](OMARCHY_HANDOFF.md) · [Windows build/adapter handoff](WINDOWS_HANDOFF.md) · [Mac native handoff](MACOS_HANDOFF.md) · [Fedora qualification](LINUX_QUALIFICATION.md) · [build recipe](BUILD.md) · [provenance](PROVENANCE.json).

The candidate binaries are not uploaded to Git or a release. Producer directory:
`/home/drak/Documents/dlms_desktop/.gate1/platform-freeze-20261018/artifacts/`.

Smallest Omarchy transfer: the exact AppImage plus SHA256SUMS into normal Downloads through the owner's existing file-transfer method. If SSH to this Fedora machine is already configured, run on Omarchy (replace `fedora` only with its already-known reachable SSH host; no SSH/network configuration is authorized):

```sh
set -eu
test ! -e "$HOME/Downloads/DLMS-Desktop-3.3.0-safety-20261018-linux-x86_64.AppImage"
scp drak@fedora:/home/drak/Documents/dlms_desktop/.gate1/platform-freeze-20261018/artifacts/DLMS-Desktop-3.3.0-safety-20261018-linux-x86_64.AppImage "$HOME/Downloads/"
printf '%s  %s\n' 'af46249a70520c2f5374419ccf7760aabee230887cc4eacaee2e02e74c12b9a5' "$HOME/Downloads/DLMS-Desktop-3.3.0-safety-20261018-linux-x86_64.AppImage" | sha256sum -c -
```

The supplied notice/source companions must remain available with any onward distribution. Four unchanged dependency companions retain Preview1 filenames and bytes; this does not imply they contain the old application source. The new application archive directly exports 4b50e2b and needs no historical overlay. No publisher signature or public-distribution approval is implied by checksums.

## Eight files

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `DLMS-Desktop-3.3.0-preview1-source-appimage-runtime.tar.zst` | 24526166 | `25b94c37be7bf97d085051976d3ad1f3720f9e9704320ae77eef30424caefb94` |
| `DLMS-Desktop-3.3.0-preview1-source-native.tar.zst` | 413729904 | `28e1043e31599a4611ee22f8492cbe84b9c2e42cfac2e1cc6d62e3fb8ac4fd46` |
| `DLMS-Desktop-3.3.0-preview1-source-python.tar.zst` | 100114172 | `40d78ccaad2cb0aadcca96f7f9cfeff06cba11e2de794ec45146954190b141f1` |
| `DLMS-Desktop-3.3.0-preview1-source-qt-pyside.tar` | 1037721600 | `2d5f30392243200188b7df70563ba9d40e9847d695c979f628e38543d9d6ff73` |
| `DLMS-Desktop-3.3.0-safety-20261018-linux-x86_64.AppImage` | 257432056 | `af46249a70520c2f5374419ccf7760aabee230887cc4eacaee2e02e74c12b9a5` |
| `DLMS-Desktop-3.3.0-safety-20261018-linux-x86_64.tar.zst` | 269137734 | `0268dd5ab14e173449e5a36dcb5bdd7e1cc809c0187abceacb67842e85792cb6` |
| `DLMS-Desktop-3.3.0-safety-20261018-notices.tar.zst` | 2004809 | `766f24c894d3dbf0805a797497edbe93a81de9b17bc74199b388e2a0fd28f87f` |
| `DLMS-Desktop-3.3.0-safety-20261018-source-application.tar.zst` | 51238884 | `59acf45f4be60a99a7c62b2ea04a6c6cbe4bda23b52badb34865a6012ec1ddc3` |

`SOURCE_MANIFEST.json` binds all 1,514 source files. `PAYLOAD_INVENTORY.json` and `APPIMAGE_INVENTORY.json` bind the actual final payload and extracted image. The AppImage removes the tar's installer entry point and adds standalone AppImage identity; code/assets otherwise match. `PROVENANCE.json` records their hashes, exact tooling and producer image. Manifests list shipped files only; no test profiles, exports, private logs, operational evidence or binaries are Git additions.

## Limits

Fedora44/COSMIC Wayland normal FUSE launch is tested. Ubuntu24 ABI inspection/build container is not native Ubuntu acceptance. Native Omarchy/Windows/Mac, physical keyboard/accessibility, actual printer/duplex, power loss, external Anki/provider and actual browser/profile selection for this exact candidate remain separately qualified. Existing portal/graphics warnings remain explicit. Mac's historical builder identity constants need a narrowly reviewed metadata adjustment before labeling a new Mac artifact. No paid signing, signing credentials or public release is included.

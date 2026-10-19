# Canonical DLMS icon — restored original round blue artwork

## Established facts

The owner identifies this original round blue DLMS artwork as **AI-generated**
and explicitly selected it as the canonical application icon for Linux, Windows
and macOS. It was recovered, not redrawn or recreated.

The exact retained master was already present at `static/favicon.ico` in accepted
source `5e5fa245ffb23617890d237c1d6c02a67ff093b1`. Despite its historical `.ico`
extension, it is a 1024×1024 RGB PNG. `dlms-icon-master.png` is an exact byte copy:

SHA-256 `be929c60a0a63373d698934930bac8af686d3a8242072e25954118f783b1af93`.

An older owner-selected 64×64 copy was also retained, SHA-256
`145e0e04e51fd62855e192c574b304f2142b01fc973cfa7531dbb288c05d4228`.
It visually corroborates the master; it is not upscaled to generate larger sizes.
No private operational file or private history is included in this provenance.

## Conversion and references

Run `python -m package_fedora.prepare_desktop_icons` with the existing pinned
Pillow dependency. The converter verifies the exact master SHA-256, converts to
RGBA and resizes using LANCZOS. It does not crop, recolor, remove the white
background, invent transparency, redraw letters or introduce new artwork.

- Qt window/application and Desktop AppImage root icon: `dlms-icon-master.png`.
- Linux hicolor: 16, 24, 32, 48, 64, 128, 256, 512 and 1024 pixels.
- Windows EXE and installer: `icons/windows/DLMSDesktop.ico`, with 16, 24, 32,
  48, 64, 128 and 256-pixel images.
- macOS bundle and test wrapper: `icons/macos/DLMSDesktop.icns`, through 1024
  pixels, including the ICNS scale entries produced by Pillow.
- `dlms_omarchy.png`: generated 64-pixel compatibility path used by the existing
  Linux installer; no claim of affiliation with Omarchy.
- Browser favicon: the stable `/static/favicon.ico` URL keeps the exact master.
  Browser-edition native Windows/AppImage/macOS packaging uses this same artwork.

The geometric replacement and its `dlms-badge.svg` generator are retired from the
active source. Historical commits and already built artifacts are unchanged.
Pixel-level format/frame tests check each conversion. They do not establish
native Explorer/Finder/Dock/taskbar acceptance or modify installed icons/caches.

## Attribution and unresolved rights information

The AI generator, model/service, creation date, prompt, account terms and any
specific generation license are **not known** from the retained files or the
owner's identification. No generator, creation record, copyright ownership or
third-party license is invented here. A statement that the removed geometric
replacement was independently drawn does not describe this restored artwork.

On 2026-10-19 the owner confirmed permission to use and redistribute the retained
image and resized derivatives: “Yes we made it together use it,” in response to
the question about redistribution permission, attribution and usage terms. This
permission covers the requested DLMS source and platform-package use. No
additional attribution or usage conditions were supplied.

The code/documentation MIT grant remains Copyright (c) 2026 Mike Buchanan.
The owner's artwork permission is recorded here separately; it is not an invented
MIT grant from an unknown generation service. The inventory identifier
`LicenseRef-DLMS-Owner-Authorized-Artwork` refers to this recorded permission,
not a standardized third-party license. Generator/service-specific terms and a
creation record remain unknown; no legal certification or ownership determination
is inferred. Third-party dependency notices remain unchanged.

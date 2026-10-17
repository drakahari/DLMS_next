# Original DLMS Desktop badge

Copyright (c) 2026 Mike Buchanan. Licensed under the [MIT License](../LICENSE).

Version 1 was authored for this project on 2026-10-17 by the coding assistant at
the owner's request. Its rounded blue square, cyan outline and four white block
letters are independently constructed from basic shapes and explicit letter
grids in `package_fedora/prepare_desktop_icons.py`. No external image, traced logo,
font file, icon library or image-generation service was used.

`dlms-badge.svg` records the editable vector geometry. The generator renders the
same design at high resolution and produces the compatibility-named
`dlms_omarchy.png`, five hicolor PNGs, Windows ICO and macOS ICNS. That historical
PNG filename is retained for existing source references; it no longer identifies
the earlier owner-selected artwork. There is no claim of affiliation with
Omarchy. Generate with `python -m package_fedora.prepare_desktop_icons` using the
declared Pillow dependency; no installed fonts or network are required.

The replaced input had SHA-256
`145e0e04e51fd62855e192c574b304f2142b01fc973cfa7531dbb288c05d4228`.
None of its image pixels are inputs to this generator. The new 64-pixel PNG has
SHA-256 `1ec18ded1259863148e89e3021a2defe185aaaeb1a68dc7d9747690467aa8315`.

All eight historical resource paths are replaced in the source snapshot. Old
private history/artifacts retain their historical artwork and evidence; they are
not part of this source export, and no installed application has been changed.
Container generation does not establish native taskbar/icon-theme acceptance.

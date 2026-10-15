# Manual color themes

DLMS offers 26 manual choices: the original five plus 21 additional Omarchy
palettes. Existing adapted Ethereal is the single Ethereal entry. Its colors,
fonts, spacing, and other presentation tokens remain unchanged.

## Source and maintenance

The source manifest is `dlms/theme_sources/omarchy-v4.0.4.json`. It maps all 22
upstream identifiers to DLMS IDs, with original palette fields, per-file SHA-256,
and immutable source URLs. The official release is
[v4.0.4](https://github.com/omacom/omarchy/releases/tag/v4.0.4), commit
`c668141e9c42b13c80c9ca4ea108e11708c5e8a5`.

Omarchy's MIT copyright and permission notice is retained in
`dlms/theme_sources/LICENSE.omarchy` (copyright David Heinemeier Hansson).
Only palette values are included. No wallpapers, previews, fonts, executable
theme configuration, runtime downloads, or Omarchy dependency are included.
The build manifest includes these local palette/notice resources; no package
was built for this change.

`dlms/themes.py` is the shared registry for CSS generation, normalization,
server validation, and both selectors. Selector groups are DLMS, Omarchy Light,
and Omarchy Dark. Display names may evolve; saved IDs must remain stable.
Changing a theme saves the existing scalar portal setting. Other open tabs use
the new colors after navigation/reload, rather than live synchronization.

## Web adaptations

Source values remain separate from derived tokens. `_web_palette` derives opaque
surfaces by blending source background/foreground at 3%, 5%, and 7%. Backgrounds
remain recognizable and are independent of uploaded wallpaper pixels.
Text is adjusted toward black/white in 1% steps only as needed: ordinary text
has a 7:1 token target, muted/link text 5.5:1, accent fill 4.5:1 against surfaces,
control boundaries 3:1, and selection text 7:1. Button text uses the better of
black/white. Focus and progress have explicit tokens.

Correct/incorrect/warning feedback uses separate green/red/amber semantic roles
and existing labels/icons, not the terminal's ANSI color names. This matters for
Hackerman, Lumon, Lupine, Matte Black, Last Horizon, Osaka Jade, Solitude, White,
and Vantablack. Neutral chrome stays recognizable in monochrome palettes; feedback,
feature icons and chart categories intentionally retain color. Category ordering
is stable and the storage chart retains its complete textual legend. Adjacent
chart colors are not guaranteed to have 3:1 contrast against each other.

Miasma and Rose Pine need substantial muted/accent contrast adjustment. All
new palettes are verified on DLMS surfaces rather than treating the terminal
foreground/background pair as sufficient. The table records source and derived
values; the registry contains the complete derivation and semantic state tokens.

| Upstream | DLMS ID | Mode | Source → web muted | Source → web accent |
|---|---|---|---|---|
| catppuccin-latte | `omarchy-catppuccin-latte` | light | `#acb0be` → `#585a61` | `#1e66f5` → `#1b5ddf` |
| catppuccin | `omarchy-catppuccin` | dark | `#585b70` → `#a1a3af` | `#89b4fa` → `#89b4fa` |
| ethereal | `ethereal` | dark | `#6d7db6` → `#c9b8a6` | `#7d82d9` → `#7d82d9` |
| everforest | `omarchy-everforest` | dark | `#475258` → `#b7bcbe` | `#7fbbb3` → `#7fbbb3` |
| flexoki-light | `omarchy-flexoki-light` | light | `#B7B5AC` → `#5d5c58` | `#205EA6` → `#205ea6` |
| gruvbox | `omarchy-gruvbox` | dark | `#665c54` → `#afaaa6` | `#7daea3` → `#7daea3` |
| hackerman | `omarchy-hackerman` | dark | `#2d3450` → `#9093a2` | `#82FB9C` → `#82fb9c` |
| kanagawa | `omarchy-kanagawa` | dark | `#54546D` → `#a3a3b0` | `#dcd7ba` → `#dcd7ba` |
| last-horizon | `omarchy-last-horizon` | dark | `#584e51` → `#999395` | `#b59790` → `#b59790` |
| lumon | `omarchy-lumon` | dark | `#304860` → `#9ea9b4` | `#8bc9eb` → `#8bc9eb` |
| lupine | `omarchy-lupine` | light | `#9e9e9e` → `#5d5d5d` | `#3264eb` → `#3060e2` |
| matte-black | `omarchy-matte-black` | dark | `#333333` → `#959595` | `#e68e0d` → `#e68e0d` |
| miasma | `omarchy-miasma` | dark | `#666666` → `#a5a5a5` | `#78824b` → `#90986b` |
| nord | `omarchy-nord` | dark | `#4c566a` → `#b9bdc5` | `#81a1c1` → `#93aeca` |
| osaka-jade | `omarchy-osaka-jade` | dark | `#53685B` → `#93a098` | `#509475` → `#59997c` |
| retro-82 | `omarchy-retro-82` | dark | `#2a6b78` → `#79a2aa` | `#faa968` → `#faa968` |
| ristretto | `omarchy-ristretto` | dark | `#72696a` → `#b0abac` | `#f38d70` → `#f38d70` |
| rose-pine | `omarchy-rose-pine` | light | `#cecacd` → `#5d5b5c` | `#56949f` → `#417079` |
| solitude | `omarchy-solitude` | dark | `#4b4e55` → `#95979b` | `#798186` → `#81898d` |
| tokyo-night | `omarchy-tokyo-night` | dark | `#414868` → `#989cad` | `#7aa2f7` → `#7aa2f7` |
| vantablack | `omarchy-vantablack` | dark | `#7a7a7a` → `#8d8d8d` | `#8d8d8d` → `#8d8d8d` |
| white | `omarchy-white` | light | `#808080` → `#5d5d5d` | `#6e6e6e` → `#6b6b6b` |

## Compatibility and acceptance limits

The five original dynamic CSS outputs are captured from HEAD
`36abbaa768b4c63dcd2a3029c461f9cddd9d0499` in
`tests/fixtures/theme_baseline.json` and must remain exact. Shared CSS retains
original fallback colors. New themes do not inherit Ethereal's font/spacing rules.
Missing or invalid stored IDs fall back to Purple & Gold without rewriting on
read. Invalid API/form submissions do not save. Failed atomic writes preserve
the previous saved file and expose a retryable error. Existing locks and CSRF
checks still protect both save paths. Older DLMS versions cannot select new IDs.

Existing and newly generated quiz pages that link `/static/style.css` receive
current colors through `/dynamic.css`; no regeneration is required. Arbitrary
older self-contained or imported HTML with embedded styles is outside this
compatibility guarantee. Printed output and embedded educational images retain
their existing behavior.

Automated token and rendered-state contrast checks, keyboard input, narrow
layouts, real Study/Exam workflows, and visual screenshot review provide bounded
evidence. They do not establish full WCAG conformance, browser-chrome zoom,
OS-specific native menu behavior, or contrast of arbitrary user images.

### Existing baseline findings (preserved)

The original Study/Exam selection buttons use blue/cyan gradients with white
text. The extended rendered check measures all gradient stop colors; some
original button pairs fall below 4.5:1. Their original colors are intentionally
preserved rather than changing an existing theme as part of this expansion.
The new themes use readable solid accent fills. Detailed baseline measurements
are produced alongside the review screenshots for each original theme.

## Required validation

Focused tests: `tests/test_manual_theme_registry.py`, `tests/test_theme_system.py`,
and the manual-theme matrix in `tests/browser/test_critical_workflows.py`.
The latter uses isolated seed pages generated before selection and a new mixed
question fixture generated after selection. Representative workflows also cover
multi-answer, matching, hotspot, saved Exam results, and recovery.

Final gates, with the project environment and isolated test roots:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider -m "not browser"
PYTHONDONTWRITEBYTECODE=1 DLMS_RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest -q -p no:cacheprovider -m browser tests/browser/test_critical_workflows.py
```

Review screenshots are test artifacts outside the repository. No running DLMS
server, production data root, or host theme is used for validation.

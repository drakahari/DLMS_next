# Appendix: Keyboard and Accessibility

DLMS is designed to remain usable with keyboard navigation, visible focus,
semantic form controls, responsive layouts, and its supported themes. This
appendix describes practical behavior in the current application. It does not
claim formal WCAG certification or complete compatibility with every browser,
screen reader, or assistive-technology combination.

## General keyboard navigation

Use **Tab** to move forward through interactive controls and **Shift+Tab** to
move backward. Native buttons, links, checkboxes, radio buttons, and selects use
their normal browser keyboard controls, including **Enter** or **Space** where
appropriate.

DLMS shows a high-visibility focus outline around keyboard-focused controls.
Do not confuse focus with selection: focus identifies the control that will
receive a keyboard action, while selected answers, active filters, and current
states are also expressed through text or control state.

At narrow widths, the main navigation becomes a menu. Opening it with the
keyboard moves focus into the navigation. Press **Escape** to close it and
return focus to the menu control.

## Forms, status, and validation

DLMS forms use visible labels or accessible names for their controls. Required
information and validation errors are expressed in text rather than color
alone. Error messages and important status changes use announcement regions so
supported screen readers can report them without forcing the user to search
the page.

When a form reports an error:

1. read the message for the specific requirement;
2. move back to the named field or question;
3. correct the value and submit again.

Confirmation dialogs are keyboard operable. Read their scope before accepting
a destructive data or maintenance action.

Tables use column headers, and dynamic controls such as Smart View and filter
buttons expose their selected state to assistive technology. Badges and notices
include text; their meaning does not depend only on color.

## Answering choice questions

A single-answer choice question presents one selection at a time. A
multi-select question allows more than one selected choice. The answer group is
named to indicate whether the user should select one answer or all correct
answers, and selected controls expose their pressed/selected state.

In Study Mode, correctness feedback is included in the accessible state or
label as well as in the visual styling. Continue with the ordinary answer and
navigation controls described in [Taking Quizzes](06-taking-quizzes.md).

## Matching questions

Matching supports two presentation styles:

- **Dropdowns** use ordinary select controls and are usually the simplest
  keyboard-first option.
- **Drag & Drop** also provides keyboard/touch selection: choose an answer chip,
  then choose its target. A pointer drag is not the only way to make a match.

If a drag-oriented layout is difficult with a particular assistive setup, use
the dropdown presentation when the quiz offers that choice.

## Hotspot answers

A playable hotspot image is keyboard focusable. Focus the image and press
**Enter** or **Space** to submit the defined keyboard answer point. DLMS sends
that action through the same hotspot scoring and answer-saving path as a
pointer answer.

Hotspot questions are inherently spatial. The keyboard action provides a
non-pointer way to answer, but understanding an image can still depend on the
description supplied by the quiz author. Authors should give the image and
question meaningful text and should not rely on color alone to identify the
target.

## Keyboard hotspot authoring

The Image Study hotspot editor provides a keyboard cursor on its region stage.
After focusing the stage:

| Key | Action |
| --- | --- |
| Arrow key | Move the authoring cursor by about 2% of the image dimension. |
| Shift+Arrow key | Move the cursor more precisely, by about 0.5%. |
| Enter or Space | Place the current point. For a circle, this places its center; for a polygon, it adds a polygon point. |

Use the visible **Undo Point**, **Clear** or **Clear Region**, **Test**, and
**Save** controls to complete the region. The image-preparation editor uses the
same keyboard cursor pattern for supported point placement. Exact controls vary
with the selected image activity, so follow the instructions displayed beside
the stage.

Keyboard authoring avoids a pointer-only interaction, but it still requires
spatial judgment. Zoom, meaningful source images, and the Test step can make
precise authoring easier. Full instructions are in
[Matching, Terminology, and Image-Based Content](11-matching-terminology-and-image-based-content.md#refine-images-and-clickable-regions).

## Themes, contrast, and high-contrast modes

DLMS provides four themes:

- Light;
- Dark;
- Purple & Gold;
- Maroon & Gold.

Shared semantic styles keep text, controls, focus outlines, badges, notices,
tables, and surfaces readable across these themes. Choose the theme that is
most comfortable in [Settings](16-settings-and-runtime.md#change-the-appearance).

The interface also supplies forced-colors/high-contrast adaptations for key
controls and hotspot states. Browser and operating-system high-contrast
behavior can differ, so confirm that the chosen browser exposes the focus and
selection states you rely on.

## Zoom, narrow windows, and motion

DLMS pages use responsive stacking and horizontally scrollable data regions
where a table cannot remain readable in a narrow content area. At high browser
zoom or a narrow window:

- open the collapsed navigation with its menu button;
- scroll a wide table within its table region rather than expecting every
  column to compress;
- allow cards and form controls to stack vertically;
- check for actions at the end of a scrollable row or panel.

The interface respects the browser's reduced-motion preference by reducing or
removing nonessential transitions and smooth scrolling.

## Screen-reader-oriented behavior

DLMS attempts to provide:

- structured page headings and labeled regions;
- explicit or accessible form names;
- named answer groups and exposed pressed/selected states;
- table header scope;
- expanded/collapsed state on disclosures and navigation;
- live announcements for important success, error, and status messages;
- text labels for states also shown through color or badges.

The quality of an imported quiz still matters. DLMS cannot create a useful
description for an image when the source or author supplies none, and OCR text
may need correction before it is understandable. Use **Review & Repair** and
the quiz editor to improve unclear material before studying it.

## Current limitations and practical alternatives

DLMS has received keyboard, theme, focus, high-contrast, and semantic hardening,
but it has not undergone formal accessibility certification. Manual use with
every screen-reader/browser pair has not been established.

The most important current limitations are spatial:

- interpreting a hotspot or diagram can require visual context even when the
  action is keyboard operable;
- drawing a precise circle, polygon, mask, or label remains easier with a
  pointer for many users;
- poorly described user-imported images can remain inaccessible until the quiz
  author improves the surrounding text.

For matching, prefer dropdowns when drag-style interaction is unsuitable. For
image questions, authors should provide meaningful question wording and, where
possible, an accessible description or equivalent textual context. If an
important workflow does not expose a usable keyboard path in a particular
environment, preserve the source data and report the exact screen, browser,
control, and assistive technology involved.

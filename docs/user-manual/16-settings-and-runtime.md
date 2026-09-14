# 16. Settings and Runtime

DLMS settings let you adapt the interface and a few optional workflows without
changing your quizzes or completed study activity. Open **Settings** from the
main navigation, then choose a category. Each category saves independently, so
saving an Appearance change does not silently replace your Parsing or External
AI preferences.

This chapter also explains the difference between normal local desktop use and
LAN/server use. That distinction affects who can reach DLMS and how the
application can be stopped.

## Choose a settings area

| Settings area | Use it to |
| --- | --- |
| **Appearance** | Choose a theme, change the Dashboard title, or use a background image. |
| **Navigation** | Show or hide optional subject-area links in the sidebar. |
| **AI Integration** | Configure optional External AI helper buttons, provider destinations, and prompt templates. |
| **Parsing** | Control optional confidence and text-cleanup tools used during quiz preparation. |
| **Application Lifecycle** | Allow an eligible local DLMS process to stop after all DLMS browser pages close. |
| **Backup & Restore** | Create a portable recovery snapshot or stage a validated restore. |
| **Reset & Remove** | Clear or reset a deliberately selected part of DLMS, or permanently remove its data. |
| **System Tools** | Run occasional page repair or open the advanced Image Study Editor. |

The last three areas can affect substantial amounts of data. Read
[Maintenance, Backup, and Data Management](17-maintenance-backup-and-data-management.md)
before using them.

## Change the appearance

Open **Settings → Appearance** to change presentation without changing study
content. DLMS provides four themes:

- Light;
- Dark;
- Purple & Gold; and
- Maroon & Gold.

The theme applies throughout DLMS. It changes colors and surfaces, not grades,
question behavior, or learning data. **Purple & Gold** is the default on a new
installation.

You can also change the title shown on the Dashboard. The title cannot be
blank. A custom background is optional; leaving the file chooser empty keeps
the current background. For a readable result, use a landscape JPG or PNG at
least 1600×900 pixels and preferably smaller than 3–4 MB.

Choose **Save Appearance** to apply all changes on that page. Other connected
browsers use the saved host settings when their pages refresh.

## Simplify the navigation

Open **Settings → Navigation** to show or hide these optional study areas:

- IT Study;
- Law Study;
- Medical Study; and
- Other Studies.

Hiding an area removes its link from the navigation. It does not delete or
disable the area's content, History, analytics, or direct page address. **Study
Packs** and **Settings** remain available, and showing an area again restores
its link.

This is useful when you want a less crowded sidebar. It is not a content-removal
tool.

## Configure optional External AI helpers

**Settings → AI Integration** controls how DLMS prepares and hands off selected
prompts to an external conversational AI. These settings do not add an AI
provider inside DLMS and do not store provider credentials.

The page lets you:

- show or hide AI explanation buttons while reviewing missed questions;
- automatically copy a prepared explanation prompt before opening a provider;
- choose ChatGPT, Claude, Gemini, or a Local / Custom URL destination;
- edit the missed-question explanation prompt;
- edit the general Study Pack prompt and its Medical safety addendum; and
- edit the Law Study prompt.

A custom destination must be a complete `http://` or `https://` address for an
external AI service. DLMS rejects an address that points back to its own local
pages. Choosing a provider merely controls the external destination that DLMS
opens; you still decide what material to paste or upload there.

The prompt-template reset buttons restore text in the form. Choose **Save AI
Settings** to keep those restored defaults. Keep each displayed placeholder in
a customized template if you still want DLMS to insert that information.

For the actual copy/paste and archive workflows, see
[External AI Workflows](12-external-ai-workflows.md).

## Configure text parsing tools

**Settings → Parsing** controls optional tools used when preparing pasted or
imported choice-question text. It does not rewrite quizzes you have already
published.

### Confidence Analysis

This option shows or hides the Confidence Analysis panel on the parsed-content
preview. It helps identify records that deserve closer review; it does not
guarantee that imported material is correct.

### Regex Strip / Replace Engine

This option makes regular-expression cleanup available before quiz parsing. It
is an advanced text-editing tool. Preview the result before parsing, especially
when a broad pattern could remove meaningful question or answer text.

### Invisible / BOM Cleanup

Automatic cleanup removes hidden characters such as byte-order marks and
zero-width spaces that can arrive through PDF or word-processor copy/paste.
These characters can otherwise interfere with question parsing.

### Show Invisible Characters

This optional diagnostic view makes hidden text characters visible during
preview. Use it when text looks normal but splits or parses unexpectedly.

## Understand how DLMS is running

The browser is DLMS's interface, but the DLMS application process runs on the
host computer. Opening or closing one browser page is therefore not the same as
starting or stopping the application.

### Local desktop mode

Normal DLMS use is loopback-only, usually at
`http://127.0.0.1:9001/`. Only the host computer can reach that address. A
packaged launch normally opens the default browser after DLMS is ready, though
automatic browser opening can be disabled or unavailable in a headless
session. If DLMS is running but no page opened, you can enter the local address
yourself.

Use **Shutdown DLMS** when you want to stop a local desktop instance
immediately.

### LAN/server mode

LAN/server mode is an explicit launch mode that binds DLMS to a non-loopback
network address. Other devices on the same reachable network can then open the
host computer's DLMS address and work with the same single-user server data.

DLMS does not provide account authentication or TLS for this mode. Use it only
on a trusted, appropriately firewalled local network. Do not expose the DLMS
port directly to the public internet.

In LAN/server mode:

- in-app and browser/API shutdown are unavailable;
- automatic browser-presence shutdown is unavailable;
- closing client browser windows does not stop DLMS; and
- the process or service must be stopped from the host computer—for example,
  from the terminal, service manager, or process manager that started it.

The runtime mode comes from how the host starts and binds DLMS, not from the
network address of an individual browser. A browser on the host computer does
not turn a LAN/server launch back into local desktop mode.

<!-- Screenshot: UM-25 — Settings overview and LAN/server lifecycle state -->

## Use browser-presence shutdown in local mode

**Settings → Application Lifecycle** provides an optional convenience for
eligible local desktop use. When enabled, open DLMS pages report that they are
present. After the last DLMS page closes, the local process may stop after a
grace period of about five minutes. Reopening a DLMS page during that grace
period cancels the pending automatic shutdown.

The feature checks whether any DLMS page remains open. It does not measure
typing, clicking, scrolling, inactivity, or quiz progress. It also does not
save an unfinished quiz; quiz recovery follows the browser-local behavior
described in [Taking Quizzes](06-taking-quizzes.md#resume-an-interrupted-quiz).

The control is disabled in LAN/server mode. A saved preference may still be
shown there, but it has no effect until DLMS is launched in eligible
loopback-only mode again.

## Know what is shared between browsers

Saved Settings are part of the DLMS data on the host. Another client connected
to the same LAN/server instance sees those settings after loading or refreshing
the relevant pages. A tab that is already open may need a refresh before a new
title, theme, or navigation choice appears.

Interrupted quiz checkpoints are different: a **This browser** Resume item
belongs to that browser profile. Two clients can therefore share the same
saved settings, Quiz Library, History, and completed learning activity while
showing different unfinished sessions. See
[History, Results, and Progress](09-history-results-and-progress.md#shared-history-and-local-recovery)
for the practical distinction.

## Return settings to their defaults

**Reset Application Settings** is under **Settings → Reset & Remove**, not on
the ordinary settings forms. It resets the complete saved portal configuration,
including appearance, navigation visibility, parsing options, External AI
settings, the browser-presence preference, and Quiz Library folder
configuration. It also removes the custom background.

It preserves quizzes, questions, completed History, Study Packs, Content Packs,
PDF & Image Import banks, Law Study content, and backup archives. Folder values
already assigned to quizzes remain with those quizzes, but empty custom-folder
definitions and hidden-folder settings are reset. DLMS creates a safety backup
before performing this reset.

Because its scope is broader than one settings page, use the narrow category
form when you only want to change one preference. The reset procedure and
other data-removal choices are covered in
[Maintenance, Backup, and Data Management](17-maintenance-backup-and-data-management.md#reset-application-settings).

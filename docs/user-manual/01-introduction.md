# 1. Introduction

DLMS is a local-first application for creating, organizing, studying, and
improving your own learning material. It brings quiz building, document import,
practice, testing, study history, targeted review, and portable content into one
desktop-style workspace.

The interface opens in a web browser, but DLMS is not a website hosted by a
third party. In normal use, the application runs on your computer and the
browser connects to that local process. Your quizzes, results, settings, and
other DLMS data stay in your user account's application-data directory unless
you deliberately export or share them.

This manual documents DLMS 3.2.2. It is written for people using the
application; native-build and release-engineering procedures remain in the
repository's maintainer documentation.

## What you can study with DLMS

At the center of DLMS is the **quiz**: a saved set of questions that you can use
in Study Mode or Exam Mode. A quiz may contain single-answer or multi-select
choices, matching activities, supporting images, or hotspot questions answered
by selecting a region of an image.

You can create this material directly or bring it in from several kinds of
sources. DLMS supports structured text, matching lists, selectable-text PDFs,
scanned pages, screenshots, images, reusable Study Packs, and structured
content returned by an external conversational AI. You do not need all of these
workflows to benefit from DLMS. A small manually created quiz or the sample text
file included with a packaged release is enough to begin.

Document extraction and optical character recognition (OCR) are not assumed to
be perfect. When imported material is incomplete or uncertain, **Review &
Repair** keeps that uncertainty visible so you can edit, exclude, reorder, and
confirm the material before publishing it. DLMS does not treat appearance,
guesswork, or an AI response as proof that an answer is correct.

## A local-first learning workspace

Normal **local desktop mode** binds DLMS to the loopback address on your own
computer. No DLMS account, hosted database, or cloud subscription is required.
The native application normally opens the local interface in your default
browser, and you can return to it at `http://127.0.0.1:9001/` while the DLMS
process is running.

DLMS can also be started deliberately in **LAN/server mode** so another device
on a trusted local network can reach the same installation. This remains a
single-user application: it does not add accounts, permissions, collaboration,
or device synchronization. LAN/server mode has no DLMS authentication or TLS,
so it is suitable only for a trusted, appropriately firewalled network and must
not be exposed directly to the public Internet.

Local-first does not remove the need to protect your computer and backups. A
person who can access your operating-system account, DLMS data directory, or an
unprotected LAN/server instance may be able to access your study material and
history.

## How the main parts work together

### Build, import, and organize

**Build Quiz** is the starting point for creating material. After publication,
ordinary quizzes appear in the **Quiz Library**, where you can find, edit, hide,
order, and organize them. Dynamic Smart Views help surface useful groups
without moving quizzes into new storage locations.

Reusable content can also live outside an ordinary quiz. A Question Bank or
Terminology Bank preserves reviewed PDF-derived material for repeated practice.
A **Study Pack** is an installed learner-facing collection that can generate
matching, quiz, image, or hotspot activities. The later content chapters explain
which source is appropriate for each task.

### Study, test, and decide what comes next

Choose **Study Mode** when you want immediate feedback as you answer. Choose
**Exam Mode** when you want a timed, test-like attempt and a saved result. Your
saved answers and attempts support History, Analytics, scheduling, and
**Learning Intelligence**.

Learning Intelligence looks across relevant quizzes to summarize concepts,
performance, recent evidence, Mastery, and Trend. It can help you identify a
weak area or launch focused practice. Generated practice keeps a relationship
to its source questions, so answering a review copy can contribute learning
evidence without turning that copy into a new independent source question.

When you are unsure what to study, begin with **Today’s Review** on the
Dashboard. It brings the most useful current actions into one short plan. More
specialized choices—including Adaptive Study, Smart Review, Concept Review,
Due Questions, Topic Retention Schedule, and missed-question review—remain
available when you want a particular kind of practice. Those workflows are
explained together later in the manual so their different purposes stay clear.

### Review outside DLMS and move your work safely

**Anki Tools** can turn selected quiz, missed-question, or Law Study material
into an `.apkg` deck, and DLMS can also prepare printable cards. Anki is a
separate application; exporting cards does not replace or remove the source
material in DLMS.

Different export formats serve different purposes. Portable Quiz Bundles move
selected ordinary quizzes without personal learning history. Study Packs and
Content Packs carry reusable study content. A full DLMS backup protects the
broader persistent workspace, including user-specific data that should not be
included in a quiz bundle. The portability and data-management chapters explain
these boundaries before you choose a format.

### Optional external AI assistance

DLMS can prepare a bounded prompt for an external conversational AI and accept
structured choice or matching content that you paste back into the application.
It also supports a separate prompt-and-ZIP workflow for AI-assisted Study Pack
creation and optional external explanation prompts in supported study screens.

These workflows are provider-neutral and optional. DLMS does not call an
AI-provider API, require an API key, or automatically trust returned material.
You choose whether to use an external provider, what to send to it, and whether
the reviewed result is suitable for your study.

## What DLMS is not

DLMS is intentionally designed for personal study. It is:

- not a cloud or software-as-a-service platform;
- not an enterprise, classroom, or multi-user learning-management system;
- not an account or collaboration service;
- not dependent on a direct AI-provider connection; and
- not a replacement for checking the accuracy and rights of material you
  import, scan, or receive from an external tool.

## How to use this manual

The first three chapters introduce the product, installation, and the common
interface. The task chapters that follow are organized around what you want to
do: create content, take quizzes, choose a review, interpret progress, work with
PDFs and OCR, manage packs, export material, protect data, or troubleshoot a
problem. Reference material and platform notes come last.

You do not need to read the manual from beginning to end. Read the next chapter
when installing DLMS, use the interface chapter to get oriented, and then move
to the chapter for the task in front of you. The in-application **Help Center**
also remains available for shorter, context-specific guidance.

## Where should I start?

If you are new to DLMS:

1. Follow [Installation and First Launch](02-installation-and-first-launch.md)
   for your operating system.
2. Use [Interface and Navigation](03-interface-and-navigation.md) to recognize
   the Dashboard, sidebar, and main destinations.
3. Import the included `sample_quiz.txt` or create a small quiz in **Build
   Quiz**.
4. Open that quiz in **Study Mode** and answer a few questions.
5. Return to the Dashboard. When you later have enough saved activity to make
   recommendations useful, use **Today’s Review** as the default answer to
   “What should I study right now?”
6. Create a backup before moving installations, performing a reset, or making a
   significant upgrade.

Start small. DLMS’s more advanced import, intelligence, scheduling, pack, and
portability tools can be introduced as your library and history grow.

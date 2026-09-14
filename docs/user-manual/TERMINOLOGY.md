# DLMS 3.2.0 terminology audit

This glossary records the vocabulary visible in the current application and the
terms the user manual should prefer. It is an audit, not a proposal to rename
the application. Where current labels differ, the manual should quote the label
the user must find and then explain it consistently.

## Core quiz and library terms

| Preferred term | Concise definition | Where users encounter it | Alternate or potentially confusing usage | Manual recommendation and related terms |
| --- | --- | --- | --- | --- |
| **Quiz** | A saved set of choice, matching, media, or hotspot questions that can be taken in Study or Exam Mode. | Dashboard, Quiz Library, builders, History, Study Packs. | “Assessment,” “practice,” and “session” sometimes describe how a quiz is used rather than a separate storage type. | Use *quiz* for the saved object and *attempt* or *session* for an individual use. |
| **Quiz Library** | The main collection and management screen for saved quizzes. | Primary navigation and Dashboard links. | The Dashboard’s recent items are not a second library. | Capitalize when naming the screen. Relate to Folder, Smart View, and Generated Practice. |
| **Source quiz** | An ordinary authored/imported quiz that supplies canonical questions for learning and generated practice. | Mostly implied by Library, review, composition, and duplicate behavior. | “Normal quiz” and “original quiz” appear in explanatory copy/tests. | Use *source quiz* only when contrasting it with generated practice; otherwise use *quiz*. |
| **Generated Practice** | A library view and badge category for generated Adaptive, Smart, Concept, Due Questions, and Topic Retention practice. | Quiz Library Smart Views and generated-quiz cards. | Mixed Quiz is generated content but is deliberately not grouped as transient Generated Practice. | Capitalize the Smart View; use lower case for the general idea. Explain that source questions and learning lineage are preserved. |
| **Mixed Quiz** | A new quiz composed from selected questions in multiple source quizzes. | Library Tools and Mixed Quiz Builder. | It is technically generated, but is a deliberate curated composition rather than transient review practice. | Keep visually and verbally distinct from Generated Practice and Adaptive/Smart review. |
| **Folder** | A user-created Quiz Library grouping with ordering and visibility controls. | Quiz Library. | Hidden folders affect normal display but search can still reveal matching quizzes. Smart Views do not move quizzes into folders. | Explain that folders are persistent organization; contrast with dynamic Smart Views. |
| **Smart View** | A derived Quiz Library filter based on current metadata or learning state. | Quiz Library. | It may look like a folder but does not store, move, or mutate quizzes. | Always call it a *Smart View* and explicitly contrast it with Folder. |
| **Needs Review** | A Smart View containing quizzes with source questions that are due or overdue. | Quiz Library Smart Views. | Could be confused with Review & Repair or low scores. | Qualify it as a schedule-derived Library view. Related: Due Questions. |
| **Recently Added** | A Smart View for quizzes with reliable creation times in the last 30 days. | Quiz Library Smart Views. | Not “recently studied.” | State the 30-day criterion and distinguish creation/import time from attempt time. |
| **Low Score** | A Smart View for quizzes whose latest completed attempt is below 75%. | Quiz Library Smart Views. | Not a mastery or weak-concept calculation. | State that it uses the latest completed attempt, not Learning Intelligence Mastery. |
| **Unfinished** | A Smart View for recoverable quiz checkpoints stored in the current browser. | Quiz Library and Today’s Review. | Can differ between devices using the same DLMS server. | Prefer “Unfinished in this browser” in explanatory prose. Related: Resume, recovery checkpoint. |
| **OCR Imported** | A Smart View for quizzes with explicit local OCR provenance. | Quiz Library Smart Views. | It is not based on filename guessing and does not include all PDF imports. | Explain that it reflects recorded OCR provenance. |
| **Portable Quiz Bundle** | A versioned ZIP that moves one or more ordinary quizzes, metadata, and supported media between DLMS installations without personal learning history. | Library Tools, Quiz Bundles export/import. | Not a backup and not a Study Pack. | Use the full term on first mention. Contrast with Backup and Study Pack. |
| **Duplicate Question Review** | An advisory scan for exact and strong possible duplicate source questions. | Library Tools, “Find Duplicates.” | A duplicate is not necessarily the same learning lineage; results do not merge or delete. | Describe findings as review candidates, especially “possible duplicate.” |

## Taking quizzes and learning evidence

| Preferred term | Concise definition | Where users encounter it | Alternate or potentially confusing usage | Manual recommendation and related terms |
| --- | --- | --- | --- | --- |
| **Study Mode** | An untimed learning mode that records responses and shows correctness, explanations, and supported teaching detail after each completed answer. | Quiz mode selection and quiz runtime. | “Practice” is sometimes used generically. | Use *Study Mode* for the named mode. Explain save acknowledgements and immediate feedback. |
| **Exam Mode** | A timed, test-like mode in which the user completes an attempt and submits it for a result. | Quiz mode selection and quiz runtime. | Timer duration is quiz-configurable; it is not a separate quiz type. | Use *Exam Mode*. Explain pause, navigation, submission, timeout, and result persistence. |
| **Attempt** | One completed or in-progress run through a quiz, especially an Exam Mode result recorded in History. | History, Analytics, results, recovery. | “Session” is used more broadly for Study Mode and generated practice. | Use *attempt* when referring to a scored/history record; use *study session* for an active learning run. |
| **Resume** | Continue a valid interrupted quiz checkpoint from the current browser. | Quiz recovery panel, Today’s Review, Unfinished Smart View. | Resume state is not server-synchronized. | Explain the browser-local boundary and that completed/safely saved sessions are cleared. |
| **Question Identity** | DLMS’s durable relationship between a source question and generated copies so learning evidence follows the source. | Primarily visible through coherent analytics/review behavior, not as a form field. | Internal names such as “Question Identity Contract v2,” UIDs, or canonical fingerprints should not appear in ordinary prose. | Explain the outcome only: generated practice counts toward the original source question; legacy content is handled conservatively. |
| **Concept** | A reusable topic label attached to a question and aggregated across quizzes. | Quiz editor, Learning Intelligence, Mixed Quiz filters, Concept Review. | “Topic” is used in retention language; tags and concepts are not always exposed identically. | Use *concept* for question metadata and cross-quiz analysis. Explain case-insensitive matching and consistent naming. |
| **Mastery** | An understandable 0–100 learning indicator combining overall accuracy, recent accuracy, amount of evidence, and recency. | Learning Intelligence topics and explanation dialog. | Not the same as raw accuracy or Trend, and limited evidence caps the displayed result. | Define in plain language first; put exact weights and thresholds in reference detail. |
| **Trend** | A direction—improving, declining, stable, or insufficient data—based on adjacent recent result windows. | Learning Intelligence concept tables. | It can differ from Mastery because it measures direction, not overall level. | Always contrast Trend with Mastery and note the minimum evidence requirement. |
| **Not enough data** | A Learning Intelligence state used when fewer than three responses support a concept. | Concept status and mastery guidance. | It does not mean zero knowledge or failure. | Say that DLMS avoids overstating mastery and caps low-evidence scores until more answers exist. |
| **Weak area** | A concept with enough evidence whose mastery or overall accuracy falls below the verified weak threshold. | Learning Intelligence and targeted review. | Not every low-evidence concept is weak. | Explain the evidence prerequisite and distinguish from Developing. |
| **Learning event** | A saved piece of question-level evidence, such as a Study Mode response, used by intelligence and scheduling. | Mostly an underlying behavior; surfaced through saves/history/intelligence. | This is more technical than users usually need. | Prefer *saved answer* or *learning evidence* in task prose; reserve *learning event* for troubleshooting/reference. |
| **History** | The screen and saved records for completed attempts, results, missed questions, and review. | Primary navigation. | Browser recovery is not History. | Capitalize the screen; distinguish durable server data from browser-local checkpoints. |
| **Analytics** | Aggregate attempt summaries such as average, best, latest, and per-quiz performance. | History/Analytics navigation. | Learning Intelligence is broader and question/concept based. | Contrast attempt statistics with Learning Intelligence. |

## Study and review terms

| Preferred term | Concise definition | Where users encounter it | Alternate or potentially confusing usage | Manual recommendation and related terms |
| --- | --- | --- | --- | --- |
| **Today’s Review** | The Dashboard’s concise daily action plan and recommended starting answer to “What should I study right now?” | Dashboard. | It composes existing recommendations; it is not another scoring engine. | Position it as the default entry point and explain its server-derived items plus browser-local resumes. |
| **Adaptive Study** | A deterministic mixed-source session balancing weak/developing concepts, misses, recent performance, review recency, and exposure. | Today’s Review and Learning Intelligence. | It overlaps in subject matter with several review paths but is the broad personalized option. | Say “use when you want DLMS to choose a balanced focus.” Avoid statistical claims. |
| **Smart Review** | A generated review made from source questions belonging to weak concepts. | Learning Intelligence review actions. | Sometimes described simply as weak-topic review. | Use when the user wants a broad weak-concept set; contrast with one-concept Concept Review. |
| **Concept Review** | A targeted generated session for one selected concept. | Learning Intelligence topic actions and Today’s Review. | “Review a weak concept” is an action label, not a separate engine. | Describe as the narrowest concept-specific path. |
| **Due Questions** | Question-level native scheduling and review based on each source question’s saved correctness history. | Today’s Review and Review Schedule. | Older/internal wording includes “native spaced review” or “Native Due Review.” | Use *Due Questions* exclusively in user prose. Contrast with Topic Retention Schedule. |
| **Topic Retention Schedule** | Concept-level retention timing based on concept mastery and evidence. | Review Schedule and Learning Intelligence links. | Older labels include “Spaced Review” and “Topic Retention / Spaced Review.” | Use *Topic Retention Schedule*; explain that it schedules concepts, not individual questions. |
| **Missed-question review** | Review or export of questions answered incorrectly in saved attempts/history. | History, Anki Tools, review links. | Can be confused with Smart Review, which is concept-based. | Use lower case unless quoting a screen control; say that it starts from actual misses. |
| **Review Schedule** | The screen showing Due Questions and concept-level Topic Retention timing, with controls to start sessions. | Learning Intelligence/navigation. | “Spaced Review” may be used for only the topic-level half. | Use the screen name, then name its two scheduling systems separately. |

## Content acquisition and repair terms

| Preferred term | Concise definition | Where users encounter it | Alternate or potentially confusing usage | Manual recommendation and related terms |
| --- | --- | --- | --- | --- |
| **Build Quiz** | The hub for manual creation and text, PDF/image, matching CSV, and external-AI workflows. | Primary navigation/Dashboard. | Individual builders have their own titles. | Capitalize the hub; describe each input path separately. |
| **Smart PDF** | DLMS’s structured selectable-text PDF analysis, classification, bank creation, and carefully bounded OCR assistance. | PDF & Image Import and Help. | It is not generic visual understanding of arbitrary textbooks. | Define its structural limits and lead into Review & Repair. |
| **OCR** | Local optical character recognition used for screenshots, scanned pages, and targeted raster-only regions. | PDF & Image Import, screenshot and matching workflows. | Selectable-text extraction is not OCR; OCR availability differs in source runs and packaged releases. | Expand on first use. State that OCR observations require review and never prove correctness by appearance alone. |
| **Review & Repair** | A staging workflow where extracted or AI-produced questions/pairs are edited, excluded, ordered, validated, and explicitly confirmed before publication. | Smart PDF, screenshot OCR, OCR matching, External AI, Content Pack import. | Several specialized review pages use the same concept but not identical controls. | Use the shared name, then describe workflow-specific controls and confirmation requirements. |
| **Question Bank** | A saved, reviewed source collection from which question practice quizzes can be generated by random, unused, sequential, range, or all selection. | PDF & Image Import bank pages. | It is not the same as Quiz Library. | Call it *Question Bank* and explain that generated quizzes are separate derived practice. |
| **Terminology Bank** | A saved, reviewed collection of terms/definitions used to generate matching or choice practice. | PDF & Image Import bank pages. | “Glossary bank” appears conceptually; matching datasets in Study Packs are separate sources. | Prefer *Terminology Bank*. Relate to matching and Review & Repair. |
| **Matching** | A question/activity that pairs left/right values, commonly terms and definitions, with configurable direction and optional round size. | Builders, quizzes, banks, Study Packs, External AI/OCR workflows. | “Terminology” describes the common content, not a different question schema. | Use *matching* for the activity and *term/definition pair* for content. |
| **Hotspot** | An image question answered by selecting a defined circle or polygon region. | Image Study builder/editor and quiz runtime. | “Clickable Region” is an authoring-mode label. | Use *hotspot question* for the result; explain pointer and keyboard methods. |
| **Image Prep** | A non-destructive image-study editing mode for masks and labels while retaining the source image. | Image Study Editor. | It is not a general-purpose photo editor. | Quote the UI label; explain original preservation and saved derivative behavior. |
| **External AI** | A provider-neutral prompt/copy/paste workflow using a conversational AI outside DLMS. | External AI Builder, Settings, Study/Law helpers. | It includes structured text workflows and a separate ZIP-producing Study Pack workflow. DLMS does not call an AI API. | Always state the external boundary and that returned material is untrusted until reviewed. |

## Packs, decks, configuration, and runtime

| Preferred term | Concise definition | Where users encounter it | Alternate or potentially confusing usage | Manual recommendation and related terms |
| --- | --- | --- | --- | --- |
| **Study Pack** | An installed, learner-facing collection of matching, image/hotspot, or quiz material used to generate study activities. | Study Packs catalog and IT/Medical/Other subject spaces. | Sometimes users may call the ZIP itself a pack; management occurs under Content Packs. | Use *Study Pack* for the learner-facing catalog/content. Contrast with Content Pack. |
| **Content Pack** | The managed, validated package installed, inspected, exported, or deleted through content management. | Content Packs screens and import review. | The installed content appears to learners as Study Packs. | Use *Content Pack* for lifecycle/administration and *Study Pack* for study use. |
| **Deck** | A collection of cards prepared for Anki export or printing. | Anki Tools and custom deck builder. | A quiz is not a deck, although quiz questions can supply cards. | Use *deck* only for the Anki/flashcard output. |
| **Anki Tools** | DLMS screens for exporting quiz, missed-question, custom, or Law cards as Anki packages and printable cards. | Navigation and Study Mode selection/export actions. | Two legacy tab-separated export endpoints remain for compatibility, but no current guided Anki Tools, quiz runtime, History Review, or Help control links to them. | Present `.apkg` and printable cards as the ordinary workflows and explain that Anki is an external application. Mention TSV only in an Advanced/Legacy Compatibility note if needed. |
| **Backup** | A portable snapshot of persistent DLMS data and settings intended for recovery or transfer. | Settings → Backup & Restore. | It is broader than a Portable Quiz Bundle and excludes transient staging/cache data. | Explain scope, safe external storage, and difference from exports. |
| **Restore** | A staged, validated replacement of persistent data from a DLMS backup, preceded by a safety backup. | Settings → Backup & Restore. | Not the same as importing a quiz/pack. | Describe review, confirmation, post-restore reload, and recovery clearing. |
| **Rebuild All Quiz Pages** | An occasional maintenance/recovery action that regenerates derived playable HTML/JSON from canonical quiz data. | Settings → System Tools and Help. | It is not a required post-update step and is not a data migration. | Use the exact name. Explicitly list the data it does not change and when to use it. |
| **Local desktop mode** | The normal loopback-only runtime at `127.0.0.1`, usually opened in a browser by the packaged application. | Launch behavior, lifecycle settings, shutdown guidance. | The UI is browser-based but DLMS is not a cloud service. | Explain local browser UI, data location, explicit Shutdown, and optional browser-presence shutdown. |
| **LAN/server mode** | Explicit non-loopback binding that makes DLMS reachable on a trusted local network. Runtime mode comes from the configured bind, not a requesting client’s address. | Launch/configuration guidance and disabled Shutdown UI. | Browser/API shutdown and automatic browser-presence shutdown are unavailable; closing client windows does not stop the server. It also has no DLMS authentication or TLS and must not be exposed to the Internet. | Use *LAN/server mode*. Tell users to stop the process/service from the host computer and explain the trusted/firewalled-network limitation prominently. |
| **This browser** | A label indicating that an unfinished checkpoint exists only in the current browser profile/device. | Today’s Review, Unfinished Smart View, recovery UI. | Server-derived recommendations remain shared after refresh. | Preserve this phrase and explain why clients of one server may show different Resume cards. |
| **Shutdown DLMS** | The immediate in-application stop action available in local loopback mode. | Navigation/footer/runtime UI. | Closing the last browser may also stop eligible local runs after a grace period. In LAN/server mode, in-app/API and automatic browser-presence shutdown are unavailable, and closing client windows does not stop DLMS. | State mode-specific behavior. In LAN/server mode, say “stop the DLMS process or service from the host computer”; avoid the ambiguous standalone phrase “manual shutdown.” |

## Inconsistencies the manual must handle

- Existing Help and lifecycle copy does not consistently distinguish a
  host-system stop from the disabled in-app shutdown action in LAN/server mode.
  Current runtime enforcement is authoritative: the manual should explicitly
  direct users to stop the process/service from the host computer; see the
  findings in [FEATURE_INVENTORY.md](FEATURE_INVENTORY.md).
- “Spaced Review” survives in some implementation and historical language for
  the concept-level workflow now presented as **Topic Retention Schedule**.
  **Due Questions** is the question-level native scheduler.
- “Generated quiz,” “review quiz,” and “practice session” overlap. The manual
  should use **Generated Practice** for the Library category, preserve **Mixed
  Quiz** as its own curated type, and use the precise workflow name elsewhere.
- “Study Pack” and “Content Pack” describe two views of related packaged
  content, not interchangeable screens.
- The Law landing page previews standalone IRAC Practice, Socratic Prep, Rule
  Flashcards, and Case Compare as future modes. Saved Case Reviews already
  contain editable IRAC and Socratic work plus rule material and Law Anki
  export, but no separate standalone modes exist and Case Compare is not
  implemented. The manual should document the embedded workflow without
  presenting preview cards as available features or calling rule material a
  native interactive flashcard mode.

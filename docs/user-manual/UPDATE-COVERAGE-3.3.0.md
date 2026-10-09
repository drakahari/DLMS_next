# 3.3.0 documentation coverage and refresh

## Revision and comparison boundary

This refresh documents `develop/3.3.0` at
`57d536f9bb20f91e8b275555e8bbfad6f0d6e83d`. The checkout was clean before
this documentation task. The owner identifies this as the accepted Ubuntu
24.04 application-package revision; this refresh does not establish native
Windows/macOS acceptance or public release.

The last substantial manual batch was September 14: architecture/drafting
`b0d2d28`, broad editorial work `37561ce`, 27 screenshot captures `b9f3174`,
and integration `8df0664`. September 17 commits `dc87736` and `0f9446c` made
smaller corrections across many chapters. Later changes updated individual
Help topics and marked-question/theme guidance, not the full manual.
The chosen comparison is **`8df0664..57d536f9`**, including those follow-up
corrections. The older feature inventory and UM-01–UM-27 capture manifest
remain dated historical evidence; they are not current behavior specifications.

Canonical sources are the Markdown chapters and task guides in this directory.
In-app Help is `static/help*.html`, registered in `dlms/routes/help.py`.
The root README and package `release_assets/README.txt` are short entry points.
There is no configured canonical manual PDF/export build; the optional future
pipeline in the manual README is a proposal, not an existing output gate.

## Change-to-documentation checklist

**Corrected** means existing guidance changed. **New** means a new section or
task guide. **Verified existing** means its procedure was checked against current
source without rewriting it merely to increase the changed-file count.

| User-facing change | Documentation coverage | Status | Application evidence |
| --- | --- | --- | --- |
| Focus desk dashboard: Study next, Continue studying, Your activity, quiet tools, Results overview | Chapters 3, 7, 9; Getting Started Help | Corrected; current dashboard image | `templates/dashboard/index.html`, `static/daily-review.js`, `static/dashboard-activity.js` |
| More review options beside a plan; request errors distinct from empty eligibility | Chapters 3, 7; Exam Plans guide | Corrected | `static/daily-review.js`, `dlms/services/daily_review.py` |
| Last regular quiz and same-folder sequence; distinct browser Resume identities | Chapters 3, 6; dashboard Help image | Corrected | `dlms/services/dashboard_activity.py`, `static/quiz-recovery.js`, dashboard sequence Firefox check |
| Durable Study sessions, first outcomes/corrections/observable assistance, explicit Finish Review | Chapter 6; Study History in chapter 9; Quizzes Help | Corrected | `dlms/services/study_sessions.py`, `static/script.js`, `static/script.js` |
| Pending saves, takeover/revision checks, expired-token recovery and older self-contained pages | Chapters 6, 18; keyboard/privacy appendices | Corrected | `static/script.js`, `static/nav-normalize.js`, `dlms/rendering/quiz_artifacts.py`, CSRF/recovery browser checks |
| Hotspot keyboard positioning and explicit submission | Chapter 6; keyboard appendix | Corrected | `static/script.js`, hotspot keyboard Firefox check |
| Separate Study/Exam History, compact disclosures, independent legacy pagination, local instants/undated records | Chapter 9; History & Analytics Help | Corrected; current row/expanded images | `dlms/routes/history.py`, `templates/study/history.html`, `static/local-time.js` |
| First-response difficulty and Learning Intelligence reset boundary; Learning Profile action controls | Chapters 7–8, 17; Learning Intelligence Help | Corrected | `dlms/services/learning.py`, `dlms/services/learning.py`, `static/learning-profile.html` |
| Optional Exam Plans, exact flat folders and Learning Scope, live material changes, study days/calendar, daily targets and honest shortfalls | New Exam Plans guide; chapter 8 links; Learning Intelligence Help | New + verified existing Help; current setup image | `dlms/services/exam_plans.py`, `dlms/routes/exam_plans.py`, `templates/learning/exam_plans.html` |
| Show/hide/pause/replace plan; stale controls and generation recovery | Exam Plans guide | New | Exam Plan save/control/publish services and setup Firefox check |
| Durable Mark for review; current/all selection, independent Anki/focused practice, supported types and legacy adoption | Chapters 6, 14; Anki Help | Verified existing + clarified type reference | `dlms/routes/review_marks.py`, `dlms/services/review_marks.py`, `static/review-marks.js` |
| Shared icon controls, keyboard tooltips/disclosures and Help enlargement | Keyboard appendix; refreshed screenshots | Corrected | `static/action-controls.js`, `static/action-controls.css`, `static/help-navigation.js` |
| 26 manual themes, adapted Ethereal, registry grouping, Appearance/sidebar persistence and older HTML limitation | Chapters 3, 16; root/package README; Settings Help | Corrected; registry-rendered Help retained | `dlms/themes.py`, `static/nav-normalize.js`, `templates/help/_theme-reference.html` |
| Unified Layout & navigation; independent preferences, scoped immediate restores; all-hidden Settings access | Chapters 3, 16; Settings Help | Corrected; current controls retained/refreshed | `dlms/routes/settings.py`, `templates/settings/dashboard.html` |
| Earned/expired/non-expiring achievements, any issuer, badge/certificate roles, edit versus renewal | New Certifications and Training guide; Getting Started and Certifications Help | New + verified existing Help; current form/detail images | `dlms/services/certifications.py`, `dlms/routes/certifications.py`, `templates/certifications/` |
| Exact Hours/Minutes, reusable library, selected multiple links, separate estimate/submitted/accepted credit, annual/cycle goals | Certifications and Training guide; privacy/reference appendices | New; current library/form/selection images | `dlms/services/certification_tracking.py`, `dlms/services/certifications.py`, guided nine-credential Firefox check |
| Three independent dates and explicit legacy classification, no invented policy verification | Certifications and Training guide; Certifications Help | New + verified existing Help; current date image | `dlms/services/certification_dates.py`, schema-10 migration and date Firefox checks |
| Optional editable presets, LPIC certification versus membership distinction, manual directional renewal relationships | Certifications and Training guide; Certifications Help | New + verified existing Help | `dlms/services/certification_presets.py`, certification rules/relationship services |
| Certification feature switch, dashboard-only preference, All/custom count and saved sort | Chapters 3, 16; Certifications guide/Help | Corrected/new; current Settings image | `dlms/routes/settings.py`, settings layout form, certification display route |
| Shared Study-style Copy & open AI, exact edited preview, selected-context privacy and LAN/clipboard/manual fallback | Chapter 12; Certifications guide/Help; privacy appendix | New + verified existing Help; current AI selection image | `static/script.js`, `static/certifications.js`, certification prompt builders |
| Library Smart Views, generated-practice grouping/source summaries, folder order/hide and duplicates | Chapter 5 | Verified existing; dashboard label corrected | Quiz Library template/services and `templates/quiz/library.html` |
| Smart PDF/OCR/structured AI, matching/image content, compact Content Pack management | Chapters 4, 10–13 | Verified existing; historical screenshots labeled by manifest | Import/authoring/pack routes and current Help topics |
| Portable Quiz Bundles distinct from full-profile backups | Chapters 15, 17; privacy/reference appendices | Verified existing + backup scope corrected | `dlms/services/portable_quiz_bundles.py`, `dlms/services/backups.py` |
| Backup/restore includes all persistent feature data; schema-10 compatibility/rollback; replaces rather than merges | Chapter 17; Maintenance and Learning Intelligence Help | Corrected | `dlms/services/backups.py`, `dlms/services/restore.py`, persistence schema checks |
| Reject unexpected executable SQLite schema before writes; safe staging and recovery limits | Chapter 17 administrator notes; Maintenance Help | New | `dlms/persistence/schema_programs.py`, database startup/staged restore |
| Collision-safe backups under same-second/concurrent creation, hard-link requirement and safe failure | Chapter 17 administrator notes; Maintenance Help | New | `dlms/services/backups.py` exclusive hard-link publication |
| All eight Reset & Remove scopes, six safety-backed resets, two exceptions, recovery clearing and permanent-removal limits | Chapter 17; Maintenance Help | Corrected/new | `templates/settings/reset-remove.html`, `app.py` maintenance handlers, `dlms/services/restore.py` |
| LAN single-user/privacy boundary, profile-path isolation and release/platform limits | Introduction, maintenance administrator section, platform/privacy appendices, root/package README | Corrected/verified existing | `dlms/runtime.py`, `dlms/runtime.py`, current release documentation |
| Reduced-round matching Exam save compatibility and dependency/security remediation | Existing Exam workflow remains unchanged; maintenance trust-boundary notes cover user consequence | Verified existing procedure; no new learner control | matching Exam regression, audit remediation record; dependency changes do not create UI workflows |

## Validation and limitations

Documentation validation checks local Markdown destinations/anchors, Help topic
links and anchors, image paths/alt text/dimensions, all reset scopes, current theme
reference and safety-sensitive restore wording. Focused Firefox captures exercise
real controls with disposable data, not illustrative mockups or owner records.
Screenshots and the exact checks/results are recorded in the refresh manifest
and task completion report. External issuer/provider policy pages are references,
not an assertion that DLMS approves a credential or verifies eligibility.

This refresh changes documentation, Help content, image assets and related tests
only. It does not change runtime behavior, user records or settings. Focused
checks are not a new whole-app audit, full release qualification, native Windows
or macOS acceptance, or an accessibility conformance claim.

### Portable quiz export follow-up (2026-10-09)

Chapter 15 and Taking Quizzes Help now cover lossless repeated-choice text,
filtered selection across pages, retained failure selections, collection
splitting/inventory, extract-then-import instructions, resource limits and older
importer restrictions. UM-06 gains an actual sample-profile export-selection
capture; the existing ordinary import-preview image remains applicable.

### Preservation-first portable transfer / schema 11 candidate

Manual 15 and Taking Quizzes Help explain format-2 receiver requirements, ordered separate choices, transferable Needs review content, complete grouped preflight, selection retention and explicit editor correction. Manual 17 and the portable preservation contract explain schema-11 compatibility and pre-upgrade-backup rollback. Selection/preflight screenshots use disposable samples. The accepted schema-10 package remains a pre-change artifact.

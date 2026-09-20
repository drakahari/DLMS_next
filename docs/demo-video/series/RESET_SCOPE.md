# Reset and clear controls: DLMS-139 narration audit

Source of truth: `dlms/services/restore.py`, maintenance/history routes,
`templates/settings/reset-remove.html`, `static/quiz-recovery.js`,
`static/daily-review.js`, and manual chapter 17. This is a documentation audit,
not a change to reset behavior. Captures show real controls without executing
destructive resets. Existing isolated application tests exercise their effects.

| User action | Removed/reset | Kept | Confirmation / backup |
|---|---|---|---|
| Clear Saved Results | Attempts, attempt answers, missed-question history | Quizzes including Generated Practice, learning events, settings, source content | Browser confirmation; no automatic backup |
| Reset Learning Intelligence | `learning_events`; derived mastery, recommendations, diagnostics and schedules | Quizzes including Generated Practice, attempts/answers/missed history, concepts, settings, sources | Confirmation and pre-reset backup |
| Reset Quiz Library & Results | Quizzes/questions/choices, Generated Practice, concepts, learning events, attempts/answers/missed history, generated pages/assets/logos and quiz registry | Packs, PDF banks/drafts, Law, settings, backup ZIPs | Confirmation and pre-reset backup; performing browser recovery cleared |
| Clear Imported / Source Content | Unprotected packs, PDF/image source banks, drafts and import staging | Published quizzes and their snapshotted dependencies, protected packs, attempts, learning evidence, settings, Law, backups | Confirmation and pre-reset backup |
| Reset Application Settings | Portal configuration and custom background; includes AI, parsing, navigation, lifecycle, empty folder definitions, hidden folders and Learning Scope exclusions | Quizzes and populated folder assignments, Generated Practice, attempts, learning evidence/schedules, packs, banks, Law, backups | Confirmation and pre-reset backup |
| Reset DLMS to Fresh State | All active runtime content/database/settings including Generated Practice, learning evidence and Law | Existing backups plus safety backup; executable/source installation | Confirmation and pre-reset backup; empty runtime recreated, performing browser recovery cleared |
| Remove DLMS Data From This Computer | Entire owned data root, including backups; schedules shutdown | Executable/source installation | Exact `REMOVE DLMS DATA` phrase plus browser confirmation; **no safety backup** |
| Dashboard Clear Saved Resume Point | This browser's checkpoint and unfinished answers only there | Quiz, completed history, scores, persisted learning evidence, settings, sources | Explicit dialog; no backup; guarded against pending submission |
| Quiz recovery Start Over | Saved recovery state; restarts current quiz session | Previously persisted attempts/evidence and quiz | Direct control, not a global reset; no safety backup |
| Finish Review | Ends the active generated-study session, clears owned recovery checkpoint after successful save | Generated quiz, recorded evidence and completion record | Explicit action; not deletion |
| Rebuild All Quiz Pages | Regenerates derived HTML/JSON from canonical quiz records | Identity, questions/answers, organization, lineage and history; failed rebuild retains old files | Confirmation; inspect rebuilt/failed report; no reset-style backup |

## Other exposed clearing controls

These were checked separately so a form action is not narrated as data deletion:

- AI settings: four prompt reset buttons replace current form values. Save AI
  Settings persists them. They do not reset other settings, quizzes or history.
- Library/Smart View/duplicate-review/search filter resets restore a view.
  Mixed-builder and Anki clear-selection controls deselect entries, not sources.
- Quiz matching clear-match removes a current placement; it does not erase
  learning events already saved. A new attempt is not a history reset.
- Image builder Clear Region resets current geometry; removing a question/choice
  edits the draft. Start Over starts a new builder workflow, not a global wipe.
- Image editor Undo Point/Clear Shape and Undo Last Edit/Clear Image Edits affect
  editable geometry/overlays. Save Region/Save Image Prep persists the source
  change; the original image and historical learning evidence remain.
- PDF and External AI Review & Repair delete/reorder/clear controls edit staged
  records. Cancel/Start Over discards the relevant staged workflow, not the
  existing published Library. Leaving an unsaved upload is not a promise that
  every temporary file is immediately purged.
- Content Pack and Portable Bundle import cancellation removes the selected
  staging area; canceling a restore discards its stage, not active user data.
- Law Cancel Workflow clears the pending workflow session, keeping saved raw
  imports and case reviews. Individual import/case deletion is separate.
- Individual quiz, folder, bank, pack and case removal are content-management
  operations, not additional global reset modes. Use their own confirmations
  and the relevant manual chapters; an export/backup is prudent beforehand.

There is no dedicated global “clear Generated Practice history” operation to
invent. Generated Practice entries are quizzes; clearing a browser resume point
does not delete them. A library reset removes them along with other quizzes.
The legacy `/wipe_database` alias maps to the quiz-library reset; no current
user-facing control calls the old `resetDatabase()` JavaScript helper.

Copy important backups outside the data root before permanent removal. Restore
is also a separate destructive replacement workflow with validation, preview,
confirmation and a pre-restore safety backup; it is covered in the approved
`portability-and-backup` video rather than repeated here.

# 6. Taking Quizzes

DLMS uses the same quiz experience for ordinary Library quizzes and most
generated practice. When you open a quiz, choose the mode that matches your
goal:

- choose **Study Mode** to learn at your own pace with immediate feedback; or
- choose **Exam Mode** for a timed, test-like attempt with results after
  submission.

Both modes use the quiz's saved questions, but they record and present your
work differently.

## Open a quiz

You can launch a quiz from the Quiz Library, Dashboard, a Study Pack or bank,
or a review action. An ordinary Library card uses **Open Quiz**. The quiz first
shows its title and a **Select Mode** panel with Study Mode and Exam Mode.

After you choose a mode, the question area shows the current question number,
the total number of questions, and a progress bar. **Previous Question** and
**Next Question** move through the set. Previous is unavailable on the first
question, and Next is hidden on the final question. Return links remain
available for the Dashboard and Quiz Library.

If the current browser already has a valid interrupted checkpoint for that
quiz, DLMS presents recovery choices before you start a new session. See
[Resume an interrupted quiz](#resume-an-interrupted-quiz) below.

## Answer the supported question types

### Single-answer choice

Select the one answer you believe is correct. In Study Mode, selecting an
answer saves learning evidence and shows immediate feedback. You can choose
another answer to try again. In Exam Mode, the selection is retained without
showing whether it is correct before submission.

### Multi-select choice

Select every answer you believe is correct. Select an answer again to remove
it. The question behaves as multi-select because its author marked multiple
answers correct; there is no separate mode switch while taking it.

Study Mode tells you to keep going until you have selected the complete correct
set and identifies an incorrect selection without revealing an unchosen answer
as if you had selected it. Exam Mode records the selected set and grades the
complete set at submission.

### Matching

Matching questions pair each left-hand item with one answer from the answer
pool. The default **Drag & Drop** view supports several interaction methods:

- drag an answer chip into its target with a mouse;
- select an answer and then select its target on touch or with the keyboard;
  or
- choose **Dropdowns** to use a select-list interface.

Use the clear control beside a placed match when you want to change it. Both
interaction modes use the same answers and grading. Some matching quizzes show
only a configured subset of a larger bank or reverse the matching direction;
the instructions and presented labels define the current attempt.

### Images and hotspots

A choice or matching question can include a supporting image above its answer
controls. A **hotspot question** instead asks you to select a particular region
of the image. Point to the requested structure and activate the image. Keyboard
users can focus the image and use Enter or Space through the supported hotspot
control.

In Study Mode, hotspot feedback reports whether the selected region is correct
and can show available explanation or source-verification detail. In Exam Mode,
the location is retained for final grading without immediate correctness.

## Use Study Mode for guided learning

Study Mode is untimed. The timer, pause control, and Submit Exam action are not
part of this mode.

For a choice question, selecting an answer immediately distinguishes a correct
or incorrect response without relying only on color. A fully correct response
can also show the saved explanation and a safe source link when those details
exist. Matching and hotspot questions provide their corresponding per-item or
location feedback.

Use Previous and Next to revisit the set. Your last selection for each question
is kept in the current session. A question is considered complete for recovery
purposes only when it has a sufficient response: one selection for a
single-answer question, the expected number of selections for a multi-select
question, every required matching target filled, or a hotspot location chosen.

### Saving Study Mode progress

Study Mode sends answer activity to DLMS as question-level learning evidence.
That evidence can later support concept intelligence, scheduling, and
recommendations. You do not need to manage a separate save file.

If a response cannot be saved, the quiz remains usable and displays **Learning
progress was not saved** with a **Retry** action. DLMS retains the unsaved
response in the browser checkpoint rather than declaring the session safely
complete. Retry while the DLMS process or server is reachable.

Once every question has a complete response and all pending response saves are
acknowledged, DLMS clears the completed recovery checkpoint. Merely arriving at
the final question does not count as completion.

### Optional learning actions

Supported choice questions in Study Mode can offer **Review This Question with
AI** and **Mark for Anki**. The first prepares context for an external provider;
DLMS does not call an AI API. The second adds the current question to a
temporary session selection, with an `.apkg` export action available at the end
when questions are marked. The External AI and Anki chapters explain these
optional workflows.

<!-- Screenshot: UM-07 — Study Mode feedback after an incorrect response -->

## Use Exam Mode for a test-like attempt

Exam Mode uses the quiz's configured timer. Older or otherwise unconfigured
quizzes fall back to the standard 90-minute duration. The remaining time is
shown in the quiz toolbar.

Answer questions and move backward or forward as needed. DLMS does not show
correctness, explanations, or Study Mode learning aids during the attempt. Use
**Pause** when you need to stop the countdown temporarily; the paused overlay
keeps the exam covered until you choose **Resume**.

Choose **Submit Exam** when you are finished. Manual submission asks for
confirmation. If time reaches zero, DLMS submits automatically. Unanswered or
incorrect items do not receive credit.

After scoring, DLMS saves one completed attempt before it treats the Exam Mode
checkpoint as finished. The results panel shows the score and percentage and
offers **Review This Attempt**, **View Full History**, **Retake Exam**, and
**Return to Dashboard**.

If the final attempt cannot be persisted, the result explicitly says it was
not saved and offers **Retry Saving Attempt**. The exact pending attempt remains
recoverable; DLMS does not clear it merely because a score appeared on screen.

<!-- Screenshot: UM-08 — Exam Mode timer, navigation, and submission -->

## Resume an interrupted quiz

DLMS keeps bounded recovery checkpoints for interrupted Study Mode and Exam
Mode sessions in the current browser profile. Reopening that quiz can show
**Continue your saved quiz?** with the saved mode, question position, and time.

- **Resume** restores the valid checkpoint and continues the session.
- **Start Over** clears that browser's checkpoint and begins without the saved
  progress.
- **Finish Saving Submitted Attempt** can appear when an Exam Mode attempt was
  already submitted but its final save still needs confirmation.

The Dashboard and the Library's **Unfinished** Smart View can also surface a
Resume action marked **This browser**. That label is important: an interrupted
checkpoint belongs to the browser profile where it was created, not to every
device connected to the same DLMS server.

DLMS validates a checkpoint against the current playable quiz. A checkpoint
that has expired, is malformed, or no longer matches an edited quiz is not
silently applied to incompatible content.

Finishing every Study Mode response and saving all of its learning activity
clears that completed checkpoint. Exam Mode clears its checkpoint only after
the final attempt is successfully persisted. If you leave on an unanswered
final question or a save fails, recovery remains available.

<!-- Screenshot: UM-09 — Interrupted quiz recovery panel -->

## Understand shared and browser-local state

This distinction matters most when two computers use the same DLMS LAN/server
installation.

| Shared from the DLMS host after refresh | Local to one browser profile |
| --- | --- |
| Completed Exam Mode attempts and History | Interrupted Study or Exam checkpoint |
| Successfully saved Study Mode learning activity | **This browser** Resume action |
| Due Questions counts and scheduling state | Current question position and unsaved recovery details |
| Learning Intelligence and other persisted recommendations | Recovery state from a different browser or device |

Two clients can therefore show different unfinished quizzes while correctly
showing the same server-derived due count after refresh. Completing a quiz on
one client updates successfully persisted learning state for the other client;
it does not copy or clear an unrelated interrupted checkpoint in that other
browser.

If you use several browser profiles on the same computer, treat them as
separate clients for recovery purposes.

## Review results and choose the next step

Exam Mode results lead directly to the saved attempt, while **History** lets you
find prior attempts by quiz and review missed-question details. Depending on
question type, Review can preserve your selected answer, the correct choice or
pairs, an explanation, or hotspot feedback.

Saved Study Mode answers and completed attempts also contribute to broader
progress and recommendation features. The next chapters explain how to use
Today’s Review, missed-question review, Due Questions, Topic Retention
Schedule, and Learning Intelligence without confusing their different roles.
When you are simply deciding what to study now, return to the Dashboard and
start with **Today’s Review**.

## If a quiz does not proceed normally

First check the question type: multi-select answers toggle on and off, matching
requires every presented target, and **Dropdowns** provides an alternative to
drag and drop. If DLMS reports an unsaved Study response or Exam attempt, keep
the page open and use the displayed **Retry** or **Finish Saving Submitted
Attempt** action. The recovery checkpoint remains until the save is safe.

For browser-specific Resume questions, stale-looking completed state, and
other symptoms, use the focused guidance in
[Troubleshooting](18-troubleshooting.md#quiz-resume-and-history-problems).

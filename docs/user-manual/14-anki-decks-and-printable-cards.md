# 14. Anki, Decks, and Printable Cards

DLMS can turn selected study material into simple front-and-back cards for use
outside its quiz interface. The normal guided outputs are an Anki `.apkg`
package or a browser-printable card layout.

Anki is a separate application. DLMS creates the package locally, but importing,
scheduling, synchronizing, and studying that deck happen in Anki. Exporting a
deck does not remove questions from DLMS or replace DLMS History, Due Questions,
or Learning Intelligence.

## Choose a card workflow

| What you want | Start with |
| --- | --- |
| A whole quiz as text front/back cards | **Anki Tools → Quiz → Anki** |
| Questions missed across completed attempts | **Anki Tools → Missed Questions → Anki** |
| A hand-picked mix of quiz, history, and Law cards | **Anki Tools → Custom Deck & Printable Cards** |
| Questions marked while studying one quiz | **Mark for Anki** in Study Mode |
| Misses from one completed attempt | The attempt's Review page |
| Rule cards from saved Law Case Reviews | **Anki Tools → Law Study Anki** |
| Physical 3 × 5 cards | **Custom Deck & Printable Cards** |

Anki exports are text front/back cards. They work best for choice questions and
recognized Law rule cards. A matching activity is not automatically expanded
into one Anki card per term/definition pair, and image or hotspot interaction is
not embedded in the current card model. Preview cards before exporting,
especially when the source quiz contains matching or image-based questions.

## Export one quiz to Anki

Open **Anki Tools** and use **Quiz → Anki** when you want one card for each
question in an existing quiz.

1. Select the **Source Quiz** and choose **Preview Cards**.
2. Check the card fronts and backs. For a choice question, the front contains
   the question and choices; the back contains the marked correct answer or
   answers.
3. Select the quiz under **Quiz to Export** and choose **Export .apkg**.
4. Save the downloaded file, then import it in Anki.

The preview shows at most the first 20 cards, but the exported deck contains
all cards in the selected quiz. DLMS names the Anki deck from the quiz title
and adds a DLMS suffix.

## Export missed questions

Use **Missed Questions → Anki** to create a deck from recorded mistakes across
completed attempts. You can filter the source before previewing or exporting:

- **Quiz** selects one quiz or all quizzes.
- **Minimum Times Missed** accepts a value from 1 to 100.
- **All Missed Questions** includes every distinct recorded miss that matches
  the other filters.
- **Currently Weak** includes a missed question whose quiz has not been
  completed again after its latest recorded miss.
- **Repeatedly Missed** requires at least two recorded misses.
- **Recovered Later** means the same quiz was completed again after the latest
  miss; it does not by itself claim that every answer in that later attempt was
  correct.
- **Missed Once** includes questions with exactly one recorded miss.

Preview the result, then choose **Export .apkg**. Each back includes the correct
answer plus the number of recorded misses and the current DLMS status used by
this export view. A question can belong to overlapping summaries—for example,
it can be both Repeatedly Missed and Currently Weak.

The attempt-specific Review page can also export the missed questions captured
for that one completed attempt. Use that route when the attempt itself defines
the deck you want; use the Anki Tools filters when you want a history-wide
selection. See
[History, Results, and Progress](09-history-results-and-progress.md#understand-missed-question-review)
for the attempt workflow.

## Mark questions during Study Mode

When **Mark for Anki** is available in Study Mode, use it to collect supported
questions from the current session:

1. choose **Mark for Anki** on each question you want to keep;
2. continue to the final question; and
3. choose the **Export Selected to Anki** action when it appears; the label
   shows how many questions you selected.

The selection belongs to that quiz session and is retained with its browser
recovery checkpoint if the session is interrupted. It is not a permanent deck
list until you export it. Exam Mode does not present this immediate study aid.

## Build a custom deck

Open **Anki Tools → Custom Deck & Printable Cards** when you want precise card
selection across several sources.

1. Enter a **Deck Name**. It may contain up to 120 characters.
2. Under **Select Quiz Questions**, filter or expand quizzes and select the
   individual questions you want.
3. Under **Select Missed / Weak Questions**, select individual history-derived
   cards. Their quiz, miss count, and current status provide context.
4. Under **Select Law Flashcards**, choose recognized cards from saved Case
   Reviews when available.
5. Check the live selected-card count and choose **Preview Deck**.
6. After reviewing the first cards, choose **Export .apkg**.

The custom output is one flat Anki deck; DLMS does not create nested subdecks
from its source groups. If the same front and back are selected through more
than one source—for example as both a quiz card and a history card—DLMS keeps
one copy in the custom deck. The preview shows the first 20 cards, while export
includes the complete deduplicated selection.

<!-- Screenshot: UM-24 — Custom deck selection and printable-card preview -->

## Export Law Study cards

Law Study Anki uses recognized **Rule Flashcards** sections from saved Case
Reviews. It does not turn every case paragraph or note into a card.

Open **Anki Tools → Law Study Anki**, then choose either:

- **Selected Cases**, where you can select one or several saved cases; or
- **Entire Course**, where DLMS combines recognized cards for the chosen
  course.

Preview the cards before choosing **Export .apkg**. The case title is added to
each card front so that combined exports retain useful context. A saved Case
Review with no recognized front/back rule cards cannot produce a Law deck.

Law rule cards can also be selected individually in the Custom Deck workspace
and included in printable output. They remain exports of material embedded in
saved Case Reviews, not a separate native Law flashcard study mode.

## Print physical cards

The printable workflow uses the same source selections as a custom deck.

1. Open **Custom Deck & Printable Cards** and select the desired quiz,
   missed-question, and/or Law cards.
2. Enter the deck name.
3. Under **Avery 5388 · 3 × 5 Index Cards**, select **Long edge — same card
   order** or **Short edge — reverse back order** to match the printer's duplex
   behavior.
4. Choose **Open Avery Print Layout**.
5. In the new view, choose **Print Cards** and use the corresponding duplex
   setting in the system print dialog.

The layout places three 3 × 5 cards on each US Letter sheet and alternates each
front sheet with its matching back sheet. Long-edge mode keeps back cards in
the same order; short-edge mode reverses the back order.

Print one duplex test sheet before using expensive card stock or printing a
large batch. Very long card content is compacted to fit, but an unusually dense
card may still be harder to read. Shorten the source content or use the Anki
deck when the printable result is too crowded.

## Import the `.apkg` file into Anki

After the download completes, open Anki and use its package-import command to
select the `.apkg` file. The exact wording can vary with the installed Anki
version. DLMS supplies a simple front/back note model; further styling,
scheduling, synchronization, and deck management are controlled by Anki.

Keep the downloaded file if you need to import it on another device, subject to
the privacy and licensing requirements of its source material. The package can
contain question text, answer choices, correct answers, miss-count/status text,
or Law rule content, depending on the workflow used. It does not contain your
full DLMS quiz library, attempt database, or backup state.

## Advanced: legacy TSV compatibility

DLMS retains legacy tab-separated Anki export endpoints for compatibility.
They are not part of the current guided Anki Tools, quiz runtime, History
Review, or Help workflow. Most users should export an `.apkg` deck or use
printable cards instead.

The legacy TSV format is not a substitute for a Portable Quiz Bundle or DLMS
backup and is not documented as a normal manual procedure.

## Troubleshoot card exports

### No preview cards appear

Check that the selected source contains text that can form a front/back card.
For missed exports, loosen the quiz, status, or minimum-miss filters. For Law
exports, choose a saved Case Review with a recognized Rule Flashcards section.

### The preview is not useful for a matching or image question

The current Anki card model is text based and does not convert matching pairs
or hotspot interaction into their own rich card types. Exclude that source from
the deck or choose a more suitable text question. Continue using the original
DLMS quiz for its interactive behavior.

### The export includes more cards than the preview

This is expected when the selection exceeds 20 cards. Preview is intentionally
limited; the downloaded `.apkg` contains all cards that matched the filters or
all cards you selected.

### The printed fronts and backs do not align

Confirm that the print dialog uses US Letter paper, the intended duplex edge,
and no unexpected scaling. Switch between long-edge and short-edge order if
your printer turns the back side differently. Always verify one test sheet.

# 8. Learning Intelligence

**Learning Intelligence** helps you look beyond the score from one quiz. It
combines recorded answer evidence by concept so you can see which topics are
well supported, which need attention, and where more practice is needed before
DLMS can draw a useful conclusion.

Use this area when you want to answer questions such as:

- Which concepts appear across my quizzes?
- How accurate have I been overall and lately?
- Is my recent performance improving, declining, or roughly stable?
- Is there enough evidence to call a concept weak or strong?
- Which concept should I study next?

Learning Intelligence is a guide for choosing study work. Its indicators are
not course grades, diagnoses, or permanent judgments about what you know.

## Understand the Learning Intelligence area

The Learning Intelligence navigation contains several related views:

- **Topic Intelligence** shows the cross-quiz concept table, Mastery, Trend,
  weak areas, and concept-focused Practice actions.
- **Learning Profile** summarizes average topic performance, strongest and
  weakest topics, activity, retention, and a useful next action.
- **Review Schedule** contains the question-level Due Questions queue and the
  concept-level Topic Retention Schedule.
- **Diagnostics** surfaces repeated answer-choice confusions and question
  patterns that may deserve review.

These views use the same saved learning evidence for different purposes. For a
day-to-day recommendation, continue to start with Today’s Review as described
in [Study and Review](07-study-and-review.md). Use Learning Intelligence when
you want to understand the evidence behind a topic or select a more specific
follow-up.

## How concepts connect activity across quizzes

A **concept** is a reusable topic label attached to a question. When questions
in several source quizzes use the same concept, Learning Intelligence combines
their evidence into one concept row. Concept matching is case-insensitive while
DLMS preserves a readable name for display.

For example, questions in an introductory quiz and a practice assessment can
both contribute to the same `file ownership` concept. This lets the concept row
describe performance across the relevant material rather than presenting one
isolated score per quiz.

Questions without concept metadata still work normally and contribute to
their applicable question-level history and scheduling. They simply cannot be
included in a concept-level row until a concept connects them to one.

Generated practice keeps its relationship to the original source question.
When you answer a generated Adaptive, Smart, Concept, Due Questions, or Topic
Retention copy, DLMS credits the source question and its concept instead of
inflating the source-question or source-quiz counts. New independently authored
source questions remain separate even when their wording happens to match.
Older compatible material continues to contribute conservatively.

## Read the concept table

<!-- Screenshot: UM-12 — Learning Intelligence -->

The Topic Intelligence page begins with summary cards for topics with evidence,
average accuracy, average Mastery, and weak areas. The concept table then gives
more detail for each topic.

| Column or indicator | What it means |
| --- | --- |
| **Concept** | The display name of the shared topic. |
| **Coverage** | How many source questions and source quizzes carry that concept. Generated copies do not enlarge this count. |
| **Results** | Counted responses, distinct questions answered, correct and incorrect totals, and the Exam-attempt and Study-session sources of that evidence. |
| **Overall accuracy** | The percentage of all counted responses for the concept that were correct. |
| **Recent accuracy** | Accuracy across up to the five latest counted responses. |
| **Trend** | Whether two recent evidence windows show improvement, decline, or roughly stable performance. |
| **Mastery** | A 0–100 study signal combining performance, evidence, and recency. |
| **Status** | **Not enough data**, **Weak area**, **Developing**, **Proficient**, or **Strong** under the current evidence rules. |
| **Practice** | **Study concept** creates Concept Review for that selected topic when source questions are available. |

Study Mode can record more than one interaction while you work through a
question. To keep repeated clicks from overpowering other evidence, DLMS counts
the latest saved response for that question in a Study session. A completed
Exam contributes one response per question for that attempt.

Use the filters to view all concepts or focus on Weak Areas, Developing,
Proficient, Strong, or Not Enough Data. Search narrows the visible topic list.
When concepts exist but none has recorded answers yet, the page preserves them
and offers a way to view the tagged concepts without pretending that
performance data exists.

## Understand Mastery

Mastery is a 0–100 summary for one concept. It is designed to help prioritize
study, not to replace the underlying response counts and accuracy values. A
Mastery value can change as you answer more questions or as older practice
becomes less recent.

The **How mastery works** dialog explains that the score combines four things:

| Factor | Weight | Plain-language meaning |
| --- | ---: | --- |
| **Overall performance** | 55% | How many of all counted answers for this concept were correct. |
| **Recent performance** | 20% | Accuracy across up to the five most recent counted answers. |
| **Evidence** | 15% | How much response evidence supports the score. Full evidence credit is reached at eight responses. |
| **Recency** | 10% | More recent practice receives more credit than older practice. |

The percentages are visible in DLMS because the model is intended to be
understandable. They do not mean that the score is precise to the decimal in a
learning-science sense. Read Mastery alongside evidence, overall accuracy,
recent accuracy, and Trend.

### Why small samples are limited

**Not enough data** means the concept has fewer than three counted responses.
DLMS can show a provisional Mastery value, but it does not label the concept
weak, developing, proficient, or strong yet.

DLMS also caps provisional scores to avoid false confidence from a tiny sample:

- one or two responses cannot produce Mastery above 59;
- three or four responses cannot produce Mastery above 74; and
- five or more responses can use the full calculated range.

A concept becomes a **Weak area** only after it has at least three counted
responses and either Mastery or overall accuracy is below 60. With sufficient
evidence, Mastery below 75 is **Developing**, below 90 is **Proficient**, and 90
or above is **Strong**.

These thresholds make the status understandable, but the surrounding details
still matter. A concept with two correct answers is not “weak”; it is simply
too lightly tested for a reliable status.

### How recency affects Mastery

The recency portion gives full credit to activity within the last seven days,
then gradually gives less credit as the last evidence becomes older. Because
recency accounts for only part of Mastery, an older strong history does not
vanish; it becomes one reason to consider refreshing the topic.

The Topic Retention Schedule adds a separate retained-mastery estimate after a
topic becomes due. That estimate is for review timing and does not rewrite the
base Mastery, response history, or accuracy shown here.

## Compare recent and overall accuracy

**Overall accuracy** uses every counted response for the concept. **Recent
accuracy** uses up to the five latest counted responses. Looking at both helps
you notice a change that an all-time average may hide.

For example:

- stronger recent accuracy than overall accuracy can suggest that newer work
  is going better than the longer history;
- weaker recent accuracy can reveal a current difficulty even when older
  results keep the overall figure high; and
- very few responses should be treated as preliminary, even if both displayed
  percentages happen to be high or low.

These are ways to read the indicators, not guarantees about future results.

## Understand Trend

**Trend** describes direction; **Mastery** summarizes the current evidence.
They can disagree without either being wrong. A concept can have modest
Mastery but an Improving trend, or strong historical Mastery with a Declining
recent trend.

Trend needs at least six counted responses. DLMS compares two adjacent recent
windows of equal size—three to five responses in each window, depending on how
much evidence exists. A change of at least 15 percentage points is shown as
**Improving** or **Declining**. A smaller change is **Roughly stable**. Before
six responses, the table shows that more data is needed.

The table includes the size of the windows and the change in points so you can
see what supports the label. Do not interpret Roughly stable as “mastered”; it
only means the two recent windows did not differ enough to receive a direction.

## Launch Concept Review with Study concept

Choose **Study concept** in a concept row when you deliberately want to
practice that topic. DLMS gathers applicable source questions across relevant
quizzes and creates a Concept Review session of up to 20 available questions.

This is the same concept-focused workflow described in
[Study and Review](07-study-and-review.md). The resulting quiz appears as
Generated Practice in the Quiz Library, while its answers continue to support
the source concept’s evidence.

The Practice column can say **No source questions** when a concept record has
evidence or metadata but no currently usable source question. Learning
Intelligence does not invent material to fill that gap.

## Use the Learning Profile for a summary

Open **Learning Profile** when you want a compact overview instead of the full
concept table. It summarizes:

- average accuracy and average Mastery for topics with enough evidence;
- current weak areas and the number of quizzes with recorded learning
  activity;
- strongest and weakest topics;
- saved Study answers, Exam answers, completed attempts, and latest activity;
- topic-retention counts; and
- a next useful action based on the available evidence.

If weak areas exist, the primary action can start Smart Review. If no weak area
qualifies but concept-level review is due, it can start a Topic Retention
session. With little evidence, the profile explains what kind of activity is
needed instead of assigning unsupported strengths or weaknesses.

## Use Diagnostics as a review prompt

<!-- Screenshot: UM-13 — Learning Diagnostics -->

**Diagnostics** looks for two kinds of patterns:

- **Repeated answer confusions** identify an incorrect choice that has been
  selected repeatedly in place of a correct choice.
- **Question review signals** identify response patterns that may make a
  question worth inspecting, such as a high miss rate or a distractor pattern.

These findings are advisory. A difficult question can be useful and correct;
a signal does not automatically change, delete, or condemn it. Use the filters,
search, and expandable details to inspect what supports each signal.

Choice-confusion analysis applies only where answer choices make sense.
Matching and hotspot responses are not forced into that model. General
question-quality classification also waits for enough evidence rather than
judging a question from one or two responses.

## Interpret common combinations

| What you see | A reasonable next step |
| --- | --- |
| Low Mastery with enough evidence | Inspect overall and recent accuracy, then consider Smart Review or Study concept. |
| Recent accuracy below a stronger overall result | Practice the concept again and watch whether newer evidence changes the direction. |
| Declining Trend | Review the recent window and consider targeted practice even if historical Mastery remains high. |
| Not enough data | Answer more tagged questions; do not treat the provisional value as a verdict. |
| Strong Mastery and stable recent results | Maintain the topic through normal review rather than assuming it can never fade. |
| A Diagnostics signal | Inspect the response pattern and source question before deciding whether the issue is knowledge, wording, or distractor quality. |

## Know the limits of the evidence

Learning Intelligence can use only activity that DLMS successfully records.
Creating or importing a quiz does not by itself prove knowledge and therefore
does not create performance evidence. A concept needs both consistent metadata
and answered questions before its metrics become useful.

An interrupted browser checkpoint is also not completed learning history. A
Study answer contributes only after its save succeeds, and an Exam contributes
its completed responses only after the attempt is persisted. On a shared LAN
installation, that saved server data is visible to other clients after refresh;
the browser-local Resume checkpoint is not.

Use [History, Results, and Progress](09-history-results-and-progress.md) to
inspect saved Exam attempts. History answers “what happened on that Exam?”;
Learning Intelligence answers “what patterns are appearing across concepts and
recorded activity?”

"""Learning intelligence, diagnostics, and adaptive review domain services."""

import json
import math
import re
from datetime import datetime, timedelta, timezone


_GENERATED_REVIEW_SOURCE_PREFIXES = (
    "smart_review_",
    "spaced_review_",
    "concept_review_",
    "adaptive_study_",
    "mixed_quiz_",
)
_GENERATED_REVIEW_TITLE_PREFIXES = (
    "smart review —",
    "spaced review —",
    "concept review —",
    "adaptive study —",
)


def _parse_learning_datetime(value):
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_generated_review_source(source_file, title=""):
    source = str(source_file or "").strip().casefold()
    normalized_title = str(title or "").strip().casefold()
    return (
        source.startswith(_GENERATED_REVIEW_SOURCE_PREFIXES)
        or normalized_title.startswith(_GENERATED_REVIEW_TITLE_PREFIXES)
    )


def _deduplicated_learning_answer_events(cur):
    """Return the canonical Study/Exam evidence rows used by learning analytics."""
    rows = cur.execute("""
        SELECT id, event_type, quiz_id, question_id, attempt_id, session_id,
               mode, was_correct, response_json, occurred_at
        FROM learning_events
        WHERE event_type IN ('study_answer', 'exam_answer')
          AND question_id IS NOT NULL
          AND was_correct IS NOT NULL
        ORDER BY occurred_at ASC, id ASC
    """).fetchall()
    deduplicated = {}
    for row in rows:
        if row["event_type"] == "exam_answer":
            scope = row["attempt_id"] or f"exam-event-{row['id']}"
        else:
            scope = row["session_id"] or f"study-event-{row['id']}"
        key = (row["event_type"], scope, row["question_id"])
        deduplicated[key] = row
    return sorted(
        deduplicated.values(),
        key=lambda row: (str(row["occurred_at"] or ""), int(row["id"])),
    )


def _normalize_concept_names(value):
    """Return stable, de-duplicated concept names from CSV/list input."""
    if isinstance(value, str):
        raw = re.split(r"[,;\n]+", value)
    elif isinstance(value, (list, tuple, set)):
        raw = list(value)
    else:
        raw = []
    out = []
    seen = set()
    for item in raw:
        name = re.sub(r"\s+", " ", str(item or "")).strip()[:120]
        key = name.casefold()
        if not name or key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out[:24]


def _question_concepts(cur, question_id):
    rows = cur.execute("""
        SELECT c.name
        FROM concepts c
        JOIN question_concepts qc ON qc.concept_id = c.id
        WHERE qc.question_id = ?
        ORDER BY c.name COLLATE NOCASE
    """, (question_id,)).fetchall()
    return [r[0] for r in rows]


def _concept_performance_trend(
    events, *, minimum_window=3, maximum_window=5, threshold_points=15.0
):
    """Compare adjacent recent evidence windows without over-reading small samples."""
    if len(events) < minimum_window * 2:
        return {
            "trend": "insufficient",
            "trend_label": "More data needed",
            "trend_delta": None,
            "trend_window_size": 0,
            "previous_accuracy": None,
        }

    window_size = min(maximum_window, len(events) // 2)
    previous = events[-(window_size * 2):-window_size]
    current = events[-window_size:]

    def accuracy(rows):
        correct = sum(1 for row in rows if int(row["was_correct"] or 0) == 1)
        return round((correct / len(rows)) * 100, 1)

    previous_accuracy = accuracy(previous)
    current_accuracy = accuracy(current)
    delta = round(current_accuracy - previous_accuracy, 1)
    if delta >= threshold_points:
        trend = "improving"
        label = "Improving"
    elif delta <= -threshold_points:
        trend = "declining"
        label = "Declining"
    else:
        trend = "stable"
        label = "Roughly stable"
    return {
        "trend": trend,
        "trend_label": label,
        "trend_delta": delta,
        "trend_window_size": window_size,
        "previous_accuracy": previous_accuracy,
    }


def _learning_intelligence_topics(cur, now=None):
    """Build explainable concept-level learning metrics for DLMS-008/009/010.

    Study responses are de-duplicated to the latest response for a question in a
    study session. Exam responses are de-duplicated to one response per
    question/attempt. This prevents multi-click Study Mode interactions from
    overpowering completed exam evidence.
    """
    now = now or datetime.now(timezone.utc)
    concept_rows = cur.execute("""
        SELECT c.id, c.name,
               COUNT(DISTINCT CASE
                   WHEN z.id IS NOT NULL
                    AND LOWER(COALESCE(z.source_file, '')) NOT LIKE 'smart_review_%'
                    AND LOWER(COALESCE(z.source_file, '')) NOT LIKE 'spaced_review_%'
                    AND LOWER(COALESCE(z.source_file, '')) NOT LIKE 'concept_review_%'
                    AND LOWER(COALESCE(z.source_file, '')) NOT LIKE 'adaptive_study_%'
                    AND LOWER(COALESCE(z.source_file, '')) NOT LIKE 'mixed_quiz_%'
                    AND LOWER(COALESCE(z.title, '')) NOT LIKE 'smart review —%'
                    AND LOWER(COALESCE(z.title, '')) NOT LIKE 'spaced review —%'
                    AND LOWER(COALESCE(z.title, '')) NOT LIKE 'concept review —%'
                    AND LOWER(COALESCE(z.title, '')) NOT LIKE 'adaptive study —%'
                   THEN qc.question_id
               END) AS question_count,
               COUNT(DISTINCT CASE
                   WHEN z.id IS NOT NULL
                    AND LOWER(COALESCE(z.source_file, '')) NOT LIKE 'smart_review_%'
                    AND LOWER(COALESCE(z.source_file, '')) NOT LIKE 'spaced_review_%'
                    AND LOWER(COALESCE(z.source_file, '')) NOT LIKE 'concept_review_%'
                    AND LOWER(COALESCE(z.source_file, '')) NOT LIKE 'adaptive_study_%'
                    AND LOWER(COALESCE(z.source_file, '')) NOT LIKE 'mixed_quiz_%'
                    AND LOWER(COALESCE(z.title, '')) NOT LIKE 'smart review —%'
                    AND LOWER(COALESCE(z.title, '')) NOT LIKE 'spaced review —%'
                    AND LOWER(COALESCE(z.title, '')) NOT LIKE 'concept review —%'
                    AND LOWER(COALESCE(z.title, '')) NOT LIKE 'adaptive study —%'
                   THEN q.quiz_id
               END) AS quiz_count
        FROM concepts c
        LEFT JOIN question_concepts qc ON qc.concept_id = c.id
        LEFT JOIN questions q ON q.id = qc.question_id
        LEFT JOIN quizzes z ON z.id = q.quiz_id
        GROUP BY c.id, c.name
        ORDER BY c.name COLLATE NOCASE
    """).fetchall()

    links = cur.execute("""
        SELECT qc.concept_id, qc.question_id
        FROM question_concepts qc
    """).fetchall()
    concepts_by_question = {}
    for row in links:
        concepts_by_question.setdefault(row["question_id"], []).append(row["concept_id"])

    evidence_by_concept = {}
    for row in _deduplicated_learning_answer_events(cur):
        for concept_id in concepts_by_question.get(row["question_id"], []):
            evidence_by_concept.setdefault(concept_id, []).append(row)

    topics = []
    for concept in concept_rows:
        events = evidence_by_concept.get(concept["id"], [])
        events.sort(key=lambda r: (str(r["occurred_at"] or ""), int(r["id"])))
        evidence = len(events)
        correct = sum(1 for r in events if int(r["was_correct"] or 0) == 1)
        incorrect = evidence - correct
        accuracy = round((correct / evidence) * 100, 1) if evidence else None

        recent = events[-5:]
        recent_correct = sum(1 for r in recent if int(r["was_correct"] or 0) == 1)
        recent_accuracy = round((recent_correct / len(recent)) * 100, 1) if recent else None
        trend = _concept_performance_trend(events)

        exam_attempts = {
            str(row["attempt_id"] or f"exam-event-{row['id']}")
            for row in events
            if row["event_type"] == "exam_answer"
        }
        study_sessions = {
            str(row["session_id"] or f"study-event-{row['id']}")
            for row in events
            if row["event_type"] == "study_answer"
        }

        last_dt = _parse_learning_datetime(events[-1]["occurred_at"]) if events else None
        days_since = max(0, int((now - last_dt).total_seconds() // 86400)) if last_dt else None
        if days_since is None:
            recency_score = 0.0
        elif days_since <= 7:
            recency_score = 100.0
        elif days_since <= 30:
            recency_score = 90.0
        elif days_since <= 90:
            recency_score = 75.0
        elif days_since <= 180:
            recency_score = 60.0
        else:
            recency_score = 45.0

        evidence_score = min(100.0, evidence * 12.5)
        if evidence:
            raw_mastery = (
                (accuracy or 0.0) * 0.55
                + (recent_accuracy or 0.0) * 0.20
                + evidence_score * 0.15
                + recency_score * 0.10
            )
            if evidence < 3:
                mastery = min(raw_mastery, 59.0)
            elif evidence < 5:
                mastery = min(raw_mastery, 74.0)
            else:
                mastery = raw_mastery
            mastery = round(max(0.0, min(100.0, mastery)), 1)
        else:
            mastery = None

        if evidence < 3:
            status = "insufficient"
            status_label = "Not enough data"
        elif mastery is not None and (mastery < 60 or (accuracy is not None and accuracy < 60)):
            status = "weak"
            status_label = "Weak area"
        elif mastery is not None and mastery < 75:
            status = "developing"
            status_label = "Developing"
        elif mastery is not None and mastery < 90:
            status = "proficient"
            status_label = "Proficient"
        else:
            status = "strong"
            status_label = "Strong"

        topics.append({
            "concept_id": concept["id"],
            "name": concept["name"],
            "question_count": concept["question_count"],
            "quiz_count": concept["quiz_count"],
            "evidence": evidence,
            "attempt_count": len(exam_attempts),
            "study_session_count": len(study_sessions),
            "practice_run_count": len(exam_attempts) + len(study_sessions),
            "answered_question_count": len({row["question_id"] for row in events}),
            "correct": correct,
            "incorrect": incorrect,
            "accuracy": accuracy,
            "recent_evidence": len(recent),
            "recent_accuracy": recent_accuracy,
            **trend,
            "mastery": mastery,
            "status": status,
            "status_label": status_label,
            "is_weak": status == "weak",
            "last_activity": events[-1]["occurred_at"] if events else None,
            "days_since_activity": days_since,
        })

    rank = {"weak": 0, "developing": 1, "proficient": 2, "strong": 3, "insufficient": 4}
    topics.sort(key=lambda item: (rank.get(item["status"], 9), item["mastery"] if item["mastery"] is not None else 999, item["name"].casefold()))
    return topics


def _retention_schedule_for_topic(topic, now=None):
    """Return a transparent review schedule and retention-adjusted mastery."""
    now = now or datetime.now(timezone.utc)
    evidence = int(topic.get("evidence") or 0)
    mastery = topic.get("mastery")
    last_raw = topic.get("last_activity")

    last_dt = _parse_learning_datetime(last_raw)
    if evidence <= 0 or mastery is None or last_dt is None:
        return {
            "review_state": "unscheduled",
            "review_state_label": "Not scheduled",
            "review_interval_days": None,
            "next_review": None,
            "days_until_review": None,
            "days_overdue": 0,
            "is_due": False,
            "is_due_soon": False,
            "retained_mastery": mastery,
            "decay_points": 0.0,
            "decay_rate_per_day": 0.0,
        }

    if evidence < 3:
        interval_days = 1
        review_state = "build_evidence"
        review_label = "Build evidence"
        next_review_dt = last_dt
        days_until = 0
        days_overdue = 0
        is_due = False
        is_due_soon = False
        decay_days = 0.0
    else:
        if mastery < 60:
            interval_days = 1
        elif mastery < 75:
            interval_days = 3
        elif mastery < 90:
            interval_days = 7
        else:
            interval_days = 14
        next_review_dt = last_dt + timedelta(days=interval_days)
        delta_seconds = (next_review_dt - now).total_seconds()
        if delta_seconds <= 0:
            overdue_seconds = -delta_seconds
            days_overdue = int(math.ceil(overdue_seconds / 86400.0)) if overdue_seconds > 0 else 0
            review_state = "overdue" if days_overdue > 0 else "due"
            review_label = "Overdue" if days_overdue > 0 else "Due now"
            days_until = 0
            is_due = True
            is_due_soon = False
            decay_days = overdue_seconds / 86400.0
        else:
            days_until = int(math.ceil(delta_seconds / 86400.0))
            days_overdue = 0
            is_due = False
            is_due_soon = days_until <= 2
            review_state = "due_soon" if is_due_soon else "fresh"
            review_label = "Due soon" if is_due_soon else "Fresh"
            decay_days = 0.0

    decay_rate = round(min(2.0, max(0.5, 0.5 + max(0.0, 80.0 - float(mastery)) * 0.03)), 2)
    decay_points = round(min(35.0, decay_days * decay_rate), 1)
    retained = round(max(0.0, float(mastery) - decay_points), 1)

    return {
        "review_state": review_state,
        "review_state_label": review_label,
        "review_interval_days": interval_days,
        "next_review": next_review_dt.isoformat() if next_review_dt else None,
        "days_until_review": days_until,
        "days_overdue": days_overdue,
        "is_due": is_due,
        "is_due_soon": is_due_soon,
        "retained_mastery": retained,
        "decay_points": decay_points,
        "decay_rate_per_day": decay_rate,
    }


def _learning_topics_with_retention(
    cur,
    now=None,
    *,
    learning_intelligence_topics=_learning_intelligence_topics,
    retention_schedule_for_topic=_retention_schedule_for_topic,
):
    topics = learning_intelligence_topics(cur, now=now)
    for topic in topics:
        topic.update(retention_schedule_for_topic(topic, now=now))
    return topics


def _review_schedule_payload(
    cur, now=None, *, learning_topics_with_retention=_learning_topics_with_retention
):
    topics = learning_topics_with_retention(cur, now=now)
    scheduled = [t for t in topics if t.get("evidence", 0) >= 3 and t.get("review_state") != "unscheduled"]
    due = [t for t in scheduled if t.get("review_state") in ("due", "overdue")]
    overdue = [t for t in scheduled if t.get("review_state") == "overdue"]
    due_soon = [t for t in scheduled if t.get("review_state") == "due_soon"]
    fresh = [t for t in scheduled if t.get("review_state") == "fresh"]
    retained = [t.get("retained_mastery") for t in scheduled if t.get("retained_mastery") is not None]
    avg_retained = round(sum(retained) / len(retained), 1) if retained else None
    order = {"overdue": 0, "due": 1, "due_soon": 2, "fresh": 3}
    scheduled.sort(key=lambda t: (
        order.get(t.get("review_state"), 9),
        t.get("next_review") or "9999",
        t.get("retained_mastery") if t.get("retained_mastery") is not None else 999,
        str(t.get("name") or "").casefold(),
    ))
    return {
        "topics": scheduled,
        "summary": {
            "scheduled_topics": len(scheduled),
            "due_now": len(due),
            "overdue": len(overdue),
            "due_soon": len(due_soon),
            "fresh": len(fresh),
            "average_retained_mastery": avg_retained,
        },
        "model": {
            "intervals": "Mastery below 60 = 1 day; 60-74 = 3 days; 75-89 = 7 days; 90+ = 14 days",
            "decay": "Retention decay starts only after the scheduled review date. Lower-mastery topics decay faster; the displayed penalty is capped at 35 points.",
            "separation": "Base mastery already includes the existing 10% recency component. Retained mastery adds a separate post-due decay estimate for review timing without changing stored answers or accuracy.",
        },
    }


def _learning_intelligence_payload(
    cur, now=None, *, learning_topics_with_retention=_learning_topics_with_retention
):
    topics = learning_topics_with_retention(cur, now=now)
    evidenced = [t for t in topics if t["evidence"] > 0]
    measurable = [t for t in topics if t["evidence"] >= 3]
    weak = [t for t in topics if t["status"] == "weak"]
    avg_accuracy = round(sum(t["accuracy"] for t in evidenced if t["accuracy"] is not None) / len(evidenced), 1) if evidenced else None
    avg_mastery = round(sum(t["mastery"] for t in measurable if t["mastery"] is not None) / len(measurable), 1) if measurable else None
    return {
        "topics": topics,
        "summary": {
            "concepts": len(topics),
            "concepts_with_evidence": len(evidenced),
            "measurable_concepts": len(measurable),
            "weak_areas": len(weak),
            "average_accuracy": avg_accuracy,
            "average_mastery": avg_mastery,
        },
        "model": {
            "mastery_formula": "55% overall accuracy + 20% recent accuracy (last 5) + 15% evidence + 10% recency",
            "evidence_credit": "Full evidence credit at 8 deduplicated responses",
            "minimum_evidence": "Fewer than 3 responses = Not enough data; 3-4 responses cannot exceed 74 mastery",
            "weak_area_rule": "At least 3 responses and mastery below 60 or accuracy below 60",
            "deduplication": "Latest Study response per question/session and one Exam response per question/attempt",
            "trend": "At least 6 responses are required. DLMS compares two adjacent equal windows of 3-5 responses; a change under 15 percentage points is roughly stable.",
            "coverage": "Question and quiz counts include tagged source material across quizzes and Study Packs, but exclude generated Smart, Spaced, Concept, and Adaptive Study copies.",
            "retention_separation": "Base mastery includes the existing recency component; retained mastery adds explicit post-due decay for review timing.",
        },
    }


def _learning_profile_payload(
    cur,
    *,
    learning_intelligence_payload=_learning_intelligence_payload,
    review_schedule_payload=_review_schedule_payload,
):
    """Summarize learner-level progress from the explainable topic model."""
    payload = learning_intelligence_payload(cur)
    topics = payload.get("topics") or []
    review_schedule = review_schedule_payload(cur)
    evidenced = [t for t in topics if t.get("evidence", 0) > 0]
    measurable = [t for t in topics if t.get("evidence", 0) >= 3]
    weak = [t for t in topics if t.get("status") == "weak"]
    strong = [t for t in topics if t.get("status") == "strong"]
    proficient = [t for t in topics if t.get("status") == "proficient"]
    developing = [t for t in topics if t.get("status") == "developing"]
    insufficient = [t for t in topics if t.get("status") == "insufficient"]

    event_counts = cur.execute("""
        SELECT event_type, COUNT(*) AS count
        FROM learning_events
        GROUP BY event_type
    """).fetchall()
    event_counts = {r["event_type"]: r["count"] for r in event_counts}

    activity = cur.execute("""
        SELECT COUNT(DISTINCT CASE WHEN event_type='attempt_completed' THEN attempt_id END) AS completed_attempts,
               COUNT(DISTINCT quiz_id) AS quizzes_studied,
               MAX(occurred_at) AS last_activity
        FROM learning_events
    """).fetchone()

    due_topics = [t for t in review_schedule.get("topics", []) if t.get("review_state") in ("due", "overdue")]

    if weak:
        recommendation = {
            "kind": "review_weak",
            "title": "Review weak areas",
            "detail": f"Start with {weak[0]['name']} and {len(weak)-1} other weak topic{'s' if len(weak)-1 != 1 else ''}." if len(weak) > 1 else f"Start with {weak[0]['name']}.",
        }
    elif due_topics:
        recommendation = {
            "kind": "review_due",
            "title": "Review topics due for reinforcement",
            "detail": f"{due_topics[0]['name']} is due now" + (f" along with {len(due_topics)-1} other topic{'s' if len(due_topics)-1 != 1 else ''}." if len(due_topics) > 1 else "."),
        }
    elif insufficient:
        recommendation = {
            "kind": "build_evidence",
            "title": "Build more evidence",
            "detail": f"Practice {insufficient[0]['name']} until DLMS has at least three deduplicated responses.",
        }
    elif developing:
        recommendation = {
            "kind": "developing",
            "title": "Strengthen developing topics",
            "detail": f"Continue practice on {developing[0]['name']} to move toward proficiency.",
        }
    elif evidenced:
        recommendation = {
            "kind": "maintain",
            "title": "Maintain your progress",
            "detail": "No weak areas currently meet the evidence threshold. Continue mixed review to keep skills fresh.",
        }
    else:
        recommendation = {
            "kind": "start",
            "title": "Start building your learning profile",
            "detail": "Tag quiz questions with concepts and answer them in Study or Exam Mode.",
        }

    strongest = sorted(
        [t for t in measurable if t.get("mastery") is not None],
        key=lambda t: (-t["mastery"], -t.get("evidence", 0), t["name"].casefold()),
    )[:5]
    weakest = sorted(
        weak,
        key=lambda t: (t.get("mastery") if t.get("mastery") is not None else 999, t.get("accuracy") if t.get("accuracy") is not None else 999, t["name"].casefold()),
    )[:5]

    return {
        "summary": payload.get("summary") or {},
        "status_counts": {
            "weak": len(weak),
            "developing": len(developing),
            "proficient": len(proficient),
            "strong": len(strong),
            "insufficient": len(insufficient),
        },
        "activity": {
            "study_answers": event_counts.get("study_answer", 0),
            "exam_answers": event_counts.get("exam_answer", 0),
            "completed_attempts": (activity["completed_attempts"] if activity else 0) or 0,
            "quizzes_studied": (activity["quizzes_studied"] if activity else 0) or 0,
            "last_activity": activity["last_activity"] if activity else None,
        },
        "strongest_topics": strongest,
        "weakest_topics": weakest,
        "recommendation": recommendation,
        "retention": review_schedule.get("summary") or {},
        "due_topics": due_topics[:5],
        "review_model": review_schedule.get("model") or {},
        "model": payload.get("model") or {},
    }


def _question_payload_from_db(
    cur, question_id, *, question_concepts=_question_concepts
):
    q = cur.execute("""
        SELECT id, question_number, question_text,
               COALESCE(question_type, 'choice') AS question_type,
               matching_round_size,
               COALESCE(matching_direction, 'term_to_definition') AS matching_direction,
               COALESCE(explanation, '') AS explanation,
               COALESCE(media_json, '{}') AS media_json,
               source_organization, source_dataset, source_version, source_url, source_license
        FROM questions WHERE id = ?
    """, (question_id,)).fetchone()
    if not q:
        return None
    item = {
        "number": q["question_number"],
        "type": q["question_type"],
        "question": q["question_text"],
        "explanation": q["explanation"] or "",
        "concepts": question_concepts(cur, q["id"]),
    }
    try:
        media = json.loads(q["media_json"] or "{}")
    except Exception:
        media = {}
    if isinstance(media, dict):
        item.update(media)
    source = {
        "organization": q["source_organization"],
        "dataset": q["source_dataset"],
        "version": q["source_version"],
        "url": q["source_url"],
        "license": q["source_license"],
    }
    if any(source.values()):
        item["source"] = source

    if q["question_type"] == "matching":
        pairs = cur.execute("""
            SELECT left_text, right_text, category, explanation, verification_json
            FROM matching_pairs WHERE question_id = ? ORDER BY pair_order, id
        """, (q["id"],)).fetchall()
        item["pairs"] = [{
            "left": r["left_text"], "right": r["right_text"],
            "category": r["category"] or "", "explanation": r["explanation"] or "",
            "verification": json.loads(r["verification_json"]) if r["verification_json"] else {},
        } for r in pairs]
        item["round_size"] = q["matching_round_size"]
        item["direction"] = q["matching_direction"]
    else:
        choices = cur.execute("""
            SELECT label, text, is_correct FROM choices
            WHERE question_id = ? ORDER BY label
        """, (q["id"],)).fetchall()
        item["choices"] = [{"label": r["label"], "text": r["text"], "is_correct": bool(r["is_correct"])} for r in choices]
        item["correct"] = [r["label"] for r in choices if r["is_correct"]]
    return item


def _review_candidates_for_topics(cur, topics):
    """Return unique source questions associated with the supplied concepts."""
    if not topics:
        return []
    topic_by_id = {t["concept_id"]: t for t in topics}
    rows = cur.execute("""
        SELECT qc.question_id, qc.concept_id, q.quiz_id, q.question_number, q.question_text
        FROM question_concepts qc
        JOIN questions q ON q.id = qc.question_id
        JOIN quizzes z ON z.id = q.quiz_id
        WHERE qc.concept_id IN (%s)
          AND LOWER(z.source_file) NOT LIKE 'smart_review_%%'
          AND LOWER(z.source_file) NOT LIKE 'spaced_review_%%'
          AND LOWER(z.source_file) NOT LIKE 'concept_review_%%'
          AND LOWER(z.source_file) NOT LIKE 'adaptive_study_%%'
          AND LOWER(z.source_file) NOT LIKE 'mixed_quiz_%%'
          AND LOWER(z.title) NOT LIKE 'smart review —%%'
          AND LOWER(z.title) NOT LIKE 'spaced review —%%'
          AND LOWER(z.title) NOT LIKE 'concept review —%%'
          AND LOWER(z.title) NOT LIKE 'adaptive study —%%'
    """ % ",".join("?" for _ in topic_by_id), tuple(topic_by_id)).fetchall()
    grouped = {}
    for row in rows:
        g = grouped.setdefault(row["question_id"], {
            "question_id": row["question_id"], "quiz_id": row["quiz_id"],
            "question_number": row["question_number"], "question_text": row["question_text"],
            "topics": [],
        })
        topic = topic_by_id.get(row["concept_id"])
        if topic:
            g["topics"].append(topic)
    candidates = list(grouped.values())
    for candidate in candidates:
        candidate["priority_mastery"] = min((t.get("retained_mastery") if t.get("retained_mastery") is not None else t.get("mastery") if t.get("mastery") is not None else 100) for t in candidate["topics"])
        candidate["topic_names"] = sorted({t["name"] for t in candidate["topics"]}, key=str.casefold)

    unique_by_fingerprint = {}
    for candidate in candidates:
        fingerprint = " ".join(str(candidate.get("question_text") or "").casefold().split())
        if not fingerprint:
            fingerprint = f"question-id:{candidate['question_id']}"
        existing = unique_by_fingerprint.get(fingerprint)
        if existing is None:
            candidate["fingerprint"] = fingerprint
            unique_by_fingerprint[fingerprint] = candidate
            continue
        topic_map = {t.get("concept_id"): t for t in existing.get("topics") or []}
        for topic in candidate.get("topics") or []:
            topic_map.setdefault(topic.get("concept_id"), topic)
        existing["topics"] = list(topic_map.values())
        existing["priority_mastery"] = min((t.get("retained_mastery") if t.get("retained_mastery") is not None else t.get("mastery") if t.get("mastery") is not None else 100) for t in existing["topics"])
        existing["topic_names"] = sorted({t["name"] for t in existing["topics"]}, key=str.casefold)
    candidates = list(unique_by_fingerprint.values())
    candidates.sort(key=lambda c: (c["priority_mastery"], -len(c["topics"]), c["quiz_id"], c["question_number"]))
    return candidates


def _smart_review_candidates(
    cur,
    *,
    learning_intelligence_topics=_learning_intelligence_topics,
    review_candidates_for_topics=_review_candidates_for_topics,
):
    """Return unique questions ranked by the weak concepts they reinforce."""
    topics = learning_intelligence_topics(cur)
    weak = [t for t in topics if t.get("status") == "weak"]
    return review_candidates_for_topics(cur, weak), weak


def _smart_review_select_candidates(candidates, weak, requested):
    """Select diverse Smart Review questions across weak concepts."""
    requested = max(1, int(requested or 1))
    weak_order = sorted(
        weak,
        key=lambda t: (
            t.get("mastery") if t.get("mastery") is not None else 999,
            t.get("accuracy") if t.get("accuracy") is not None else 999,
            str(t.get("name") or "").casefold(),
        ),
    )
    by_concept = {t["concept_id"]: [] for t in weak_order}
    for candidate in candidates:
        for topic in candidate.get("topics") or []:
            concept_id = topic.get("concept_id")
            if concept_id in by_concept:
                by_concept[concept_id].append(candidate)

    selected = []
    selected_ids = set()
    offsets = {concept_id: 0 for concept_id in by_concept}
    made_progress = True
    while len(selected) < requested and made_progress:
        made_progress = False
        for topic in weak_order:
            concept_id = topic["concept_id"]
            pool = by_concept.get(concept_id) or []
            idx = offsets[concept_id]
            while idx < len(pool) and pool[idx]["question_id"] in selected_ids:
                idx += 1
            offsets[concept_id] = idx + 1
            if idx >= len(pool):
                continue
            candidate = pool[idx]
            selected.append(candidate)
            selected_ids.add(candidate["question_id"])
            made_progress = True
            if len(selected) >= requested:
                break

    if len(selected) < requested:
        for candidate in candidates:
            if candidate["question_id"] in selected_ids:
                continue
            selected.append(candidate)
            selected_ids.add(candidate["question_id"])
            if len(selected) >= requested:
                break
    return selected


def _review_select_candidates(
    candidates,
    topics,
    requested,
    *,
    smart_review_select_candidates=_smart_review_select_candidates,
):
    return smart_review_select_candidates(candidates, topics, requested)


def _adaptive_study_candidates(
    cur,
    now=None,
    *,
    learning_topics_with_retention=_learning_topics_with_retention,
):
    """Rank canonical source questions for a deterministic adaptive session.

    Priority points intentionally use only existing, explainable evidence:
    weak concepts (+40), developing concepts (+15), review timing (+8 to +25),
    recent/previous misses (+10 to +35), low recent accuracy (+15), and unseen
    or stale material (+5 to +20). More than two prior responses gradually
    reduce priority, capped at 15 points, so frequently repeated questions do
    not crowd out other useful material.
    """
    now = now or datetime.now(timezone.utc)
    topics = learning_topics_with_retention(cur, now=now)
    topics_by_id = {topic["concept_id"]: topic for topic in topics}

    question_rows = cur.execute("""
        SELECT q.id, q.quiz_id, q.question_number, q.question_text,
               COALESCE(q.question_type, 'choice') AS question_type,
               COALESCE(z.source_file, '') AS source_file,
               COALESCE(z.title, '') AS quiz_title
        FROM questions q
        JOIN quizzes z ON z.id = q.quiz_id
        ORDER BY q.quiz_id, q.question_number, q.id
    """).fetchall()
    concept_links = cur.execute("""
        SELECT question_id, concept_id
        FROM question_concepts
        ORDER BY question_id, concept_id
    """).fetchall()
    concepts_by_question = {}
    for link in concept_links:
        concepts_by_question.setdefault(link["question_id"], []).append(
            link["concept_id"]
        )

    groups = {}
    question_to_key = {}
    for row in question_rows:
        normalized = re.sub(
            r"\s+", " ", str(row["question_text"] or "").strip()
        ).casefold()
        key = (
            str(row["question_type"] or "choice").casefold(),
            normalized or f"question-id:{row['id']}",
        )
        question_to_key[row["id"]] = key
        group = groups.setdefault(
            key,
            {
                "source_rows": [],
                "concept_ids": set(),
                "events": [],
            },
        )
        if _is_generated_review_source(row["source_file"], row["quiz_title"]):
            continue
        group["source_rows"].append(row)
        group["concept_ids"].update(concepts_by_question.get(row["id"], []))

    for event in _deduplicated_learning_answer_events(cur):
        key = question_to_key.get(event["question_id"])
        if key in groups:
            groups[key]["events"].append(event)

    candidates = []
    for group in groups.values():
        if not group["source_rows"]:
            continue
        source = group["source_rows"][0]
        events = sorted(
            group["events"],
            key=lambda row: (str(row["occurred_at"] or ""), int(row["id"])),
        )
        linked_topics = [
            topics_by_id[concept_id]
            for concept_id in sorted(group["concept_ids"])
            if concept_id in topics_by_id
        ]
        evidence = len(events)
        recent = events[-5:]
        recent_accuracy = None
        if recent:
            recent_accuracy = round(
                sum(int(row["was_correct"] or 0) for row in recent)
                * 100.0
                / len(recent),
                1,
            )

        last_activity = events[-1]["occurred_at"] if events else None
        last_activity_dt = _parse_learning_datetime(last_activity)
        days_since_activity = None
        if last_activity_dt is not None:
            days_since_activity = max(
                0, int((now - last_activity_dt).total_seconds() // 86400)
            )

        incorrect_events = [
            event for event in events if int(event["was_correct"] or 0) == 0
        ]
        last_miss = incorrect_events[-1] if incorrect_events else None
        last_miss_dt = (
            _parse_learning_datetime(last_miss["occurred_at"])
            if last_miss is not None
            else None
        )
        days_since_miss = None
        if last_miss_dt is not None:
            days_since_miss = max(
                0, int((now - last_miss_dt).total_seconds() // 86400)
            )

        score = 0
        components = {}
        reasons = []
        weak_topics = [topic for topic in linked_topics if topic["status"] == "weak"]
        developing_topics = [
            topic for topic in linked_topics if topic["status"] == "developing"
        ]
        if weak_topics:
            components["weak_concept"] = 40
            reasons.append(
                "Weak concept: "
                + ", ".join(topic["name"] for topic in weak_topics[:2])
            )
        elif developing_topics:
            components["developing_concept"] = 15
            reasons.append(
                "Developing concept: "
                + ", ".join(topic["name"] for topic in developing_topics[:2])
            )

        review_states = {topic.get("review_state") for topic in linked_topics}
        if "overdue" in review_states:
            components["review_recency"] = 25
            reasons.append("Concept review is overdue")
        elif "due" in review_states:
            components["review_recency"] = 18
            reasons.append("Concept review is due")
        elif "due_soon" in review_states:
            components["review_recency"] = 8
            reasons.append("Concept review is due soon")

        if last_miss is not None:
            if days_since_miss is not None and days_since_miss <= 14:
                components["recent_miss"] = 35
                reasons.append("Missed within the last 14 days")
            elif days_since_miss is not None and days_since_miss <= 30:
                components["recent_miss"] = 20
                reasons.append("Missed within the last 30 days")
            else:
                components["previous_miss"] = 10
                reasons.append("Previously missed")

        if len(recent) >= 3 and recent_accuracy is not None and recent_accuracy < 60:
            components["low_recent_accuracy"] = 15
            reasons.append("Recent accuracy is below 60%")

        if evidence == 0:
            components["study_recency"] = 20
            reasons.append("Not studied yet")
        elif days_since_activity is not None and days_since_activity >= 30:
            components["study_recency"] = 20
            reasons.append(f"Not reviewed for {days_since_activity} days")
        elif days_since_activity is not None and days_since_activity >= 14:
            components["study_recency"] = 12
            reasons.append(f"Not reviewed for {days_since_activity} days")
        elif days_since_activity is not None and days_since_activity >= 7:
            components["study_recency"] = 5
            reasons.append(f"Not reviewed for {days_since_activity} days")

        repeat_penalty = min(15, max(0, evidence - 2) * 3)
        if repeat_penalty:
            components["repeat_penalty"] = -repeat_penalty
        score = sum(components.values())
        if not reasons:
            reasons.append("Mixed review for continued practice")

        candidates.append(
            {
                "question_id": source["id"],
                "quiz_id": source["quiz_id"],
                "question_number": source["question_number"],
                "question_text": source["question_text"],
                "question_type": source["question_type"],
                "source_question_ids": [row["id"] for row in group["source_rows"]],
                "topics": linked_topics,
                "topic_names": sorted(
                    {topic["name"] for topic in linked_topics}, key=str.casefold
                ),
                "concept_ids": sorted(group["concept_ids"]),
                "priority_score": score,
                "score_components": components,
                "selection_reasons": reasons,
                "evidence": evidence,
                "recent_accuracy": recent_accuracy,
                "last_activity": last_activity,
                "days_since_activity": days_since_activity,
                "days_since_miss": days_since_miss,
            }
        )

    candidates.sort(
        key=lambda candidate: (
            -candidate["priority_score"],
            candidate["evidence"],
            -(
                candidate["days_since_activity"]
                if candidate["days_since_activity"] is not None
                else 10**9
            ),
            candidate["quiz_id"],
            candidate["question_number"],
            candidate["question_id"],
        )
    )
    return candidates


def _adaptive_study_select_candidates(candidates, requested):
    """Select deterministically while spreading concepts and source quizzes."""
    requested = max(1, int(requested or 1))
    remaining = list(enumerate(candidates))
    selected = []
    concept_uses = {}
    quiz_uses = {}
    while remaining and len(selected) < requested:
        ranked = []
        for original_index, candidate in remaining:
            concept_ids = candidate.get("concept_ids") or []
            diversity_penalty = 8 * max(
                (concept_uses.get(concept_id, 0) for concept_id in concept_ids),
                default=0,
            )
            quiz_id = candidate.get("quiz_id")
            if quiz_id is not None:
                diversity_penalty += 4 * quiz_uses.get(quiz_id, 0)
            ranked.append(
                (
                    -(candidate.get("priority_score", 0) - diversity_penalty),
                    original_index,
                    candidate,
                )
            )
        _adjusted, original_index, chosen = min(ranked, key=lambda item: item[:2])
        selected.append(chosen)
        for concept_id in chosen.get("concept_ids") or []:
            concept_uses[concept_id] = concept_uses.get(concept_id, 0) + 1
        quiz_id = chosen.get("quiz_id")
        if quiz_id is not None:
            quiz_uses[quiz_id] = quiz_uses.get(quiz_id, 0) + 1
        remaining = [item for item in remaining if item[0] != original_index]
    return selected


def _response_selected_labels(value):
    """Normalize recorded choice selections into stable A-Z labels."""
    if isinstance(value, str):
        raw = re.split(r"[,;\s]+", value.strip())
    elif isinstance(value, (list, tuple, set)):
        raw = list(value)
    else:
        return []
    out = []
    seen = set()
    for item in raw:
        label = str(item or "").strip().upper()
        if re.fullmatch(r"[A-Z]", label) and label not in seen:
            seen.add(label)
            out.append(label)
    return out


def _question_diagnostics_payload(
    cur,
    *,
    question_concepts=_question_concepts,
    response_selected_labels=_response_selected_labels,
):
    """DLMS-015/016: explainable confusion and question-quality signals."""
    qrows = cur.execute("""
        SELECT q.id, q.quiz_id, q.question_number, q.question_text,
               COALESCE(q.question_type,'choice') AS question_type,
               z.title AS quiz_title, COALESCE(z.source_file,'') AS source_file
        FROM questions q JOIN quizzes z ON z.id=q.quiz_id
        ORDER BY q.id
    """).fetchall()

    groups = {}
    question_to_key = {}
    for q in qrows:
        qtype = (q['question_type'] or 'choice').lower()
        norm = re.sub(r"\s+", " ", str(q['question_text'] or '').strip()).casefold()
        key = (qtype, norm)
        question_to_key[q['id']] = key
        g = groups.setdefault(key, {
            'question_type': qtype, 'question_text': q['question_text'] or '',
            'question_ids': [], 'source_question_ids': [], 'quiz_titles': set(),
            'concepts': set(), 'choice_map': {}, 'correct_labels': set(),
        })
        g['question_ids'].append(q['id'])
        g['quiz_titles'].add(q['quiz_title'] or '')
        if not _is_generated_review_source(q['source_file'], q['quiz_title']):
            g['source_question_ids'].append(q['id'])
        for concept in question_concepts(cur, q['id']):
            g['concepts'].add(concept)
        if qtype == 'choice':
            for choice in cur.execute("SELECT label,text,is_correct FROM choices WHERE question_id=? ORDER BY label", (q['id'],)).fetchall():
                label = str(choice['label'] or '').upper()
                if label and label not in g['choice_map']:
                    g['choice_map'][label] = choice['text'] or ''
                if choice['is_correct']:
                    g['correct_labels'].add(label)

    evidence_by_group = {}
    for event in _deduplicated_learning_answer_events(cur):
        key = question_to_key.get(event['question_id'])
        if key in groups:
            evidence_by_group.setdefault(key, []).append(event)

    question_rows = []
    confusion = {}
    for key, group in groups.items():
        events = evidence_by_group.get(key, [])
        evidence = len(events)
        correct = sum(1 for event in events if int(event['was_correct'] or 0) == 1)
        incorrect = evidence - correct
        accuracy = round(correct / evidence * 100, 1) if evidence else None
        option_counts = {label: 0 for label in group['choice_map']}
        incorrect_option_counts = {label: 0 for label in group['choice_map']}
        for event in events:
            try:
                payload = json.loads(event['response_json'] or '{}')
            except Exception:
                payload = {}
            selected = response_selected_labels(payload.get('selected'))
            for label in selected:
                if label in option_counts:
                    option_counts[label] += 1
            if not int(event['was_correct'] or 0) and group['question_type'] == 'choice':
                wrong = [item for item in selected if item not in group['correct_labels']]
                missing = [item for item in group['correct_labels'] if item not in selected]
                for wrong_label in wrong:
                    incorrect_option_counts[wrong_label] = incorrect_option_counts.get(wrong_label, 0) + 1
                    targets = missing or sorted(group['correct_labels'])
                    for correct_label in targets:
                        confusion_key = (group['choice_map'].get(wrong_label, wrong_label), group['choice_map'].get(correct_label, correct_label))
                        row = confusion.setdefault(confusion_key, {'selected_text': confusion_key[0], 'correct_text': confusion_key[1], 'count': 0, 'question_keys': set(), 'concepts': set()})
                        row['count'] += 1
                        row['question_keys'].add(key)
                        row['concepts'].update(group['concepts'])

        signals = []
        if evidence < 5:
            status = 'insufficient'
            status_label = 'Not enough data'
        else:
            if accuracy is not None and accuracy < 40:
                signals.append('Very difficult / review wording or coverage')
            elif accuracy is not None and accuracy < 60:
                signals.append('High miss rate')
            if evidence >= 10 and accuracy is not None and accuracy >= 95:
                signals.append('Very easy')
            if group['question_type'] == 'choice' and evidence >= 8:
                for label, count in incorrect_option_counts.items():
                    if count >= 3 and (count / evidence) >= 0.30:
                        signals.append(f"Strong distractor: {label}")
                for label, count in option_counts.items():
                    if label not in group['correct_labels'] and count == 0:
                        signals.append(f"Unused distractor: {label}")
            status = 'review' if signals else 'healthy'
            status_label = 'Review suggested' if signals else 'Healthy'
        question_rows.append({
            'question_text': group['question_text'], 'question_type': group['question_type'],
            'source_question_count': len(group['source_question_ids']), 'evidence': evidence,
            'correct': correct, 'incorrect': incorrect, 'accuracy': accuracy,
            'status': status, 'status_label': status_label, 'signals': signals,
            'concepts': sorted(group['concepts'], key=str.casefold),
            'quiz_titles': sorted(item for item in group['quiz_titles'] if item),
            'option_selection_counts': option_counts,
        })

    question_rows.sort(key=lambda row: ({'review': 0, 'healthy': 1, 'insufficient': 2}.get(row['status'], 9), row['accuracy'] if row['accuracy'] is not None else 999, row['question_text'].casefold()))
    confusions = []
    for row in confusion.values():
        if row['count'] < 2:
            continue
        confusions.append({'selected_text': row['selected_text'], 'correct_text': row['correct_text'], 'count': row['count'], 'question_count': len(row['question_keys']), 'concepts': sorted(row['concepts'], key=str.casefold)})
    confusions.sort(key=lambda row: (-row['count'], -row['question_count'], row['selected_text'].casefold(), row['correct_text'].casefold()))

    measurable = [question for question in question_rows if question['evidence'] >= 5]
    return {
        'summary': {
            'questions_with_evidence': sum(1 for question in question_rows if question['evidence'] > 0),
            'questions_measurable': len(measurable),
            'review_suggested': sum(1 for question in question_rows if question['status'] == 'review'),
            'confusion_pairs': len(confusions),
        },
        'confusions': confusions[:50], 'questions': question_rows,
        'model': {
            'confusion_rule': 'Repeated incorrect selected-answer → correct-answer pair, minimum 2 occurrences.',
            'quality_rule': 'Signals are review prompts, not proof a question is bad. Minimum 5 responses for general quality classification; distractor signals require at least 8.',
            'clone_handling': 'Generated review copies are grouped with identical source question text so practice contributes evidence without creating duplicate rows.'
        }
    }

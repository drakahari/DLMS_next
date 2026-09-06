"""Learning intelligence, diagnostics, and adaptive review domain services."""

import json
import math
import re
from datetime import datetime, timedelta, timezone


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
                   WHEN z.source_file IS NULL OR (LOWER(z.source_file) NOT LIKE 'smart_review_%' AND LOWER(z.source_file) NOT LIKE 'spaced_review_%')
                   THEN qc.question_id
               END) AS question_count
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

    rows = cur.execute("""
        SELECT id, event_type, quiz_id, question_id, attempt_id, session_id,
               mode, was_correct, occurred_at
        FROM learning_events
        WHERE event_type IN ('study_answer', 'exam_answer')
          AND question_id IS NOT NULL
          AND was_correct IS NOT NULL
        ORDER BY occurred_at ASC, id ASC
    """).fetchall()

    dedup = {}
    for row in rows:
        if row["event_type"] == "exam_answer":
            scope = row["attempt_id"] or f"exam-event-{row['id']}"
        else:
            scope = row["session_id"] or f"study-event-{row['id']}"
        key = (row["event_type"], scope, row["question_id"])
        dedup[key] = row

    evidence_by_concept = {}
    for row in dedup.values():
        for concept_id in concepts_by_question.get(row["question_id"], []):
            evidence_by_concept.setdefault(concept_id, []).append(row)

    def parse_dt(value):
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            try:
                dt = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            except ValueError:
                return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

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

        last_dt = parse_dt(events[-1]["occurred_at"]) if events else None
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
            "evidence": evidence,
            "correct": correct,
            "incorrect": incorrect,
            "accuracy": accuracy,
            "recent_accuracy": recent_accuracy,
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

    def parse_dt(value):
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            try:
                dt = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            except ValueError:
                return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    last_dt = parse_dt(last_raw)
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
          AND LOWER(z.title) NOT LIKE 'smart review —%%'
          AND LOWER(z.title) NOT LIKE 'spaced review —%%'
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
        sf = (q['source_file'] or '').lower()
        if not (sf.startswith('smart_review_') or sf.startswith('spaced_review_')):
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

    erows = cur.execute("""
        SELECT id,event_type,question_id,attempt_id,session_id,was_correct,response_json,occurred_at
        FROM learning_events
        WHERE event_type IN ('study_answer','exam_answer') AND question_id IS NOT NULL AND was_correct IS NOT NULL
        ORDER BY occurred_at,id
    """).fetchall()
    dedup = {}
    for event in erows:
        scope = (event['attempt_id'] or f"exam-{event['id']}") if event['event_type'] == 'exam_answer' else (event['session_id'] or f"study-{event['id']}")
        dedup[(event['event_type'], scope, event['question_id'])] = event

    evidence_by_group = {}
    for event in dedup.values():
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
            'clone_handling': 'Smart/Spaced Review copies are grouped with identical source question text so practice contributes evidence without creating duplicate rows.'
        }
    }

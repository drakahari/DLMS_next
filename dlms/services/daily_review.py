"""Deterministic composition of existing signals into Today's Review."""

from datetime import datetime, timezone

from .question_identity import quiz_generation_kind


DEFAULT_DUE_QUESTION_BATCH_SIZE = 20
MAX_DUE_QUESTION_BATCH_SIZE = 50


def build_daily_review_plan(
    cur,
    *,
    registry,
    installed_content_packs,
    review_schedule_payload,
    learning_intelligence_payload,
    adaptive_study_candidates,
    learning_answer_events,
    parse_datetime,
    now=None,
    due_batch_size=DEFAULT_DUE_QUESTION_BATCH_SIZE,
    scope=None,
):
    """Compose canonical recommendations without owning their scoring rules.

    This service deliberately assigns only category order. Due dates, concept
    status, and adaptive ranking remain owned by their canonical services.
    Browser-local unfinished sessions are merged by the Dashboard after this
    server-derived plan is returned.
    """
    now = now or datetime.now(timezone.utc)
    schedule = review_schedule_payload(cur, now=now)
    intelligence = learning_intelligence_payload(cur, now=now)
    adaptive = adaptive_study_candidates(cur, now=now)

    valid_registry = []
    registry_by_quiz_id = {}
    quiz_metadata = {
        str(row["id"]): row
        for row in cur.execute(
            "SELECT id, title, source_file, generation_kind FROM quizzes"
        ).fetchall()
    }
    for raw in registry if isinstance(registry, list) else []:
        if not isinstance(raw, dict):
            continue
        quiz_id = str(raw.get("id") or "").strip()
        quiz_file = str(raw.get("html") or "").strip()
        if not quiz_id or not quiz_file:
            continue
        title = str(raw.get("title") or "Untitled Quiz").strip() or "Untitled Quiz"
        source_pack_id = str(raw.get("source_pack_id") or "").strip().casefold()
        metadata = quiz_metadata.get(quiz_id)
        stored_generation_kind = (
            metadata["generation_kind"]
            if metadata is not None
            else raw.get("generation_kind")
        )
        classified_generation_kind = quiz_generation_kind(
            generation_kind=stored_generation_kind,
            source_file=(
                metadata["source_file"] if metadata is not None else quiz_file
            ),
            title=(metadata["title"] if metadata is not None else title),
        )
        if classified_generation_kind == "native_spaced_review":
            generated_kind = "native_due"
        elif classified_generation_kind in {
            "spaced_review",
            "concept_review",
            "smart_review",
        }:
            generated_kind = "concept_review"
        elif classified_generation_kind == "adaptive_study":
            generated_kind = "adaptive"
        else:
            generated_kind = None
        item = {
            "id": quiz_id,
            "title": title,
            "html": quiz_file,
            "source_pack_id": source_pack_id or None,
            "generation_kind": stored_generation_kind,
            "generated_kind": generated_kind,
        }
        valid_registry.append(item)
        registry_by_quiz_id.setdefault(quiz_id, item)

    items = []
    covered_question_ids = set()
    due_questions = [
        question
        for question in schedule.get("questions") or []
        if question.get("schedule_state") in {"due", "overdue"}
    ]
    due_concepts = set()
    next_due_batch_size = 0
    if due_questions:
        try:
            requested_due_batch_size = int(due_batch_size)
        except (TypeError, ValueError):
            requested_due_batch_size = DEFAULT_DUE_QUESTION_BATCH_SIZE
        next_due_batch_size = min(
            len(due_questions),
            max(1, min(requested_due_batch_size, MAX_DUE_QUESTION_BATCH_SIZE)),
        )
        for question in due_questions:
            source_ids = question.get("source_question_ids") or [
                question.get("question_id")
            ]
            covered_question_ids.update(
                int(question_id)
                for question_id in source_ids
                if isinstance(question_id, int)
            )
            due_concepts.update(
                str(name).strip().casefold()
                for name in question.get("concepts") or []
                if str(name).strip()
            )
        overdue_count = sum(
            question.get("schedule_state") == "overdue"
            for question in due_questions
        )
        reason = (
            f"{len(due_questions)} source question"
            f"{'s are' if len(due_questions) != 1 else ' is'} due now."
        )
        if overdue_count:
            reason += (
                f" {overdue_count} "
                f"{'are' if overdue_count != 1 else 'is'} overdue."
            )
        if len(due_questions) > next_due_batch_size:
            reason += (
                f" Next review: up to {next_due_batch_size} questions."
                " Today’s Review recalculates the remaining total after you finish."
            )
        items.append(
            {
                "id": "native-due",
                "kind": "native_due",
                "priority": 10,
                "title": "Review due questions",
                "reason": reason,
                "action": {
                    "label": "Review Due Questions",
                    "url": "/native-spaced-review/generate",
                    "method": "POST",
                    "fields": {
                        "question_count": str(next_due_batch_size)
                    },
                },
            }
        )

    concept_options = [
        topic
        for topic in intelligence.get("topics") or []
        if topic.get("status") in {"weak", "developing"}
        and int(topic.get("evidence") or 0) >= 3
        and int(topic.get("question_count") or 0) > 0
        and str(topic.get("name") or "").strip().casefold() not in due_concepts
    ]
    selected_concept = concept_options[0] if concept_options else None
    if selected_concept:
        status = selected_concept["status"]
        label = "weak" if status == "weak" else "developing"
        accuracy = selected_concept.get("accuracy")
        accuracy_text = (
            f" Accuracy is {round(float(accuracy))}%."
            if accuracy is not None
            else ""
        )
        items.append(
            {
                "id": f"concept-{selected_concept['concept_id']}",
                "kind": "weak_concept",
                "priority": 20,
                "title": f"Review {selected_concept['name']}",
                "reason": (
                    f"Learning Intelligence identifies this as a {label} concept."
                    f"{accuracy_text}"
                ),
                "action": {
                    "label": "Review This Concept",
                    "url": "/concept-review/generate",
                    "method": "POST",
                    "fields": {
                        "concept_id": str(selected_concept["concept_id"]),
                        "question_count": "20",
                    },
                },
            }
        )

    # Adaptive Study is already a cross-signal recommendation. Do not present
    # it as another card when a more specific due/concept action is already in
    # the plan; that would describe the same material twice.
    if adaptive and not due_questions and selected_concept is None:
        top = adaptive[0]
        evidence = sum(
            int(candidate.get("evidence") or 0) for candidate in adaptive
        )
        if evidence == 0:
            title = "Build your learning baseline"
            reason = (
                "You have study material but little recorded history. "
                "Start a balanced Adaptive Study session."
            )
        else:
            title = "Study what you need most"
            first_reason = next(
                (
                    str(candidate_reason).strip()
                    for candidate_reason in top.get("selection_reasons") or []
                    if str(candidate_reason).strip()
                ),
                "Existing learning signals identify useful material to practice",
            )
            reason = (
                "Adaptive Study's highest remaining signal is: "
                f"{first_reason}."
            )
        items.append(
            {
                "id": "adaptive-study",
                "kind": "adaptive",
                "priority": 40,
                "title": title,
                "reason": reason,
                "action": {
                    "label": "Study What I Need Most",
                    "url": "/adaptive-study/generate",
                    "method": "POST",
                    "fields": {"question_count": "20"},
                },
            }
        )

    installed_by_id = (
        {
            str(pack.get("id") or "").strip().casefold(): pack
            for pack in installed_content_packs
            if isinstance(pack, dict) and str(pack.get("id") or "").strip()
        }
        if isinstance(installed_content_packs, list)
        else {}
    )
    latest_pack_activity = {}
    recent_pack_recommended = False
    if installed_by_id:
        for event in learning_answer_events(cur):
            if scope is not None and event["question_id"] not in scope.eligible_question_ids:
                continue
            quiz = registry_by_quiz_id.get(str(event["quiz_id"] or ""))
            pack_id = quiz.get("source_pack_id") if quiz else None
            occurred_at = parse_datetime(event["occurred_at"])
            if not pack_id or pack_id not in installed_by_id or occurred_at is None:
                continue
            if event["question_id"] in covered_question_ids:
                continue
            previous = latest_pack_activity.get(pack_id)
            if previous is None or occurred_at > previous[0]:
                latest_pack_activity[pack_id] = (occurred_at, event)
    if latest_pack_activity:
        pack_id, (last_activity, _event) = max(
            latest_pack_activity.items(), key=lambda item: (item[1][0], item[0])
        )
        days_since = max(0, int((now - last_activity).total_seconds() // 86400))
        if days_since <= 30:
            pack = installed_by_id[pack_id]
            pack_name = str(pack.get("name") or pack_id).strip() or pack_id
            when = (
                "today"
                if days_since == 0
                else f"{days_since} day{'s' if days_since != 1 else ''} ago"
            )
            items.append(
                {
                    "id": f"study-pack-{pack_id}",
                    "kind": "study_pack",
                    "priority": 50,
                    "title": f"Continue {pack_name}",
                    "reason": (
                        f"Your most recent activity in this Study Pack was {when}."
                    ),
                    "action": {
                        "label": "Continue Study Pack",
                        "url": f"/study-packs?installed={pack_id}",
                        "method": "GET",
                        "fields": {},
                    },
                }
            )
            recent_pack_recommended = True

    items.sort(key=lambda item: (item["priority"], item["id"]))
    return {
        "items": items[:4],
        "summary": {
            "due_questions": len(due_questions),
            "next_due_batch_questions": next_due_batch_size,
            "overdue_questions": sum(
                question.get("schedule_state") == "overdue"
                for question in due_questions
            ),
            "weak_or_developing_concepts": len(concept_options),
            "adaptive_candidates": len(adaptive),
            "recent_study_pack": recent_pack_recommended,
        },
        "quiz_index": valid_registry,
        "empty_state": {
            "title": "Nothing needs immediate attention",
            "detail": (
                "Complete a quiz or begin a Study session to build today's "
                "recommendations."
            ),
            "action": {"label": "Browse Quiz Library", "url": "/library"},
        },
        "model": {
            "order": (
                "Due questions, weak/developing concepts, unfinished browser "
                "sessions, Adaptive Study, then recent Study Pack activity."
            ),
            "deduplication": (
                "Specific due or concept actions replace broader Adaptive Study "
                "suggestions when they would describe the same daily need."
            ),
        },
    }

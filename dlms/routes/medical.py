"""Medical Study catalog, matching, anatomy, and generation routes."""

import random
import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from typing import Any

from flask import Blueprint, flash, redirect, render_template, request, url_for


Dependency = Callable[..., Any]


@dataclass(frozen=True)
class MedicalRouteDependencies:
    discover_content_packs: Dependency
    is_medical_content_pack: Dependency
    load_content_pack_dataset: Dependency
    load_content_pack_image_dataset: Dependency
    content_pack_folder: Dependency
    get_content_pack: Dependency
    hotspot_concepts: Dependency
    standalone_matching_concepts: Dependency
    publish_quiz: Dependency


def _bind_dependencies(view_func, dependencies):
    @wraps(view_func)
    def bound_view(**view_args):
        return view_func(dependencies, **view_args)

    return bound_view


def _medical_pack_page_data(dependencies):
    discover_content_packs = dependencies.discover_content_packs
    _is_medical_content_pack = dependencies.is_medical_content_pack
    load_content_pack_dataset = dependencies.load_content_pack_dataset
    load_content_pack_image_dataset = dependencies.load_content_pack_image_dataset
    """Aggregate validated datasets from every installed medical-domain Study Pack."""
    packs = discover_content_packs()
    medical_packs = [
        (pack_id, candidate)
        for pack_id, candidate in packs.items()
        if _is_medical_content_pack(pack_id, candidate)
    ]
    if not medical_packs:
        return None, [], []

    # Keep the historical base pack first when installed, but never require it.
    medical_packs.sort(key=lambda item: (item[0] != "medical", str(item[1].get("name") or item[0]).casefold()))

    if len(medical_packs) == 1:
        pack = dict(medical_packs[0][1])
    else:
        pack = {
            "id": "medical_collection",
            "name": "DLMS Medical Study",
            "version": f"{len(medical_packs)} installed packs",
            "description": "Aggregated medical study content from installed Medical-domain Study Packs.",
        }

    datasets = []
    image_datasets = []

    for pack_id, source_pack in medical_packs:
        for descriptor in source_pack.get("datasets", []):
            if not isinstance(descriptor, dict):
                print(f"[MEDICAL PACK] Skipping invalid dataset descriptor in {pack_id!r}: {descriptor!r}")
                continue
            dataset_id = str(descriptor.get("id") or "").strip()
            try:
                data = load_content_pack_dataset(pack_id, dataset_id)
                datasets.append({
                    "pack_id": pack_id,
                    "pack_name": source_pack.get("name") or pack_id,
                    "id": dataset_id,
                    "title": descriptor.get("title") or data.get("title") or dataset_id,
                    "description": descriptor.get("description") or data.get("description") or "",
                    "type": descriptor.get("type") or data.get("type") or "matching",
                    "term_count": len(data.get("terms") or []),
                    "category": data.get("category") or "",
                })
            except Exception as exc:
                print(f"[MEDICAL PACK] Dataset {pack_id}/{dataset_id!r} unavailable: {exc}")

        for descriptor in source_pack.get("image_datasets", []):
            if not isinstance(descriptor, dict):
                print(f"[MEDICAL PACK] Skipping invalid image dataset descriptor in {pack_id!r}: {descriptor!r}")
                continue
            dataset_id = str(descriptor.get("id") or "").strip()
            try:
                data = load_content_pack_image_dataset(pack_id, dataset_id)
                image_count = len(data.get("images") or [])
                hotspot_count = sum(len(img.get("hotspots") or []) for img in (data.get("images") or []))
                image_datasets.append({
                    "pack_id": pack_id,
                    "pack_name": source_pack.get("name") or pack_id,
                    "id": dataset_id,
                    "title": descriptor.get("title") or data.get("title") or dataset_id,
                    "description": descriptor.get("description") or data.get("description") or "",
                    "image_count": image_count,
                    "hotspot_count": hotspot_count,
                    "category": data.get("category") or "Anatomy",
                })
            except Exception as exc:
                print(f"[MEDICAL PACK] Image dataset {pack_id}/{dataset_id!r} unavailable: {exc}")

    return pack, datasets, image_datasets

def _medical_not_installed(dependencies):
    CONTENT_PACK_FOLDER = dependencies.content_pack_folder()
    """Render Medical Study as an available feature even when no content is installed."""
    empty_pack = {
        "name": "Medical Study",
        "version": "No packs installed",
    }
    return render_template(
        "medical/empty.html",
        pack=empty_pack,
        pack_folder=CONTENT_PACK_FOLDER,
        medical_section="home",
    )

def medical_study_home(dependencies):
    pack, datasets, image_datasets = _medical_pack_page_data(dependencies)
    if not pack:
        return _medical_not_installed(dependencies)

    total_terms = sum(d["term_count"] for d in datasets)
    total_images = sum(d["image_count"] for d in image_datasets)
    total_hotspots = sum(d["hotspot_count"] for d in image_datasets)

    return render_template(
        "medical/index.html",
        pack=pack,
        datasets=datasets,
        image_datasets=image_datasets,
        total_terms=total_terms,
        total_images=total_images,
        total_hotspots=total_hotspots,
        medical_section="home",
    )

def medical_ai_content_builder(dependencies):
    """Compatibility entry point: use the unified Study Pack AI Builder."""
    query = {"domain": "Medical", "from": "medical"}
    topic = str(request.values.get("topic") or "").strip()
    if topic:
        query["topic"] = topic
    return redirect(url_for("study_packs.study_pack_ai_builder", **query))

def medical_matching(dependencies):
    pack, datasets, image_datasets = _medical_pack_page_data(dependencies)
    if not pack:
        return _medical_not_installed(dependencies)

    total_terms = sum(d["term_count"] for d in datasets)

    return render_template(
        "medical/matching.html",
        pack=pack,
        datasets=datasets,
        total_terms=total_terms,
        medical_section="matching",
    )

def medical_anatomy(dependencies):
    pack, datasets, image_datasets = _medical_pack_page_data(dependencies)
    if not pack:
        return _medical_not_installed(dependencies)

    total_images = sum(d["image_count"] for d in image_datasets)
    total_hotspots = sum(d["hotspot_count"] for d in image_datasets)
    image_framework = pack.get("image_framework") or {}

    return render_template(
        "medical/anatomy.html",
        pack=pack,
        image_datasets=image_datasets,
        total_images=total_images,
        total_hotspots=total_hotspots,
        image_framework=image_framework,
        medical_section="anatomy",
    )

def medical_generate_anatomy_quiz(dependencies):
    get_content_pack = dependencies.get_content_pack
    _is_medical_content_pack = dependencies.is_medical_content_pack
    load_content_pack_image_dataset = dependencies.load_content_pack_image_dataset
    _hotspot_concepts = dependencies.hotspot_concepts
    _publish_quiz = dependencies.publish_quiz
    pack_id = request.form.get("pack_id", "medical").strip().lower() or "medical"
    pack = get_content_pack(pack_id)
    if not pack or not _is_medical_content_pack(pack_id, pack):
        flash("Requested Medical Study content pack is not installed.", "error")
        return redirect("/content-packs")

    dataset_id = request.form.get("dataset_id", "").strip()
    try:
        data = load_content_pack_image_dataset(pack_id, dataset_id)
    except Exception as exc:
        print(f"[MEDICAL ANATOMY LOAD ERROR] {type(exc).__name__}: {exc}")
        flash("Unable to load the selected anatomy dataset.", "error")
        return redirect("/medical/anatomy")

    runtime_questions = []
    db_questions = []
    qnum = 1

    for image in data.get("images", []):
        image_url = url_for(
            "core.content_pack_asset",
            pack_id=pack_id,
            asset_path=image.get("file")
        )
        source = image.get("source") or data.get("source") or {}

        hotspots = list(image.get("hotspots") or [])
        random.shuffle(hotspots)

        for hotspot in hotspots:
            label = str(hotspot.get("label") or "").strip()
            if not label:
                continue
            prompt = str(hotspot.get("prompt") or f"Identify the {label}.").strip()
            concepts = _hotspot_concepts(
                hotspot,
                image,
                hotspot,
                data,
                context=f"medical anatomy hotspot {hotspot.get('id') or label!r}",
            )

            runtime_questions.append({
                "number": qnum,
                "type": "hotspot",
                "question": prompt,
                "image_url": image_url,
                "image_alt": image.get("alt_text") or data.get("title") or "Study image",
                "image_edits": image.get("edits") or [],
                "target": hotspot.get("shape") or {},
                "target_label": label,
                "explanation": hotspot.get("explanation") or "",
                "concepts": concepts,
                "verification": hotspot.get("verification") or {},
                "image_source": {
                    "organization": source.get("organization") or "",
                    "work": source.get("work") or "",
                    "url": source.get("url") or image.get("source_url") or "",
                    "license": source.get("license") or image.get("license") or "",
                    "attribution": source.get("attribution") or image.get("attribution") or "",
                }
            })

            # Database/history surrogate. Runtime scoring still uses hotspot geometry.
            db_questions.append({
                "number": qnum,
                "type": "choice",
                "question": prompt + " [Image hotspot]",
                "choices": [
                    {"label": "A", "text": label, "is_correct": True}
                ],
                "concepts": concepts,
                "source": {
                    "organization": source.get("organization") or "",
                    "dataset": data.get("title") or dataset_id,
                    "version": pack.get("version") or "",
                    "url": source.get("url") or image.get("source_url") or "",
                    "license": source.get("license") or image.get("license") or "",
                }
            })
            qnum += 1

    if not runtime_questions:
        flash("This anatomy dataset contains no usable hotspots.", "error")
        return redirect("/medical/anatomy")

    title = str(data.get("title") or data["_descriptor"].get("title") or "Medical Anatomy").strip()
    quiz_title = f"{title} — Hotspot Practice"

    safe_pack = re.sub(r"[^a-z0-9]+", "_", pack_id.lower()).strip("_") or "medical"
    safe_id = re.sub(r"[^a-z0-9]+", "_", dataset_id.lower()).strip("_") or "anatomy"
    quiz_id, html_name = _publish_quiz(
        quiz_title,
        runtime_questions,
        db_questions,
        filename_prefix=f"medical_anatomy_{safe_pack}_{safe_id}",
        exam_minutes=90,
        source_pack_id=pack_id,
        source_dataset_id=dataset_id,
    )

    return redirect(f"/quizzes/{html_name}")

def medical_generate_quiz(dependencies):
    get_content_pack = dependencies.get_content_pack
    _is_medical_content_pack = dependencies.is_medical_content_pack
    load_content_pack_dataset = dependencies.load_content_pack_dataset
    _standalone_matching_concepts = dependencies.standalone_matching_concepts
    _publish_quiz = dependencies.publish_quiz
    pack_id = request.form.get("pack_id", "medical").strip().lower() or "medical"
    pack = get_content_pack(pack_id)
    if not pack or not _is_medical_content_pack(pack_id, pack):
        flash("Requested Medical Study content pack is not installed.", "error")
        return redirect("/content-packs")

    dataset_id = request.form.get("dataset_id", "").strip()
    direction = request.form.get("direction", "random").strip()
    if direction not in {"term_to_definition", "definition_to_term", "random"}:
        direction = "random"

    try:
        data = load_content_pack_dataset(pack_id, dataset_id)
    except Exception as exc:
        print(f"[MEDICAL DATASET LOAD ERROR] {type(exc).__name__}: {exc}")
        flash("Unable to load the selected medical dataset.", "error")
        return redirect("/medical/matching")

    terms = data.get("terms") or []
    if len(terms) < 2:
        flash("This medical dataset does not contain enough terms.", "error")
        return redirect("/medical/matching")

    try:
        round_size = int(request.form.get("round_size", "10"))
    except (TypeError, ValueError):
        round_size = 10
    round_size = max(2, min(round_size, min(100, len(terms))))

    title = str(data.get("title") or data["_descriptor"].get("title") or "Medical Practice").strip()
    quiz_title = f"{title} — {round_size}-Pair Practice"
    source = data.get("source") or {}

    pairs = [
        {
            "left": item["term"],
            "right": item["definition"],
            "category": item.get("category", ""),
            "explanation": (
                item.get("explanation")
                or item.get("study_explanation")
                or ""
            ),
            "verification": item.get("verification") or data.get("verification") or {},
            "source": item.get("source") or source or {},
        }
        for item in terms
    ]
    quiz_data = [{
        "number": 1,
        "type": "matching",
        "question": str(data.get("question_text") or "Match each medical term with its correct definition.").strip(),
        "pairs": pairs,
        "round_size": round_size,
        "direction": direction,
        "concepts": _standalone_matching_concepts(
            data, context=f"matching dataset {dataset_id!r}"
        ),
        "source": {
            "organization": source.get("organization") or pack.get("publisher") or "",
            "dataset": source.get("dataset") or title,
            "version": source.get("version") or pack.get("version") or "",
            "url": source.get("url") or "",
            "license": source.get("license") or "",
        },
    }]

    safe_pack = re.sub(r"[^a-z0-9]+", "_", pack_id.lower()).strip("_") or "medical"
    safe_id = re.sub(r"[^a-z0-9]+", "_", dataset_id.lower()).strip("_") or "medical"
    quiz_id, html_name = _publish_quiz(
        quiz_title,
        quiz_data,
        filename_prefix=f"medical_{safe_pack}_{safe_id}",
        exam_minutes=90,
        source_pack_id=pack_id,
        source_dataset_id=dataset_id,
    )

    return redirect(f"/quizzes/{html_name}")

def create_medical_blueprint(dependencies: MedicalRouteDependencies) -> Blueprint:
    blueprint = Blueprint("medical", __name__)
    routes = (
        ("/medical", "medical_study_home", medical_study_home, ["GET"]),
        ("/medical/ai-builder", "medical_ai_content_builder", medical_ai_content_builder, ["GET", "POST"]),
        ("/medical/matching", "medical_matching", medical_matching, ["GET"]),
        ("/medical/anatomy", "medical_anatomy", medical_anatomy, ["GET"]),
        ("/medical/anatomy/generate", "medical_generate_anatomy_quiz", medical_generate_anatomy_quiz, ["POST"]),
        ("/medical/generate", "medical_generate_quiz", medical_generate_quiz, ["POST"]),
    )
    for rule, endpoint, view_func, methods in routes:
        blueprint.add_url_rule(
            rule,
            endpoint=endpoint,
            view_func=_bind_dependencies(view_func, dependencies),
            methods=methods,
        )
    return blueprint

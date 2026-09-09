"""Study Pack catalog, generation, AI-builder, and image-builder routes."""

import json
import os
import random
import re
import secrets
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from typing import Any

from flask import Blueprint, flash, redirect, render_template, request, send_from_directory, url_for
from werkzeug.utils import secure_filename


Dependency = Callable[..., Any]


@dataclass(frozen=True)
class StudyPackRouteDependencies:
    content_pack_ai_workflow: Dependency
    stage_content_pack_upload: Dependency
    discover_content_packs: Dependency
    study_pack_catalog_domain_group: Dependency
    load_content_pack_dataset: Dependency
    load_content_pack_image_dataset: Dependency
    load_content_pack_quiz_dataset: Dependency
    get_content_pack: Dependency
    quiz_dataset_runtime: Dependency
    create_quiz_from_runtime: Dependency
    publish_quiz: Dependency
    standalone_matching_concepts: Dependency
    hotspot_concepts: Dependency
    load_portal_config: Dependency
    default_study_content_pack_prompt: Dependency
    default_medical_study_pack_ai_addendum: Dependency
    safe_image_builder_draft: Dependency
    safe_pack_child: Dependency
    passive_pack_image_extensions: Dependency
    decode_raster_image: Dependency
    image_builder_draft_folder: Dependency
    image_builder_total_upload_max_bytes: Dependency
    raster_upload_max_bytes: Dependency
    store_raster_upload: Dependency
    create_image_study_pack: Dependency
    generated_quiz_artifact_identity: Dependency


def _bind_dependencies(view_func, dependencies):
    @wraps(view_func)
    def bound_view(**view_args):
        return view_func(dependencies, **view_args)

    return bound_view


def study_pack_ai_builder_import(dependencies):
    CONTENT_PACK_AI_WORKFLOW = dependencies.content_pack_ai_workflow()
    _stage_content_pack_upload = dependencies.stage_content_pack_upload
    """Return a completed AI-generated ZIP to the standard import pipeline."""
    try:
        token = _stage_content_pack_upload(
            request.files.get("pack_zip"), workflow=CONTENT_PACK_AI_WORKFLOW
        )
        return redirect(url_for("content_packs.content_pack_import_review", token=token))
    except Exception as exc:
        print(f"[AI STUDY PACK IMPORT ERROR] {type(exc).__name__}: {exc}")
        flash("Study Pack ZIP could not be validated. Check the local DLMS log for details.", "error")
        return redirect(url_for("study_packs.study_pack_ai_builder"))

def _study_pack_catalog(dependencies):
    discover_content_packs = dependencies.discover_content_packs
    study_pack_catalog_domain_group = dependencies.study_pack_catalog_domain_group
    load_content_pack_dataset = dependencies.load_content_pack_dataset
    load_content_pack_image_dataset = dependencies.load_content_pack_image_dataset
    load_content_pack_quiz_dataset = dependencies.load_content_pack_quiz_dataset
    result = []
    for pack_id, pack in discover_content_packs().items():
        datasets, image_datasets, quiz_datasets = [], [], []
        for d in pack.get("datasets") or []:
            if not isinstance(d, dict): continue
            did = str(d.get("id") or "").strip()
            if not did: continue
            try:
                data = load_content_pack_dataset(pack_id, did)
                datasets.append({"id": did, "title": d.get("title") or data.get("title") or did, "description": d.get("description") or data.get("description") or "", "term_count": len(data.get("terms") or []), "category": data.get("category") or ""})
            except Exception as exc:
                print(f"[STUDY PACKS] Skipping {pack_id}/{did}: {exc}")
        for d in pack.get("image_datasets") or []:
            if not isinstance(d, dict): continue
            did = str(d.get("id") or "").strip()
            if not did: continue
            try:
                data = load_content_pack_image_dataset(pack_id, did)
                images = data.get("images") or []
                image_datasets.append({"id": did, "title": d.get("title") or data.get("title") or did, "description": d.get("description") or data.get("description") or "", "image_count": len(images), "hotspot_count": sum(len(i.get("hotspots") or []) for i in images), "category": data.get("category") or "Image Study"})
            except Exception as exc:
                print(f"[STUDY PACKS] Skipping image {pack_id}/{did}: {exc}")
        for d in pack.get("quiz_datasets") or []:
            if not isinstance(d, dict): continue
            did = str(d.get("id") or "").strip()
            if not did: continue
            try:
                data = load_content_pack_quiz_dataset(pack_id, did)
                qs, images = data.get("questions") or [], data.get("images") or []
                quiz_datasets.append({"id": did, "title": d.get("title") or data.get("title") or did, "description": d.get("description") or data.get("description") or "", "question_count": len(qs), "image_count": len(images), "hotspot_count": sum(1 for q in qs if str(q.get("type") or "") == "hotspot"), "category": data.get("category") or "Question Set"})
            except Exception as exc:
                print(f"[STUDY PACKS] Skipping questions {pack_id}/{did}: {exc}")
        if datasets or image_datasets or quiz_datasets:
            result.append({"id": pack_id, "name": pack.get("name") or pack_id, "version": pack.get("version") or "", "description": pack.get("description") or "", "domain": pack.get("content_domain") or ("medical" if pack_id == "medical" else "general"), "domain_group": study_pack_catalog_domain_group(pack_id, pack), "datasets": datasets, "image_datasets": image_datasets, "quiz_datasets": quiz_datasets})
    return sorted(result, key=lambda p: p["name"].casefold())

def study_packs_home(dependencies):
    packs = _study_pack_catalog(dependencies)
    domain_group = str(request.args.get("domain_group") or "").strip().lower()
    requested_installed_id = str(request.args.get("installed") or "").strip().lower()
    other_mode = domain_group == "other"
    if other_mode:
        packs = [pack for pack in packs if pack.get("domain_group") == "other"]
    total_pack_count = len(packs)
    domain_filter_counts = {
        group: sum(1 for pack in packs if pack.get("domain_group") == group)
        for group in ("it", "medical", "other")
    }
    domain_filter_counts = {
        group: count for group, count in domain_filter_counts.items() if count
    }
    installed_pack_id = next(
        (pack["id"] for pack in packs if pack["id"] == requested_installed_id), ""
    )
    return render_template(
        "study_packs/catalog.html",
        packs=packs,
        medical_pack_installed=True,
        other_mode=other_mode,
        installed_pack_id=installed_pack_id,
        total_pack_count=total_pack_count,
        domain_filter_counts=domain_filter_counts,
    )

def study_pack_generate_quiz_dataset(dependencies):
    get_content_pack = dependencies.get_content_pack
    load_content_pack_quiz_dataset = dependencies.load_content_pack_quiz_dataset
    _quiz_dataset_runtime = dependencies.quiz_dataset_runtime
    _create_quiz_from_runtime = dependencies.create_quiz_from_runtime
    pack_id = str(request.form.get("pack_id") or "").strip().lower()
    dataset_id = str(request.form.get("dataset_id") or "").strip()
    pack = get_content_pack(pack_id)
    if not pack:
        flash("Study pack is not installed.", "error")
        return redirect("/study-packs")
    try:
        data = load_content_pack_quiz_dataset(pack_id, dataset_id)
        runtime_questions, db_questions = _quiz_dataset_runtime(pack_id, data)
        title = str(data.get("title") or data["_descriptor"].get("title") or "Study Questions").strip()
        _, html_name = _create_quiz_from_runtime(
            f"{title} — Practice", runtime_questions, db_questions,
            filename_prefix=f"study_questions_{pack_id}_{dataset_id}", exam_minutes=90,
            source_pack_id=pack_id, source_dataset_id=dataset_id
        )
        return redirect(f"/quizzes/{html_name}")
    except Exception as exc:
        print(f"[STUDY PACK QUIZ BUILD ERROR] {type(exc).__name__}: {exc}")
        flash("Unable to build the selected Study Pack quiz.", "error")
        return redirect("/study-packs")

def study_pack_generate_matching(dependencies):
    get_content_pack = dependencies.get_content_pack
    load_content_pack_dataset = dependencies.load_content_pack_dataset
    _standalone_matching_concepts = dependencies.standalone_matching_concepts
    _publish_quiz = dependencies.publish_quiz
    pack_id=str(request.form.get("pack_id") or "").strip().lower(); dataset_id=str(request.form.get("dataset_id") or "").strip(); direction=str(request.form.get("direction") or "random").strip()
    if direction not in {"term_to_definition","definition_to_term","random"}: direction="random"
    pack=get_content_pack(pack_id)
    if not pack: flash("Study pack is not installed.","error"); return redirect("/study-packs")
    try: data=load_content_pack_dataset(pack_id,dataset_id)
    except Exception as exc:
        print(f"[STUDY PACK DATASET LOAD ERROR] {type(exc).__name__}: {exc}")
        flash("Unable to load the selected study dataset.", "error")
        return redirect("/study-packs")
    terms=data.get("terms") or []
    if len(terms)<2: flash("This dataset does not contain enough items.","error"); return redirect("/study-packs")
    try: round_size=int(request.form.get("round_size","10"))
    except (TypeError,ValueError): round_size=10
    round_size=max(2,min(round_size,min(100,len(terms))))
    title=str(data.get("title") or data["_descriptor"].get("title") or "Study Practice").strip(); source=data.get("source") or {}
    pairs=[{"left":i["term"],"right":i["definition"],"category":i.get("category","") ,"explanation":i.get("explanation") or i.get("study_explanation") or "","verification":i.get("verification") or data.get("verification") or {},"source":i.get("source") or source or {}} for i in terms]
    quiz_data=[{"number":1,"type":"matching","question":str(data.get("question_text") or "Match each item with its best answer.").strip(),"pairs":pairs,"round_size":round_size,"direction":direction,"concepts":_standalone_matching_concepts(data, context=f"matching dataset {dataset_id!r}"),"source":{"organization":source.get("organization") or pack.get("publisher") or "","dataset":source.get("dataset") or title,"version":source.get("version") or pack.get("version") or "","url":source.get("url") or "","license":source.get("license") or ""}}]
    safe_pack=re.sub(r"[^a-z0-9]+","_",pack_id).strip("_") or "study"; safe_id=re.sub(r"[^a-z0-9]+","_",dataset_id.lower()).strip("_") or "dataset"; quiz_title=f"{title} — {round_size}-Pair Practice"
    quiz_id,html_name=_publish_quiz(quiz_title,quiz_data,filename_prefix=f"study_{safe_pack}_{safe_id}",exam_minutes=90,source_pack_id=pack_id,source_dataset_id=dataset_id)
    return redirect(f"/quizzes/{html_name}")

def study_pack_generate_image(dependencies):
    get_content_pack = dependencies.get_content_pack
    load_content_pack_image_dataset = dependencies.load_content_pack_image_dataset
    _hotspot_concepts = dependencies.hotspot_concepts
    _publish_quiz = dependencies.publish_quiz
    pack_id=str(request.form.get("pack_id") or "").strip().lower(); dataset_id=str(request.form.get("dataset_id") or "").strip(); pack=get_content_pack(pack_id)
    if not pack: flash("Study pack is not installed.","error"); return redirect("/study-packs")
    try: data=load_content_pack_image_dataset(pack_id,dataset_id)
    except Exception as exc:
        print(f"[STUDY PACK IMAGE LOAD ERROR] {type(exc).__name__}: {exc}")
        flash("Unable to load the selected image dataset.", "error")
        return redirect("/study-packs")
    runtime_questions=[]; db_questions=[]; qnum=1
    for image in data.get("images") or []:
        image_url=url_for("core.content_pack_asset",pack_id=pack_id,asset_path=image.get("file")); source=image.get("source") or data.get("source") or {}; hotspots=list(image.get("hotspots") or []); random.shuffle(hotspots)
        for hotspot in hotspots:
            label=str(hotspot.get("label") or "").strip()
            if not label: continue
            prompt=str(hotspot.get("prompt") or f"Identify {label}.").strip()
            runtime_questions.append({"number":qnum,"type":"hotspot","question":prompt,"image_url":image_url,"image_alt":image.get("alt_text") or data.get("title") or "Study image","image_edits":image.get("edits") or [],"target":hotspot.get("shape") or {},"target_label":label,"explanation":hotspot.get("explanation") or "","verification":hotspot.get("verification") or {},"image_source":{"organization":source.get("organization") or "","work":source.get("work") or "","url":source.get("url") or image.get("source_url") or "","license":source.get("license") or image.get("license") or "","attribution":source.get("attribution") or image.get("attribution") or ""}})
            concepts=_hotspot_concepts(hotspot, image, hotspot, data, context=f"image dataset hotspot {hotspot.get('id') or label!r}")
            runtime_questions[-1]["concepts"]=concepts
            db_questions.append({"number":qnum,"type":"choice","question":prompt+" [Image hotspot]","choices":[{"label":"A","text":label,"is_correct":True}],"concepts":concepts,"source":{"organization":source.get("organization") or "","dataset":data.get("title") or dataset_id,"version":pack.get("version") or "","url":source.get("url") or image.get("source_url") or "","license":source.get("license") or image.get("license") or ""}}); qnum+=1
    if not runtime_questions: flash("This image dataset contains no usable targets.","error"); return redirect("/study-packs")
    title=str(data.get("title") or data["_descriptor"].get("title") or "Image Study").strip(); quiz_title=f"{title} — Image Practice"; safe_pack=re.sub(r"[^a-z0-9]+","_",pack_id).strip("_") or "study"; safe_id=re.sub(r"[^a-z0-9]+","_",dataset_id.lower()).strip("_") or "images"
    quiz_id,html_name=_publish_quiz(quiz_title,runtime_questions,db_questions,filename_prefix=f"study_image_{safe_pack}_{safe_id}",exam_minutes=90,source_pack_id=pack_id,source_dataset_id=dataset_id)
    return redirect(f"/quizzes/{html_name}")

def study_pack_ai_builder(dependencies):
    load_portal_config = dependencies.load_portal_config
    DEFAULT_STUDY_CONTENT_PACK_PROMPT = dependencies.default_study_content_pack_prompt()
    DEFAULT_MEDICAL_STUDY_PACK_AI_ADDENDUM = dependencies.default_medical_study_pack_ai_addendum()
    cfg = load_portal_config()

    allowed_domains = ["IT / Cybersecurity", "General", "Science", "Medical", "History", "Language", "Other"]
    requested_domain = str(request.args.get("domain") or "").strip()
    domain = requested_domain if requested_domain in allowed_domains else "IT / Cybersecurity"
    from_section = str(request.args.get("from") or "").strip().lower()

    topic = str(request.args.get("topic") or "").strip()
    difficulty = "Foundational" if domain == "Medical" else "Intermediate"
    size = "Standard"
    image_count = "2–3"
    image_style = "Mixed"
    include_matching = True
    include_images = True
    include_multiple_choice = False
    generated_prompt = ""

    ai_provider = str(cfg.get("ai_provider") or "chatgpt").strip().lower()
    if ai_provider not in {"chatgpt","claude","gemini","local"}:
        ai_provider = "chatgpt"

    if request.method == "POST":
        topic = str(request.form.get("topic") or "").strip()
        domain = str(request.form.get("domain") or "General").strip()
        if domain not in allowed_domains:
            domain = "General"
        difficulty = str(request.form.get("difficulty") or "Intermediate").strip()
        size = str(request.form.get("size") or "Standard").strip()
        image_count = str(request.form.get("image_count") or "2–3").strip()
        image_style = str(request.form.get("image_style") or "Mixed").strip()
        ai_provider = str(request.form.get("ai_provider") or ai_provider).strip().lower()
        from_section = str(request.form.get("from_section") or "").strip().lower()

        include_matching = "include_matching" in request.form
        include_images = "include_images" in request.form
        include_multiple_choice = "include_multiple_choice" in request.form

        if difficulty not in {"Foundational","Intermediate","Comprehensive"}:
            difficulty = "Intermediate"
        if size not in {"Compact","Standard","Large"}:
            size = "Standard"
        if image_count not in {"None","1","2–3","4–6"}:
            image_count = "2–3"
        if image_style not in {"Real / photographic","Diagram / schematic","Drawn educational illustration","Mixed"}:
            image_style = "Mixed"
        if ai_provider not in {"chatgpt","claude","gemini","local"}:
            ai_provider = "chatgpt"

        requested = []
        if include_matching:
            requested.append(
                "Create one or more high-quality matching datasets with unique terms, unique record IDs where IDs are used, "
                "one-to-one term/answer mappings, meaningfully distinct answers, no duplicate or near-duplicate pairs, "
                "and enough semantic distinction to remain unambiguous when shuffled. Repair all collisions before delivery, "
                "and include source-supported Study Mode explanations."
            )
        if include_multiple_choice:
            mcq_counts = {
                "Compact": "about 10–15",
                "Standard": "about 20–30",
                "Large": "about 40–60",
            }
            requested.append(
                f"Create {mcq_counts[size]} source-supported single-select multiple-choice questions. "
                "Use the DLMS choice-question JSON contract: 2–26 distinct choices, exactly one true "
                "JSON is_correct value, a concise explanation, and question-level source support. "
                "Vary the supplied correct-choice position naturally across the question set; do not put "
                "every correct answer in the same position and do not force perfect equality. "
                "Do not guess: omit any question whose correct answer cannot be supported reliably."
            )
        if include_images:
            requested.append("Create image/diagram hotspot datasets when they genuinely improve learning, following the image count and style request below.")
        if not requested:
            requested.append("Choose the most appropriate DLMS study content types for this topic.")
        requested.append(
            "For every generated question, include the exact question-level field \"concepts\" with 1–3 "
            "specific reusable concepts. Reuse spelling for the same skill; avoid broad metadata labels."
        )

        size_map = {
            "Compact": "Keep the pack focused: about 20–40 high-value matching items per dataset.",
            "Standard": "Aim for useful depth: about 40–80 distinct matching items per dataset when supported.",
            "Large": "Build broad coverage without padding; split large subjects into multiple focused datasets."
        }

        if include_images and image_count != "None":
            image_guidance = (
                f"Request {image_count} useful image(s) when possible. Preferred style: {image_style}. "
                "Bundle exact legally reusable images and create separate hotspot lists for each image. "
                "If multiple images cover different subtopics, create separate image datasets."
            )
        else:
            image_guidance = "Do not create image datasets for this request."

        domain_slug = re.sub(r"[^a-z0-9]+","_",domain.lower()).strip("_") or "general"

        if topic:
            study_pack_template = str(cfg.get("study_pack_ai_prompt_template") or DEFAULT_STUDY_CONTENT_PACK_PROMPT)
            medical_addendum = str(cfg.get("medical_study_pack_ai_addendum") or DEFAULT_MEDICAL_STUDY_PACK_AI_ADDENDUM)
            generated_prompt = (
                study_pack_template
                .replace("{{domain}}", domain)
                .replace("{{domain_slug}}", domain_slug)
                .replace("{{topic}}", topic)
                .replace("{{content_request}}", "\n".join(f"- {x}" for x in requested))
                .replace("{{difficulty}}", difficulty)
                .replace("{{size_guidance}}", size_map.get(size, size_map["Standard"]))
                .replace("{{image_guidance}}", image_guidance)
            )
            if domain == "Medical":
                generated_prompt += "\n\n" + medical_addendum.strip()
        else:
            generated_prompt = "Enter a study topic before generating the prompt."

    providers = {
        "chatgpt":"https://chatgpt.com/",
        "claude":"https://claude.ai/",
        "gemini":"https://gemini.google.com/",
        "local":str(cfg.get("ai_custom_url") or "").strip()
    }
    ai_url = providers.get(ai_provider,"")
    if from_section == "medical" or domain == "Medical":
        back_url, back_label = "/medical", "Medical Study"
    elif from_section == "other":
        back_url, back_label = "/study-packs?domain_group=other", "Other Studies"
    else:
        back_url, back_label = "/study-packs", "Study Packs"

    return render_template("study_packs/ai-builder.html",
        topic=topic,
        domain=domain,
        domains=allowed_domains,
        difficulty=difficulty,
        size=size,
        image_count=image_count,
        image_style=image_style,
        ai_provider=ai_provider,
        include_matching=include_matching,
        include_images=include_images,
        include_multiple_choice=include_multiple_choice,
        generated_prompt=generated_prompt,
        ai_url=ai_url,
        from_section=from_section,
        back_url=back_url,
        back_label=back_label,
        medical_pack_installed=True,
    )

def image_builder_draft_asset(dependencies, draft_id, filename):
    _safe_image_builder_draft = dependencies.safe_image_builder_draft
    _safe_pack_child = dependencies.safe_pack_child
    PASSIVE_PACK_IMAGE_EXTENSIONS = dependencies.passive_pack_image_extensions()
    _decode_raster_image = dependencies.decode_raster_image
    try:
        draft_root = _safe_image_builder_draft(draft_id)
        file_path = _safe_pack_child(draft_root, filename)
    except Exception:
        return "Draft image not found", 404
    if not os.path.isfile(file_path):
        return "Draft image not found", 404
    if os.path.splitext(file_path)[1].lower() not in PASSIVE_PACK_IMAGE_EXTENSIONS:
        return "Unsupported image", 415
    try:
        _decode_raster_image(file_path, PASSIVE_PACK_IMAGE_EXTENSIONS)
    except ValueError:
        return "Invalid draft image", 415
    return send_from_directory(draft_root, os.path.relpath(file_path, draft_root))

def image_quiz_builder(dependencies):
    IMAGE_BUILDER_DRAFT_FOLDER = dependencies.image_builder_draft_folder()
    IMAGE_BUILDER_TOTAL_UPLOAD_MAX_BYTES = dependencies.image_builder_total_upload_max_bytes()
    RASTER_UPLOAD_MAX_BYTES = dependencies.raster_upload_max_bytes()
    PASSIVE_PACK_IMAGE_EXTENSIONS = dependencies.passive_pack_image_extensions()
    _store_raster_upload = dependencies.store_raster_upload
    draft = None
    if request.method == "POST":
        files = [f for f in request.files.getlist("study_images") if f and f.filename]
        if not files:
            flash("Choose at least one image.", "error")
            return redirect("/study-packs/image-builder")
        if len(files) > 12:
            flash("Upload at most 12 images at one time.", "error")
            return redirect("/study-packs/image-builder")

        draft_id = f"{int(time.time())}_{secrets.token_hex(5)}"
        draft_root = os.path.join(IMAGE_BUILDER_DRAFT_FOLDER, draft_id)
        os.makedirs(draft_root, exist_ok=False)
        images, used = [], set()
        remaining_upload_bytes = IMAGE_BUILDER_TOTAL_UPLOAD_MAX_BYTES
        for n, uploaded in enumerate(files, 1):
            original = secure_filename(uploaded.filename or "")
            ext = os.path.splitext(original)[1].lower()
            if ext not in {".png", ".jpg", ".jpeg", ".webp"}:
                shutil.rmtree(draft_root, ignore_errors=True)
                flash("Images must be PNG, JPG/JPEG, or WEBP.", "error")
                return redirect("/study-packs/image-builder")
            base = re.sub(r"[^A-Za-z0-9_-]+", "_", os.path.splitext(original)[0]).strip("_") or f"image_{n}"
            filename = f"{base}{ext}"
            counter = 2
            while filename.casefold() in used:
                filename = f"{base}_{counter}{ext}"
                counter += 1
            used.add(filename.casefold())
            try:
                _store_raster_upload(
                    uploaded, draft_root, filename, PASSIVE_PACK_IMAGE_EXTENSIONS,
                    min(RASTER_UPLOAD_MAX_BYTES, remaining_upload_bytes),
                )
                remaining_upload_bytes -= int(getattr(uploaded, "_dlms_consumed_bytes", 0))
            except ValueError as exc:
                shutil.rmtree(draft_root, ignore_errors=True)
                flash(f"Image {uploaded.filename!r} was rejected: {exc}", "error")
                return redirect("/study-packs/image-builder")
            images.append({
                "id": f"image_{n}", "filename": filename,
                "original_name": uploaded.filename,
                "url": url_for("study_packs.image_builder_draft_asset", draft_id=draft_id, filename=filename),
            })
        draft = {"id": draft_id, "images": images}

    return render_template(
        "study_packs/image-builder.html", draft=draft,
        medical_pack_installed=True
    )

def image_quiz_builder_save(dependencies):
    _safe_image_builder_draft = dependencies.safe_image_builder_draft
    _create_image_study_pack = dependencies.create_image_study_pack
    _generated_quiz_artifact_identity = dependencies.generated_quiz_artifact_identity
    draft_id = str(request.form.get("draft_id") or "").strip()
    title = str(request.form.get("pack_title") or "").strip()
    subject = str(request.form.get("subject") or "General").strip()
    description = str(request.form.get("description") or "").strip()
    source_note = str(request.form.get("source_note") or "").strip()
    rights_ok = bool(request.form.get("rights_ok"))
    if not title:
        return "Study pack title is required", 400
    if not rights_ok:
        return "Confirm permission to use the uploaded images.", 400

    try:
        draft_root = _safe_image_builder_draft(draft_id)
        payload = json.loads(str(request.form.get("builder_payload") or ""))
    except Exception as exc:
        print(f"[IMAGE BUILDER INPUT ERROR] {type(exc).__name__}: {exc}")
        return "Invalid image-builder data. Restart the image workflow and try again.", 400

    images_payload = payload.get("images") or []
    questions_payload = payload.get("questions") or []
    if not images_payload or not questions_payload:
        return "At least one image and one question are required.", 400

    try:
        result = _create_image_study_pack(
            draft_root=draft_root,
            title=title,
            subject=subject,
            description=description,
            source_note=source_note,
            images_payload=images_payload,
            questions_payload=questions_payload,
            artifact_identity=_generated_quiz_artifact_identity(),
            exam_minutes=request.form.get("exam_minutes"),
        )
        flash("Image study pack and quiz created successfully.", "success")
        return redirect(f"/quizzes/{result['html_name']}")
    except Exception as exc:
        print(f"[IMAGE BUILDER CREATE ERROR] {type(exc).__name__}: {exc}")
        return "Unable to create the image Study Pack. Check the local DLMS log for details.", 400

def create_study_packs_blueprint(dependencies: StudyPackRouteDependencies) -> Blueprint:
    blueprint = Blueprint("study_packs", __name__)
    routes = (
        ("/study-packs/ai-builder/import", "study_pack_ai_builder_import", study_pack_ai_builder_import, ["POST"]),
        ("/study-packs", "study_packs_home", study_packs_home, ["GET"]),
        ("/study-packs/quiz/generate", "study_pack_generate_quiz_dataset", study_pack_generate_quiz_dataset, ["POST"]),
        ("/study-packs/generate", "study_pack_generate_matching", study_pack_generate_matching, ["POST"]),
        ("/study-packs/image/generate", "study_pack_generate_image", study_pack_generate_image, ["POST"]),
        ("/study-packs/ai-builder", "study_pack_ai_builder", study_pack_ai_builder, ["GET", "POST"]),
        ("/image-builder/drafts/<draft_id>/<path:filename>", "image_builder_draft_asset", image_builder_draft_asset, ["GET"]),
        ("/study-packs/image-builder", "image_quiz_builder", image_quiz_builder, ["GET", "POST"]),
        ("/study-packs/image-builder/save", "image_quiz_builder_save", image_quiz_builder_save, ["POST"]),
    )
    for rule, endpoint, view_func, methods in routes:
        blueprint.add_url_rule(
            rule,
            endpoint=endpoint,
            view_func=_bind_dependencies(view_func, dependencies),
            methods=methods,
        )
    return blueprint

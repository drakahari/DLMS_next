"""Read-only IT Study routes."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from flask import Blueprint, render_template


@dataclass(frozen=True)
class ITStudyDependencies:
    """Configured application services required by the IT Study routes."""

    discover_content_packs: Callable[[], dict[str, dict[str, Any]]]
    load_content_pack_dataset: Callable[[str, str], dict[str, Any]]
    load_content_pack_image_dataset: Callable[[str, str], dict[str, Any]]
    load_content_pack_quiz_dataset: Callable[[str, str], dict[str, Any]]
    is_it_pack_manifest: Callable[[str, dict[str, Any]], bool]


def _it_pack_page_data(dependencies: ITStudyDependencies):
    """Aggregate validated datasets from installed IT / Cybersecurity Study Packs."""
    packs = dependencies.discover_content_packs()
    it_packs = [
        (pack_id, candidate)
        for pack_id, candidate in packs.items()
        if dependencies.is_it_pack_manifest(pack_id, candidate)
    ]
    it_packs.sort(key=lambda item: str(item[1].get("name") or item[0]).casefold())

    if not it_packs:
        return None, [], [], []

    if len(it_packs) == 1:
        pack = dict(it_packs[0][1])
    else:
        pack = {
            "id": "it_collection",
            "name": "DLMS IT Study",
            "version": f"{len(it_packs)} installed packs",
            "description": "Aggregated IT and cybersecurity study content from installed Study Packs.",
        }

    datasets, image_datasets, quiz_datasets = [], [], []
    for pack_id, source_pack in it_packs:
        for descriptor in source_pack.get("datasets") or []:
            if not isinstance(descriptor, dict):
                continue
            dataset_id = str(descriptor.get("id") or "").strip()
            try:
                data = dependencies.load_content_pack_dataset(pack_id, dataset_id)
                datasets.append({
                    "pack_id": pack_id,
                    "pack_name": source_pack.get("name") or pack_id,
                    "id": dataset_id,
                    "title": descriptor.get("title") or data.get("title") or dataset_id,
                    "description": descriptor.get("description") or data.get("description") or "",
                    "type": descriptor.get("type") or data.get("type") or "matching",
                    "term_count": len(data.get("terms") or []),
                    "category": data.get("category") or "IT / Cybersecurity",
                })
            except Exception as exc:
                print(f"[IT STUDY] Dataset {pack_id}/{dataset_id!r} unavailable: {exc}")

        for descriptor in source_pack.get("image_datasets") or []:
            if not isinstance(descriptor, dict):
                continue
            dataset_id = str(descriptor.get("id") or "").strip()
            try:
                data = dependencies.load_content_pack_image_dataset(pack_id, dataset_id)
                images = data.get("images") or []
                image_datasets.append({
                    "pack_id": pack_id,
                    "pack_name": source_pack.get("name") or pack_id,
                    "id": dataset_id,
                    "title": descriptor.get("title") or data.get("title") or dataset_id,
                    "description": descriptor.get("description") or data.get("description") or "",
                    "image_count": len(images),
                    "hotspot_count": sum(len(im.get("hotspots") or []) for im in images if isinstance(im, dict)),
                    "category": data.get("category") or "Diagrams & Images",
                })
            except Exception as exc:
                print(f"[IT STUDY] Image dataset {pack_id}/{dataset_id!r} unavailable: {exc}")

        for descriptor in source_pack.get("quiz_datasets") or []:
            if not isinstance(descriptor, dict):
                continue
            dataset_id = str(descriptor.get("id") or "").strip()
            try:
                data = dependencies.load_content_pack_quiz_dataset(pack_id, dataset_id)
                quiz_datasets.append({
                    "pack_id": pack_id,
                    "pack_name": source_pack.get("name") or pack_id,
                    "id": dataset_id,
                    "title": descriptor.get("title") or data.get("title") or dataset_id,
                    "description": descriptor.get("description") or data.get("description") or "",
                    "question_count": len(data.get("questions") or []),
                    "image_count": len(data.get("images") or []),
                    "category": data.get("category") or "Question Set",
                })
            except Exception as exc:
                print(f"[IT STUDY] Question dataset {pack_id}/{dataset_id!r} unavailable: {exc}")

    return pack, datasets, image_datasets, quiz_datasets


def _it_empty_page():
    pack = {"name": "IT Study", "version": "No packs installed"}
    return render_template(
        "it/empty.html",
        pack=pack,
        it_section="home",
    )


def create_it_blueprint(dependencies: ITStudyDependencies) -> Blueprint:
    """Create the IT Study Blueprint with configured content-pack services."""
    blueprint = Blueprint("it", __name__, url_prefix="/it")

    @blueprint.get("")
    def it_study_home():
        pack, datasets, image_datasets, quiz_datasets = _it_pack_page_data(dependencies)
        if not pack:
            return _it_empty_page()
        total_terms = sum(d["term_count"] for d in datasets)
        total_images = sum(d["image_count"] for d in image_datasets)
        total_hotspots = sum(d["hotspot_count"] for d in image_datasets)
        total_questions = sum(d["question_count"] for d in quiz_datasets)
        return render_template(
            "it/index.html",
            pack=pack,
            datasets=datasets,
            image_datasets=image_datasets,
            quiz_datasets=quiz_datasets,
            total_terms=total_terms,
            total_images=total_images,
            total_hotspots=total_hotspots,
            total_questions=total_questions,
            pack_count=len([
                1
                for pack_id, candidate in dependencies.discover_content_packs().items()
                if dependencies.is_it_pack_manifest(pack_id, candidate)
            ]),
            it_section="home",
        )

    @blueprint.get("/matching")
    def it_matching():
        pack, datasets, image_datasets, quiz_datasets = _it_pack_page_data(dependencies)
        if not pack:
            return _it_empty_page()
        total_terms = sum(d["term_count"] for d in datasets)
        return render_template(
            "it/matching.html",
            pack=pack,
            datasets=datasets,
            total_terms=total_terms,
            it_section="matching",
        )

    @blueprint.get("/images")
    def it_images():
        pack, datasets, image_datasets, quiz_datasets = _it_pack_page_data(dependencies)
        if not pack:
            return _it_empty_page()
        total_images = sum(d["image_count"] for d in image_datasets)
        total_hotspots = sum(d["hotspot_count"] for d in image_datasets)
        return render_template(
            "it/images.html",
            pack=pack,
            image_datasets=image_datasets,
            total_images=total_images,
            total_hotspots=total_hotspots,
            it_section="images",
        )

    return blueprint

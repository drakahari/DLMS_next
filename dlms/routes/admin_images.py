"""Administrative image and hotspot editor routes."""

import json
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from functools import wraps
from typing import Any

from flask import Blueprint, jsonify, render_template, request, url_for


Dependency = Callable[..., Any]


@dataclass(frozen=True)
class AdminImageRouteDependencies:
    discover_content_packs: Dependency
    load_content_pack_image_dataset: Dependency
    load_content_pack_quiz_dataset: Dependency
    validate_hotspot_shape: Dependency
    get_content_pack: Dependency
    safe_pack_child: Dependency


def _bind_dependencies(view_func, dependencies):
    @wraps(view_func)
    def bound_view(**view_args):
        return view_func(dependencies, **view_args)

    return bound_view


def _hotspot_editor_catalog(dependencies):
    discover_content_packs = dependencies.discover_content_packs
    load_content_pack_image_dataset = dependencies.load_content_pack_image_dataset
    load_content_pack_quiz_dataset = dependencies.load_content_pack_quiz_dataset
    catalog = []
    for pack_id, pack in discover_content_packs().items():
        for kind, key in (("hotspot", "image_datasets"), ("quiz", "quiz_datasets")):
            for descriptor in (pack.get(key) or []):
                dataset_id = str(descriptor.get("id") or "").strip()
                if not dataset_id:
                    continue
                try:
                    data = load_content_pack_image_dataset(pack_id, dataset_id) if kind == "hotspot" else load_content_pack_quiz_dataset(pack_id, dataset_id)
                except Exception as exc:
                    print(f"[IMAGE EDITOR] Unable to load {pack_id}/{kind}/{dataset_id}: {exc}")
                    continue
                images = data.get("images") or []
                if not images:
                    continue
                catalog.append({
                    "pack_id": pack_id,
                    "pack_name": pack.get("name") or pack_id,
                    "dataset_id": dataset_id,
                    "dataset_kind": kind,
                    "title": descriptor.get("title") or data.get("title") or dataset_id,
                    "images": len(images),
                    "hotspots": sum(len(im.get("hotspots") or []) for im in images if isinstance(im, dict)),
                })
    return catalog

def admin_hotspot_editor(dependencies):
    load_content_pack_image_dataset = dependencies.load_content_pack_image_dataset
    load_content_pack_quiz_dataset = dependencies.load_content_pack_quiz_dataset
    catalog = _hotspot_editor_catalog(dependencies)
    selected_pack = request.args.get("pack", "").strip()
    selected_dataset = request.args.get("dataset", "").strip()
    selected_kind = request.args.get("kind", "").strip().lower()
    if selected_kind not in {"hotspot", "quiz"}:
        selected_kind = ""
    if (not selected_pack or not selected_dataset) and catalog:
        selected_pack = catalog[0]["pack_id"]
        selected_dataset = catalog[0]["dataset_id"]
        selected_kind = catalog[0]["dataset_kind"]
    if not selected_kind and selected_pack and selected_dataset:
        match = next((c for c in catalog if c["pack_id"] == selected_pack and c["dataset_id"] == selected_dataset), None)
        selected_kind = (match or {}).get("dataset_kind") or "hotspot"

    editor_data = None
    load_error = None
    if selected_pack and selected_dataset:
        try:
            data = load_content_pack_quiz_dataset(selected_pack, selected_dataset) if selected_kind == "quiz" else load_content_pack_image_dataset(selected_pack, selected_dataset)
            images = []
            for image in data.get("images") or []:
                images.append({
                    "id": image.get("id") or image.get("file"),
                    "file": image.get("file") or "",
                    "url": url_for("core.content_pack_asset", pack_id=selected_pack, asset_path=image.get("file")),
                    "alt_text": image.get("alt_text") or data.get("title") or "Study image",
                    "hotspots": image.get("hotspots") or [],
                    "edits": image.get("edits") or [],
                })
            editor_data = {
                "pack_id": selected_pack, "dataset_id": selected_dataset,
                "dataset_kind": selected_kind, "title": data.get("title") or selected_dataset,
                "images": images,
            }
        except Exception as exc:
            print(f"[IMAGE EDITOR LOAD ERROR] {type(exc).__name__}: {exc}")
            load_error = "The selected image dataset could not be loaded. Check the local DLMS log for details."
    return render_template(
        "admin/image-editor.html",
        catalog=catalog, selected_pack=selected_pack, selected_dataset=selected_dataset,
        selected_kind=selected_kind, editor_data=editor_data, load_error=load_error,
        medical_pack_installed=True,
    )

def admin_hotspot_save(dependencies):
    _validate_hotspot_shape = dependencies.validate_hotspot_shape
    get_content_pack = dependencies.get_content_pack
    _safe_pack_child = dependencies.safe_pack_child
    payload=request.get_json(force=True) or {}
    pack_id=str(payload.get("pack_id") or "").strip().lower()
    dataset_id=str(payload.get("dataset_id") or "").strip()
    image_id=str(payload.get("image_id") or "").strip()
    hotspot_id=str(payload.get("hotspot_id") or "").strip()
    try:
        shape=_validate_hotspot_shape(payload.get("shape"))
        pack=get_content_pack(pack_id)
        if not pack: raise FileNotFoundError("Content pack is not installed")
        dataset_kind=str(payload.get("dataset_kind") or "hotspot").strip().lower()
        descriptor_key="quiz_datasets" if dataset_kind=="quiz" else "image_datasets"
        descriptor=next((d for d in (pack.get(descriptor_key) or []) if isinstance(d,dict) and str(d.get("id") or "").strip()==dataset_id),None)
        if not descriptor: raise KeyError("Image-capable dataset is not declared by this pack")
        dataset_path=_safe_pack_child(pack["_root"],str(descriptor.get("path") or "").strip())
        with open(dataset_path,"r",encoding="utf-8") as f: data=json.load(f)
        target_image=next((im for im in (data.get("images") or []) if str(im.get("id") or im.get("file") or "")==image_id),None)
        if not target_image: raise KeyError("Image record not found")
        target_hotspot=next((h for h in (target_image.get("hotspots") or []) if str(h.get("id") or "")==hotspot_id),None)
        if not target_hotspot: raise KeyError("Hotspot record not found")
        backup_path=dataset_path+".pre_editor.bak"
        backup_created=False
        if not os.path.exists(backup_path): shutil.copy2(dataset_path,backup_path); backup_created=True
        target_hotspot["shape"]=shape
        target_hotspot["calibration"]={"tool":"DLMS Image Study Editor","updated_at":datetime.now().isoformat(timespec="seconds")}
        tmp_path=dataset_path+".tmp"
        with open(tmp_path,"w",encoding="utf-8") as f:
            json.dump(data,f,indent=2,ensure_ascii=False); f.write("\n")
        os.replace(tmp_path,dataset_path)
        return jsonify({"ok":True,"shape":shape,"backup_created":backup_created})
    except Exception as exc:
        print(f"[IMAGE EDITOR HOTSPOT SAVE ERROR] {type(exc).__name__}: {exc}")
        return jsonify({"error": "The hotspot could not be saved. Verify the selected dataset and geometry."}), 400

def admin_image_edits_save(dependencies):
    get_content_pack = dependencies.get_content_pack
    _safe_pack_child = dependencies.safe_pack_child
    """Persist non-destructive study-image masks and text labels in the image dataset JSON."""
    payload = request.get_json(force=True) or {}
    pack_id = str(payload.get("pack_id") or "").strip().lower()
    dataset_id = str(payload.get("dataset_id") or "").strip()
    image_id = str(payload.get("image_id") or "").strip()
    edits = payload.get("edits") or []
    try:
        if not isinstance(edits, list) or len(edits) > 200:
            raise ValueError("Image edits must be a list of at most 200 items")
        cleaned = []
        for raw in edits:
            if not isinstance(raw, dict):
                continue
            kind = str(raw.get("type") or "").strip().lower()
            if kind == "mask":
                x=float(raw.get("x")); y=float(raw.get("y")); w=float(raw.get("w")); h=float(raw.get("h"))
                style=str(raw.get("style") or "blur").strip().lower()
                if style not in {"blur","white","black"}: style="blur"
                if not (0 <= x <= 1 and 0 <= y <= 1 and 0 < w <= 1 and 0 < h <= 1 and x+w <= 1.001 and y+h <= 1.001):
                    raise ValueError("Mask rectangle must use normalized coordinates inside the image")
                cleaned.append({"type":"mask","x":round(x,6),"y":round(y,6),"w":round(w,6),"h":round(h,6),"style":style})
            elif kind == "text":
                x=float(raw.get("x")); y=float(raw.get("y")); text=str(raw.get("text") or "").strip()
                size=int(raw.get("size") or 18)
                tone=str(raw.get("tone") or "light").strip().lower()
                if tone not in {"light","dark"}: tone="light"
                if not text: raise ValueError("Text label cannot be empty")
                if len(text) > 180: raise ValueError("Text label is too long")
                if not (0 <= x <= 1 and 0 <= y <= 1): raise ValueError("Text position must be normalized")
                size=max(10,min(size,48))
                cleaned.append({"type":"text","x":round(x,6),"y":round(y,6),"text":text,"size":size,"tone":tone})
            else:
                raise ValueError("Unsupported image edit type")

        pack=get_content_pack(pack_id)
        if not pack: raise FileNotFoundError("Content pack is not installed")
        dataset_kind=str(payload.get("dataset_kind") or "hotspot").strip().lower()
        descriptor_key="quiz_datasets" if dataset_kind=="quiz" else "image_datasets"
        descriptor=next((d for d in (pack.get(descriptor_key) or []) if isinstance(d,dict) and str(d.get("id") or "").strip()==dataset_id),None)
        if not descriptor: raise KeyError("Image-capable dataset is not declared by this pack")
        dataset_path=_safe_pack_child(pack["_root"],str(descriptor.get("path") or "").strip())
        with open(dataset_path,"r",encoding="utf-8") as f: data=json.load(f)
        target_image=next((im for im in (data.get("images") or []) if isinstance(im,dict) and str(im.get("id") or im.get("file") or "")==image_id),None)
        if not target_image: raise KeyError("Image record not found")
        backup_path=dataset_path+".pre_editor.bak"
        backup_created=False
        if not os.path.exists(backup_path): shutil.copy2(dataset_path,backup_path); backup_created=True
        target_image["edits"] = cleaned
        target_image["edit_metadata"] = {"tool":"DLMS Image Study Editor","updated_at":datetime.now().isoformat(timespec="seconds"),"non_destructive":True}
        tmp_path=dataset_path+".tmp"
        with open(tmp_path,"w",encoding="utf-8") as f:
            json.dump(data,f,indent=2,ensure_ascii=False); f.write("\n")
        os.replace(tmp_path,dataset_path)
        return jsonify({"ok":True,"edits":cleaned,"backup_created":backup_created})
    except Exception as exc:
        print(f"[IMAGE EDITOR PREP SAVE ERROR] {type(exc).__name__}: {exc}")
        return jsonify({"error": "The image preparation changes could not be saved. Verify the submitted edits."}), 400

def create_admin_images_blueprint(dependencies: AdminImageRouteDependencies) -> Blueprint:
    blueprint = Blueprint("admin_images", __name__)
    routes = (
        ("/admin/hotspots", "admin_hotspot_editor", admin_hotspot_editor, ["GET"]),
        ("/admin/image-editor", "admin_hotspot_editor", admin_hotspot_editor, ["GET"]),
        ("/admin/hotspots/save", "admin_hotspot_save", admin_hotspot_save, ["POST"]),
        ("/admin/image-editor/hotspot/save", "admin_hotspot_save", admin_hotspot_save, ["POST"]),
        ("/admin/image-editor/edits/save", "admin_image_edits_save", admin_image_edits_save, ["POST"]),
    )
    bound_views = {}
    for rule, endpoint, view_func, methods in routes:
        bound_view = bound_views.setdefault(
            endpoint, _bind_dependencies(view_func, dependencies)
        )
        blueprint.add_url_rule(
            rule,
            endpoint=endpoint,
            view_func=bound_view,
            methods=methods,
        )
    return blueprint

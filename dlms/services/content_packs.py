"""Content-pack catalog loading, archive inspection, and validation services."""

import json
import os
import re
import unicodedata
import zipfile
from datetime import datetime

def _safe_pack_child(pack_root, relative_path):
    """Resolve a pack-relative path without allowing traversal outside the pack."""
    pack_root = os.path.realpath(pack_root)
    candidate = os.path.realpath(os.path.join(pack_root, relative_path))
    if candidate != pack_root and not candidate.startswith(pack_root + os.sep):
        raise ValueError("Content pack path escapes its pack directory")
    return candidate


def discover_content_packs(content_pack_folder, *, expected_schema_version):
    """
    Discover valid content packs under APP_DATA_DIR/content_packs.

    A pack is a directory containing manifest.json. Invalid packs are skipped
    rather than preventing DLMS from starting.
    """
    packs = {}
    try:
        entries = sorted(os.listdir(content_pack_folder))
    except OSError as exc:
        print(f"[CONTENT PACKS] Unable to list {content_pack_folder}: {exc}")
        return packs

    for entry in entries:
        pack_root = os.path.join(content_pack_folder, entry)
        manifest_path = os.path.join(pack_root, "manifest.json")
        if not os.path.isdir(pack_root) or not os.path.isfile(manifest_path):
            continue

        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f) or {}

            pack_id = str(manifest.get("id") or "").strip().lower()
            if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", pack_id):
                raise ValueError("manifest id must contain only lowercase letters, numbers, _ or -")

            schema_version = int(manifest.get("schema_version", 0))
            if schema_version != expected_schema_version:
                raise ValueError(
                    f"unsupported schema_version {schema_version}; "
                    f"expected {expected_schema_version}"
                )

            datasets = manifest.get("datasets") or []
            if not isinstance(datasets, list):
                raise ValueError("datasets must be a list")
            invalid_dataset_entries = [
                item for item in datasets
                if not isinstance(item, dict)
            ]
            if invalid_dataset_entries:
                raise ValueError(
                    "datasets entries must be descriptor objects, not string paths"
                )

            image_datasets = manifest.get("image_datasets") or []
            if not isinstance(image_datasets, list):
                raise ValueError("image_datasets must be a list")
            invalid_image_entries = [
                item for item in image_datasets
                if not isinstance(item, dict)
            ]
            if invalid_image_entries:
                raise ValueError(
                    "image_datasets entries must be descriptor objects, not string paths"
                )

            quiz_datasets = manifest.get("quiz_datasets") or []
            if not isinstance(quiz_datasets, list):
                raise ValueError("quiz_datasets must be a list")
            if any(not isinstance(item, dict) for item in quiz_datasets):
                raise ValueError("quiz_datasets entries must be descriptor objects, not string paths")

            manifest["_root"] = pack_root
            manifest["_manifest_path"] = manifest_path
            packs[pack_id] = manifest

        except Exception as exc:
            print(f"[CONTENT PACKS] Skipping invalid pack {entry!r}: {exc}")

    return packs


def get_content_pack(pack_id, *, discover_content_packs):
    return discover_content_packs().get(str(pack_id or "").strip().lower())


def load_content_pack_dataset(
    pack_id,
    dataset_id,
    *,
    get_content_pack,
    schema_version,
    safe_pack_child,
    matching_record_validation_errors,
    set_content_pack_concepts,
    standalone_matching_concepts,
):
    """Load and validate one JSON dataset declared in a pack manifest."""
    pack = get_content_pack(pack_id)
    if not pack:
        raise FileNotFoundError(f"Content pack {pack_id!r} is not installed")

    dataset_id = str(dataset_id or "").strip()
    descriptor = next(
        (item for item in pack.get("datasets", [])
         if str(item.get("id") or "").strip() == dataset_id),
        None
    )
    if not descriptor:
        raise KeyError(f"Dataset {dataset_id!r} is not declared by pack {pack_id!r}")

    rel_path = str(descriptor.get("path") or "").strip()
    if not rel_path:
        raise ValueError("Dataset descriptor is missing path")

    dataset_path = safe_pack_child(pack["_root"], rel_path)
    if not os.path.isfile(dataset_path):
        raise FileNotFoundError(f"Dataset file not found: {rel_path}")

    with open(dataset_path, "r", encoding="utf-8") as f:
        data = json.load(f) or {}

    if int(data.get("schema_version", 0)) != schema_version:
        raise ValueError("Dataset schema version is not supported")

    terms = data.get("terms") or []
    if not isinstance(terms, list):
        raise ValueError("Dataset terms must be a list")

    matching_errors = matching_record_validation_errors(
        terms,
        context=f"matching dataset {dataset_id!r}",
        left_key="term",
        right_key="definition",
        record_name="item",
    )
    if matching_errors:
        raise ValueError("; ".join(matching_errors))

    set_content_pack_concepts(data, context=f"matching dataset {dataset_id!r}")

    cleaned = []
    for index, item in enumerate(terms, 1):
        term = str(item.get("term") or "").strip()
        definition = str(item.get("definition") or "").strip()
        cleaned_item = {
            "term": term,
            "definition": definition,
            "category": str(item.get("category") or "").strip(),
            "explanation": str(item.get("explanation") or "").strip(),
            "verification": item.get("verification") if isinstance(item.get("verification"), dict) else {},
        }
        if str(item.get("id") or "").strip():
            cleaned_item["id"] = str(item.get("id")).strip()
        concepts = set_content_pack_concepts(
            item, context=f"matching dataset {dataset_id!r}, term {index}"
        )
        if "concepts" in item:
            cleaned_item["concepts"] = concepts
        cleaned.append(cleaned_item)

    data["terms"] = cleaned
    standalone_matching_concepts(data, context=f"matching dataset {dataset_id!r}")
    data["_descriptor"] = descriptor
    data["_pack"] = pack
    return data


def load_content_pack_image_dataset(
    pack_id,
    dataset_id,
    *,
    get_content_pack,
    schema_version,
    safe_pack_child,
    decode_raster_image,
    passive_pack_image_extensions,
    set_content_pack_concepts,
):
    """Load one image/hotspot dataset declared by an installed content pack."""
    pack = get_content_pack(pack_id)
    if not pack:
        raise FileNotFoundError(f"Content pack {pack_id!r} is not installed")

    dataset_id = str(dataset_id or "").strip()
    descriptor = next(
        (item for item in (pack.get("image_datasets") or [])
         if str(item.get("id") or "").strip() == dataset_id),
        None
    )
    if not descriptor:
        raise KeyError(f"Image dataset {dataset_id!r} is not declared by pack {pack_id!r}")

    rel_path = str(descriptor.get("path") or "").strip()
    if not rel_path:
        raise ValueError("Image dataset descriptor is missing path")

    dataset_path = safe_pack_child(pack["_root"], rel_path)
    if not os.path.isfile(dataset_path):
        raise FileNotFoundError(f"Image dataset file not found: {rel_path}")

    with open(dataset_path, "r", encoding="utf-8") as f:
        data = json.load(f) or {}

    if int(data.get("schema_version", 0)) != schema_version:
        raise ValueError("Image dataset schema version is not supported")

    images = data.get("images") or []
    if not isinstance(images, list) or not images:
        raise ValueError("Image dataset must contain at least one image")

    for image in images:
        if not isinstance(image, dict):
            raise ValueError("Each image record must be an object")
        rel_file = str(image.get("file") or "").strip()
        if not rel_file:
            raise ValueError("Image record is missing file")
        image_path = safe_pack_child(pack["_root"], rel_file)
        if not os.path.isfile(image_path):
            raise FileNotFoundError(f"Pack image not found: {rel_file}")
        decode_raster_image(image_path, passive_pack_image_extensions)
        hotspots = image.get("hotspots") or []
        if not isinstance(hotspots, list) or not hotspots:
            raise ValueError(f"Image {rel_file!r} has no hotspots")
        set_content_pack_concepts(image, context=f"image dataset {dataset_id!r}, image {rel_file!r}")
        for hotspot_number, hotspot in enumerate(hotspots, 1):
            if not isinstance(hotspot, dict):
                raise ValueError(f"Image {rel_file!r} hotspot {hotspot_number} must be an object")
            set_content_pack_concepts(
                hotspot,
                context=f"image dataset {dataset_id!r}, image {rel_file!r}, hotspot {hotspot_number}",
            )

    set_content_pack_concepts(data, context=f"image dataset {dataset_id!r}")
    data["_descriptor"] = descriptor
    data["_pack"] = pack
    return data


def load_content_pack_quiz_dataset(
    pack_id,
    dataset_id,
    *,
    get_content_pack,
    schema_version,
    safe_pack_child,
    decode_raster_image,
    passive_pack_image_extensions,
    matching_comparison_key,
    matching_record_validation_errors,
    normalize_content_pack_choice_question,
    set_content_pack_concepts,
):
    """Load a generic mixed-question dataset declared by an installed content pack."""
    pack = get_content_pack(pack_id)
    if not pack:
        raise FileNotFoundError(f"Content pack {pack_id!r} is not installed")
    dataset_id = str(dataset_id or "").strip()
    descriptor = next(
        (item for item in (pack.get("quiz_datasets") or [])
         if isinstance(item, dict) and str(item.get("id") or "").strip() == dataset_id),
        None
    )
    if not descriptor:
        raise KeyError(f"Quiz dataset {dataset_id!r} is not declared by pack {pack_id!r}")
    rel_path = str(descriptor.get("path") or "").strip()
    if not rel_path:
        raise ValueError("Quiz dataset descriptor is missing path")
    dataset_path = safe_pack_child(pack["_root"], rel_path)
    if not os.path.isfile(dataset_path):
        raise FileNotFoundError(f"Quiz dataset file not found: {rel_path}")
    with open(dataset_path, "r", encoding="utf-8") as f:
        data = json.load(f) or {}
    if int(data.get("schema_version", 0)) != schema_version:
        raise ValueError("Quiz dataset schema version is not supported")

    images = data.get("images") or []
    if not isinstance(images, list):
        raise ValueError("Quiz dataset images must be a list")
    image_ids = set()
    normalized_image_ids = {}
    for image in images:
        if not isinstance(image, dict):
            raise ValueError("Each quiz dataset image must be an object")
        image_id = str(image.get("id") or "").strip()
        rel_file = str(image.get("file") or "").strip()
        if not image_id or not rel_file:
            raise ValueError("Each quiz dataset image requires id and file")
        normalized_image_id = matching_comparison_key(image_id)
        if normalized_image_id in normalized_image_ids:
            raise ValueError(
                f"Duplicate image id {image_id!r}; earlier image uses "
                f"{normalized_image_ids[normalized_image_id]!r}"
            )
        normalized_image_ids[normalized_image_id] = image_id
        image_ids.add(image_id)
        image_path = safe_pack_child(pack["_root"], rel_file)
        if not os.path.isfile(image_path):
            raise FileNotFoundError(f"Pack image not found: {rel_file}")
        decode_raster_image(image_path, passive_pack_image_extensions)
        if not isinstance(image.get("hotspots") or [], list):
            raise ValueError("Image hotspots must be a list")
        set_content_pack_concepts(image, context=f"quiz dataset {dataset_id!r}, image {image_id!r}")
        for hotspot_number, hotspot in enumerate(image.get("hotspots") or [], 1):
            if not isinstance(hotspot, dict):
                raise ValueError(f"Quiz dataset image {image_id!r} hotspot {hotspot_number} must be an object")
            set_content_pack_concepts(
                hotspot,
                context=f"quiz dataset {dataset_id!r}, image {image_id!r}, hotspot {hotspot_number}",
            )

    questions = data.get("questions") or []
    if not isinstance(questions, list) or not questions:
        raise ValueError("Quiz dataset must contain at least one question")
    allowed = {"choice", "matching", "hotspot"}
    cleaned = []
    for question_number, raw in enumerate(questions, 1):
        if not isinstance(raw, dict):
            raise ValueError(f"Quiz dataset question {question_number} must be an object")
        qtype = str(raw.get("type") or "choice").strip().lower()
        if qtype not in allowed:
            raise ValueError(
                f"Quiz dataset question {question_number} has unsupported type {qtype!r}"
            )
        question = raw.get("question")
        if not isinstance(question, str) or not question.strip():
            raise ValueError(
                f"Quiz dataset question {question_number} must have a non-empty question string"
            )
        image_id = str(raw.get("image_id") or "").strip()
        if image_id and image_id not in image_ids:
            raise ValueError(f"Question references unknown image id: {image_id}")
        if qtype == "matching":
            matching_errors = matching_record_validation_errors(
                raw.get("pairs") or [],
                context=f"mixed dataset {dataset_id!r}, matching question {question_number} {question!r}",
                left_key="left",
                right_key="right",
                record_name="pair",
            )
            if matching_errors:
                raise ValueError("; ".join(matching_errors))
            item = dict(raw)
            item["type"] = qtype
            item["question"] = question.strip()
        elif qtype == "choice":
            item = normalize_content_pack_choice_question(
                raw,
                context=f"quiz dataset {dataset_id!r}, choice question {question_number}",
            )
        else:
            item = dict(raw)
            item["type"] = qtype
            item["question"] = question.strip()
        set_content_pack_concepts(
            item, context=f"quiz dataset {dataset_id!r}, question {question_number} {question!r}"
        )
        cleaned.append(item)
    if not cleaned:
        raise ValueError("Quiz dataset has no usable questions")
    data["questions"] = cleaned
    set_content_pack_concepts(data, context=f"quiz dataset {dataset_id!r}")
    data["_descriptor"] = descriptor
    data["_pack"] = pack
    data["_dataset_path"] = dataset_path
    return data


def _content_pack_tracked_quiz_count(pack_id, registry):
    return sum(
        1 for item in registry
        if str(item.get("source_pack_id") or "").strip().lower() == str(pack_id or "").strip().lower()
    )


def _folder_size_bytes(path):
    total = 0
    for root_dir, _, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root_dir, name))
            except OSError:
                pass
    return total


def _content_pack_validation_record(name, status, detail):
    return {"name": str(name), "status": str(status), "detail": str(detail)}


def _matching_comparison_key(value, *, fold_case=True):
    """Normalize matching values for deterministic ambiguity checks only."""
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    normalized = " ".join(normalized.strip().split())
    return normalized.casefold() if fold_case else normalized


def _matching_case_only_term_warnings(
    records,
    *,
    context,
    left_key="term",
    record_name="item",
    matching_comparison_key=_matching_comparison_key,
):
    """Return non-blocking diagnostics for case-only term variants."""
    if not isinstance(records, list):
        return []
    warnings_found = []
    seen = {}
    for number, record in enumerate(records, 1):
        if not isinstance(record, dict):
            continue
        original = str(record.get(left_key) or "").strip()
        case_sensitive_key = matching_comparison_key(original, fold_case=False)
        if not case_sensitive_key:
            continue
        folded_key = case_sensitive_key.casefold()
        earlier = seen.get(folded_key)
        if earlier and earlier[1] != case_sensitive_key:
            earlier_number, _, earlier_original = earlier
            warnings_found.append(
                f"{context}: case-only {left_key} variants at {record_name} "
                f"{earlier_number} {earlier_original!r} and {record_name} "
                f"{number} {original!r}; verify that case is intentionally significant"
            )
        elif not earlier:
            seen[folded_key] = (number, case_sensitive_key, original)
    return warnings_found


def _matching_record_validation_errors(
    records,
    *,
    context,
    left_key="term",
    right_key="definition",
    record_name="item",
    matching_comparison_key=_matching_comparison_key,
):
    """Return precise deterministic errors for one matching record collection."""
    if not isinstance(records, list):
        return [f"{context}: matching records must be a list"]

    errors = []
    seen_ids = {}
    seen_left = {}
    seen_right = {}
    seen_pairs = {}
    distinct_pairs = set()

    for number, record in enumerate(records, 1):
        location = f"{record_name} {number}"
        if not isinstance(record, dict):
            errors.append(f"{context}: {location} must be an object")
            continue

        original_id = str(record.get("id") or "").strip()
        original_left = str(record.get(left_key) or "").strip()
        original_right = str(record.get(right_key) or "").strip()
        normalized_id = matching_comparison_key(original_id)
        normalized_left = matching_comparison_key(original_left, fold_case=False)
        normalized_right = matching_comparison_key(original_right)

        if not normalized_left:
            errors.append(f"{context}: {location} is missing {left_key}")
        if not normalized_right:
            errors.append(f"{context}: {location} is missing {right_key}")

        if normalized_id:
            earlier = seen_ids.get(normalized_id)
            if earlier:
                earlier_number, earlier_id, earlier_left, earlier_right, earlier_pair = earlier
                current_pair = (normalized_left, normalized_right)
                if current_pair == earlier_pair:
                    errors.append(
                        f"{context}: duplicate ID {original_id!r} at {location}; "
                        f"earlier {record_name} {earlier_number} uses ID {earlier_id!r} "
                        f"for {earlier_left!r} -> {earlier_right!r}"
                    )
                else:
                    errors.append(
                        f"{context}: conflicting ID {original_id!r} at {location} "
                        f"({original_left!r} -> {original_right!r}); earlier {record_name} "
                        f"{earlier_number} uses ID {earlier_id!r} for "
                        f"{earlier_left!r} -> {earlier_right!r}"
                    )
            else:
                seen_ids[normalized_id] = (
                    number, original_id, original_left, original_right,
                    (normalized_left, normalized_right),
                )

        if not normalized_left or not normalized_right:
            continue

        pair_key = (normalized_left, normalized_right)
        earlier_pair = seen_pairs.get(pair_key)
        if earlier_pair:
            earlier_number, earlier_left, earlier_right = earlier_pair
            errors.append(
                f"{context}: exact duplicate pair at {location} "
                f"({original_left!r} -> {original_right!r}); earlier {record_name} "
                f"{earlier_number} is {earlier_left!r} -> {earlier_right!r}"
            )
        else:
            seen_pairs[pair_key] = (number, original_left, original_right)
            distinct_pairs.add(pair_key)

        earlier_left = seen_left.get(normalized_left)
        if earlier_left:
            earlier_number, earlier_value, earlier_answer, earlier_answer_key = earlier_left
            if normalized_right == earlier_answer_key:
                errors.append(
                    f"{context}: duplicate {left_key} {original_left!r} at {location}; "
                    f"earlier {record_name} {earlier_number} uses {earlier_value!r}"
                )
            else:
                errors.append(
                    f"{context}: one {left_key} maps to multiple answers at {location}: "
                    f"{original_left!r} -> {original_right!r}; earlier {record_name} "
                    f"{earlier_number} maps {earlier_value!r} -> {earlier_answer!r}"
                )
        else:
            seen_left[normalized_left] = (
                number, original_left, original_right, normalized_right,
            )

        earlier_right = seen_right.get(normalized_right)
        if earlier_right:
            earlier_number, earlier_answer, earlier_term, earlier_term_key = earlier_right
            if normalized_left == earlier_term_key:
                errors.append(
                    f"{context}: duplicate {right_key} {original_right!r} at {location}; "
                    f"earlier {record_name} {earlier_number} uses {earlier_answer!r}"
                )
            else:
                errors.append(
                    f"{context}: multiple terms map to one answer at {location}: "
                    f"{original_left!r} -> {original_right!r}; earlier {record_name} "
                    f"{earlier_number} maps {earlier_term!r} -> {earlier_answer!r}"
                )
        else:
            seen_right[normalized_right] = (
                number, original_right, original_left, normalized_left,
            )

    if len(distinct_pairs) < 2:
        errors.append(
            f"{context}: matching data needs at least two valid distinct pairs; "
            f"found {len(distinct_pairs)}"
        )
    return errors


def _content_pack_choice_question_errors(
    question,
    *,
    context,
    require_single_select=False,
    matching_comparison_key=_matching_comparison_key,
):
    """Return deterministic structural errors for one mixed choice question."""
    if not isinstance(question, dict):
        return [f"{context}: choice question must be an object"]

    errors = []
    question_text = question.get("question")
    if not isinstance(question_text, str) or not question_text.strip():
        errors.append(f"{context}: choice question must have a non-empty question string")

    choices = question.get("choices")
    if not isinstance(choices, list):
        return errors + [f"{context}: choices must be a list"]
    if len(choices) < 2:
        errors.append(f"{context}: choice question needs at least two choices")
    if len(choices) > 26:
        errors.append(f"{context}: choice question may contain at most 26 choices")

    seen_text = {}
    correct_count = 0
    for number, choice in enumerate(choices, 1):
        location = f"choice {number}"
        if not isinstance(choice, dict):
            errors.append(f"{context}: {location} must be an object")
            continue
        text = choice.get("text")
        if not isinstance(text, str) or not text.strip():
            errors.append(f"{context}: {location} must have a non-empty text string")
        else:
            normalized = matching_comparison_key(text)
            earlier = seen_text.get(normalized)
            if earlier:
                errors.append(
                    f"{context}: duplicate choice text at {location}; "
                    f"earlier choice {earlier} has the same normalized text"
                )
            else:
                seen_text[normalized] = number

        is_correct = choice.get("is_correct")
        if not isinstance(is_correct, bool):
            errors.append(f"{context}: {location} is_correct must be a JSON boolean")
        elif is_correct:
            correct_count += 1

    if correct_count == 0:
        errors.append(f"{context}: choice question must have at least one correct choice")
    elif require_single_select and correct_count != 1:
        errors.append(
            f"{context}: AI Study Pack multiple-choice questions must have exactly one correct choice"
        )
    return errors


def _normalize_content_pack_choice_question(
    question,
    *,
    context,
    require_single_select=False,
    content_pack_choice_question_errors=_content_pack_choice_question_errors,
):
    """Validate and normalize the canonical Study Pack choice-question form.

    Study Pack authors provide text plus a real JSON ``is_correct`` boolean.
    DLMS owns the generated A-Z labels used by the quiz runtime.
    """
    errors = content_pack_choice_question_errors(
        question, context=context, require_single_select=require_single_select
    )
    if errors:
        raise ValueError("; ".join(errors))

    normalized = dict(question)
    normalized["type"] = "choice"
    normalized["question"] = question["question"].strip()
    normalized["choices"] = [
        {
            "label": chr(65 + number),
            "text": choice["text"].strip(),
            "is_correct": choice["is_correct"],
        }
        for number, choice in enumerate(question["choices"])
    ]
    return normalized


def _content_pack_answer_position_concentration(questions):
    """Describe an obviously suspicious single-select answer-position skew."""
    positions = []
    for question in questions if isinstance(questions, list) else []:
        if not isinstance(question, dict):
            continue
        if str(question.get("type") or "choice").strip().lower() != "choice":
            continue
        choices = question.get("choices")
        if not isinstance(choices, list):
            continue
        correct = [
            index for index, choice in enumerate(choices)
            if isinstance(choice, dict) and choice.get("is_correct") is True
        ]
        if len(correct) == 1:
            positions.append(correct[0])

    total = len(positions)
    if total < 4:
        return None
    counts = {}
    for position in positions:
        counts[position] = counts.get(position, 0) + 1
    position, count = max(counts.items(), key=lambda item: item[1])
    concentration = count / total
    if count != total and (total < 8 or concentration < 0.75):
        return None
    return {
        "position": position,
        "label": chr(65 + position),
        "count": count,
        "total": total,
        "percentage": round(concentration * 100),
    }


def _safe_zip_member_name(name):
    """Return a normalized safe archive member path or raise ValueError."""
    raw = str(name or "").replace("\\", "/")
    if not raw or raw.startswith("/") or re.match(r"^[A-Za-z]:/", raw):
        raise ValueError("archive contains an absolute path")
    parts = [p for p in raw.split("/") if p not in {"", "."}]
    if not parts or any(p == ".." for p in parts):
        raise ValueError("archive contains an unsafe relative path")
    return "/".join(parts)


def _inspect_content_pack_zip(
    zip_path,
    *,
    max_files,
    max_uncompressed_bytes,
    max_single_file_bytes,
    safe_zip_member_name=_safe_zip_member_name,
):
    """Security-check a pack ZIP and return its single top-level folder name."""
    total_size = 0
    file_count = 0
    top_levels = set()
    seen_names = set()

    with zipfile.ZipFile(zip_path, "r") as archive:
        infos = archive.infolist()
        if not infos:
            raise ValueError("ZIP is empty")

        for info in infos:
            normalized = safe_zip_member_name(info.filename)
            top_levels.add(normalized.split("/", 1)[0])

            # Reject duplicate normalized paths and Unix symlinks.
            key = normalized.casefold()
            if key in seen_names:
                raise ValueError(f"ZIP contains duplicate path: {normalized}")
            seen_names.add(key)
            unix_mode = (info.external_attr >> 16) & 0xFFFF
            if (unix_mode & 0o170000) == 0o120000:
                raise ValueError(f"ZIP contains a symbolic link: {normalized}")

            if info.is_dir():
                continue
            file_count += 1
            total_size += int(info.file_size or 0)
            if file_count > max_files:
                raise ValueError(f"ZIP contains more than {max_files} files")
            if int(info.file_size or 0) > max_single_file_bytes:
                raise ValueError(f"ZIP member is too large: {normalized}")
            if total_size > max_uncompressed_bytes:
                raise ValueError("ZIP expands beyond the permitted size limit")

    if len(top_levels) != 1:
        raise ValueError("ZIP must contain exactly one top-level Study Pack folder")
    root_name = next(iter(top_levels))
    if root_name in {".", ".."} or not root_name.strip():
        raise ValueError("ZIP top-level folder name is invalid")
    return {"root_name": root_name, "file_count": file_count, "uncompressed_bytes": total_size}


def _read_json_file(path, label, errors):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        print(f"[CONTENT PACK JSON ERROR] {label}: {type(exc).__name__}: {exc}")
        errors.append(f"{label} is not valid JSON")
        return None


def _validate_staged_content_pack(
    pack_root,
    *,
    require_single_select=False,
    expected_schema_version,
    safe_pack_child,
    read_json_file,
    validation_record,
    matching_comparison_key,
    matching_record_validation_errors,
    matching_case_only_term_warnings,
    content_pack_choice_question_errors,
    content_pack_answer_position_concentration,
    content_pack_concepts,
    standalone_matching_concepts,
    validate_hotspot_shape,
    validate_raster_image,
):
    """Independently validate a staged pack before installation."""
    errors, warnings, checks = [], [], []
    pack_root = os.path.realpath(pack_root)
    manifest_path = os.path.join(pack_root, "manifest.json")

    if not os.path.isfile(manifest_path):
        errors.append("Top-level Study Pack folder is missing manifest.json")
        return {"valid": False, "errors": errors, "warnings": warnings, "checks": checks, "manifest": {}}

    manifest = read_json_file(manifest_path, "manifest.json", errors)
    if not isinstance(manifest, dict):
        if manifest is not None:
            errors.append("manifest.json must contain a JSON object")
        return {"valid": False, "errors": errors, "warnings": warnings, "checks": checks, "manifest": {}}

    schema = manifest.get("schema_version")
    if schema == expected_schema_version:
        checks.append(validation_record("Manifest schema", "PASS", f"schema_version {schema}"))
    else:
        errors.append(f"manifest schema_version must be {expected_schema_version}")
        checks.append(validation_record("Manifest schema", "FAIL", f"found {schema!r}"))

    pack_id = str(manifest.get("id") or "").strip().lower()
    if re.fullmatch(r"[a-z0-9][a-z0-9_-]*", pack_id):
        checks.append(validation_record("Pack ID", "PASS", pack_id))
    else:
        errors.append("manifest id must use lowercase letters, numbers, _ or -")
        checks.append(validation_record("Pack ID", "FAIL", pack_id or "missing"))

    descriptor_groups = [
        ("datasets", "matching"),
        ("image_datasets", "hotspot"),
        ("quiz_datasets", "mixed"),
    ]
    descriptor_ids = set()
    normalized_descriptor_ids = {}
    declared_paths = []
    all_descriptors_valid = True
    parsed_dataset_files = []

    for key, kind in descriptor_groups:
        entries = manifest.get(key) or []
        if not isinstance(entries, list):
            errors.append(f"{key} must be a list")
            all_descriptors_valid = False
            continue
        for index, descriptor in enumerate(entries, 1):
            if not isinstance(descriptor, dict):
                errors.append(f"{key}[{index}] must be a descriptor object, not a path string")
                all_descriptors_valid = False
                continue
            did = str(descriptor.get("id") or "").strip()
            title = str(descriptor.get("title") or "").strip()
            dtype = str(descriptor.get("type") or "").strip()
            rel_path = str(descriptor.get("path") or "").strip()
            if not did or not title or not dtype or not rel_path:
                errors.append(f"{key}[{index}] requires id, title, type, and path")
                all_descriptors_valid = False
                continue
            normalized_did = matching_comparison_key(did)
            if normalized_did in normalized_descriptor_ids:
                errors.append(
                    f"duplicate dataset id {did!r}; earlier descriptor uses "
                    f"{normalized_descriptor_ids[normalized_did]!r}"
                )
                all_descriptors_valid = False
            else:
                normalized_descriptor_ids[normalized_did] = did
            descriptor_ids.add(did)
            try:
                dataset_path = safe_pack_child(pack_root, rel_path)
            except Exception:
                errors.append(f"{key}[{index}] path escapes the pack: {rel_path}")
                all_descriptors_valid = False
                continue
            declared_paths.append(rel_path)
            if not os.path.isfile(dataset_path):
                errors.append(f"declared dataset file is missing: {rel_path}")
                all_descriptors_valid = False
                continue
            data = read_json_file(dataset_path, rel_path, errors)
            if isinstance(data, dict):
                parsed_dataset_files.append((key, did, rel_path, data))

    checks.append(validation_record(
        "Dataset descriptors",
        "PASS" if all_descriptors_valid else "FAIL",
        f"{len(descriptor_ids)} descriptor(s) checked"
    ))

    # Validate dataset internals and all referenced image files.
    referenced_files_ok = True
    duplicates_ok = True
    image_license_missing = 0
    dataset_source_missing = 0
    answer_distribution_warnings = []

    for group, did, rel_path, data in parsed_dataset_files:
        if data.get("schema_version") != expected_schema_version:
            errors.append(f"{rel_path}: schema_version must be {expected_schema_version}")

        data_id = str(data.get("id") or "").strip()
        if data_id and data_id != did:
            errors.append(f"{rel_path}: dataset id {data_id!r} does not match manifest descriptor id {did!r}")

        if not isinstance(data.get("source"), dict) or not data.get("source"):
            dataset_source_missing += 1

        try:
            content_pack_concepts(data, context=f"{rel_path} (dataset {did!r})")
        except ValueError as exc:
            errors.append(str(exc))

        if group == "datasets":
            terms = data.get("terms") or []
            if not isinstance(terms, list) or not terms:
                errors.append(f"{rel_path}: matching dataset must contain terms")
                continue
            matching_errors = matching_record_validation_errors(
                terms,
                context=f"{rel_path} (dataset {did!r})",
                left_key="term",
                right_key="definition",
                record_name="item",
            )
            if matching_errors:
                duplicates_ok = False
                errors.extend(matching_errors)
            for item_number, term in enumerate(terms, 1):
                try:
                    content_pack_concepts(
                        term, context=f"{rel_path} (dataset {did!r}), term {item_number}"
                    )
                except ValueError as exc:
                    errors.append(str(exc))
            try:
                standalone_matching_concepts(
                    data, context=f"{rel_path} (dataset {did!r})"
                )
            except ValueError as exc:
                errors.append(str(exc))
            warnings.extend(matching_case_only_term_warnings(
                terms,
                context=f"{rel_path} (dataset {did!r})",
                left_key="term",
                record_name="item",
            ))

        elif group in {"image_datasets", "quiz_datasets"}:
            images = data.get("images") or []
            if group == "image_datasets" and (not isinstance(images, list) or not images):
                errors.append(f"{rel_path}: image dataset must contain at least one image")
                continue
            if not isinstance(images, list):
                errors.append(f"{rel_path}: images must be a list")
                continue

            image_ids = {}
            for n, image in enumerate(images, 1):
                if not isinstance(image, dict):
                    errors.append(f"{rel_path}: image {n} must be an object")
                    continue
                try:
                    content_pack_concepts(
                        image, context=f"{rel_path} (dataset {did!r}), image {n}"
                    )
                except ValueError as exc:
                    errors.append(str(exc))
                image_id = str(image.get("id") or f"image_{n}").strip()
                normalized_image_id = matching_comparison_key(image_id)
                if normalized_image_id in image_ids:
                    duplicates_ok = False
                    errors.append(
                        f"{rel_path}: duplicate image id {image_id!r} at image {n}; "
                        f"earlier image uses {image_ids[normalized_image_id]!r}"
                    )
                else:
                    image_ids[normalized_image_id] = image_id
                rel_image = str(image.get("file") or "").strip()
                if not rel_image:
                    errors.append(f"{rel_path}: image {n} is missing file")
                    referenced_files_ok = False
                    continue
                try:
                    image_path = safe_pack_child(pack_root, rel_image)
                except Exception:
                    errors.append(f"{rel_path}: image path escapes pack: {rel_image}")
                    referenced_files_ok = False
                    continue
                if not os.path.isfile(image_path):
                    errors.append(f"{rel_path}: referenced image is missing: {rel_image}")
                    referenced_files_ok = False
                else:
                    try:
                        validate_raster_image(image_path)
                    except ValueError as exc:
                        errors.append(f"{rel_path}: unsafe or invalid image {rel_image}: {exc}")
                        referenced_files_ok = False

                source = image.get("source") if isinstance(image.get("source"), dict) else {}
                license_text = str(image.get("license") or source.get("license") or "").strip()
                if not license_text:
                    image_license_missing += 1

                hotspots = image.get("hotspots") or []
                if not isinstance(hotspots, list):
                    errors.append(f"{rel_path}: hotspots for {rel_image} must be a list")
                    continue
                for h, hotspot in enumerate(hotspots, 1):
                    if not isinstance(hotspot, dict):
                        errors.append(f"{rel_path}: hotspot {h} for {rel_image} must be an object")
                        continue
                    try:
                        content_pack_concepts(
                            hotspot,
                            context=f"{rel_path} (dataset {did!r}), image {n}, hotspot {h}",
                        )
                    except ValueError as exc:
                        errors.append(str(exc))
                    shape = hotspot.get("shape")
                    try:
                        validate_hotspot_shape(shape)
                    except Exception as exc:
                        errors.append(f"{rel_path}: invalid hotspot geometry for {rel_image}: {exc}")

            if group == "quiz_datasets":
                questions = data.get("questions") or []
                if not isinstance(questions, list) or not questions:
                    errors.append(f"{rel_path}: mixed question dataset must contain questions")
                elif isinstance(questions, list):
                    skew = content_pack_answer_position_concentration(questions)
                    if skew:
                        answer_distribution_warnings.append(
                            f"{rel_path}: suspicious correct-answer position concentration: "
                            f"{skew['count']} of {skew['total']} single-select questions use "
                            f"position {skew['label']} ({skew['percentage']}%)."
                        )
                    for question_number, question in enumerate(questions, 1):
                        if not isinstance(question, dict):
                            errors.append(
                                f"{rel_path}: mixed question {question_number} must be an object"
                            )
                            continue
                        try:
                            content_pack_concepts(
                                question,
                                context=f"{rel_path} (dataset {did!r}), question {question_number}",
                            )
                        except ValueError as exc:
                            errors.append(str(exc))
                        qtype = str(question.get("type") or "choice").strip().lower()
                        question_text = question.get("question")
                        context = (
                            f"{rel_path} (dataset {did!r}), {qtype} question "
                            f"{question_number} {str(question_text or '').strip()!r}"
                        )
                        if qtype not in {"choice", "matching", "hotspot"}:
                            errors.append(
                                f"{rel_path}: mixed question {question_number} has unsupported type {qtype!r}"
                            )
                            continue
                        if not isinstance(question_text, str) or not question_text.strip():
                            errors.append(
                                f"{rel_path}: mixed question {question_number} must have a non-empty question string"
                            )
                        if qtype == "choice":
                            choice_errors = content_pack_choice_question_errors(
                                question,
                                context=context,
                                require_single_select=require_single_select,
                            )
                            if choice_errors:
                                duplicates_ok = False
                                errors.extend(choice_errors)
                            continue
                        if qtype != "matching":
                            continue
                        matching_errors = matching_record_validation_errors(
                            question.get("pairs") or [],
                            context=context,
                            left_key="left",
                            right_key="right",
                            record_name="pair",
                        )
                        if matching_errors:
                            duplicates_ok = False
                            errors.extend(matching_errors)
                        warnings.extend(matching_case_only_term_warnings(
                            question.get("pairs") or [],
                            context=context,
                            left_key="left",
                            record_name="pair",
                        ))

    checks.append(validation_record(
        "Referenced files", "PASS" if referenced_files_ok else "FAIL",
        "all declared dataset/image paths resolved" if referenced_files_ok else "one or more files are missing or unsafe"
    ))
    checks.append(validation_record(
        "Matching uniqueness / IDs", "PASS" if duplicates_ok else "FAIL",
        "dataset/image IDs and matching records are deterministic and unambiguous" if duplicates_ok else "matching ambiguity or an ID collision was detected"
    ))
    warnings.extend(answer_distribution_warnings)
    checks.append(validation_record(
        "Answer-position distribution",
        "WARN" if answer_distribution_warnings else "PASS",
        f"{len(answer_distribution_warnings)} suspicious dataset(s) need review"
        if answer_distribution_warnings else
        "no obviously pathological single-select answer-position concentration detected",
    ))

    if image_license_missing:
        warnings.append(f"{image_license_missing} image record(s) do not contain explicit license metadata")
        checks.append(validation_record("Image licenses", "WARN", f"{image_license_missing} image record(s) need review"))
    else:
        checks.append(validation_record("Image licenses", "PASS", "all image records include license metadata or no images are present"))

    if dataset_source_missing:
        warnings.append(f"{dataset_source_missing} dataset file(s) do not contain top-level source metadata")
        checks.append(validation_record("Dataset sources", "WARN", f"{dataset_source_missing} dataset(s) need source review"))
    else:
        checks.append(validation_record("Dataset sources", "PASS", "top-level source metadata present"))

    # AI self-validation is informative only; DLMS never trusts it in place of its own validation.
    ai_validation_path = os.path.join(pack_root, "PACK_VALIDATION.json")
    if os.path.isfile(ai_validation_path):
        ai_validation = read_json_file(ai_validation_path, "PACK_VALIDATION.json", warnings)
        ai_status = "PASS"
        ai_detail = "present; independently revalidated by DLMS"
        if not isinstance(ai_validation, dict):
            ai_status = "WARN"
            ai_detail = "present but not a usable JSON object"
        else:
            declared_pack_id = str(ai_validation.get("pack_id") or "").strip().lower()
            overall_status = str(ai_validation.get("overall_status") or "").strip().upper()
            ai_checks = ai_validation.get("checks")
            ai_issues = []
            if declared_pack_id and declared_pack_id != pack_id:
                ai_issues.append(f"declares pack_id {declared_pack_id!r}, expected {pack_id!r}")
            if overall_status and overall_status != "PASS":
                ai_issues.append(f"overall_status is {overall_status}")
            if ai_checks is not None and not isinstance(ai_checks, list):
                ai_issues.append("checks is not a list")
            if ai_issues:
                ai_status = "WARN"
                ai_detail = "; ".join(ai_issues)
                warnings.append("PACK_VALIDATION.json self-check needs review: " + ai_detail)
        checks.append(validation_record("AI self-validation", ai_status, ai_detail))
    else:
        checks.append(validation_record(
            "Validation metadata",
            "INFO",
            "PACK_VALIDATION.json not present; optional for legacy/hand-built packs. Current AI Builder outputs include it."
        ))

    checks.append(validation_record(
        "JSON parse check", "PASS" if not any("valid JSON" in e for e in errors) else "FAIL",
        f"{1 + len(parsed_dataset_files)} JSON file(s) inspected"
    ))
    checks.append(validation_record("Top-level folder", "PASS", os.path.basename(pack_root)))

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
        "manifest": manifest,
        "pack_id": pack_id,
        "pack_name": str(manifest.get("name") or pack_id or os.path.basename(pack_root)),
        "dataset_count": len(descriptor_ids),
    }


def content_pack_management_summary(
    content_pack_folder,
    *,
    discover_content_packs,
    validate_staged_content_pack,
    content_pack_tracked_quiz_count,
    validation_record,
    format_bytes,
    folder_size_bytes=_folder_size_bytes,
    datetime_class=datetime,
):
    """Return every installed pack folder, including invalid packs, with independent validation state."""
    discovered = discover_content_packs()
    by_root = {os.path.realpath(p.get("_root")): (pid, p) for pid, p in discovered.items()}
    rows = []
    try:
        entries = sorted(os.listdir(content_pack_folder), key=str.casefold)
    except OSError:
        entries = []

    for folder in entries:
        root = os.path.join(content_pack_folder, folder)
        if not os.path.isdir(root):
            continue

        report = validate_staged_content_pack(root)
        manifest = report.get("manifest") if isinstance(report.get("manifest"), dict) else {}
        resolved = by_root.get(os.path.realpath(root))
        pack_id = str(report.get("pack_id") or manifest.get("id") or "").strip().lower()
        runtime_pack = resolved[1] if resolved else {}
        matching = len(manifest.get("datasets") or []) if isinstance(manifest.get("datasets") or [], list) else 0
        image = len(manifest.get("image_datasets") or []) if isinstance(manifest.get("image_datasets") or [], list) else 0
        mixed = len(manifest.get("quiz_datasets") or []) if isinstance(manifest.get("quiz_datasets") or [], list) else 0
        protected = bool(manifest.get("protected"))
        generated = content_pack_tracked_quiz_count(pack_id) if pack_id and resolved else 0
        if report.get("valid") and pack_id and not resolved:
            report["valid"] = False
            report.setdefault("errors", []).append("Pack is structurally valid but is not discoverable at runtime, usually because another installed folder uses the same pack id.")
            report.setdefault("checks", []).append(validation_record("Runtime discovery", "FAIL", "pack id conflict or runtime discovery failure"))
        warning_count = len(report.get("warnings") or [])
        error_count = len(report.get("errors") or [])
        if report.get("valid") and warning_count:
            status = "Valid with warnings"
            status_detail = f"DLMS validation passed with {warning_count} warning(s)."
        elif report.get("valid"):
            status = "Valid"
            status_detail = "DLMS independent validation passed without warnings."
        else:
            status = "Invalid"
            first_error = (report.get("errors") or ["Pack failed independent validation."])[0]
            status_detail = first_error

        try:
            installed_at = datetime_class.fromtimestamp(os.path.getmtime(root)).strftime("%b %d, %Y %I:%M %p")
        except OSError:
            installed_at = "Unavailable"

        rows.append({
            "folder": folder,
            "id": pack_id,
            "name": manifest.get("name") or runtime_pack.get("name") or folder,
            "version": manifest.get("version") or runtime_pack.get("version") or "",
            "description": manifest.get("description") or runtime_pack.get("description") or "",
            "domain": manifest.get("content_domain") or manifest.get("extends") or "General",
            "matching_count": matching,
            "image_count": image,
            "mixed_count": mixed,
            "dataset_count": matching + image + mixed,
            "file_count": sum(len(files) for _, _, files in os.walk(root)),
            "size": format_bytes(folder_size_bytes(root)),
            "status": status,
            "status_detail": status_detail,
            "protected": protected,
            "generated_quizzes": generated,
            "warning_count": warning_count,
            "error_count": error_count,
            "validation_report": report,
            "installed_at": installed_at,
            "exportable": bool(report.get("valid")),
        })
    return rows


def _content_pack_folder_report(
    folder,
    content_pack_folder,
    *,
    validate_staged_content_pack,
    get_content_pack,
    validation_record,
    format_bytes,
    content_pack_tracked_quiz_count,
    folder_size_bytes=_folder_size_bytes,
    datetime_class=datetime,
):
    """Safely load one installed pack folder and return its independent validation report."""
    folder = str(folder or "").strip()
    if not folder or folder in {".", ".."} or os.path.basename(folder) != folder:
        raise ValueError("Invalid Content Pack folder")
    root = os.path.realpath(os.path.join(content_pack_folder, folder))
    content_root = os.path.realpath(content_pack_folder)
    if os.path.dirname(root) != content_root or not os.path.isdir(root):
        raise FileNotFoundError("Content Pack folder was not found")
    report = validate_staged_content_pack(root)
    pack_id = str(report.get("pack_id") or "").strip().lower()
    discovered = get_content_pack(pack_id) if pack_id else None
    if report.get("valid") and pack_id and (not discovered or os.path.realpath(discovered.get("_root") or "") != root):
        report["valid"] = False
        report.setdefault("errors", []).append("Pack is structurally valid but is not discoverable at runtime, usually because another installed folder uses the same pack id.")
        report.setdefault("checks", []).append(validation_record("Runtime discovery", "FAIL", "pack id conflict or runtime discovery failure"))
    report["folder"] = folder
    report["root"] = root
    report["file_count"] = sum(len(files) for _, _, files in os.walk(root))
    report["size"] = format_bytes(folder_size_bytes(root))
    report["generated_quizzes"] = content_pack_tracked_quiz_count(pack_id) if pack_id and discovered else 0
    try:
        report["installed_at"] = datetime_class.fromtimestamp(os.path.getmtime(root)).strftime("%b %d, %Y %I:%M %p")
    except OSError:
        report["installed_at"] = "Unavailable"
    return report


def _is_medical_pack_manifest(pack_id, pack):
    """Return True when an installed pack declares itself as medical content."""
    if not isinstance(pack, dict):
        return False
    return (
        str(pack.get("content_domain") or "").strip().lower() == "medical"
        or str(pack.get("extends") or "").strip().lower() == "medical"
        # Backward compatibility for the original Medical Study Pack manifest.
        or str(pack_id or "").strip().lower() == "medical"
    )


def _medical_content_available(
    packs=None, *, discover_content_packs, is_medical_pack_manifest
):
    """Return whether Medical Study currently has installed Medical-domain content."""
    packs = packs if isinstance(packs, dict) else discover_content_packs()
    return any(is_medical_pack_manifest(pack_id, pack) for pack_id, pack in packs.items())


def _normalized_content_domain(value):
    """Normalize a human-readable content domain into a stable comparison key."""
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _is_it_pack_manifest(
    pack_id, pack, *, normalized_content_domain=_normalized_content_domain
):
    """Return True for Study Packs intended for IT / Cybersecurity study."""
    if not isinstance(pack, dict):
        return False
    domain = normalized_content_domain(pack.get("content_domain") or pack.get("extends"))
    return domain in {"it", "it_cybersecurity", "cybersecurity", "information_technology"}


def _it_content_available(
    packs=None, *, discover_content_packs, is_it_pack_manifest
):
    packs = packs if isinstance(packs, dict) else discover_content_packs()
    return any(is_it_pack_manifest(pack_id, pack) for pack_id, pack in packs.items())


def content_pack_summary(*, discover_content_packs):
    packs = discover_content_packs()
    summary = []
    for pack_id, pack in packs.items():
        dataset_count = (
            len(pack.get("datasets") or [])
            + len(pack.get("image_datasets") or [])
            + len(pack.get("quiz_datasets") or [])
        )
        summary.append({
            "id": pack_id,
            "name": pack.get("name") or pack_id,
            "version": pack.get("version") or "",
            "description": pack.get("description") or "",
            "modules": pack.get("modules") or [],
            "dataset_count": dataset_count,
        })
    return summary


def _content_pack_concepts(record, *, context, normalize_concept_names):
    """Return validated canonical concepts from a Study Pack record.

    ``concepts`` is the canonical schema field.  ``tags`` remains a legacy
    alias for packs created before question-level concepts were introduced.
    A present canonical field deliberately takes precedence over its alias.
    """
    if not isinstance(record, dict):
        raise ValueError(f"{context}: record must be an object")
    field = "concepts" if "concepts" in record else "tags" if "tags" in record else None
    if field is None:
        return []
    value = record.get(field)
    if not isinstance(value, (str, list)):
        raise ValueError(f"{context}: {field} must be a string or list of strings")
    values = re.split(r"[,;\n]+", value) if isinstance(value, str) else value
    if len(values) > 24:
        raise ValueError(f"{context}: {field} may contain at most 24 concepts")
    for index, item in enumerate(values, 1):
        if not isinstance(item, str):
            raise ValueError(f"{context}: {field}[{index}] must be a string")
        name = re.sub(r"\s+", " ", item).strip()
        if not name:
            raise ValueError(f"{context}: {field}[{index}] must not be empty")
        if len(name) > 120:
            raise ValueError(f"{context}: {field}[{index}] must be 120 characters or fewer")
    # Keep persistence, validation, and Edit Quiz normalization exactly aligned.
    return normalize_concept_names(value)


def _set_content_pack_concepts(
    record, *, context, content_pack_concepts, normalize_concept_names
):
    """Validate a record and write its canonical normalized concepts in place."""
    concepts = content_pack_concepts(record, context=context)
    if "concepts" in record or "tags" in record:
        record["concepts"] = concepts
        record.pop("tags", None)
    return concepts


def _standalone_matching_concepts(
    data, *, context, content_pack_concepts, normalize_concept_names
):
    """Choose concepts for a generated standalone matching question.

    Dataset-level concepts are the explicit question-level metadata.  When
    absent, term-level concepts are combined, normalized, and capped using the
    same persistence limits.  Categories are intentionally never concepts.
    """
    if "concepts" in data or "tags" in data:
        return content_pack_concepts(data, context=context)
    combined = []
    for index, term in enumerate(data.get("terms") or [], 1):
        if "concepts" in term or "tags" in term:
            combined.extend(content_pack_concepts(
                term, context=f"{context}, term {index}"
            ))
    if len(normalize_concept_names(combined)) > 24:
        raise ValueError(f"{context}: combined term concepts may contain at most 24 concepts")
    return normalize_concept_names(combined)


def _hotspot_concepts(
    question,
    image,
    hotspot,
    dataset,
    *,
    context,
    content_pack_concepts,
    normalize_concept_names,
):
    """Use the nearest explicit concept metadata for a hotspot question."""
    for record, label in ((question, "question"), (hotspot, "hotspot"), (image, "image"), (dataset, "dataset")):
        if isinstance(record, dict) and ("concepts" in record or "tags" in record):
            return content_pack_concepts(record, context=f"{context}, {label}")
    return []

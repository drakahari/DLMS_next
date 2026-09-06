"""Persistence and normalization helpers for DLMS Quiz and Law registries."""

import json
import os

from dlms.persistence import json_files


def load_law_registry(
    registry_path,
    *,
    atomic_write_json=json_files._atomic_write_json,
    preserve_malformed_json=json_files._preserve_malformed_json,
):
    default = {
        "version": "1",
        "cases": [],
        "folders": [
            "Torts",
            "Contracts",
            "Civil Procedure",
            "Criminal Law",
            "Property",
            "Constitutional Law",
            "Legal Writing"
        ]
    }

    os.makedirs(os.path.dirname(registry_path), exist_ok=True)

    if not os.path.exists(registry_path):
        try:
            atomic_write_json(registry_path, default, expected_type=dict)
            return default.copy()
        except Exception as e:
            print(f"[LAW REGISTRY ERROR] create failed: {e}")
            return default.copy()

    try:
        with open(registry_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeError) as e:
        try:
            preserve_malformed_json(registry_path)
        except Exception as preserve_error:
            raise RuntimeError(
                "Malformed law.json could not be preserved safely"
            ) from preserve_error
        print(f"[LAW REGISTRY ERROR] load failed: {e}")
        return default.copy()
    except Exception as e:
        print(f"[LAW REGISTRY ERROR] load failed: {e}")
        return default.copy()

    if not isinstance(data, dict):
        try:
            preserve_malformed_json(registry_path)
        except Exception as preserve_error:
            raise RuntimeError(
                "Malformed law.json could not be preserved safely"
            ) from preserve_error
        print("[LAW REGISTRY ERROR] law.json must contain a JSON object")
        return default.copy()

    if (
        ("cases" in data and not isinstance(data["cases"], list))
        or ("folders" in data and not isinstance(data["folders"], list))
    ):
        preserve_malformed_json(registry_path)

    cfg = default.copy()
    cfg.update(data)

    if not isinstance(cfg.get("cases"), list):
        cfg["cases"] = []

    if not isinstance(cfg.get("folders"), list):
        cfg["folders"] = default["folders"]

    return cfg


def save_law_registry(
    registry_path,
    registry,
    *,
    atomic_write_json=json_files._atomic_write_json,
):
    try:
        os.makedirs(os.path.dirname(registry_path), exist_ok=True)

        if not isinstance(registry, dict):
            registry = {
                "version": "1",
                "cases": [],
                "folders": []
            }

        registry.setdefault("version", "1")
        registry.setdefault("cases", [])
        registry.setdefault("folders", [])

        atomic_write_json(registry_path, registry, expected_type=dict)

    except Exception as e:
        print(f"[LAW REGISTRY ERROR] save failed: {e}")
        raise


def load_registry(registry_path, *, registry_lock):
    with registry_lock:
        if not os.path.exists(registry_path):
            return []

        try:
            with open(registry_path, "r", encoding="utf-8") as f:
                registry = json.load(f)

            if registry is None:
                return []

            if not isinstance(registry, list):
                raise ValueError("Quiz registry must contain a JSON list")

            return registry

        except Exception as e:
            print(f"[REGISTRY ERROR] load_registry failed: {e}")
            raise RuntimeError(
                f"Quiz registry could not be loaded safely: {e}"
            ) from e


def save_registry(
    registry_path,
    registry,
    *,
    registry_lock,
    atomic_write_json=json_files._atomic_write_json,
):
    try:
        os.makedirs(os.path.dirname(registry_path), exist_ok=True)

        with registry_lock:
            validated = json.loads(json.dumps(registry))
            if not isinstance(validated, list):
                raise ValueError("Quiz registry must contain a JSON list")

            atomic_write_json(
                registry_path,
                registry,
                indent=4,
                expected_type=list,
            )

    except Exception as e:
        print(f"[REGISTRY ERROR] save_registry failed: {e}")
        raise


def normalize_quiz_folders(registry, *, registry_lock, save_registry):
    """
    Backward-compatible folder support for the Quiz Library.

    Existing quizzes may not have a folder field yet.
    This guarantees every quiz has one without changing quiz files,
    quiz IDs, history, results, or generated HTML/JSON.
    """
    with registry_lock:
        changed = False

        for q in registry:
            folder = str(q.get("folder") or "").strip()

            if not folder:
                q["folder"] = "Uncategorized"
                changed = True

        if changed:
            save_registry(registry)

        return registry

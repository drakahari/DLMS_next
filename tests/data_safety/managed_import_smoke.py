"""Fresh disposable service-level smoke for the managed receiver."""
import json
import os
from pathlib import Path
import sys

from desktop.isolation import AREA, PROJECT, isolated_environment, profile_paths
from desktop.profile_state import new_manifest, publish_manifest
from desktop.backend import acquire_writer_lock


def main():
    name = sys.argv[1]
    paths = profile_paths(name)
    if not (paths["root"] / "desktop-profile.json").exists():
        publish_manifest(paths, new_manifest(name, 49123))
    env = isolated_environment(paths)
    os.environ.clear()
    os.environ.update(env)
    os.environ["PYTHONNOUSERSITE"] = "1"
    os.environ["DLMS_DESKTOP_NONCE"] = "a" * 32
    os.environ["DLMS_DESKTOP_PORT"] = "49123"
    sys.path.insert(0, str(PROJECT))
    lock = acquire_writer_lock(paths["root"] / "backend-writer.lock")
    import app
    from desktop import import_operations
    from werkzeug.datastructures import FileStorage
    mode = sys.argv[2] if len(sys.argv) > 2 else "install"
    fixture = sys.argv[3] if len(sys.argv) > 3 else "data-safety-two.zip"
    if mode == "stage-seed":
        app._publish_quiz("Unrelated Sentinel", [{"number": 1, "type": "choice",
            "question": "Keep this unrelated item?", "choices": [
                {"label": "A", "text": "Yes", "is_correct": True},
                {"label": "B", "text": "No", "is_correct": False}]}],
            registry_folder="Uncategorized")
    if mode == "resume":
        token = sorted((paths["backend"] / "uploads/quiz_bundles").iterdir())[-1].name
    else:
        with (AREA / "fixtures" / fixture).open("rb") as stream:
            token = app._portable_quiz_bundle_service.stage_portable_quiz_bundle(
                FileStorage(stream=stream, filename="synthetic.zip"), content_length=None,
                staging_folder=app.PORTABLE_QUIZ_BUNDLE_STAGING_FOLDER,
                bounded_save_upload=app._bounded_save_upload,
                inspect_bundle=app._inspect_portable_quiz_bundle,
                secure_filename=app.secure_filename)
    if mode != "legacy-stage":
        import_operations.stamp_stage(app, token)
    print("TOKEN", token, flush=True)
    (paths["root"] / "gate-a-token.txt").write_text(token + "\n")
    if mode in {"stage", "stage-seed", "legacy-stage"}:
        lock.close()
        return
    result = app._install_staged_portable_quiz_bundle(token)
    print(json.dumps(result, indent=2), flush=True)
    lock.close()


if __name__ == "__main__":
    main()

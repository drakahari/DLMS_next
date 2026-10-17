"""Native completed-file flush and failure boundaries for staged image packs."""
import os
import json
from pathlib import Path
import subprocess
import sys

import pytest

from dlms.services import content_pack_mutations


def test_completed_staged_file_flush_preserves_bytes_and_closes_handle(tmp_path):
    path = tmp_path / "staged image café 日本.bin"
    original = bytes(range(256)) + b"\r\ncompleted staged bytes\n"
    path.write_bytes(original)
    opened = []
    flushed = []

    def record_open(name, mode):
        handle = open(name, mode)
        opened.append(handle)
        return handle

    def record_flush(fd):
        handle = opened[-1]
        assert handle.fileno() == fd
        assert handle.writable() == (os.name == "nt")
        os.fsync(fd)
        flushed.append(fd)

    content_pack_mutations._fsync_regular_file(
        path, open_file=record_open, fsync=record_flush
    )
    assert len(flushed) == 1
    assert len(opened) == 1 and opened[0].closed
    assert path.read_bytes() == original


def test_flush_failure_propagates_closes_handle_and_preserves_staged_bytes(tmp_path):
    path = tmp_path / "failure image.bin"
    original = b"already completed bytes\x00\xff"
    path.write_bytes(original)
    opened = []
    failure = OSError("synthetic disk flush failed")

    def record_open(name, mode):
        handle = open(name, mode)
        opened.append(handle)
        return handle

    def fail_flush(fd):
        assert opened[-1].fileno() == fd
        raise failure

    with pytest.raises(OSError) as caught:
        content_pack_mutations._fsync_regular_file(
            path, open_file=record_open, fsync=fail_flush
        )
    assert caught.value is failure
    assert len(opened) == 1 and opened[0].closed
    assert path.read_bytes() == original


def test_missing_stage_is_not_created_and_flush_is_not_attempted(tmp_path):
    path = tmp_path / "missing stage.bin"
    flushed = []
    with pytest.raises(FileNotFoundError):
        content_pack_mutations._fsync_regular_file(path, fsync=flushed.append)
    assert flushed == []
    assert not path.exists()


_IMAGE_WORKFLOW = r'''
import hashlib, io, json, os, sys
from pathlib import Path
from PIL import Image
import app

phase, receipt = sys.argv[1:]
app.ensure_db_initialized()
client = app.app.test_client()
if phase == "create":
    draft_id = "windows_flush_draft_123"
    draft = Path(app.IMAGE_BUILDER_DRAFT_FOLDER) / draft_id
    draft.mkdir(parents=True)
    image = io.BytesIO()
    Image.new("RGB", (16, 16), (30, 90, 150)).save(image, "PNG")
    (draft / "diagram.png").write_bytes(image.getvalue())
    with client.get("/study-packs/image-builder") as page:
        assert page.status_code == 200
        token = client.get_cookie("dlms_csrf_token").value
    payload = {
        "images": [{"id": "image_1", "filename": "diagram.png", "original_name": "diagram.png"}],
        "questions": [{"type": "choice", "question": "Which staged image — café 日本?", "image_id": "image_1",
                       "choices": [{"text": "One", "is_correct": True}, {"text": "Two", "is_correct": False}]}],
    }
    with client.post("/study-packs/image-builder/save", data={
        "csrf_token": token, "draft_id": draft_id, "pack_title": "Native staged images",
        "subject": "General", "rights_ok": "on", "builder_payload": json.dumps(payload),
    }) as result:
        assert result.status_code == 302, (result.status_code, result.text)
    assert not draft.exists()

registry = app.load_registry()
assert len(registry) == 1, registry
quiz = registry[0]
with client.get("/api/study/quiz/" + str(quiz["id"])) as status:
    assert status.status_code == 200
    assert status.json["readiness"]["ready"]
packs = app.discover_content_packs()
assert len(packs) == 1 and quiz["source_pack_id"] in packs
root = Path(app.CONTENT_PACK_FOLDER)
files = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
         for p in root.rglob("*") if p.is_file()}
assert any(p.endswith("/diagram.png") for p in files)
if phase == "create":
    png_hash = hashlib.sha256(image.getvalue()).hexdigest()
    assert png_hash in [digest for name, digest in files.items() if name.endswith("/diagram.png")]
connection = app.get_db()
try:
    questions = [row[0] for row in connection.execute("SELECT question_text FROM questions WHERE quiz_id=?", (quiz["id"],))]
    assert questions == ["Which staged image — café 日本?"]
finally:
    connection.close()
assert not any(Path(app.CONTENT_PACK_STAGING_FOLDER).iterdir())
# First startup fills an omitted folder with Uncategorized. Compare published
# identity and content rather than that existing registry-default migration.
identity = {key: quiz[key] for key in ("id", "html", "title", "source_pack_id", "source_dataset_id")}
Path(receipt).write_text(json.dumps({"quiz": identity, "pack_files": files, "questions": questions}, ensure_ascii=False), encoding="utf-8")
'''


def test_image_study_pack_publication_survives_separate_process_reopen(tmp_path):
    """Use the actual receiver and reopen its published Unicode content/assets."""
    data = tmp_path / "synthetic image profile café 日本"
    environment = os.environ.copy()
    environment.update(QUIZAPP_DATA_DIR=str(data), PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    receipts = []
    for phase in ("create", "reopen"):
        receipt = tmp_path / (phase + ".json")
        result = subprocess.run(
            [sys.executable, "-c", _IMAGE_WORKFLOW, phase, str(receipt)],
            cwd=Path(__file__).resolve().parents[1], env=environment,
            capture_output=True, text=True, encoding="utf-8", timeout=60,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        receipts.append(json.loads(receipt.read_text(encoding="utf-8")))
    assert receipts[0] == receipts[1]

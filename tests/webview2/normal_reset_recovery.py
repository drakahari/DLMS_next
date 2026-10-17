"""Normal startup rollback of an externally seeded closed synthetic reset.

The mutation/journal is staged by a separate source helper while DLMS is closed.
This is not a UI-accepted interruption or a normal-package reset invocation.
The unmodified normal executable alone performs startup reconciliation/reopen.
"""
from contextlib import closing
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / ".gate1/windows-native"


def digest(path):
    with path.open("rb") as stream: return hashlib.file_digest(stream, "sha256").hexdigest()


def facts(backend):
    with closing(sqlite3.connect(backend / "results.db")) as conn:
        rows = {name: conn.execute(f'SELECT * FROM "{name}" ORDER BY rowid').fetchall()
                for name in ("quizzes", "questions", "choices", "matching_pairs", "attempts", "attempt_answers", "study_sessions", "study_responses")}
    assets = {path.relative_to(backend).as_posix(): digest(path)
              for directory in ("data", "quizzes", "quiz_assets") for path in (backend / directory).rglob("*")
              if path.is_file() and not path.name.startswith("parse_log_")}
    return {"rows": rows, "assets": assets, "theme": json.loads((backend / "config/portal.json").read_text())["theme"]}


def seed(data, output, safety):
    from package_windows.entry import root_path
    root_path(data)
    from desktop import isolation, maintenance
    isolation.AREA = maintenance.AREA = data
    isolation.PROFILES = data / "profiles"
    paths = isolation.profile_paths("normal01", create=False)
    from desktop.profile_state import read_manifest
    manifest = read_manifest(paths, "normal01")
    if manifest is None: raise ValueError("The exact synthetic normal profile must already exist")
    operation = uuid.uuid4().hex
    if maintenance.read_marker("normal01") is not None: raise ValueError("Preserve an existing journal")
    from desktop.backend import acquire_writer_lock
    writer = acquire_writer_lock(paths["root"] / "backend-writer.lock")
    try:
        with maintenance._external_lock("normal01"):
            backend = paths["backend"]
            before = maintenance._file_inventory(backend)
            directories = maintenance._directory_inventory(backend)
            recovery = maintenance._recovery_dir("normal01", operation)
            maintenance._owned_dir(recovery, create=True)
            preimage = maintenance._copy_verified(backend, recovery / "backend")
            retained = recovery / "externally-seeded-reset-safety.zip"
            shutil.copyfile(safety, retained)
            with retained.open("r+b" if os.name == "nt" else "rb") as stream: os.fsync(stream.fileno())
            assert digest(safety) == digest(retained)
            value = {"version": 1, "name": "normal01", "scope": "settings", "operation_id": operation,
                     "profile_uuid": manifest["uuid"], "epoch": manifest["epoch"], "new_epoch": None,
                     "preimage_sha256": preimage, "phase": "prepared", "safety_backup": retained.name,
                     "retained_safety_sha256": digest(retained), "postimage_sha256": None,
                     "preimage_directories": maintenance._digest(directories), "postimage_directories": None}
            maintenance._write("normal01", value)
            assert maintenance._file_inventory(backend) == before
            baseline = {"operation_id": operation, "manifest": manifest,
                        "preimage_sha256": preimage, "directories_sha256": maintenance._digest(directories),
                        "facts": facts(backend), "retained_safety_sha256": digest(retained),
                        "external_journal_seed": True, "ui_accepted_interruption": False}
            (output / "seed-baseline.json").write_text(json.dumps(baseline, indent=2) + "\n")
            value["phase"] = "mutation_started"; maintenance._write("normal01", value)
            # The helper owns only this explicitly marked synthetic backend.
            (backend / "config/portal.json").unlink()
            source = next(path for path in (backend / "data").rglob("*.json") if path.is_file())
            source.unlink()
            (backend / "externally-seeded-partial-reset.tmp").write_bytes(b"synthetic interrupted reset")
            os._exit(79)  # Exact child only; release its writer/maintenance handles.
    finally:
        writer.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    exe, out = args.exe.resolve(strict=True), args.output.absolute()
    if out.exists() or not all(path.is_relative_to(WORK) for path in (exe, out)):
        raise ValueError("Fresh project-local normal candidate/evidence only")
    out.mkdir(mode=0o700)
    from package_windows_webview2.acceptance import payload_binding
    binding = payload_binding(exe, args.inventory)
    report = {"normal_package_startup_reconciliation": True, "normal_package_reset_invocation": False,
              "external_journal_seed": True, "source_helper_mutation": True,
              "ui_accepted_interruption": False, "app_test_hooks": False, "physical_acceptance": False,
              "normal_executable": str(exe), **binding, "passed": False}
    def invoke(module, values, label, timeout=180):
        with (out / (label + ".log")).open("w", encoding="utf-8") as log:
            result = subprocess.run([sys.executable, "-X", "utf8", "-m", module, *map(str, values)],
                                    cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
        assert result.returncode == 0, label
    try:
        workflow = out / "initial-normal-workflow"
        invoke("tests.webview2.normal_candidate", ["--exe", exe, "--inventory", args.inventory, "--output", workflow], "initial-normal-workflow")
        data = workflow / "Synthetic data 日本語 with spaces"
        backend = data / "profiles/normal01/backend"
        before = facts(backend)
        external = {name: digest(workflow / name) for name in ("normal-export.zip", "library-reference.txt", "individual-quiz.txt")}
        command = [sys.executable, "-X", "utf8", "-m", "tests.webview2.normal_reset_recovery", "--seed", str(data), str(out), str(workflow / "normal-export.zip")]
        with (out / "external-seed.log").open("w", encoding="utf-8") as log:
            child = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=90)
        assert child.returncode == 79
        baseline = json.loads((out / "seed-baseline.json").read_text())
        marker = data / "maintenance/normal01/active.json"
        assert json.loads(marker.read_text())["phase"] == "mutation_started"
        assert not (backend / "config/portal.json").exists()
        invoke("tests.webview2.normal_walkthrough_launch", ["--exe", exe, "--inventory", args.inventory,
               "--data-root", data, "--profile", "normal01", "--expected-workflow", workflow / "result.json",
               "--output", out / "normal-reconcile-reopen"], "normal-reconcile-reopen")
        completed = data / "maintenance/normal01" / ("receipt-" + baseline["operation_id"] + ".json")
        receipt = json.loads(completed.read_text())
        assert receipt["phase"] == "rolled_back" and receipt["preimage_sha256"] == baseline["preimage_sha256"]
        assert receipt["preimage_directories"] == baseline["directories_sha256"] and not marker.exists()
        assert facts(backend) == before
        assert not (backend / "externally-seeded-partial-reset.tmp").exists()
        assert all(digest(workflow / name) == value for name, value in external.items())
        retained = data / "recovery/normal01" / baseline["operation_id"] / receipt["safety_backup"]
        assert digest(retained) == baseline["retained_safety_sha256"]
        with closing(sqlite3.connect(backend / "results.db")) as conn:
            assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert payload_binding(exe, args.inventory) == binding
        report.update(passed=True, quiz_study_exam_theme_assets_preserved=True, external_exports_backup_preserved=external,
                      actual_frozen_journal_reconciled=True, rollback_receipt_sha256=digest(completed),
                      preimage_sha256=baseline["preimage_sha256"], retained_safety_sha256=digest(retained),
                      separate_normal_reopens=2, normal_cleanup_verified=True, payload_verified_before_and_after=True)
    finally:
        (out / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    if sys.argv[1:2] == ["--seed"]:
        if len(sys.argv) != 5: raise SystemExit("Exact source-helper arguments required")
        data, output, safety = map(lambda value: Path(value).resolve(strict=True), sys.argv[2:])
        if not all(path.is_relative_to(WORK) for path in (data, output, safety)):
            raise ValueError("Only explicit project-local synthetic seed paths")
        seed(data, output, safety)
    else:
        main()

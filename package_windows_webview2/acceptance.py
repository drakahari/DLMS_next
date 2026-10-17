"""Bind normal-package test evidence to every exact frozen payload byte."""
from pathlib import Path
import hashlib
import json
import os
import stat


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def payload_binding(executable, inventory_path):
    executable, inventory_path = Path(executable).absolute(), Path(inventory_path).absolute()
    if executable.name != "DLMS-Desktop-WebView2.exe":
        raise ValueError("Expected the normal WebView2 executable")
    if os.name == "nt":
        from desktop.windows_files import assert_path
        assert_path(executable, leaf=True)
        assert_path(inventory_path, leaf=True)
    payload = executable.parent
    inventory_bytes = inventory_path.read_bytes()
    inventory_sha256 = hashlib.sha256(inventory_bytes).hexdigest()
    rows = json.loads(inventory_bytes)
    expected = {}
    for row in rows:
        name = row["path"]
        if not isinstance(name, str) or not name:
            raise ValueError("Unsafe or duplicate payload inventory entry")
        path = Path(name)
        if (path.is_absolute() or path.drive or ".." in path.parts
                or "\\" in name or ":" in name or name in expected):
            raise ValueError("Unsafe or duplicate payload inventory entry")
        expected[name] = row["sha256"]
    actual = {}
    pending = [payload]
    while pending:
        directory = pending.pop()
        value = directory.lstat()
        if not stat.S_ISDIR(value.st_mode) or getattr(value, "st_file_attributes", 0) & 0x400:
            raise ValueError("Payload directory aliases are refused")
        for path in directory.iterdir():
            value = path.lstat()
            if getattr(value, "st_file_attributes", 0) & 0x400:
                raise ValueError("Payload reparse points are refused")
            if stat.S_ISDIR(value.st_mode):
                pending.append(path)
            elif stat.S_ISREG(value.st_mode) and value.st_nlink == 1:
                actual[path.relative_to(payload).as_posix()] = digest(path)
            else:
                raise ValueError("Payload non-regular or linked entries are refused")
    if actual != expected:
        raise ValueError("Unknown, missing or changed payload bytes")
    if digest(inventory_path) != inventory_sha256:
        raise ValueError("Payload inventory changed during verification")
    return {"normal_executable_sha256": actual[executable.name],
            "payload_inventory_sha256": inventory_sha256}


def require_normal_acceptance(receipt, executable, inventory_path):
    executable = Path(executable).absolute()
    if (Path(receipt["normal_executable"]).resolve() != executable.resolve()
            or len(receipt["runs"]) < 2 or receipt.get("instrumented") is not False
            or receipt.get("payload_verified_before_and_after") is not True
            or receipt.get("owned_webview2_renderer_verified") is not True
            or receipt.get("ocr") is not True
            or not all(run.get("exact_cleanup") is True for run in receipt["runs"])):
        raise ValueError("Normal executable acceptance does not match the payload")
    binding = payload_binding(executable, inventory_path)
    if any(receipt.get(key) != value for key, value in binding.items()):
        raise ValueError("Normal executable acceptance is not bound to these payload bytes")
    return binding

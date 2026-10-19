"""Manual, per-user Fedora synthetic pilot install and exact-owned removal.

This source-side tool is not bundled into the application. It never installs
system-wide, updates an existing pilot, or removes profile data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import shutil

APP_ID = "io.github.drakahari.DLMSDesktop"
VERSION = "pilot-01"
PROFILE = "pilot01"
ARTWORK_SHA256 = "f14a4011e95c2823ab7b29da3904010338a6ad22222d9aabf367189945c06888"
SIZES = (16, 24, 32, 48, 64)
MARKER_NAME = ".dlms-desktop-installed-pilot.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inventory(root: Path) -> str:
    """Canonical file/link digest, compatible with artifact_inventory.py."""
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"Payload is not a plain directory: {root}")
    entries = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            if not path.resolve().is_relative_to(root):
                raise ValueError(f"Payload link escapes its root: {relative}")
            entries.append({"path": relative, "kind": "symlink",
                            "target": os.readlink(path), "bytes": 0})
        elif path.is_file():
            entries.append({"path": relative, "kind": "file",
                            "bytes": path.stat().st_size, "sha256": sha256(path)})
        elif not path.is_dir():
            raise ValueError(f"Payload contains a special file: {relative}")
    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def paths(home: Path) -> dict[str, Path]:
    from desktop.install_manifest import layout
    return layout(home)


def _assert_home(home: Path) -> None:
    if (not home.is_absolute() or home.is_symlink() or not home.is_dir()
            or home.stat().st_uid != os.getuid()):
        raise ValueError("Pilot home must be an existing, owned absolute directory")


def _assert_parent_chain(path: Path, home: Path) -> None:
    if not path.is_relative_to(home):
        raise ValueError("Pilot output escapes the selected home")
    for part in (path, *path.parents):
        if part == home:
            break
        if part.is_symlink():
            raise ValueError(f"Pilot path has a symlink component: {part}")
        if part.exists() and (not part.is_dir() or part.stat().st_uid != os.getuid()):
            if part != path or part.is_dir():
                raise ValueError(f"Pilot path has an unexpected parent: {part}")


def _mkdir_parent(path: Path, home: Path, *, public: bool = False) -> None:
    _assert_parent_chain(path, home)
    missing = []
    parent = path.parent
    while parent != home and not parent.exists():
        missing.append(parent)
        parent = parent.parent
    for part in reversed(missing):
        part.mkdir(mode=0o755 if public else 0o700)
    _assert_parent_chain(path, home)


def _write_exclusive(path: Path, data: bytes, mode: int) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), mode)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _atomic_manifest(path: Path, value: dict) -> None:
    temporary = path.with_name(".pilot-install-" + value["install_id"] + ".tmp")
    _write_exclusive(temporary, (json.dumps(value, sort_keys=True, indent=2) + "\n").encode(), 0o600)
    os.replace(temporary, path)


def _pilot_marker(root: Path, install_id: str) -> dict:
    return {"kind": "dlms-desktop-installed-synthetic-pilot", "version": 1,
            "uid": os.getuid(), "root": str(root), "profile": PROFILE,
            "install_id": install_id}


def _launcher(p: dict[str, Path]) -> bytes:
    # All paths are generated below one known home. There is no shell expansion
    # of user-supplied data and no generic `--data-root` fallback.
    for path in (p["current"], p["data"], p["manifest"]):
        if re.search(r"[^A-Za-z0-9_./-]", str(path)):
            raise ValueError("Pilot launcher path requires shell quoting beyond this bounded layout")
    text = ("#!/bin/sh\n"
            "# DLMS Desktop synthetic Fedora pilot; preserve graphical XDG_RUNTIME_DIR.\n"
            f"test -f '{p['manifest']}' || exit 2\n"
            f"test -x '{p['current']}/DLMS-Desktop/DLMS-Desktop' || exit 2\n"
            f"exec '{p['current']}/DLMS-Desktop/DLMS-Desktop' --profile {PROFILE} "
            f"--installed-pilot-root '{p['data']}'\n")
    return text.encode()


def _entry(p: dict[str, Path]) -> bytes:
    return ("[Desktop Entry]\nType=Application\nName=DLMS Desktop (Pilot)\n"
            "Comment=Synthetic Fedora installation pilot\n"
            f"Exec={p['launcher']}\nIcon={p['icon_64']}\nTerminal=false\n"
            "Categories=Education;\nStartupNotify=true\n").encode()


def repair_icon_entry(home: Path, backup_dir: Path) -> dict:
    """Repair only the verified pilot desktop entry; retain exact rollback bytes.

    The payload, launcher, icon files and profile are untouched. The backup
    directory must be a fresh, owned directory outside the installed target.
    """
    before = removal_plan(home)
    p = paths(home)
    for key in ("entry", "icon_64", "manifest"):
        if p[key].is_symlink() or not p[key].is_file() or p[key].stat().st_uid != os.getuid():
            raise ValueError(f"Pilot {key} must be an owned regular file")
    if (not backup_dir.is_absolute() or any(part.is_symlink() for part in (backup_dir, *backup_dir.parents))
            or not backup_dir.is_dir() or backup_dir.stat().st_uid != os.getuid()):
        raise ValueError("Icon repair backup directory must be a plain, owned directory")
    if backup_dir == p["opt"] or backup_dir.is_relative_to(p["opt"]) or backup_dir.is_relative_to(p["data"]):
        raise ValueError("Icon repair backups must be outside the installed pilot")
    if any(backup_dir.iterdir()):
        raise FileExistsError("Icon repair backup directory must be empty")
    if sha256(p["icon_64"]) != before["file_sha256"]["icon_64"]:
        raise ValueError("Pilot icon changed")
    old_entry = p["entry"].read_bytes()
    if old_entry != _entry(p).replace(f"Icon={p['icon_64']}".encode(), f"Icon={APP_ID}".encode()):
        raise ValueError("Pilot desktop entry is not the reviewed prior version")
    _write_exclusive(backup_dir / "entry.before.desktop", old_entry, 0o600)
    _write_exclusive(backup_dir / "manifest.before.json", p["manifest"].read_bytes(), 0o600)
    replacement = p["entry"].with_name(".dlms-desktop-pilot-icon.tmp")
    _write_exclusive(replacement, _entry(p), 0o644)
    os.replace(replacement, p["entry"])
    after = dict(before)
    after["file_sha256"] = {**before["file_sha256"], "entry": sha256(p["entry"])}
    _atomic_manifest(p["manifest"], after)
    removal_plan(home)
    return after


def install(home: Path, payload: Path, archive: Path, archive_digest: str,
            payload_digest: str, *, fail_at: str | None = None) -> dict:
    """Create only new pilot paths; failures retain a partial manifest for review."""
    _assert_home(home)
    p = paths(home)
    payload = payload.absolute()
    if not re.fullmatch(r"[0-9a-f]{64}", archive_digest) or sha256(archive) != archive_digest:
        raise ValueError("Reviewed archive SHA-256 differs")
    if not re.fullmatch(r"[0-9a-f]{64}", payload_digest) or inventory(payload) != payload_digest:
        raise ValueError("Reviewed extracted-payload inventory differs")
    exe = payload / "DLMS-Desktop"
    artwork = payload / "_internal/desktop_assets/dlms_omarchy.png"
    if not exe.is_file() or not os.access(exe, os.X_OK) or sha256(artwork) != ARTWORK_SHA256:
        raise ValueError("Pilot payload lacks the reviewed executable or artwork")
    icon_sources = {size: payload / "_internal/desktop_assets/icons/hicolor"
                    / f"{size}x{size}/apps/{APP_ID}.png" for size in SIZES}
    if any(not path.is_file() for path in icon_sources.values()):
        raise ValueError("Pilot payload has incomplete launcher icon resources")
    # The application-specific opt root and every published leaf must be new.
    for key, path in p.items():
        _assert_parent_chain(path, home)
        if (key == "opt" or key in {"version", "current", "manifest", "launcher", "entry", "data"}
                or key.startswith("icon_")) and (path.exists() or path.is_symlink()):
            raise FileExistsError(f"Pilot target already exists; no overwrite: {path}")
    install_id = os.urandom(16).hex()
    manifest = {"version": 1, "phase": "installing", "install_id": install_id,
                "home": str(home), "archive_sha256": archive_digest,
                "payload_inventory_sha256": payload_digest,
                "owned_paths": {key: str(value) for key, value in p.items()}}
    _mkdir_parent(p["opt"], home)
    p["opt"].mkdir(mode=0o700)
    _write_exclusive(p["manifest"], (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode(), 0o600)
    _mkdir_parent(p["version"], home)
    p["version"].mkdir(mode=0o700)
    shutil.copytree(payload, p["version"] / "DLMS-Desktop", symlinks=True)
    if inventory(p["version"] / "DLMS-Desktop") != payload_digest:
        raise RuntimeError("Installed payload differs from the reviewed source")
    if fail_at == "payload":
        raise RuntimeError("Synthetic failure after payload copy")
    _mkdir_parent(p["data"], home)
    p["data"].mkdir(mode=0o700)
    _write_exclusive(p["marker"], (json.dumps(_pilot_marker(p["data"], install_id), sort_keys=True) + "\n").encode(), 0o600)
    hashes = {"marker": sha256(p["marker"])}
    for size, source in icon_sources.items():
        target = p[f"icon_{size}"]
        _mkdir_parent(target, home, public=True)
        _write_exclusive(target, source.read_bytes(), 0o644)
        hashes[f"icon_{size}"] = sha256(target)
    _mkdir_parent(p["launcher"], home, public=True)
    _write_exclusive(p["launcher"], _launcher(p), 0o755)
    hashes["launcher"] = sha256(p["launcher"])
    if fail_at == "resources":
        raise RuntimeError("Synthetic failure after launcher and icons")
    os.symlink(f"versions/{VERSION}", p["current"])
    manifest.update({"phase": "activating", "file_sha256": hashes,
                     "current_target": f"versions/{VERSION}"})
    _atomic_manifest(p["manifest"], manifest)
    if fail_at == "activation":
        raise RuntimeError("Synthetic failure after pointer publication")
    _mkdir_parent(p["entry"], home, public=True)
    _write_exclusive(p["entry"], _entry(p), 0o644)
    manifest["file_sha256"]["entry"] = sha256(p["entry"])
    manifest["phase"] = "complete"
    _atomic_manifest(p["manifest"], manifest)
    return manifest


def removal_plan(home: Path) -> dict:
    """Verify exact-owned pilot files; never include the data root in removal."""
    _assert_home(home)
    p = paths(home)
    manifest_path = p["manifest"]
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("Pilot installation manifest is unavailable")
    manifest = json.loads(manifest_path.read_text())
    if "manifest_format" in manifest or manifest.get("version") == 2:
        from .manual_replace import removal_plan as expanded_plan
        return expanded_plan(home)
    if (manifest.get("version") != 1 or manifest.get("phase") != "complete"
            or manifest.get("home") != str(home)
            or manifest.get("owned_paths") != {key: str(value) for key, value in p.items()}
            or manifest.get("current_target") != f"versions/{VERSION}"):
        raise ValueError("Pilot installation identity or phase needs inspection")
    if not p["current"].is_symlink() or os.readlink(p["current"]) != manifest["current_target"]:
        raise ValueError("Pilot pointer changed; removal refused")
    if inventory(p["version"] / "DLMS-Desktop") != manifest["payload_inventory_sha256"]:
        raise ValueError("Pilot payload changed; removal refused")
    for key, digest in manifest["file_sha256"].items():
        if sha256(p[key]) != digest:
            raise ValueError(f"Pilot-owned file changed; removal refused: {p[key]}")
    if p["data"].is_symlink() or not p["data"].is_dir():
        raise ValueError("Pilot data root changed; removal refused")
    marker = json.loads(p["marker"].read_text())
    if marker != _pilot_marker(p["data"], manifest["install_id"]):
        raise ValueError("Pilot data marker changed; removal refused")
    # A descriptor may be stale; conservatively refuse until inspected.
    for owner in (p["data"] / "shell" / PROFILE / "instance-owner.json",
                  p["data"] / "profiles" / PROFILE / "instance-owner.json"):
        if owner.exists() or owner.is_symlink():
            raise ValueError("Pilot profile may be in use; removal refused")
    return manifest


def remove(home: Path) -> None:
    """Remove reviewed application files only; retain all pilot data."""
    plan = removal_plan(home)
    if 'retained_versions' in plan:
        raise ValueError('Expanded installation removal is plan-only; retained versions/data preserved')
    p = paths(home)
    # Disable menu launch before deleting its target. Never touch data root.
    p["entry"].unlink()
    p["launcher"].unlink()
    p["current"].unlink()
    for size in SIZES:
        p[f"icon_{size}"].unlink()
    shutil.rmtree(p["version"])
    p["manifest"].unlink()
    for directory in (p["version"].parent, p["opt"]):
        directory.rmdir()  # Refuse to remove a directory containing unrelated work.


def main() -> None:
    parser = argparse.ArgumentParser(description="Explicit Fedora per-user synthetic DLMS Desktop pilot")
    parser.add_argument("--payload", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--archive-sha256")
    parser.add_argument("--payload-inventory-sha256")
    parser.add_argument("--removal-plan", action="store_true")
    parser.add_argument("--remove", action="store_true")
    parser.add_argument("--repair-icon-entry", action="store_true")
    parser.add_argument("--repair-backup-dir", type=Path)
    args = parser.parse_args()
    home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    if args.repair_icon_entry:
        if args.repair_backup_dir is None:
            parser.error("icon repair requires --repair-backup-dir")
        result = repair_icon_entry(home, args.repair_backup_dir)
        print(json.dumps({"phase": result["phase"], "entry_sha256": result["file_sha256"]["entry"],
                          "backup_dir": str(args.repair_backup_dir)}, indent=2))
    elif args.removal_plan or args.remove:
        result = removal_plan(home)
        if args.remove:
            remove(home)
            print("Pilot application files removed; synthetic data root retained:", paths(home)["data"])
        else:
            print(json.dumps(result, indent=2))
    else:
        if not all((args.payload, args.archive, args.archive_sha256, args.payload_inventory_sha256)):
            parser.error("install requires --payload, --archive and both reviewed SHA-256 values")
        result = install(home, args.payload, args.archive,
                         args.archive_sha256, args.payload_inventory_sha256)
        print(json.dumps({"phase": result["phase"], "install_id": result["install_id"],
                          "owned_paths": result["owned_paths"]}, indent=2))


if __name__ == "__main__":
    main()

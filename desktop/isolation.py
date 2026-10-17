"""Fail-closed, project-local paths for the Gate 1 proof of concept."""
from __future__ import annotations

import os
from pathlib import Path
import re
import stat
import sys

FROZEN = bool(getattr(sys, "frozen", False))
PROJECT = Path(sys._MEIPASS).resolve() if FROZEN else Path(__file__).resolve().parent.parent
if FROZEN:
    configured_area = os.environ.get("DLMS_DESKTOP_DATA_ROOT", "")
    if not configured_area or not Path(configured_area).is_absolute():
        raise RuntimeError("Packaged Desktop requires an explicit absolute scoped data root")
    AREA = Path(configured_area)
    if AREA.is_symlink() or AREA.resolve().is_relative_to(PROJECT):
        raise RuntimeError("Packaged Desktop data root is unsafe or inside the application payload")
else:
    macos = sys.modules.get('package_macos')
    if sys.platform == 'darwin' and macos is not None and macos.ACTIVE:
        from .macos_paths import prepare_root
        AREA = prepare_root(os.environ.get('DLMS_MACOS_DATA_ROOT'), create=False)
    else:
        AREA = PROJECT / ".gate1" / "windows-native" / "data" if os.name == "nt" else PROJECT / ".gate1"
PROFILES = AREA / "profiles"
NAME = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")


def assert_safe_leaf(path: Path) -> None:
    """Reject planted symlinks and special files before shell-owned writes."""
    if os.name == "nt":
        from .windows_files import assert_path
        assert_path(path, leaf=True)
    if path.is_symlink():
        raise ValueError(f"Disposable output is a symlink: {path}")
    if path.exists() and not stat.S_ISREG(path.stat().st_mode):
        raise ValueError(f"Disposable output is not a regular file: {path}")


def profile_paths(name: str, *, create: bool = True) -> dict[str, Path]:
    if not NAME.fullmatch(name):
        raise ValueError("Profile name must be 1–32 lowercase letters, digits, _ or -, starting with a letter.")
    tombstone = AREA / "removed" / f"{name}.json"
    if create and (tombstone.exists() or tombstone.is_symlink()):
        raise ValueError(f"Disposable profile {name} has an intentional-removal record. Use a new profile name; it will not be silently recreated")
    roots = (AREA, PROFILES, PROFILES / name)
    for path in roots:
        if os.name == "nt":
            from .windows_files import assert_path
            assert_path(path)
        if path.is_symlink():
            raise ValueError(f"Disposable profile path is a symlink: {path}")
        if path.exists() and not path.is_dir():
            raise ValueError(f"Disposable profile path is not a directory: {path}")
        if create:
            path.mkdir(mode=0o700, exist_ok=True)
    profile = roots[-1]
    resolved = profile.resolve()
    if resolved.parent != PROFILES.resolve():
        raise ValueError("Disposable profile escapes this project.")
    paths = {
        "root": profile,
        "backend": profile / "backend",
        "web_storage": profile / "web" / "storage",
        "web_cache": profile / "web" / "cache",
        "home": profile / "home",
        "xdg_data": profile / "xdg" / "data",
        "xdg_config": profile / "xdg" / "config",
        "xdg_cache": profile / "xdg" / "cache",
        "tmp": profile / "tmp",
        "downloads": profile / "downloads",
        "logs": profile / "logs",
    }
    for path in paths.values():
        if os.name == "nt":
            from .windows_files import assert_path
            assert_path(path)
        for component in (path, *path.parents):
            if component == profile.parent:
                break
            if component.is_symlink():
                raise ValueError(f"Disposable profile component is a symlink: {component}")
        if create:
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
            if os.name == "nt":
                assert_path(path)
    return paths


def isolated_environment(paths: dict[str, Path]) -> dict[str, str]:
    result = {key: value for key, value in os.environ.items()
              if not key.startswith(("DLMS_", "QUIZAPP_"))
              and key not in {"QTWEBENGINE_DISABLE_SANDBOX", "QTWEBENGINE_CHROMIUM_FLAGS",
                              "QTWEBENGINE_PROCESS_PATH", "QT_PLUGIN_PATH",
                              "QT_QPA_PLATFORM_PLUGIN_PATH", "PYTHONPATH", "PYTHONHOME"}}
    result.update({
        "HOME": str(paths["home"]),
        "XDG_DATA_HOME": str(paths["xdg_data"]),
        "XDG_CONFIG_HOME": str(paths["xdg_config"]),
        "XDG_CACHE_HOME": str(paths["xdg_cache"]),
        "TMPDIR": str(paths["tmp"]),
        "TMP": str(paths["tmp"]),
        "TEMP": str(paths["tmp"]),
        "QUIZAPP_DATA_DIR": str(paths["backend"]),
        "DLMS_DESKTOP_PROFILE": str(paths["root"]),
        "DLMS_NO_BROWSER": "1",
    })
    if os.name == "nt":
        from .windows_home import prepare
        prepare(paths['home'])
        result.update(USERPROFILE=str(paths["home"]), LOCALAPPDATA=str(paths["xdg_data"]),
                      APPDATA=str(paths["xdg_config"]))
    if FROZEN:
        result["DLMS_DESKTOP_DATA_ROOT"] = str(AREA)
        result["DLMS_DESKTOP_ROOT_KIND"] = os.environ.get("DLMS_DESKTOP_ROOT_KIND", "disposable")
    macos = sys.modules.get('package_macos')
    if sys.platform == 'darwin' and macos is not None and macos.ACTIVE:
        result['DLMS_MACOS_DATA_ROOT'] = str(AREA)
        result['DLMS_DESKTOP_DATA_ROOT'] = str(AREA)
        result['DLMS_DESKTOP_ROOT_KIND'] = 'macos-candidate'
    # The Wayland socket is supplied by the existing desktop session. It is a
    # display transport, not an application data profile; do not change it.
    return result

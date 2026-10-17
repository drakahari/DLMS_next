"""Compare one normal frozen payload with the checked-out Desktop source.

Run with the pinned build environment. This reads the artifact and source only;
it does not launch DLMS or open a profile.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import marshal
from pathlib import Path
from types import CodeType

from PyInstaller.archive.readers import CArchiveReader


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalized(code: CodeType) -> CodeType:
    return code.replace(
        co_filename="",
        co_consts=tuple(normalized(item) if isinstance(item, CodeType) else item
                        for item in code.co_consts),
    )


def module_path(project: Path, name: str) -> Path:
    if name == "app":
        return project / "app.py"
    parts = name.split(".")
    base = project / ({"desktop":"desktop", "package_fedora":"package_fedora"}.get(parts[0],"dlms"))
    suffix = parts[1:]
    file = base.joinpath(*suffix).with_suffix(".py") if suffix else base / "__init__.py"
    if file.is_file():
        return file
    package = base.joinpath(*suffix) / "__init__.py"
    if package.is_file():
        return package
    raise FileNotFoundError(f"Frozen module has no captured source: {name}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", required=True, type=Path)
    parser.add_argument("--payload", required=True, type=Path)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--build-pyz", required=True, type=Path)
    parser.add_argument("--ocr-bundle", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    project, payload = args.project.resolve(), args.payload.resolve()
    if args.output.resolve().is_relative_to(payload):
        raise ValueError("Evidence output must stay outside the payload")
    archive = CArchiveReader(str(args.exe.resolve()))
    if "entry_normal" not in archive.toc or "entry_instrumented" in archive.toc:
        raise AssertionError("The executable is not the normal entry")
    packed_pyz = archive.extract("PYZ.pyz")
    if packed_pyz != args.build_pyz.read_bytes():
        raise AssertionError("Embedded PYZ differs from the build output")
    pyz = archive.open_embedded_archive("PYZ.pyz")
    selected = sorted(name for name in pyz.toc
                      if name == "app" or name == "desktop" or name.startswith("desktop.")
                      or name == "dlms" or name.startswith("dlms.")
                      or name == "package_fedora" or name.startswith("package_fedora."))
    if not selected or any(name.startswith("tests.") for name in pyz.toc):
        raise AssertionError("Frozen module selection is unexpected")
    expected_modules = {"app"}
    for prefix, base in (("desktop", project / "desktop"),
                         ("dlms", project / "dlms")):
        for path in base.rglob("*.py"):
            parts = list(path.relative_to(base).with_suffix("").parts)
            if parts[-1] == "__init__":
                parts.pop()
            expected_modules.add(".".join((prefix, *parts)))
    expected_modules.update({'package_fedora','package_fedora.manage','package_fedora.manage_gui',
                             'package_fedora.installation','package_fedora.install_pilot',
                             'package_fedora.manual_replace','package_fedora.replace_pilot',
                             'package_fedora.user_variant'})
    if set(selected) != expected_modules:
        raise AssertionError(f"Frozen module set differs: missing={sorted(expected_modules-set(selected))}, "
                             f"extra={sorted(set(selected)-expected_modules)}")
    modules = {}
    for name in selected:
        path = module_path(project, name)
        source = path.read_bytes()
        actual = pyz.extract(name)
        expected = compile(source, str(path), "exec", dont_inherit=True, optimize=0)
        if normalized(actual) != normalized(expected):
            raise AssertionError(f"Frozen module differs from source: {name} ({path}; "
                                 f"stored={digest(marshal.dumps(normalized(actual)))}, "
                                 f"compiled={digest(marshal.dumps(normalized(expected)))})")
        modules[name] = {"source": path.relative_to(project).as_posix(),
                         "source_sha256": digest(source)}
    entry = (project / "package_fedora/entry_normal.py").read_bytes()
    if normalized(marshal.loads(archive.extract("entry_normal"))) != normalized(
            compile(entry, "entry_normal.py", "exec", dont_inherit=True, optimize=0)):
        raise AssertionError("Frozen normal entry differs from source")
    assets = []
    for source_root, target_root in (
        (project / "static", payload / "_internal/static"),
        (project / "templates", payload / "_internal/templates"),
        (project / "dlms/theme_sources", payload / "_internal/dlms/theme_sources"),
        (project / "desktop_assets", payload / "_internal/desktop_assets"),
    ):
        for source_path in sorted(source_root.rglob("*")):
            if not source_path.is_file():
                continue
            relative = source_path.relative_to(source_root)
            target = target_root / relative
            if not target.is_file() or source_path.read_bytes() != target.read_bytes():
                raise AssertionError(f"Frozen asset differs: {relative}")
            assets.append(target.relative_to(payload).as_posix())
    for source_path, target in (
        (project / "init.sql", payload / "_internal/init.sql"),
        (project / "LICENSE", payload / "_internal/notices/source/LICENSE"),
    ):
        if not target.is_file() or source_path.read_bytes() != target.read_bytes():
            raise AssertionError(f"Frozen asset differs: {target}")
        assets.append(target.relative_to(payload).as_posix())
    ocr_files = []
    for source_path in sorted(args.ocr_bundle.resolve().rglob("*")):
        if not source_path.is_file():
            continue
        target = payload / "_internal/ocr/tesseract" / source_path.relative_to(args.ocr_bundle.resolve())
        if not target.is_file() or source_path.read_bytes() != target.read_bytes():
            raise AssertionError(f"Frozen OCR file differs: {source_path.name}")
        ocr_files.append(target.relative_to(payload).as_posix())
    result = {"embedded_pyz_sha256": digest(packed_pyz), "embedded_pyz_matches_build": True,
              "normal_entry_matches": True, "modules": modules,
              "module_count": len(modules), "asset_count": len(assets),
              "ocr_file_count": len(ocr_files), "assets": assets, "ocr_files": ocr_files,
              "tests_modules_present": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items()
                      if key not in {"modules", "assets", "ocr_files"}}, indent=2))


if __name__ == "__main__":
    main()

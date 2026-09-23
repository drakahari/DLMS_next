"""Check the active native-build interpreter without building or importing DLMS."""
from __future__ import annotations

import ast
import importlib
from importlib import metadata
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
# Distribution names are not always import names. Versions live only in the lock.
IMPORT_NAMES = {
    "pyinstaller": "PyInstaller",
    "pyinstaller-hooks-contrib": "_pyinstaller_hooks_contrib",
    "pillow": "PIL.Image",
    "pyyaml": "yaml",
}


def locked_requirements(path: Path, seen=None) -> dict[str, str]:
    """Read our exact-pin build manifest, including its runtime lock inclusion.

    Fail closed if future manifest syntax needs support instead of ignoring it.
    """
    seen = set() if seen is None else seen
    path = path.resolve()
    if path in seen:
        raise ValueError(f"Repeated/circular requirements inclusion: {path}")
    seen.add(path)
    pins = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("-r "):
            entries = locked_requirements(path.parent / line[3:].strip(), seen)
        else:
            match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+!-]+)", line)
            if not match:
                raise ValueError(f"Unsupported release requirement in {path}: {line}")
            name, version = match.groups()
            entries = {re.sub(r"[-_.]+", "-", name).lower(): version}
        for name, version in entries.items():
            if name in pins and pins[name] != version:
                raise ValueError(f"Conflicting release pins for {name}")
            pins[name] = version
    return pins


def spec_dependencies(root: Path) -> tuple[set[str], set[str]]:
    """Read literal hidden imports and metadata requirements without executing specs."""
    imports, distributions = set(), set()
    for filename in ("DLMS.spec", "DLMS-OCR-Probe.spec"):
        tree = ast.parse((root / filename).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "hiddenimports":
                imports.update(ast.literal_eval(node.value))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "copy_metadata":
                distributions.add(ast.literal_eval(node.args[0]))
    # Local DLMS modules are not imported: doing so can initialize application data.
    return {name for name in imports if not name.startswith("dlms.")}, distributions


def build_python(root: Path, platform: str = sys.platform) -> Path:
    return root / ".venv-build" / ("Scripts/python.exe" if platform == "win32" else "bin/python")


def check_dependencies(root: Path = ROOT) -> None:
    try:
        pins = locked_requirements(root / "requirements-build.txt")
        imports, extra_metadata = spec_dependencies(root)
        problems = []
        for name in sorted(set(pins) | extra_metadata):
            try:
                installed = metadata.version(name)
            except metadata.PackageNotFoundError:
                problems.append(f"{name}: missing distribution metadata")
                continue
            if name in pins and installed != pins[name]:
                problems.append(f"{name}: installed {installed}, locked version {pins[name]} required")
        imports.update(IMPORT_NAMES.get(name, name.replace("-", "_")) for name in pins)
        imports.add("PyInstaller.utils.hooks")
        for name in sorted(imports):
            try:
                importlib.import_module(name)
            except Exception as exc:
                problems.append(f"{name}: import failed ({type(exc).__name__}: {exc})")
        if problems:
            raise RuntimeError("\n".join(problems))
        result = subprocess.run([sys.executable, "-m", "pip", "check"],
                                capture_output=True, text=True, timeout=60, check=False)
        if result.returncode:
            raise RuntimeError(f"pip check failed: {result.stdout.strip()} {result.stderr.strip()}")
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        raise RuntimeError(
            f"Release dependency preflight failed for Python: {sys.executable}\n{exc}\n"
            f"Use the dedicated build interpreter: {build_python(root)}\n"
            "Create/repair that environment with python -m venv .venv-build and its "
            "Python -m pip install -r requirements-build.txt; rerun the builder with that Python."
        ) from exc
    print(f"Release dependencies OK: {sys.executable} ({len(pins)} locked distributions; imports and pip check passed)")


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    try:
        check_dependencies()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

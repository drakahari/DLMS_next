"""Prepare a validated, target-native Tesseract bundle for PyInstaller."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
from typing import Callable
import urllib.request

if __package__:
    from tools.pyinstaller_ocr import validate_tesseract_bundle
else:
    from pyinstaller_ocr import validate_tesseract_bundle


MAX_LICENSE_BYTES = 128 * 1024
OFFICIAL_LICENSES = {
    "tesseract": {
        "url": (
            "https://raw.githubusercontent.com/tesseract-ocr/tesseract/"
            "64eab6c457b2337dd690746a5fde5c222b40d5f8/LICENSE"
        ),
        "sha256": "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30",
    },
    "tessdata": {
        "url": (
            "https://raw.githubusercontent.com/tesseract-ocr/tessdata/"
            "4767ea922bcc460e70b87b1d303ebdfed0897da8/LICENSE"
        ),
        "sha256": "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30",
    },
    "leptonica": {
        "url": (
            "https://raw.githubusercontent.com/DanBloomberg/leptonica/"
            "63aef18d98432b8582a1565e241f7bd2ee9cc8d9/leptonica-license.txt"
        ),
        "sha256": "87829abb5bbb00b55a107365da89e9a33f86c4250169e5a1e5588505be7d5806",
    },
}


class BundlePreparationError(ValueError):
    """Raised when native OCR bundle sources cannot be prepared safely."""


@dataclass(frozen=True)
class BundleSources:
    platform_name: str
    executable: Path
    tessdata_dir: Path
    tesseract_license: Path
    tessdata_license: Path
    leptonica_license: Path


def detect_platform(system: str | None = None) -> str:
    """Map the native operating system to an explicit bundle target."""
    detected = str(system or platform.system()).casefold()
    mapping = {
        "linux": "linux",
        "darwin": "macos",
        "macos": "macos",
        "windows": "windows",
        "win32": "windows",
    }
    try:
        return mapping[detected]
    except KeyError as exc:
        raise BundlePreparationError(
            f"Unsupported OCR bundle platform: {system or platform.system()}"
        ) from exc


def default_license_cache(environ: dict[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    configured = env.get("DLMS_OCR_LICENSE_CACHE")
    if configured:
        return Path(configured).expanduser().resolve()
    if platform.system() == "Windows":
        base = Path(env.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(env.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return (base / "dlms" / "ocr-licenses").resolve()


def _rooted(filesystem_root: Path, absolute_path: str) -> Path:
    return filesystem_root / absolute_path.lstrip("/\\")


def _first_nonempty_file(label: str, candidates) -> Path:
    for candidate in candidates:
        if candidate is None:
            continue
        path = Path(candidate).expanduser().resolve()
        try:
            if path.is_file() and path.stat().st_size > 0:
                return path
        except OSError:
            continue
    raise BundlePreparationError(f"Could not locate {label}.")


def _brew_prefix(formula: str) -> Path | None:
    brew = shutil.which("brew")
    if not brew:
        return None
    completed = subprocess.run(
        [brew, "--prefix", formula],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        timeout=10,
        check=False,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        return None
    return Path(completed.stdout.strip()).expanduser().resolve()


def _read_bounded(path: Path) -> bytes:
    with path.open("rb") as handle:
        payload = handle.read(MAX_LICENSE_BYTES + 1)
    if not payload or len(payload) > MAX_LICENSE_BYTES:
        raise BundlePreparationError(f"License file is empty or too large: {path}")
    return payload


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _download_license(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "DLMS-OCR-Bundle-Prep"})
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = response.read(MAX_LICENSE_BYTES + 1)
    if not payload or len(payload) > MAX_LICENSE_BYTES:
        raise BundlePreparationError("Downloaded license is empty or too large.")
    return payload


def _cached_official_license(
    name: str,
    cache_root: Path,
    *,
    allow_download: bool,
    downloader: Callable[[str], bytes],
) -> Path:
    definition = OFFICIAL_LICENSES[name]
    destination = cache_root / f"{name}-{definition['sha256'][:12]}-LICENSE.txt"
    if destination.is_file():
        payload = _read_bounded(destination)
        if _sha256(payload) == definition["sha256"]:
            return destination.resolve()
        if not allow_download:
            raise BundlePreparationError(
                f"Cached {name} license checksum is invalid: {destination}"
            )
    if not allow_download:
        raise BundlePreparationError(
            f"Could not locate the {name} license. Supply its explicit path or "
            "rerun with --download-missing-licenses to fetch the pinned official text."
        )
    payload = downloader(definition["url"])
    if _sha256(payload) != definition["sha256"]:
        raise BundlePreparationError(
            f"Downloaded {name} license did not match its pinned SHA-256."
        )
    cache_root.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink()
        except OSError:
            pass
    return destination.resolve()


def _license_source(
    name: str,
    explicit: str | os.PathLike[str] | None,
    candidates,
    cache_root: Path,
    *,
    allow_download: bool,
    downloader: Callable[[str], bytes],
) -> Path:
    if explicit is not None:
        return _first_nonempty_file(f"{name} license", [explicit])
    try:
        return _first_nonempty_file(f"{name} license", candidates)
    except BundlePreparationError:
        return _cached_official_license(
            name,
            cache_root,
            allow_download=allow_download,
            downloader=downloader,
        )


def discover_bundle_sources(
    platform_name: str,
    *,
    executable: str | os.PathLike[str] | None = None,
    tessdata_dir: str | os.PathLike[str] | None = None,
    tesseract_license: str | os.PathLike[str] | None = None,
    tessdata_license: str | os.PathLike[str] | None = None,
    leptonica_license: str | os.PathLike[str] | None = None,
    filesystem_root: str | os.PathLike[str] = "/",
    which: Callable[[str], str | None] = shutil.which,
    brew_prefix: Callable[[str], Path | None] = _brew_prefix,
    cache_root: str | os.PathLike[str] | None = None,
    allow_download: bool = False,
    downloader: Callable[[str], bytes] = _download_license,
) -> BundleSources:
    """Discover native sources through explicit, testable platform layouts."""
    platform_name = detect_platform(platform_name)
    root = Path(filesystem_root)
    executable_name = "tesseract.exe" if platform_name == "windows" else "tesseract"
    discovered_executable = executable or which(executable_name)
    if discovered_executable is None and platform_name == "windows":
        discovered_executable = which("tesseract")

    tesseract_prefix = None
    leptonica_prefix = None
    if platform_name == "macos":
        tesseract_prefix = brew_prefix("tesseract")
        leptonica_prefix = brew_prefix("leptonica")
        if discovered_executable is None and tesseract_prefix is not None:
            discovered_executable = tesseract_prefix / "bin" / "tesseract"

    executable_path = _first_nonempty_file(
        "the target-native Tesseract executable", [discovered_executable]
    )
    install_prefix = executable_path.parent.parent

    if platform_name == "linux":
        tessdata_candidates = (
            _rooted(root, "/usr/share/tesseract-ocr/5/tessdata"),
            _rooted(root, "/usr/share/tesseract/tessdata"),
            _rooted(root, "/usr/share/tessdata"),
        )
        tesseract_license_candidates = (
            _rooted(root, "/usr/share/doc/tesseract-ocr/copyright"),
            _rooted(root, "/usr/share/licenses/tesseract/LICENSE"),
        )
        tessdata_license_candidates = (
            _rooted(root, "/usr/share/doc/tesseract-ocr-eng/copyright"),
        )
        leptonica_license_candidates = (
            _rooted(root, "/usr/share/doc/liblept5/copyright"),
            _rooted(root, "/usr/share/doc/libleptonica6/copyright"),
            _rooted(root, "/usr/share/licenses/leptonica/leptonica-license.txt"),
        )
    elif platform_name == "macos":
        tesseract_prefix = tesseract_prefix or install_prefix
        tessdata_candidates = (tesseract_prefix / "share" / "tessdata",)
        tesseract_license_candidates = (tesseract_prefix / "LICENSE",)
        tessdata_license_candidates = ()
        leptonica_license_candidates = (
            leptonica_prefix / "LICENSE" if leptonica_prefix else None,
            leptonica_prefix / "leptonica-license.txt" if leptonica_prefix else None,
        )
    else:
        tessdata_candidates = (
            executable_path.parent / "tessdata",
            install_prefix / "tessdata",
            install_prefix / "share" / "tessdata",
        )
        common_license_candidates = (
            install_prefix / "LICENSE",
            install_prefix / "LICENSE.txt",
        )
        tesseract_license_candidates = common_license_candidates
        tessdata_license_candidates = (
            install_prefix / "tessdata" / "LICENSE",
            install_prefix / "tessdata" / "LICENSE.txt",
        )
        leptonica_license_candidates = (
            install_prefix / "leptonica-license.txt",
            install_prefix / "licenses" / "leptonica-LICENSE.txt",
        )

    selected_tessdata = Path(tessdata_dir).expanduser().resolve() if tessdata_dir else None
    if selected_tessdata is None:
        for candidate in tessdata_candidates:
            if (
                candidate.is_dir()
                and (candidate / "eng.traineddata").is_file()
                and (candidate / "configs" / "tsv").is_file()
            ):
                selected_tessdata = candidate.resolve()
                break
    if selected_tessdata is None:
        raise BundlePreparationError(
            "Could not locate tessdata containing both eng.traineddata and configs/tsv. "
            "Supply --tessdata-dir."
        )
    for relative in ("eng.traineddata", "configs/tsv"):
        source = selected_tessdata / relative
        if not source.is_file() or source.stat().st_size == 0:
            raise BundlePreparationError(f"Missing or empty tessdata source: {source}")

    selected_cache = Path(cache_root or default_license_cache()).expanduser().resolve()
    selected_tesseract_license = _license_source(
        "tesseract",
        tesseract_license,
        tesseract_license_candidates,
        selected_cache,
        allow_download=allow_download,
        downloader=downloader,
    )
    try:
        selected_tessdata_license = _license_source(
            "tessdata",
            tessdata_license,
            tessdata_license_candidates,
            selected_cache,
            allow_download=False,
            downloader=downloader,
        )
    except BundlePreparationError:
        if tessdata_license is not None:
            raise
        tesseract_payload = _read_bounded(selected_tesseract_license)
        if _sha256(tesseract_payload) == OFFICIAL_LICENSES["tessdata"]["sha256"]:
            selected_tessdata_license = selected_tesseract_license
        else:
            selected_tessdata_license = _cached_official_license(
                "tessdata",
                selected_cache,
                allow_download=allow_download,
                downloader=downloader,
            )
    selected_leptonica_license = _license_source(
        "leptonica",
        leptonica_license,
        leptonica_license_candidates,
        selected_cache,
        allow_download=allow_download,
        downloader=downloader,
    )
    return BundleSources(
        platform_name=platform_name,
        executable=executable_path,
        tessdata_dir=selected_tessdata,
        tesseract_license=selected_tesseract_license,
        tessdata_license=selected_tessdata_license,
        leptonica_license=selected_leptonica_license,
    )


def ensure_local_only_output(
    output: Path,
    repository_root: Path,
    *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> None:
    """Reject a generated output inside Git unless its path is ignored."""
    output = output.resolve()
    repository_root = repository_root.resolve()
    if not (repository_root / ".git").exists():
        return
    try:
        relative = output.relative_to(repository_root)
    except ValueError:
        return
    completed = runner(
        [
            "git",
            "check-ignore",
            "--quiet",
            "--",
            (relative / ".dlms-ocr-bundle-check").as_posix(),
        ],
        cwd=repository_root,
        check=False,
    )
    if completed.returncode != 0:
        raise BundlePreparationError(
            "OCR bundle output inside the repository must be ignored by Git. "
            "Use .ocr-bundle, add a local .git/info/exclude rule, or choose an outside path."
        )


def _native_libraries(executable: Path, platform_name: str):
    for path in sorted(executable.parent.iterdir()):
        if not path.is_file() or path == executable:
            continue
        folded = path.name.casefold()
        if (
            platform_name == "windows" and path.suffix.casefold() == ".dll"
            or platform_name == "macos" and path.suffix.casefold() == ".dylib"
            or platform_name == "linux" and ".so" in folded
        ):
            yield path


def prepare_bundle(
    sources: BundleSources,
    output: str | os.PathLike[str],
    *,
    repository_root: str | os.PathLike[str] | None = None,
) -> Path:
    """Copy sources atomically into a new validated local bundle."""
    output = Path(output).expanduser().resolve()
    if output.exists():
        raise BundlePreparationError(
            f"Output already exists: {output}. Remove it or use --validate-only."
        )
    if repository_root is not None:
        ensure_local_only_output(output, Path(repository_root))
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output.name}-preparing-", dir=output.parent)
    )
    try:
        bin_dir = temporary / "bin"
        tessdata_dir = temporary / "tessdata"
        licenses_dir = temporary / "licenses"
        (tessdata_dir / "configs").mkdir(parents=True)
        bin_dir.mkdir()
        licenses_dir.mkdir()
        executable_name = (
            "tesseract.exe" if sources.platform_name == "windows" else "tesseract"
        )
        copied_executable = bin_dir / executable_name
        shutil.copy2(sources.executable, copied_executable)
        for library in _native_libraries(sources.executable, sources.platform_name):
            shutil.copy2(library, bin_dir / library.name)
        shutil.copy2(sources.tessdata_dir / "eng.traineddata", tessdata_dir)
        shutil.copy2(sources.tessdata_dir / "configs" / "tsv", tessdata_dir / "configs")
        for source, destination in (
            (sources.tesseract_license, "tesseract-LICENSE.txt"),
            (sources.tessdata_license, "tessdata-LICENSE.txt"),
            (sources.leptonica_license, "leptonica-LICENSE.txt"),
        ):
            shutil.copy2(source, licenses_dir / destination)
        validate_tesseract_bundle(temporary, platform_name=sources.platform_name)
        temporary.rename(output)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return output


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare or validate a target-native DLMS Tesseract bundle."
    )
    parser.add_argument("--output", default=".ocr-bundle")
    parser.add_argument("--tesseract-executable")
    parser.add_argument("--tessdata-dir")
    parser.add_argument("--tesseract-license")
    parser.add_argument("--tessdata-license")
    parser.add_argument("--leptonica-license")
    parser.add_argument("--license-cache")
    parser.add_argument("--download-missing-licenses", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    platform_name = detect_platform()
    output = Path(args.output).expanduser().resolve()
    try:
        if args.validate_only:
            validate_tesseract_bundle(output, platform_name=platform_name)
            print(f"Validated {platform_name} OCR bundle: {output}")
            return 0
        sources = discover_bundle_sources(
            platform_name,
            executable=args.tesseract_executable,
            tessdata_dir=args.tessdata_dir,
            tesseract_license=args.tesseract_license,
            tessdata_license=args.tessdata_license,
            leptonica_license=args.leptonica_license,
            cache_root=args.license_cache,
            allow_download=args.download_missing_licenses,
        )
        prepared = prepare_bundle(
            sources,
            output,
            repository_root=Path(__file__).resolve().parents[1],
        )
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"ERROR: {exc}") from exc
    print(f"Prepared validated {platform_name} OCR bundle: {prepared}")
    if platform_name == "windows":
        print(f'$env:DLMS_TESSERACT_BUNDLE_ROOT = "{prepared}"')
    else:
        print(f'export DLMS_TESSERACT_BUNDLE_ROOT="{prepared}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

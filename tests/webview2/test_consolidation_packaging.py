"""Canonical Windows freeze inputs, without invoking a compiler or freezer."""
import ast
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPECS = (
    "package_windows/DLMS-Desktop.spec",
    "package_windows_webview2/DLMS-Desktop-WebView2.spec",
)


@pytest.mark.parametrize("relative", SPECS)
def test_windows_build_spec_is_present_and_not_ignored(relative):
    spec = ROOT / relative
    assert spec.is_file(), "A fresh checkout must contain the Windows freeze specification"
    # --no-index also checks tracked files: tracking once must not conceal a
    # broad ignore rule that would silently drop a future relocated spec.
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", relative],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr


@pytest.mark.parametrize("relative", SPECS)
def test_windows_build_spec_uses_the_single_canonical_application(relative):
    text = (ROOT / relative).read_text(encoding="utf-8")
    tree = ast.parse(text, filename=relative)
    sources = [node.value for node in tree.body if isinstance(node, ast.Assign)
               and any(isinstance(target, ast.Name) and target.id == "source"
                       for target in node.targets)]
    assert len(sources) == 1
    assert isinstance(sources[0], ast.Name) and sources[0].id == "root"
    # These expressions supply actual freezer inputs. Require their canonical
    # counterparts, preserving the original OCR fixture leaves and asset names.
    for value in (
        "tests/fixtures/ocr/pdf/fully-scanned.pdf",
        "tests/fixtures/ocr/dlms-question.png",
        "static", "templates", "dlms/theme_sources", "init.sql",
    ):
        assert (ROOT / value).exists(), value
        assert value in text, value
    assert (ROOT / "app.py").is_file()
    assert not (ROOT / "source").exists(), "No second active application tree"
    assert 'collect_submodules("dlms")' in text
    assert "console=False" in text and "upx=False" in text


def test_both_windows_builders_reference_the_restored_specs():
    for directory, relative in zip(("package_windows", "package_windows_webview2"), SPECS):
        assert relative in (ROOT / directory / "build.py").read_text(encoding="utf-8")


@pytest.mark.parametrize("present,visible,listed,accepted", [
    (False, False, False, True),
    (True, False, False, True),
    (True, True, False, False),
    (True, False, True, False),
])
def test_normal_menu_probe_accepts_absence_but_rejects_exposed_debug_actions(
    present, visible, listed, accepted,
):
    from tests.webview2.gui_native_followup import assert_no_mix_diagnostic
    action = SimpleNamespace(isVisible=lambda: visible) if present else None
    window = SimpleNamespace(mix_diagnostic_action=action,
                             mode_menu=SimpleNamespace(actions=lambda: [action] if listed else []))
    if accepted:
        assert_no_mix_diagnostic(window)
    else:
        with pytest.raises(AssertionError):
            assert_no_mix_diagnostic(window)

import importlib.util
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "capture_user_manual_screenshots.py"
IMAGE_ROOT = ROOT / "docs" / "user-manual" / "images"


def _load_capture_tool():
    spec = importlib.util.spec_from_file_location("manual_screenshot_capture", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _png_dimensions(path):
    header = path.read_bytes()[:24]
    assert header.startswith(b"\x89PNG\r\n\x1a\n")
    assert header[12:16] == b"IHDR"
    return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")


def test_manual_capture_contract_covers_all_planned_ids():
    tool = _load_capture_tool()
    ids = [item.screenshot_id for item in tool.CAPTURES]
    filenames = [item.filename for item in tool.CAPTURES]

    assert ids == [f"UM-{number:02d}" for number in range(1, 28)]
    assert len(filenames) == len(set(filenames))
    assert all(name.startswith(f"{screenshot_id}-") and name.endswith(".png") for screenshot_id, name in zip(ids, filenames))
    assert {item.classification for item in tool.CAPTURES} == {
        "Fully automatable",
        "Partially automatable",
    }
    assert {item.screenshot_id for item in tool.CAPTURES if item.classification == "Partially automatable"} == {
        "UM-06", "UM-14", "UM-20", "UM-22", "UM-24", "UM-27",
    }


def test_manual_capture_assets_and_sidecar_match_contract():
    tool = _load_capture_tool()
    metadata = json.loads((IMAGE_ROOT / "capture-metadata.json").read_text(encoding="utf-8"))
    records = metadata["captures"]

    # Captures retain their original version when only release text changes.
    # Their provenance must agree with the capture manifest, not today's app.
    manifest = (ROOT / "docs/user-manual/SCREENSHOT_MANIFEST.md").read_text(encoding="utf-8")
    captured_version = re.search(r"\*\*Application:\*\* DLMS (\d+\.\d+\.\d+)", manifest)
    assert captured_version is not None
    assert metadata["version"] == captured_version.group(1)
    assert metadata["theme"] == tool.THEME == "light"
    assert metadata["viewport"] == {"width": 1440, "height": 1000, "device_scale": 1}
    assert metadata["fixture_version"] == tool.FIXTURE_VERSION
    assert [record["screenshot_id"] for record in records] == [item.screenshot_id for item in tool.CAPTURES]

    for item, record in zip(tool.CAPTURES, records):
        path = IMAGE_ROOT / item.filename
        assert path.is_file()
        assert _png_dimensions(path) == (tool.WIDTH, tool.HEIGHT)
        assert record["filename"] == item.filename
        assert record["status"] == "Captured"
        assert record["dimensions"] == "1440×1000"
        assert record["classification"] == item.classification


def test_future_captures_read_the_current_application_version():
    tool = _load_capture_tool()
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    version = re.search(r'^APP_VERSION = "([^"]+)"$', source, re.MULTILINE)
    assert version is not None
    assert tool._application_version() == version.group(1)

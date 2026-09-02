"""DLMS-083 regressions for the retired legacy Settings upload path."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from tests._isolation import ensure_test_data_isolation


ensure_test_data_isolation()
import app as dlms
from tests.csrf_test_utils import csrf_token


def _png_bytes():
    output = io.BytesIO()
    Image.new("RGB", (12, 9), (30, 90, 160)).save(output, format="PNG")
    return output.getvalue()


class LegacySettingsRetirementTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dlms-legacy-settings-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.client = dlms.app.test_client()
        self.headers = {"X-CSRFToken": csrf_token(self.client)}

    def test_legacy_settings_bookmark_redirects_to_appearance(self):
        response = self.client.get("/settings/legacy")

        self.assertEqual(302, response.status_code)
        self.assertTrue(response.headers["Location"].endswith("/settings/appearance"))

    def test_legacy_form_post_does_not_write_upload_or_configuration(self):
        background = self.root / "backgrounds"
        portal = self.root / "config" / "portal.json"
        portal.parent.mkdir(parents=True)
        original = {"title": "Existing title", "background_image": "existing.png", "theme": "dark"}
        portal.write_text(json.dumps(original), encoding="utf-8")

        with mock.patch.object(dlms, "BACKGROUND_FOLDER", str(background)), mock.patch.object(
            dlms, "PORTAL_CONFIG", str(portal)
        ):
            response = self.client.post(
                "/save_settings",
                data={
                    "portal_title": "Legacy replacement",
                    "background_image": (io.BytesIO(_png_bytes()), "legacy.png", "image/png"),
                },
                headers=self.headers,
                content_type="multipart/form-data",
            )

        self.assertEqual(303, response.status_code)
        self.assertTrue(response.headers["Location"].endswith("/settings/appearance"))
        self.assertFalse((background / "legacy.png").exists())
        self.assertEqual(original, json.loads(portal.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()

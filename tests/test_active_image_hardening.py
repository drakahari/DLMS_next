import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from tests._isolation import ensure_test_data_isolation
ensure_test_data_isolation()
import app as dlms
from tests.csrf_test_utils import csrf_token


def image_bytes(image_format, color=(24, 110, 190)):
    output = io.BytesIO()
    Image.new("RGB", (12, 9), color).save(output, format=image_format)
    return output.getvalue()


class ActiveImageHardeningTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dlms-active-image-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def _post_background(self, filename, content, content_type="application/octet-stream"):
        client = dlms.app.test_client()
        background = self.root / "backgrounds"
        portal = self.root / "portal.json"
        with mock.patch.object(dlms, "BACKGROUND_FOLDER", str(background)), mock.patch.object(
            dlms, "PORTAL_CONFIG", str(portal)
        ), mock.patch.object(dlms, "load_portal_config", return_value={"title": "DLMS", "theme": "dark"}):
            response = client.post(
                "/settings/appearance/save",
                data={
                    "csrf_token": csrf_token(client), "portal_title": "DLMS", "theme": "dark",
                    "background_image": (io.BytesIO(content), filename, content_type),
                },
                content_type="multipart/form-data",
            )
        return response, background, portal

    def test_valid_png_and_jpeg_backgrounds_are_accepted_and_reencoded(self):
        for filename, image_format in (("safe.png", "PNG"), ("safe.jpg", "JPEG")):
            with self.subTest(filename=filename):
                original = image_bytes(image_format)
                response, background, portal = self._post_background(filename, original)
                self.assertEqual(response.status_code, 302)
                stored = background / filename
                self.assertTrue(stored.is_file())
                frames, metadata = dlms._decode_raster_image(str(stored))
                self.assertEqual(metadata["size"], (12, 9))
                self.assertEqual(metadata["format"], image_format)
                self.assertTrue(frames)
                self.assertEqual(json.loads(portal.read_text())["background_image"], filename)

    def test_html_or_script_bytes_renamed_as_png_are_rejected_regardless_of_content_type(self):
        attacks = (
            (b"<!doctype html><script>alert(1)</script>", "image/png"),
            (b"console.log('not an image')", "image/png"),
        )
        for payload, content_type in attacks:
            with self.subTest(payload=payload[:12]):
                response, background, portal = self._post_background("attack.png", payload, content_type)
                self.assertEqual(response.status_code, 400)
                self.assertFalse((background / "attack.png").exists())
                self.assertFalse(portal.exists())

    def test_valid_raster_with_trailing_active_bytes_is_normalized(self):
        marker = b"<script>alert(1)</script>"
        response, background, _portal = self._post_background("polyglot.png", image_bytes("PNG") + marker, "image/png")
        self.assertEqual(response.status_code, 302)
        stored = (background / "polyglot.png").read_bytes()
        self.assertNotIn(marker, stored)
        self.assertTrue(stored.startswith(b"\x89PNG\r\n\x1a\n"))

    def _make_image_pack(self, filename, payload):
        root = self.root / "pack"
        (root / "data").mkdir(parents=True)
        (root / "images").mkdir()
        (root / "images" / filename).write_bytes(payload)
        manifest = {
            "schema_version": 1, "id": "secure_images", "name": "Secure Images",
            "datasets": [], "image_datasets": [],
            "quiz_datasets": [{"id": "quiz", "title": "Quiz", "type": "quiz", "path": "data/quiz.json"}],
        }
        dataset = {
            "schema_version": 1, "id": "quiz", "source": {"organization": "Test"},
            "images": [{"id": "image", "file": f"images/{filename}", "license": "CC0", "hotspots": []}],
            "questions": [{
                "type": "choice", "question": "Which?", "image_id": "image",
                "choices": [{"text": "One", "is_correct": True}, {"text": "Two", "is_correct": False}],
            }],
        }
        (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (root / "data" / "quiz.json").write_text(json.dumps(dataset), encoding="utf-8")
        return root

    def test_content_pack_rasters_are_validated_and_normalized(self):
        marker = b"<script>alert(1)</script>"
        root = self._make_image_pack("diagram.png", image_bytes("PNG") + marker)
        report = dlms._validate_staged_content_pack(str(root), normalize_images=True)
        self.assertTrue(report["valid"], report["errors"])
        self.assertNotIn(marker, (root / "images" / "diagram.png").read_bytes())

    def test_content_pack_rejects_fake_raster_and_svg(self):
        fake = self._make_image_pack("diagram.png", b"<html><script>alert(1)</script></html>")
        report = dlms._validate_staged_content_pack(str(fake))
        self.assertFalse(report["valid"])
        self.assertTrue(any("unsafe or invalid image" in error for error in report["errors"]))

        shutil_root = self.root / "svg-pack"
        fake.rename(shutil_root)
        dataset_path = shutil_root / "data" / "quiz.json"
        dataset = json.loads(dataset_path.read_text())
        dataset["images"][0]["file"] = "images/diagram.svg"
        dataset_path.write_text(json.dumps(dataset), encoding="utf-8")
        (shutil_root / "images" / "diagram.png").unlink()
        (shutil_root / "images" / "diagram.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"><script>alert(1)</script></svg>',
            encoding="utf-8",
        )
        svg_report = dlms._validate_staged_content_pack(str(shutil_root))
        self.assertFalse(svg_report["valid"])
        self.assertTrue(any("SVG" in error or "active formats" in error for error in svg_report["errors"]))

    def test_quiz_asset_serving_rejects_active_content_and_serves_png_with_nosniff(self):
        quiz_assets = self.root / "quiz_assets"
        bucket = quiz_assets / "bucket" / "images"
        bucket.mkdir(parents=True)
        (bucket / "bad.svg").write_text("<svg onload='alert(1)'></svg>", encoding="utf-8")
        (bucket / "bad.png").write_text("<script>alert(1)</script>", encoding="utf-8")
        (bucket / "safe.png").write_bytes(image_bytes("PNG"))
        with mock.patch.object(dlms, "QUIZ_ASSET_FOLDER", str(quiz_assets)):
            client = dlms.app.test_client()
            self.assertEqual(client.get("/quiz-assets/bucket/images/bad.svg").status_code, 415)
            self.assertEqual(client.get("/quiz-assets/bucket/images/bad.png").status_code, 415)
            response = client.get("/quiz-assets/bucket/images/safe.png")
        try:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, "image/png")
            self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")
        finally:
            response.close()

    def test_user_background_and_static_routes_do_not_serve_active_files(self):
        static_root = self.root / "static"
        (static_root / "bg").mkdir(parents=True)
        (static_root / "logos").mkdir()
        (static_root / "bg" / "safe.jpg").write_bytes(image_bytes("JPEG"))
        (static_root / "bg" / "attack.png").write_text("<html><script>alert(1)</script>", encoding="utf-8")
        (static_root / "logos" / "attack.svg").write_text("<svg onload='alert(1)'></svg>", encoding="utf-8")
        (static_root / "page.html").write_text("<script>alert(1)</script>", encoding="utf-8")
        with mock.patch.object(dlms, "APP_DATA_DIR", str(self.root)):
            client = dlms.app.test_client()
            safe = client.get("/user-bg/safe.jpg")
            try:
                self.assertEqual(safe.status_code, 200)
                self.assertEqual(safe.mimetype, "image/jpeg")
                self.assertEqual(safe.headers.get("X-Content-Type-Options"), "nosniff")
            finally:
                safe.close()
            self.assertEqual(client.get("/user-bg/attack.png").status_code, 415)
            self.assertEqual(client.get("/user-static/logos/attack.svg").status_code, 415)
            self.assertEqual(client.get("/user-static/page.html").status_code, 415)

    def test_image_builder_accepts_valid_png_and_rejects_fake_png(self):
        client = dlms.app.test_client()
        draft_root = self.root / "drafts"
        draft_root.mkdir()
        with mock.patch.object(dlms, "IMAGE_BUILDER_DRAFT_FOLDER", str(draft_root)):
            accepted = client.post(
                "/study-packs/image-builder",
                data={"csrf_token": csrf_token(client), "study_images": (io.BytesIO(image_bytes("PNG")), "diagram.png")},
                content_type="multipart/form-data",
            )
            self.assertEqual(accepted.status_code, 200)
            self.assertIn("diagram.png", accepted.get_data(as_text=True))
            rejected = client.post(
                "/study-packs/image-builder",
                data={"csrf_token": csrf_token(client), "study_images": (io.BytesIO(b"<html>bad</html>"), "fake.png", "image/png")},
                content_type="multipart/form-data",
            )
            self.assertEqual(rejected.status_code, 302)
            self.assertEqual(len(list(draft_root.glob("*/fake.png"))), 0)

    def test_image_builder_permission_panel_has_scoped_wrapping_layout(self):
        self.assertIn('class="image-builder-rights"', dlms.IMAGE_QUIZ_BUILDER_TEMPLATE)
        self.assertIn('name="rights_ok" required', dlms.IMAGE_QUIZ_BUILDER_TEMPLATE)
        self.assertIn("not cleared for redistribution", dlms.IMAGE_QUIZ_BUILDER_TEMPLATE)

        styles = Path(dlms.STATIC_ROOT, "style.css").read_text(encoding="utf-8")
        self.assertIn(".image-builder-rights input[type=\"checkbox\"]", styles)
        self.assertIn("grid-template-columns:20px minmax(0,1fr)", styles)
        self.assertIn(".image-builder-rights span { min-width:0;overflow-wrap:anywhere; }", styles)
        self.assertIn(".image-builder-submit-row { margin-top:18px;justify-content:flex-start;flex-wrap:wrap; }", styles)


if __name__ == "__main__":
    unittest.main()

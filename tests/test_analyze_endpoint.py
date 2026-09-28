"""POST /analyze returns the evidence pack as a zip; auth and length limits hold."""
import io
import os
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("API_KEY", "test-key")

import clips  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

HEADERS = {"X-API-Key": os.environ["API_KEY"]}
BODY = {"video_url": "https://www.instagram.com/reel/TEST123/"}


@unittest.skipUnless(clips.HAVE_FFMPEG, "needs ffmpeg")
class AnalyzeEndpointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.video = clips.hard_cut(cls.tmp.name)
        cls.client = TestClient(main.app)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def fake_fetch(self, url, workdir):
        return self.video

    def test_returns_the_pack_as_a_zip(self):
        with mock.patch.object(main, "fetch_video_with_audio", self.fake_fetch):
            r = self.client.post("/analyze", json=BODY, headers=HEADERS)
        self.assertEqual(r.status_code, 200, r.text[:300])
        self.assertEqual(r.headers["content-type"], "application/zip")
        names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
        for expected in ("timeline.json", "summary.md", "motion.png", "sheets/sheet_01.jpg"):
            self.assertIn(expected, names)
        self.assertEqual(r.headers["x-cut-count"], "1")

    def test_needs_the_api_key(self):
        r = self.client.post("/analyze", json=BODY)
        self.assertEqual(r.status_code, 401)

    def test_refuses_long_videos(self):
        with mock.patch.object(main, "fetch_video_with_audio", self.fake_fetch), \
                mock.patch.dict(os.environ, {"ANALYZE_MAX_SECONDS": "1"}):
            r = self.client.post("/analyze", json=BODY, headers=HEADERS)
        self.assertEqual(r.status_code, 422)
        self.assertIn("longer than", r.json()["detail"])


if __name__ == "__main__":
    unittest.main()

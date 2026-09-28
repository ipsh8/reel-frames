"""/transcript: info.json always; people-written English subtitles beat YouTube's auto ones."""
import base64
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("API_KEY", "test-key")

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
import youtube_service as yt  # noqa: E402
from test_youtube_cache import INFO, FakeYDL  # noqa: E402

URL = "https://youtu.be/reFzEtCG_m8"
HEADERS = {"X-API-Key": os.environ["API_KEY"]}


class PickTrack(unittest.TestCase):
    def test_manual_english_wins(self):
        self.assertEqual(yt.pick_subtitle_track({"subtitle_langs": ["en-GB"], "auto_caption_langs": ["en-orig"]}),
                         ("en-GB", False))

    def test_auto_original_before_auto_translated(self):
        self.assertEqual(yt.pick_subtitle_track({"subtitle_langs": [], "auto_caption_langs": ["en", "en-orig"]}),
                         ("en-orig", True))

    def test_nothing_english(self):
        self.assertIsNone(yt.pick_subtitle_track({"subtitle_langs": [], "auto_caption_langs": []}))


class Endpoint(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [mock.patch.object(yt, "CACHE_DIR", self.tmp.name),
                        mock.patch.object(yt.yt_dlp, "YoutubeDL", FakeYDL)]
        for p in self.patches:
            p.start()
        FakeYDL.calls, FakeYDL.fail_with = [], None
        self.client = TestClient(main.app)

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def post(self, **body):
        return self.client.post("/transcript", json={"video_url": URL, **body}, headers=HEADERS)

    def test_zip_has_info_and_manual_transcript(self):
        r = self.post()
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.headers["X-Transcript"], "manual")
        z = zipfile.ZipFile(io.BytesIO(r.content))
        self.assertEqual(sorted(z.namelist()), ["info.json", "transcript.vtt"])
        self.assertEqual(json.loads(z.read("info.json"))["title"], "A film")
        subs_call = FakeYDL.calls[-1][1]
        self.assertEqual((subs_call["subtitleslangs"], subs_call["writesubtitles"]), (["en"], True))

    def test_json_output_for_n8n(self):
        r = self.post(output="json")
        body = r.json()
        self.assertEqual(body["transcript"], "manual")
        names = {f["filename"]: base64.b64decode(f["content_base64"]) for f in body["files"]}
        self.assertTrue(names["transcript.vtt"].startswith(b"WEBVTT"))

    def test_no_subtitles_still_returns_info(self):
        with mock.patch.dict(INFO, {"subtitles": {}, "automatic_captions": {}}):
            r = self.post(output="json")
        self.assertEqual(r.json()["transcript"], "none")
        self.assertEqual([f["filename"] for f in r.json()["files"]], ["info.json"])

    def test_blocked_subtitles_say_why(self):
        yt.cached_video(URL)
        FakeYDL.fail_with = "HTTP Error 429: Too Many Requests"
        r = self.post(output="json")
        self.assertEqual(r.json()["transcript"], "blocked")
        self.assertIn("429", r.json()["note"])

    def test_second_call_does_not_refetch(self):
        self.post()
        before = len(FakeYDL.calls)
        self.post()
        self.assertEqual(len(FakeYDL.calls), before)

    def test_only_youtube(self):
        r = self.client.post("/transcript", json={"video_url": "https://www.instagram.com/reel/X/"},
                             headers=HEADERS)
        self.assertEqual(r.status_code, 422)


if __name__ == "__main__":
    unittest.main()

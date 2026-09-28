"""cached_video: one YouTube download per video, reused, pruned, proxied, cookied."""
import base64
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("API_KEY", "test-key")

import main  # noqa: E402
import youtube_service as yt  # noqa: E402

URL = "https://m.youtube.com/watch?v=reFzEtCG_m8&list=PL1&t=30s"
INFO = {"id": "reFzEtCG_m8", "title": "A film", "channel": "Chan", "duration": 1685,
        "webpage_url": "https://www.youtube.com/watch?v=reFzEtCG_m8", "description": "d",
        "chapters": [{"start_time": 0, "end_time": 98, "title": "Welcome"}],
        "subtitles": {"en": [{}], "fr": [{}]}, "automatic_captions": {"en-orig": [{}], "de": [{}]}}


class FakeYDL:
    """Stands in for yt_dlp.YoutubeDL: writes the file yt-dlp would and records how it was called."""
    calls: list = []
    fail_with = None

    def __init__(self, opts):
        self.opts = dict(opts)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, url, download):
        FakeYDL.calls.append((url, self.opts))
        if FakeYDL.fail_with:
            raise yt.yt_dlp.utils.DownloadError(FakeYDL.fail_with)
        out = self.opts["outtmpl"]
        if self.opts.get("skip_download"):
            lang = self.opts["subtitleslangs"][0]
            with open(out.replace("%(ext)s", f"{lang}.vtt"), "w") as f:
                f.write("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhello\n")
        else:
            with open(out.replace("%(ext)s", "mp4"), "wb") as f:
                f.write(b"fake-mp4")
        return INFO


class CacheTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [mock.patch.object(yt, "CACHE_DIR", self.tmp.name),
                        mock.patch.object(yt.yt_dlp, "YoutubeDL", FakeYDL),
                        mock.patch.dict(os.environ, {}, clear=False)]
        for p in self.patches:
            p.start()
        for k in ("YTDLP_PROXY", "YT_COOKIES_FILE", "YT_COOKIES_B64", "YT_CACHE_SECONDS"):
            os.environ.pop(k, None)
        FakeYDL.calls, FakeYDL.fail_with = [], None

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def test_second_call_reuses_the_download(self):
        first = yt.cached_video(URL)
        second = yt.cached_video("https://youtu.be/reFzEtCG_m8")
        self.assertEqual(first, second)
        self.assertEqual(len(FakeYDL.calls), 1)
        with open(first, "rb") as f:
            self.assertEqual(f.read(), b"fake-mp4")

    def test_only_one_video_is_ever_requested(self):
        yt.cached_video(URL)
        url, opts = FakeYDL.calls[0]
        self.assertEqual(url, "https://www.youtube.com/watch?v=reFzEtCG_m8")
        self.assertTrue(opts["noplaylist"])
        self.assertIn("height<=720", opts["format"])

    def test_info_json_keeps_chapters_and_english_tracks(self):
        folder = os.path.dirname(yt.cached_video(URL))
        with open(os.path.join(folder, "info.json")) as f:
            info = json.load(f)
        self.assertEqual(info["chapters"], [{"start": 0, "end": 98, "title": "Welcome"}])
        self.assertEqual(info["subtitle_langs"], ["en"])
        self.assertEqual(info["auto_caption_langs"], ["en-orig"])

    def test_old_entries_are_pruned_fresh_ones_kept(self):
        os.environ["YT_CACHE_SECONDS"] = "60"
        old, fresh = (os.path.join(self.tmp.name, n) for n in ("old", "fresh"))
        os.makedirs(old)
        os.makedirs(fresh)
        past = time.time() - 120
        os.utime(old, (past, past))
        yt.prune_cache()
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(fresh))

    def test_proxy_is_used_for_youtube(self):
        os.environ["YTDLP_PROXY"] = "http://u:p@proxy.example.net:8000"
        yt.cached_video(URL)
        self.assertEqual(FakeYDL.calls[0][1]["proxy"], "http://u:p@proxy.example.net:8000")

    def test_cookies_from_base64_become_a_cookies_file(self):
        text = "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tabc\n"
        os.environ["YT_COOKIES_B64"] = base64.b64encode(text.encode()).decode()
        yt.cached_video(URL)
        with open(FakeYDL.calls[0][1]["cookiefile"]) as f:
            self.assertEqual(f.read(), text)

    def test_bot_check_is_a_422_that_says_so_and_can_be_retried(self):
        FakeYDL.fail_with = "ERROR: [youtube] reFzEtCG_m8: Sign in to confirm you're not a bot"
        with self.assertRaises(main.HTTPException) as caught:
            yt.cached_video(URL)
        self.assertEqual(caught.exception.status_code, 422)
        self.assertIn("not a bot", caught.exception.detail)
        FakeYDL.fail_with = None
        self.assertTrue(os.path.exists(yt.cached_video(URL)))

    def test_download_endpoint_serves_the_cached_file_and_keeps_it(self):
        from fastapi.testclient import TestClient
        r = TestClient(main.app).post("/download", json={"video_url": URL},
                                      headers={"X-API-Key": os.environ["API_KEY"]})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.content, b"fake-mp4")
        self.assertTrue(os.path.exists(yt.cached_video(URL)))
        self.assertEqual(len(FakeYDL.calls), 1)


if __name__ == "__main__":
    unittest.main()

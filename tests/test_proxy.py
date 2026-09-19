"""YTDLP_PROXY: /audio and /download reach Instagram through a proxy; /frames doesn't.

Instagram sends this server muted copies of some reels (`has_audio: false`, no
audio stream offered) whether it is logged in or not, and whichever region it
runs in. The same request from a home connection gets the sound. These tests
never touch the internet; the proxy below is a placeholder.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("API_KEY", "test-key")

import main  # noqa: E402

PROXY = "http://someuser:s3cret-pass@proxy.example.net:8000"


class FakeYDL:
    """Records the options yt-dlp was given, and can fail like it does."""
    seen: dict = {}
    fail_with = None

    def __init__(self, opts):
        FakeYDL.seen = dict(opts)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, url, download):
        if FakeYDL.fail_with:
            raise main.yt_dlp.utils.DownloadError(FakeYDL.fail_with)
        open(os.path.join(os.path.dirname(FakeYDL.seen["outtmpl"]), "media.m4a"), "wb").close()
        return {"format_id": "a", "formats": [{"format_id": "a", "acodec": "mp4a"}]}


class Proxy(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start()
        for k in ("YTDLP_PROXY", "IG_COOKIES", "IG_COOKIES_FILE"):
            os.environ.pop(k, None)
        FakeYDL.seen, FakeYDL.fail_with = {}, None
        self.ydl = mock.patch.object(main.yt_dlp, "YoutubeDL", FakeYDL)
        self.ydl.start()

    def tearDown(self):
        self.ydl.stop()
        self.env.stop()

    def fetch(self):
        with tempfile.TemporaryDirectory() as wd:
            return main.fetch_media("https://www.instagram.com/reel/X/", wd, "ba")

    def test_no_proxy_means_a_direct_connection(self):
        _, summary = self.fetch()
        self.assertNotIn("proxy", FakeYDL.seen)
        self.assertIn("proxy off", summary)

    def test_audio_and_download_go_through_the_proxy(self):
        os.environ["YTDLP_PROXY"] = PROXY
        _, summary = self.fetch()
        self.assertEqual(FakeYDL.seen["proxy"], PROXY)
        self.assertIn("proxy on", summary)

    def test_the_summary_never_contains_the_proxy_address(self):
        """The summary ends up in n8n and in the Railway logs."""
        os.environ["YTDLP_PROXY"] = PROXY
        _, summary = self.fetch()
        self.assertNotIn("s3cret-pass", summary)
        self.assertNotIn("proxy.example.net", summary)

    def test_an_error_mentioning_the_proxy_has_the_password_removed(self):
        os.environ["YTDLP_PROXY"] = PROXY
        FakeYDL.fail_with = f"Unable to connect to proxy {PROXY}: refused"
        with self.assertRaises(main.HTTPException) as caught:
            self.fetch()
        self.assertNotIn("s3cret-pass", caught.exception.detail)
        self.assertIn("<proxy>", caught.exception.detail)

    def test_credentials_alone_in_an_error_are_removed_too(self):
        os.environ["YTDLP_PROXY"] = PROXY
        FakeYDL.fail_with = "auth failed for someuser:s3cret-pass"
        with self.assertRaises(main.HTTPException) as caught:
            self.fetch()
        self.assertNotIn("s3cret-pass", caught.exception.detail)

    def test_frames_does_not_use_the_proxy(self):
        """Frames never need sound, and the proxy is billed per byte."""
        os.environ["YTDLP_PROXY"] = PROXY
        self.assertNotIn("--proxy", main._ytdlp_cookies(["yt-dlp", "-g", "u"]))

    def test_whitespace_around_a_pasted_proxy_is_ignored(self):
        os.environ["YTDLP_PROXY"] = "  " + PROXY + "\n"
        self.assertEqual(main.ytdlp_proxy(), PROXY)


if __name__ == "__main__":
    unittest.main()

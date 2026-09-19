"""IG_COOKIES: a browser Cookie header becomes a login yt-dlp can use.

Without a login, Instagram withholds some reels' audio from the Railway server
(the audio stream is simply absent from what it is offered), while the same reel
fetched logged-out from a home connection has it. These tests never touch the
network; the values below are placeholders, not real cookies.
"""
import os
import stat
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("API_KEY", "test-key")

from yt_dlp.cookies import YoutubeDLCookieJar  # noqa: E402

import main  # noqa: E402

HEADER = "csrftoken=abc; sessionid=123%3Axyz%3A9; ds_user_id=42; rur=\"x=1,y=2\""


def load_with_ytdlp(path):
    """Read the file the way yt-dlp will, so a format mistake fails here."""
    jar = YoutubeDLCookieJar(path)
    jar.load()
    return {c.name: c for c in jar}


class CookieFile(unittest.TestCase):
    def setUp(self):
        main._cookie_cache.clear()
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start()
        os.environ.pop("IG_COOKIES", None)
        os.environ.pop("IG_COOKIES_FILE", None)

    def tearDown(self):
        self.env.stop()
        main._cookie_cache.clear()

    def test_nothing_set_means_no_cookies(self):
        self.assertEqual(main.cookie_file(), (None, "off"))

    def test_a_cookie_header_becomes_a_file_ytdlp_can_load(self):
        os.environ["IG_COOKIES"] = HEADER
        path, status = main.cookie_file()
        cookies = load_with_ytdlp(path)
        self.assertEqual(cookies["sessionid"].value, "123%3Axyz%3A9")
        self.assertEqual(cookies["sessionid"].domain, ".instagram.com")
        self.assertIn("csrftoken", cookies)
        self.assertEqual(status, "on (IG_COOKIES)")

    def test_a_value_containing_equals_signs_survives_whole(self):
        os.environ["IG_COOKIES"] = HEADER
        path, _ = main.cookie_file()
        self.assertEqual(load_with_ytdlp(path)["rur"].value, '"x=1,y=2"')

    def test_a_paste_wrapped_in_quotes_is_unwrapped_without_eating_a_value(self):
        os.environ["IG_COOKIES"] = "'" + HEADER + "'"
        path, _ = main.cookie_file()
        cookies = load_with_ytdlp(path)
        self.assertEqual(cookies["csrftoken"].value, "abc")
        self.assertEqual(cookies["rur"].value, '"x=1,y=2"')

    def test_pasting_the_header_name_too_still_works(self):
        """DevTools can copy the line as `cookie: a=1; b=2`."""
        os.environ["IG_COOKIES"] = "Cookie: " + HEADER
        path, _ = main.cookie_file()
        self.assertIn("sessionid", load_with_ytdlp(path))

    def test_cookies_without_a_sessionid_are_flagged_as_not_a_login(self):
        """csrftoken alone is what a logged-out browser has. The error message
        has to say so, or a bad paste looks exactly like a working one."""
        os.environ["IG_COOKIES"] = "csrftoken=abc; mid=zzz"
        _, status = main.cookie_file()
        self.assertIn("no sessionid", status)

    def test_the_file_is_readable_only_by_this_user(self):
        os.environ["IG_COOKIES"] = HEADER
        path, _ = main.cookie_file()
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)

    def test_the_conversion_happens_once_per_value(self):
        os.environ["IG_COOKIES"] = HEADER
        self.assertEqual(main.cookie_file()[0], main.cookie_file()[0])

    def test_a_cookies_file_takes_precedence_when_both_are_set(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as fh:
            fh.write(b"# Netscape HTTP Cookie File\n")
        try:
            os.environ["IG_COOKIES_FILE"] = fh.name
            os.environ["IG_COOKIES"] = HEADER
            self.assertEqual(main.cookie_file(), (fh.name, "on (IG_COOKIES_FILE)"))
        finally:
            os.unlink(fh.name)

    def test_a_cookies_file_path_that_does_not_exist_falls_back(self):
        os.environ["IG_COOKIES_FILE"] = "/nope/cookies.txt"
        os.environ["IG_COOKIES"] = HEADER
        self.assertEqual(main.cookie_file()[1], "on (IG_COOKIES)")

    def test_both_download_paths_hand_the_cookies_to_ytdlp(self):
        """/frames uses the yt-dlp command line; /audio and /download use the
        library. A fix on only one of them would leave /audio still logged out."""
        os.environ["IG_COOKIES"] = HEADER
        path, _ = main.cookie_file()
        self.assertEqual(main._ytdlp_cookies(["yt-dlp", "-g", "u"])[1:3], ["--cookies", path])

        seen = {}

        class FakeYDL:
            def __init__(self, opts):
                seen.update(opts)
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
            def extract_info(self, url, download):
                open(os.path.join(os.path.dirname(seen["outtmpl"]), "media.m4a"), "wb").close()
                return {"format_id": "a", "formats": [{"format_id": "a", "acodec": "mp4a"}]}

        with tempfile.TemporaryDirectory() as wd, mock.patch.object(main.yt_dlp, "YoutubeDL", FakeYDL):
            _, summary = main.fetch_media("https://www.instagram.com/reel/X/", wd, "ba")
        self.assertEqual(seen["cookiefile"], path)
        self.assertIn("cookies on (IG_COOKIES)", summary)


if __name__ == "__main__":
    unittest.main()

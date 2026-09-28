"""YouTube links: find the video id in every link shape, and never a playlist."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from youtube_service import canonical_url, classify_url, is_short, youtube_id  # noqa: E402

VID = "reFzEtCG_m8"


class Ids(unittest.TestCase):
    def test_every_link_shape(self):
        for url in (f"https://www.youtube.com/watch?v={VID}",
                    f"https://youtube.com/watch?feature=share&v={VID}&t=120s",
                    f"https://youtu.be/{VID}?si=abc123",
                    f"https://m.youtube.com/watch?v={VID}&list=PL123&index=4",
                    f"https://www.youtube.com/live/{VID}",
                    f"https://www.youtube.com/embed/{VID}"):
            self.assertEqual(youtube_id(url), VID, url)
        self.assertEqual(youtube_id("https://www.youtube.com/shorts/abcdefghijk"), "abcdefghijk")

    def test_not_a_video(self):
        for url in ("https://www.instagram.com/reel/DdjzUhwM0sV/",
                    "https://www.youtube.com/playlist?list=PL123",
                    f"https://notyoutube.com/watch?v={VID}",
                    "https://www.youtube.com/watch?v=short",
                    "not a url"):
            self.assertIsNone(youtube_id(url), url)

    def test_classify(self):
        self.assertEqual(classify_url(f"https://youtu.be/{VID}"), "youtube")
        self.assertEqual(classify_url("https://www.instagram.com/reel/X/"), "instagram")
        self.assertEqual(classify_url("https://cdn.example.com/v.mp4"), "direct")

    def test_canonical_drops_playlist_time_and_share_tokens(self):
        self.assertEqual(canonical_url(f"https://m.youtube.com/watch?v={VID}&list=PL1&index=2&t=9s&si=x"),
                         f"https://www.youtube.com/watch?v={VID}")

    def test_shorts(self):
        self.assertTrue(is_short("https://www.youtube.com/shorts/abcdefghijk"))
        self.assertFalse(is_short(f"https://www.youtube.com/watch?v={VID}"))


if __name__ == "__main__":
    unittest.main()

"""The evidence pack: every file the AI pass needs, and an honest token estimate."""
import json
import math
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import clips  # noqa: E402

if clips.HAVE_FFMPEG:
    from PIL import Image  # noqa: E402

    from analysis.pack import build_pack  # noqa: E402
    from analysis.render import image_tokens  # noqa: E402


@unittest.skipUnless(clips.HAVE_FFMPEG, "needs ffmpeg")
class PackTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = cls.tmp.name
        a, b = clips.two_scenes(cls.dir)
        cls.video = clips.concat(cls.dir, "twocut.mp4", [a, b, a, b])   # 4 s, cuts at 30, 60, 90
        cls.out = os.path.join(cls.dir, "pack")
        cls.timeline = build_pack(cls.video, cls.out)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_writes_every_part(self):
        for name in ("timeline.json", "summary.md", "motion.png"):
            self.assertTrue(os.path.exists(os.path.join(self.out, name)), name)
        with open(os.path.join(self.out, "timeline.json")) as f:
            saved = json.load(f)
        for key in ("version", "source", "cuts", "shots", "audio", "frames", "images", "token_estimate"):
            self.assertIn(key, saved)

    def test_one_strip_per_cut(self):
        strips = self.timeline["images"]["strips"]
        self.assertEqual([s["frame"] for s in strips], [30, 60, 90])
        for s in strips:
            self.assertTrue(os.path.exists(os.path.join(self.out, s["file"])))

    def test_sheets_cover_the_reel_at_2fps(self):
        sheets = self.timeline["images"]["sheets"]
        self.assertEqual(len(sheets), 1)                     # 8 tiles at 2 fps fit one sheet
        self.assertEqual(sheets[0]["tiles"], 8)

    def test_token_estimate_matches_the_images(self):
        total = 0
        for rel in self.timeline["token_estimate"]["per_image"]:
            w, h = Image.open(os.path.join(self.out, rel)).size
            total += image_tokens(w, h)
        self.assertEqual(self.timeline["token_estimate"]["total"], total)

    def test_image_tokens_follow_the_resize_rule(self):
        self.assertEqual(image_tokens(750, 1), 1)
        self.assertEqual(image_tokens(1000, 1000), math.ceil(1000 * 1000 / 750))
        # a huge image is scaled down before it's counted, so it caps out
        self.assertLessEqual(image_tokens(4000, 4000), 1600)

    def test_summary_lists_shots_and_cuts(self):
        with open(os.path.join(self.out, "summary.md")) as f:
            text = f.read()
        self.assertIn("| S04 |", text)
        self.assertIn("hard", text)


if __name__ == "__main__":
    unittest.main()

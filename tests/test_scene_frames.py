"""Scene mode: one frame per scene, spaced by min_gap, with a frame at least every max_gap."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("API_KEY", "test-key")

import clips  # noqa: E402

if clips.HAVE_FFMPEG:
    from fastapi.testclient import TestClient  # noqa: E402
    import main  # noqa: E402
    from scene_frames import extract_scene_frames  # noqa: E402


def four_scenes(d):
    """Four visibly different 2 s scenes: hard cuts at 2, 4 and 6 s."""
    parts = [clips.static(d, f"s{i}.mp4", 2, clips.still(d, f"s{i}.png", source=src))
             for i, src in enumerate(("testsrc2", "mandelbrot", "smptebars", "rgbtestsrc"))]
    return clips.concat(d, "four.mp4", parts)


@unittest.skipUnless(clips.HAVE_FFMPEG, "needs ffmpeg")
class SceneFrames(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.video = four_scenes(cls.tmp.name)
        cls.still_video = clips.static(cls.tmp.name, "long.mp4", 7)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def times(self, video, **kw):
        args = dict(start=0.0, threshold=0.3, min_gap=1.0, max_gap=60.0, max_frames=50,
                    width=None, quality=4, timeout=120)
        args.update(kw)
        with tempfile.TemporaryDirectory() as wd:
            return [t for _, t in extract_scene_frames(video, workdir=wd, **args)]

    def assertTimes(self, got, want):
        self.assertEqual(len(got), len(want), got)
        for g, w in zip(got, want):
            self.assertAlmostEqual(g, w, delta=0.51)

    def test_one_frame_per_scene(self):
        self.assertTimes(self.times(self.video), [0, 2, 4, 6])

    def test_cuts_closer_than_min_gap_are_skipped(self):
        self.assertTimes(self.times(self.video, min_gap=3.0), [0, 4])

    def test_long_static_shot_still_gets_a_frame_every_max_gap(self):
        self.assertTimes(self.times(self.still_video, max_gap=3.0), [0, 3, 6])

    def test_endpoint_scene_mode(self):
        with mock.patch.object(main, "resolve_url", lambda url: self.video):
            r = TestClient(main.app).post("/frames", headers={"X-API-Key": os.environ["API_KEY"]}, json={
                "video_url": "https://youtu.be/reFzEtCG_m8", "mode": "scene", "min_gap": 1,
                "output": "json", "max_frames": 400})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual((body["mode"], body["count"]), ("scene", 4))
        self.assertAlmostEqual(body["frames"][2]["timestamp"], 4, delta=0.51)

    def test_interval_mode_keeps_its_own_limit(self):
        r = TestClient(main.app).post("/frames", headers={"X-API-Key": os.environ["API_KEY"]}, json={
            "video_url": "https://cdn.example.com/v.mp4", "max_frames": 400})
        self.assertEqual(r.status_code, 422)


if __name__ == "__main__":
    unittest.main()

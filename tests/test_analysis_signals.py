"""Per-frame signals: the camera-motion numbers must have the right sign and size."""
import os
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import clips  # noqa: E402

if clips.HAVE_FFMPEG:
    from analysis.probe import probe  # noqa: E402
    from analysis.signals import measure  # noqa: E402


@unittest.skipUnless(clips.HAVE_FFMPEG, "needs ffmpeg")
class SignalsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = cls.tmp.name

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def signals(self, path):
        return measure(path, probe(path))

    def test_probe_reads_basic_facts(self):
        info = probe(clips.static(self.dir, "p.mp4", 2))
        self.assertEqual((info.width, info.height), (clips.W, clips.H))
        self.assertAlmostEqual(info.fps, 30, places=2)
        self.assertEqual(info.frames, 60)
        self.assertFalse(info.has_audio)

    def test_static_clip_has_no_motion(self):
        s = self.signals(clips.static(self.dir))
        for channel in (s.dx, s.dy, s.zoom):
            self.assertLess(abs(np.median(channel[1:])), 0.001)

    def test_camera_panning_right_moves_content_left(self):
        s = self.signals(clips.pan_right(self.dir))
        self.assertLess(np.median(s.dx[1:]), -0.002)
        self.assertLess(abs(np.median(s.dy[1:])), 0.001)

    def test_push_in_expands_content(self):
        s = self.signals(clips.push_in(self.dir))
        self.assertGreater(np.median(s.zoom[1:]), 0.002)

    def test_arrays_cover_every_frame(self):
        path = clips.static(self.dir, "len.mp4", 1)
        s = self.signals(path)
        self.assertEqual(len(s.diff), 30)
        self.assertEqual(len(s.luma), 30)
        self.assertEqual(s.dx[0], 0)


if __name__ == "__main__":
    unittest.main()

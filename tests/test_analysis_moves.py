"""Camera moves: the right label over the right frames, plus the source frame rate."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import clips  # noqa: E402

if clips.HAVE_FFMPEG:
    from analysis.cuts import shots_from_cuts  # noqa: E402
    from analysis.moves import camera_moves, source_cadence  # noqa: E402
    from analysis.probe import probe  # noqa: E402
    from analysis.signals import measure  # noqa: E402


@unittest.skipUnless(clips.HAVE_FFMPEG, "needs ffmpeg")
class MovesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = cls.tmp.name

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def analyse(self, path):
        info = probe(path)
        sig = measure(path, info)
        shot = shots_from_cuts([], info.frames, info.fps)[0]
        return sig, shot

    def test_pan(self):
        sig, shot = self.analyse(clips.pan_right(self.dir))
        moves = camera_moves(sig, shot)
        self.assertEqual([m.type for m in moves], ["pan-right"])

    def test_push_in(self):
        sig, shot = self.analyse(clips.push_in(self.dir))
        moves = camera_moves(sig, shot)
        self.assertEqual([m.type for m in moves], ["push-in"])
        self.assertGreater(moves[0].total, 0.2)   # ends >20 % bigger

    def test_hold_then_pan(self):
        sig, shot = self.analyse(clips.hold_then_pan(self.dir))
        moves = camera_moves(sig, shot)
        self.assertEqual([m.type for m in moves], ["static", "pan-right"])
        self.assertAlmostEqual(moves[1].start_frame, 30, delta=3)

    def test_static(self):
        sig, shot = self.analyse(clips.static(self.dir))
        self.assertEqual([m.type for m in camera_moves(sig, shot)], ["static"])

    def test_24fps_source_conformed_to_30(self):
        sig, shot = self.analyse(clips.pan_24_in_30(self.dir))
        self.assertEqual(source_cadence(sig, shot)["source_fps"], 24)
        self.assertEqual([m.type for m in camera_moves(sig, shot)], ["pan-right"])

    def test_native_30fps(self):
        sig, shot = self.analyse(clips.pan_right(self.dir))
        self.assertEqual(source_cadence(sig, shot)["source_fps"], 30)


if __name__ == "__main__":
    unittest.main()

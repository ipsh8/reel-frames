"""Cut detection must find each edit at the right frame and name its kind."""
import os
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import clips  # noqa: E402

if clips.HAVE_FFMPEG:
    from analysis.cuts import _peaks, detect_cuts, shots_from_cuts  # noqa: E402
    from analysis.probe import probe  # noqa: E402
    from analysis.signals import measure  # noqa: E402


@unittest.skipUnless(clips.HAVE_FFMPEG, "needs ffmpeg")
class CutsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = cls.tmp.name

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def cuts(self, path):
        info = probe(path)
        return detect_cuts(measure(path, info)), info

    def test_hard_cut_found_at_first_frame_of_new_shot(self):
        cuts, _ = self.cuts(clips.hard_cut(self.dir))
        self.assertEqual([(c.frame, c.type) for c in cuts], [(30, "hard")])

    def test_cut_next_to_a_busy_shot_is_still_found(self):
        # Numbers from the reference reel's f738: walking legs at 24-in-30 fps
        # keep the typical change near 0.06, so the cut is only ~3x typical.
        change = np.array([0.0, 0.07] * 10 + [0.19] + [0.07, 0.06] * 5)
        spread = np.where(change > 0.1, 0.875, 0.3)
        self.assertIn(20, _peaks(change, spread, 0.02))

    def test_busy_spike_confined_to_part_of_the_frame_is_not_let_through(self):
        change = np.array([0.0, 0.07] * 10 + [0.19] + [0.07, 0.06] * 5)
        spread = np.full_like(change, 0.3)
        self.assertNotIn(20, _peaks(change, spread, 0.02))

    def test_white_frames_make_a_flash_cut(self):
        cuts, _ = self.cuts(clips.flash_cut(self.dir))
        self.assertEqual(len(cuts), 1, cuts)
        self.assertEqual(cuts[0].type, "flash")
        self.assertIn(cuts[0].frame, (30, 32))

    def test_crossfade_is_one_dissolve_spanning_the_fade(self):
        cuts, _ = self.cuts(clips.dissolve(self.dir))
        self.assertEqual(len(cuts), 1, cuts)
        cut = cuts[0]
        self.assertEqual(cut.type, "dissolve")
        self.assertLessEqual(cut.span[0], 32)
        self.assertGreaterEqual(cut.span[1], 43)

    def test_camera_moves_are_not_cuts(self):
        for make in (clips.pan_right, clips.push_in, clips.static):
            cuts, _ = self.cuts(make(self.dir))
            self.assertEqual(cuts, [], make.__name__)

    def test_caption_appearing_is_a_graphic_event_not_a_cut(self):
        cuts, info = self.cuts(clips.caption_pop(self.dir))
        self.assertEqual([(c.frame, c.type) for c in cuts], [(30, "graphic")])
        self.assertEqual(len(shots_from_cuts(cuts, info.frames, info.fps)), 1)

    def test_shots_partition_the_frames(self):
        cuts, info = self.cuts(clips.hard_cut(self.dir))
        shots = shots_from_cuts(cuts, info.frames, info.fps)
        self.assertEqual([(s.start_frame, s.end_frame) for s in shots], [(0, 29), (30, 59)])
        self.assertIsNone(shots[0].cut_in)
        self.assertEqual(shots[1].cut_in.type, "hard")


if __name__ == "__main__":
    unittest.main()

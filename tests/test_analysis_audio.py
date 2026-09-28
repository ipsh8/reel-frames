"""Audio: onsets land on the clicks, tempo comes out right, silent video is handled."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import clips  # noqa: E402

if clips.HAVE_FFMPEG:
    from analysis.audio import analyze_audio  # noqa: E402
    from analysis.cuts import Cut  # noqa: E402


@unittest.skipUnless(clips.HAVE_FFMPEG, "needs ffmpeg")
class AudioTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = cls.tmp.name
        cls.clicks = clips.click_track(cls.dir, every=0.5, seconds=4)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_onsets_on_every_click(self):
        audio = analyze_audio(self.clicks, 30, [])
        self.assertTrue(audio["available"])
        expected = [i * 0.5 for i in range(8)]
        self.assertEqual(len(audio["onsets"]), len(expected), audio["onsets"])
        for got, want in zip(audio["onsets"], expected):
            self.assertAlmostEqual(got, want, delta=1 / 30)

    def test_tempo(self):
        self.assertAlmostEqual(analyze_audio(self.clicks, 30, [])["tempo_bpm"], 120, delta=3)

    def test_cut_alignment(self):
        on_beat = Cut(30, 1.0, "hard", 0.3, (30, 30))
        off_beat = Cut(36, 1.2, "hard", 0.3, (36, 36))   # nearest click is 1.0 s, 6 frames earlier
        audio = analyze_audio(self.clicks, 30, [on_beat, off_beat])
        self.assertEqual(audio["cut_offsets_frames"], {"30": 0, "36": -6})
        self.assertEqual(audio["cuts_on_onset_ratio"], 0.5)
        # 2 onsets/s, ±2 frames at 30 fps → 5/30 s of every second counts as "on"
        self.assertAlmostEqual(audio["chance_ratio"], 0.33, delta=0.02)

    def test_video_without_audio(self):
        audio = analyze_audio(clips.static(self.dir, "mute.mp4", 1), 30, [])
        self.assertEqual(audio, {"available": False, "onsets": [], "tempo_bpm": None,
                                 "cut_offsets_frames": {}, "cuts_on_onset_ratio": None,
                                 "chance_ratio": None})


if __name__ == "__main__":
    unittest.main()

"""/audio and /download must yield sound even when Instagram's pre-muxed MP4 is silent.

Instagram lists its pre-muxed MP4s with unknown codecs, and some of them carry
no audio track, while a separate audio-only DASH stream does. A stand-in for
yt-dlp reproduces that here, so these tests never touch the network. They need
ffmpeg and ffprobe on PATH, same as the service itself.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("API_KEY", "test-key")

import yt_dlp  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

REEL_URL = "https://www.instagram.com/reel/TEST123/"
HEADERS = {"X-API-Key": os.environ["API_KEY"]}
HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def _ffmpeg(*args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def _stream_types(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", path],
        capture_output=True, text=True, check=True).stdout
    return {line.strip() for line in out.splitlines() if line.strip()}


class FakeInstagram:
    """Serves the formats yt-dlp would see for one reel.

    "b" is always the pre-muxed MP4, which is silent. "ba" and "bv*+ba" exist
    only when the reel has a separate audio stream.
    """

    def __init__(self, fixtures, has_audio_stream):
        self.fixtures = fixtures
        self.has_audio_stream = has_audio_stream
        self.requested_formats = []

    def _pick(self, fmt):
        available = {"b": "silent_muxed"}
        if self.has_audio_stream:
            available.update({"ba": "audio_only", "bv*+ba": "merged"})
        for alternative in fmt.split("/"):
            if alternative in available:
                return alternative, self.fixtures[available[alternative]]
        raise yt_dlp.utils.DownloadError(f"Requested format is not available: {fmt}")

    def _formats(self):
        # The pre-muxed file's codecs are unknown, as Instagram reports them.
        formats = [{"format_id": "1", "acodec": None}]
        if self.has_audio_stream:
            formats += [{"format_id": "dash-a", "acodec": "mp4a.40.5"},
                        {"format_id": "dash-v", "acodec": "none"}]
        return formats

    def youtube_dl(self, opts):
        fake = self

        class _YDL:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def extract_info(self, url, download=True):
                fake.requested_formats.append(opts["format"])
                picked, source = fake._pick(opts["format"])
                ext = os.path.splitext(source)[1].lstrip(".")
                shutil.copy(source, opts["outtmpl"].replace("%(ext)s", ext))
                return {"format_id": picked, "formats": fake._formats()}

        return _YDL()


@unittest.skipUnless(HAVE_FFMPEG, "needs ffmpeg and ffprobe on PATH")
class MediaAudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_dir = tempfile.mkdtemp(prefix="reel_fixtures_")
        video = ["-f", "lavfi", "-i", "testsrc=size=64x64:rate=10:duration=2"]
        tone = ["-f", "lavfi", "-i", "sine=frequency=440:duration=2"]
        cls.fixtures = {
            "silent_muxed": os.path.join(cls.fixture_dir, "silent.mp4"),
            "audio_only": os.path.join(cls.fixture_dir, "audio.m4a"),
            "merged": os.path.join(cls.fixture_dir, "merged.mp4"),
        }
        _ffmpeg(*video, "-pix_fmt", "yuv420p", cls.fixtures["silent_muxed"])
        _ffmpeg(*tone, "-c:a", "aac", cls.fixtures["audio_only"])
        _ffmpeg(*video, *tone, "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                cls.fixtures["merged"])
        cls.client = TestClient(main.app)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.fixture_dir, ignore_errors=True)

    def _serve(self, has_audio_stream):
        fake = FakeInstagram(self.fixtures, has_audio_stream)
        patcher = mock.patch.object(main.yt_dlp, "YoutubeDL", side_effect=fake.youtube_dl)
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake

    def _save(self, content, suffix):
        fd, path = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(fd, "wb") as f:
            f.write(content)
        self.addCleanup(os.remove, path)
        return path

    def test_audio_comes_from_the_audio_stream_when_the_muxed_file_is_silent(self):
        self._serve(has_audio_stream=True)
        resp = self.client.post("/audio", json={"video_url": REEL_URL}, headers=HEADERS)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.headers["content-type"], "audio/mpeg")
        self.assertEqual(_stream_types(self._save(resp.content, ".mp3")), {"audio"})

    def test_audio_on_a_reel_with_no_sound_says_so_plainly(self):
        self._serve(has_audio_stream=False)
        resp = self.client.post("/audio", json={"video_url": REEL_URL}, headers=HEADERS)
        self.assertEqual(resp.status_code, 422)
        detail = resp.json()["detail"]
        self.assertIn("REEL_HAS_NO_AUDIO", detail)
        # Says what Instagram offered the server, since a browser may be offered more.
        self.assertIn("picked b; offered (id=audio codec) 1=?", detail)

    def test_download_merges_the_audio_back_in_when_the_muxed_file_is_silent(self):
        fake = self._serve(has_audio_stream=True)
        resp = self.client.post("/download", json={"video_url": REEL_URL}, headers=HEADERS)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(_stream_types(self._save(resp.content, ".mp4")), {"video", "audio"})
        self.assertEqual(fake.requested_formats[-1], main.MERGED_VIDEO_FORMAT)

    def test_download_of_a_reel_with_no_sound_still_returns_the_video(self):
        self._serve(has_audio_stream=False)
        resp = self.client.post("/download", json={"video_url": REEL_URL}, headers=HEADERS)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(_stream_types(self._save(resp.content, ".mp4")), {"video"})


if __name__ == "__main__":
    unittest.main()

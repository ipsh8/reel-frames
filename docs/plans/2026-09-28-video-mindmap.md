# Video → mind map implementation plan

> **For agentic workers:** executed inline (superpowers:executing-plans). Steps use `- [ ]`.

**Goal:** YouTube links go through the same REEL FRAMES workflow as reels, land
in Drive with the video, info, transcript and scene frames, and a
`video-mindmap` skill turns that folder into `workflow.md`, a Whimsical mind
map and a frame atlas, then expands any node on request.

**Architecture:** `reel-frames` gets a `youtube_service` module with:

- URL helpers
- a download cache that fetches each video once
- `/transcript`

It also gets a `scene_frames` module for picking frames at scene changes.
`main.py` sends YouTube links through the cache. n8n branches per link.

The skill is Claude-driven, with small scripts. `map.json` is the single source
of truth, and the outline for Whimsical and the atlas page are both generated
from it.

**Tech stack:** Python 3.12, FastAPI, yt-dlp[default] with Deno, ffmpeg,
Pillow, faster-whisper through `uv run` (PEP 723), the n8n MCP workflow SDK,
the Whimsical MCP, and Artifacts.

**Spec:** `docs/specs/2026-09-28-video-mindmap-design.md`

**Two decisions made while planning** (the spec is updated in Task 1):

- **`/transcript` always returns `info.json`.** The transcript source goes in
  an `X-Transcript` header: `manual`, `auto`, `none` or `blocked`. Missing
  subtitles are not an error, because n8n needs `info.json` either way.
- **How a node shows its source:**
  - A timestamp (`▶ 16:22`) means *from the video*.
  - `🔍` means *added research*.
  - Nodes the user added by hand in Whimsical get `source: "user"`.

  This replaces a separate 🎬 tag on every node, which would be noise across
  60+ nodes.

---

## File map

**reel-frames**

| File | Responsibility |
|---|---|
| `youtube_service.py` | `youtube_id`, `classify_url`, `canonical_url`, `is_short`, YouTube cookies, `cached_video`, `prune_cache`, `summarize_info`, `pick_subtitle_track`, `cached_transcript`, `POST /transcript` |
| `scene_frames.py` | `select_expr`, `extract_scene_frames` |
| `main.py` | YouTube branch in `resolve_url` and `fetch_media`, `/download` serves the cache, `/frames` scene mode, includes the transcript router, version 3.5.0 |
| `Dockerfile`, `requirements.txt` | Deno and `yt-dlp[default]` |
| `tests/test_youtube_urls.py`, `tests/test_youtube_cache.py`, `tests/test_transcript.py`, `tests/test_scene_frames.py` | new tests |
| `.env.example`, `README.md`, `CHANGELOG.md`, `docs/features/…`, `docs/features/INDEX.md` | docs |

**Skill** (`~/.skillbook/skills/video-mindmap/`)

| File | Responsibility |
|---|---|
| `SKILL.md` | the procedure: pull, transcript, breakdown, frames, Whimsical, atlas, expand |
| `references/map-schema.md` | map.json fields and rules, plus the `workflow.md` template |
| `scripts/mapfile.py` | validate, next-code, add, reconcile, set |
| `scripts/to_outline.py` | map.json → indented outline |
| `scripts/transcript_md.py` | vtt + chapters → deduped, timestamped `transcript.md` |
| `scripts/frames_at.py` | candidate frames per node, plus labelled contact sheets (Pillow) |
| `scripts/render_atlas.py`, `scripts/atlas_template.html` | the atlas page and its frames |
| `scripts/transcribe.py` | faster-whisper fallback → `transcript.vtt` |
| `tests/test_*.py` | stdlib unittest for mapfile, to_outline, transcript_md, render_atlas |

**n8n:** workflow `B56j7gqfSRCOiYdy` (REEL FRAMES to Drive).

---

### Task 1: Spec touch-up

**Files:** Modify `docs/specs/2026-09-28-video-mindmap-design.md`

- [ ] **Step 1:** In the component table, replace the `/transcript` row with:
  `/transcript` (new) returns `info.json`, plus `transcript.vtt` when
  subtitles exist, as a zip or as JSON. The header `X-Transcript` is
  `manual`, `auto`, `none` or `blocked`.
- [ ] **Step 2:** In Goals, item 6, replace the 🎬/🔍 wording with:
  `▶ mm:ss` = from the video, `🔍` = added research.
- [ ] **Step 3:** Commit `docs: spec follows the planned /transcript shape and node markers`.

### Task 2: YouTube URL helpers

**Files:**
- Create: `youtube_service.py`
- Test: `tests/test_youtube_urls.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2:** Run `.venv/bin/python -m unittest tests.test_youtube_urls -v`.
  Expected: ImportError (no `youtube_service`).
- [ ] **Step 3: Implement.** Create `youtube_service.py` with the header and
  URL helpers. Later tasks append to this file.

```python
"""YouTube: link handling, a once-per-video download cache, and POST /transcript.

YouTube bot-checks data-centre IPs like Railway's, so every endpoint that needs
a YouTube video goes through cached_video(). The first call downloads the
video (720p max); later calls within YT_CACHE_SECONDS reuse the file. A long
video therefore costs one request for the video and one for its subtitles,
however many endpoints n8n calls.
"""
import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
import zipfile
from typing import Literal, Optional
from urllib.parse import parse_qs, urlparse

import yt_dlp
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

router = APIRouter()

_ID = re.compile(r"[A-Za-z0-9_-]{11}")
_PATH_ID = re.compile(r"^/(?:shorts|live|embed|v)/([A-Za-z0-9_-]{11})(?:/|$)")
_HOSTS = {"youtube.com", "youtube-nocookie.com"}


def youtube_id(url: str) -> Optional[str]:
    """The 11-character video id, or None when the link is not one YouTube video."""
    try:
        parts = urlparse(url.strip())
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    for prefix in ("www.", "m.", "music."):
        host = host.removeprefix(prefix)
    if host == "youtu.be":
        vid = parts.path.lstrip("/").split("/")[0]
    elif host in _HOSTS:
        match = _PATH_ID.match(parts.path)
        vid = match.group(1) if match else (parse_qs(parts.query).get("v") or [""])[0]
    else:
        return None
    return vid if _ID.fullmatch(vid or "") else None


def classify_url(url: str) -> Literal["instagram", "youtube", "direct"]:
    if youtube_id(url):
        return "youtube"
    return "instagram" if "instagram.com" in url else "direct"


def is_short(url: str) -> bool:
    return urlparse(url).path.startswith("/shorts/")


def canonical_url(url: str) -> str:
    """The plain watch link. Drops list=, t= and share tokens so yt-dlp fetches exactly one video."""
    return f"https://www.youtube.com/watch?v={youtube_id(url)}"
```

- [ ] **Step 4:** Run the test again. Expected: 5 tests OK.
- [ ] **Step 5:** Commit `feat: recognise YouTube links (id, kind, canonical form)`.

### Task 3: YouTube download cache, cookies and proxy

**Files:**
- Modify: `youtube_service.py` (append)
- Test: `tests/test_youtube_cache.py`

- [ ] **Step 1: Write the failing test**

```python
"""cached_video: one YouTube download per video, reused, pruned, proxied, cookied."""
import base64
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("API_KEY", "test-key")

import main  # noqa: E402
import youtube_service as yt  # noqa: E402

URL = "https://m.youtube.com/watch?v=reFzEtCG_m8&list=PL1&t=30s"
INFO = {"id": "reFzEtCG_m8", "title": "A film", "channel": "Chan", "duration": 1685,
        "webpage_url": "https://www.youtube.com/watch?v=reFzEtCG_m8", "description": "d",
        "chapters": [{"start_time": 0, "end_time": 98, "title": "Welcome"}],
        "subtitles": {"en": [{}], "fr": [{}]}, "automatic_captions": {"en-orig": [{}], "de": [{}]}}


class FakeYDL:
    """Stands in for yt_dlp.YoutubeDL: writes the file yt-dlp would and records how it was called."""
    calls: list = []
    fail_with = None

    def __init__(self, opts):
        self.opts = dict(opts)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, url, download):
        FakeYDL.calls.append((url, self.opts))
        if FakeYDL.fail_with:
            raise yt.yt_dlp.utils.DownloadError(FakeYDL.fail_with)
        out = self.opts["outtmpl"]
        if self.opts.get("skip_download"):
            lang = self.opts["subtitleslangs"][0]
            with open(out.replace("%(ext)s", f"{lang}.vtt"), "w") as f:
                f.write("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhello\n")
        else:
            with open(out.replace("%(ext)s", "mp4"), "wb") as f:
                f.write(b"fake-mp4")
        return INFO


class CacheTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [mock.patch.object(yt, "CACHE_DIR", self.tmp.name),
                        mock.patch.object(yt.yt_dlp, "YoutubeDL", FakeYDL),
                        mock.patch.dict(os.environ, {}, clear=False)]
        for p in self.patches:
            p.start()
        for k in ("YTDLP_PROXY", "YT_COOKIES_FILE", "YT_COOKIES_B64", "YT_CACHE_SECONDS"):
            os.environ.pop(k, None)
        FakeYDL.calls, FakeYDL.fail_with = [], None

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def test_second_call_reuses_the_download(self):
        first = yt.cached_video(URL)
        second = yt.cached_video("https://youtu.be/reFzEtCG_m8")
        self.assertEqual(first, second)
        self.assertEqual(len(FakeYDL.calls), 1)
        with open(first, "rb") as f:
            self.assertEqual(f.read(), b"fake-mp4")

    def test_only_one_video_is_ever_requested(self):
        yt.cached_video(URL)
        url, opts = FakeYDL.calls[0]
        self.assertEqual(url, "https://www.youtube.com/watch?v=reFzEtCG_m8")
        self.assertTrue(opts["noplaylist"])
        self.assertIn("height<=720", opts["format"])

    def test_info_json_keeps_chapters_and_english_tracks(self):
        folder = os.path.dirname(yt.cached_video(URL))
        with open(os.path.join(folder, "info.json")) as f:
            info = json.load(f)
        self.assertEqual(info["chapters"], [{"start": 0, "end": 98, "title": "Welcome"}])
        self.assertEqual(info["subtitle_langs"], ["en"])
        self.assertEqual(info["auto_caption_langs"], ["en-orig"])

    def test_old_entries_are_pruned_fresh_ones_kept(self):
        os.environ["YT_CACHE_SECONDS"] = "60"
        old, fresh = (os.path.join(self.tmp.name, n) for n in ("old", "fresh"))
        os.makedirs(old)
        os.makedirs(fresh)
        past = time.time() - 120
        os.utime(old, (past, past))
        yt.prune_cache()
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(fresh))

    def test_proxy_is_used_for_youtube(self):
        os.environ["YTDLP_PROXY"] = "http://u:p@proxy.example.net:8000"
        yt.cached_video(URL)
        self.assertEqual(FakeYDL.calls[0][1]["proxy"], "http://u:p@proxy.example.net:8000")

    def test_cookies_from_base64_become_a_cookies_file(self):
        text = "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tabc\n"
        os.environ["YT_COOKIES_B64"] = base64.b64encode(text.encode()).decode()
        yt.cached_video(URL)
        with open(FakeYDL.calls[0][1]["cookiefile"]) as f:
            self.assertEqual(f.read(), text)

    def test_bot_check_is_a_422_that_says_so_and_can_be_retried(self):
        FakeYDL.fail_with = "ERROR: [youtube] reFzEtCG_m8: Sign in to confirm you're not a bot"
        with self.assertRaises(main.HTTPException) as caught:
            yt.cached_video(URL)
        self.assertEqual(caught.exception.status_code, 422)
        self.assertIn("not a bot", caught.exception.detail)
        FakeYDL.fail_with = None
        self.assertTrue(os.path.exists(yt.cached_video(URL)))

    def test_download_endpoint_serves_the_cached_file_and_keeps_it(self):
        from fastapi.testclient import TestClient
        r = TestClient(main.app).post("/download", json={"video_url": URL},
                                      headers={"X-API-Key": os.environ["API_KEY"]})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.content, b"fake-mp4")
        self.assertTrue(os.path.exists(yt.cached_video(URL)))
        self.assertEqual(len(FakeYDL.calls), 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2:** Run `.venv/bin/python -m unittest tests.test_youtube_cache -v`.
  Expected: AttributeError (`CACHE_DIR`, `cached_video`).
- [ ] **Step 3: Implement.** Append to `youtube_service.py`:

```python
CACHE_DIR = os.path.join(tempfile.gettempdir(), "yt-cache")
# 720p keeps a 30-minute video around 200-400 MB: small enough for n8n to pass
# to Drive, sharp enough for frames. mp4/m4a first so no remux is needed.
VIDEO_FORMAT = ("bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720][ext=mp4]/"
                "bv*[height<=720]+ba/b[height<=720]/b")

_cookie_lock = threading.Lock()
_cookie_files: dict = {}          # YT_COOKIES_B64 value -> file made from it
_locks_guard = threading.Lock()
_video_locks: dict = {}           # video id -> lock, so one video downloads once at a time


def cache_seconds() -> float:
    return float(os.getenv("YT_CACHE_SECONDS", "3600"))


def cookie_file() -> Optional[str]:
    """cookies.txt for YouTube: YT_COOKIES_FILE, or YT_COOKIES_B64 (base64 of one, for Railway)."""
    path = os.getenv("YT_COOKIES_FILE", "").strip()
    if path and os.path.isfile(path):
        return path
    raw = os.getenv("YT_COOKIES_B64", "").strip()
    if not raw:
        return None
    with _cookie_lock:
        made = _cookie_files.get(raw)
        if not made or not os.path.exists(made):
            fd, made = tempfile.mkstemp(prefix="yt-cookies-", suffix=".txt")
            with os.fdopen(fd, "wb") as f:
                f.write(base64.b64decode(raw))
            _cookie_files[raw] = made
    return made


def _run_ydl(url: str, extra: dict, what: str) -> dict:
    import main  # main imports this module, so a top-level import would be circular
    opts = {"quiet": True, "no_warnings": True, "noprogress": True, "noplaylist": True,
            "socket_timeout": main.YTDLP_TIMEOUT, **extra}
    cookies = cookie_file()
    if cookies:
        opts["cookiefile"] = cookies
    proxy = main.ytdlp_proxy()
    if proxy:
        opts["proxy"] = proxy
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=True) or {}
    except yt_dlp.utils.DownloadError as e:
        raise HTTPException(422, main._redact_proxy(f"YouTube {what} failed: {e}", proxy))


def _lock_for(vid: str) -> threading.Lock:
    with _locks_guard:
        return _video_locks.setdefault(vid, threading.Lock())


def video_dir(vid: str) -> str:
    return os.path.join(CACHE_DIR, vid)


def prune_cache() -> None:
    """Delete videos unused for YT_CACHE_SECONDS: Railway's disk is small and videos are big."""
    if not os.path.isdir(CACHE_DIR):
        return
    now = time.time()
    for name in os.listdir(CACHE_DIR):
        path = os.path.join(CACHE_DIR, name)
        if now - os.path.getmtime(path) > cache_seconds():
            shutil.rmtree(path, ignore_errors=True)


def summarize_info(info: dict) -> dict:
    """The parts of yt-dlp's info that the breakdown uses; the full dict is megabytes of formats."""
    def english(tracks):
        return sorted(lang for lang in (tracks or {}) if lang == "en" or lang.startswith("en-"))
    return {
        "id": info.get("id"),
        "title": info.get("title"),
        "channel": info.get("channel") or info.get("uploader"),
        "duration": info.get("duration"),
        "upload_date": info.get("upload_date"),
        "webpage_url": info.get("webpage_url"),
        "description": info.get("description"),
        "chapters": [{"start": c.get("start_time"), "end": c.get("end_time"), "title": c.get("title")}
                     for c in info.get("chapters") or []],
        "subtitle_langs": english(info.get("subtitles")),
        "auto_caption_langs": english(info.get("automatic_captions")),
    }


def _as_mp4(folder: str) -> str:
    """The downloaded file as video.mp4; remuxes the rare webm/mkv that the last format fallback gives."""
    video = os.path.join(folder, "video.mp4")
    if os.path.exists(video):
        return video
    found = [n for n in os.listdir(folder)
             if n.startswith("video.") and not n.endswith((".part", ".ytdl"))]
    if not found:
        raise HTTPException(422, "yt-dlp finished but no video file was found.")
    src = os.path.join(folder, found[0])
    out = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", src,
                          "-c", "copy", "-movflags", "+faststart", video],
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise HTTPException(422, f"Could not remux {found[0]} to mp4: {out.stderr.strip()[:300]}")
    os.remove(src)
    return video


def cached_video(url: str) -> str:
    """Local path of the video (720p max mp4), downloading it on first use."""
    vid = youtube_id(url)
    if not vid:
        raise HTTPException(422, f"Not a YouTube video link: {url[:200]}")
    with _lock_for(vid):
        prune_cache()
        folder = video_dir(vid)
        video = os.path.join(folder, "video.mp4")
        if os.path.exists(video):
            os.utime(folder)
            return video
        shutil.rmtree(folder, ignore_errors=True)  # leftovers of a failed attempt
        os.makedirs(folder)
        try:
            info = _run_ydl(canonical_url(url), {
                "format": VIDEO_FORMAT, "merge_output_format": "mp4",
                "outtmpl": os.path.join(folder, "video.%(ext)s")}, "download")
            video = _as_mp4(folder)
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        with open(os.path.join(folder, "info.json"), "w") as f:
            json.dump(summarize_info(info), f, indent=2, ensure_ascii=False)
        return video
```

- [ ] **Step 4: Wire it into `main.py`.**
  - Add `import youtube_service` after the other service imports.
  - In `resolve_url`, replace `if "instagram.com" not in url: return url` with:

    ```python
    kind = youtube_service.classify_url(url)
    if kind == "youtube":
        return youtube_service.cached_video(url)
    if kind != "instagram":
        return url
    ```

  - In `fetch_media`, replace `if "instagram.com" not in url: return url, ""` with:

    ```python
    kind = youtube_service.classify_url(url)
    if kind == "youtube":
        return youtube_service.cached_video(url), "youtube (cached download)"
    if kind != "instagram":
        return url, ""
    ```

  - At the top of `download()`, before `workdir = …`:

    ```python
    if youtube_service.classify_url(req.video_url) == "youtube":
        # The cached file is already an mp4 with sound; copying 300 MB again would only cost time.
        return FileResponse(youtube_service.cached_video(req.video_url),
                            media_type="video/mp4", filename="video.mp4")
    ```

  - Update the docstrings of `resolve_url` and `fetch_media` to say
    "Instagram or YouTube".

- [ ] **Step 5:** Run `.venv/bin/python -m unittest discover -s tests`.
  Expected: every test OK, the old 55 plus the new ones.
- [ ] **Step 6:** Commit `feat: fetch each YouTube video once and reuse it across endpoints`.

### Task 4: `POST /transcript`

**Files:**
- Modify: `youtube_service.py` (append), `main.py` (include the router)
- Test: `tests/test_transcript.py`

- [ ] **Step 1: Write the failing test**

```python
"""/transcript: info.json always; people-written English subtitles beat YouTube's auto ones."""
import base64
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("API_KEY", "test-key")

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
import youtube_service as yt  # noqa: E402
from test_youtube_cache import INFO, FakeYDL  # noqa: E402

URL = "https://youtu.be/reFzEtCG_m8"
HEADERS = {"X-API-Key": os.environ["API_KEY"]}


class PickTrack(unittest.TestCase):
    def test_manual_english_wins(self):
        self.assertEqual(yt.pick_subtitle_track({"subtitle_langs": ["en-GB"], "auto_caption_langs": ["en-orig"]}),
                         ("en-GB", False))

    def test_auto_original_before_auto_translated(self):
        self.assertEqual(yt.pick_subtitle_track({"subtitle_langs": [], "auto_caption_langs": ["en", "en-orig"]}),
                         ("en-orig", True))

    def test_nothing_english(self):
        self.assertIsNone(yt.pick_subtitle_track({"subtitle_langs": [], "auto_caption_langs": []}))


class Endpoint(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [mock.patch.object(yt, "CACHE_DIR", self.tmp.name),
                        mock.patch.object(yt.yt_dlp, "YoutubeDL", FakeYDL)]
        for p in self.patches:
            p.start()
        FakeYDL.calls, FakeYDL.fail_with = [], None
        self.client = TestClient(main.app)

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def post(self, **body):
        return self.client.post("/transcript", json={"video_url": URL, **body}, headers=HEADERS)

    def test_zip_has_info_and_manual_transcript(self):
        r = self.post()
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.headers["X-Transcript"], "manual")
        z = zipfile.ZipFile(io.BytesIO(r.content))
        self.assertEqual(sorted(z.namelist()), ["info.json", "transcript.vtt"])
        self.assertEqual(json.loads(z.read("info.json"))["title"], "A film")
        subs_call = FakeYDL.calls[-1][1]
        self.assertEqual((subs_call["subtitleslangs"], subs_call["writesubtitles"]), (["en"], True))

    def test_json_output_for_n8n(self):
        r = self.post(output="json")
        body = r.json()
        self.assertEqual(body["transcript"], "manual")
        names = {f["filename"]: base64.b64decode(f["content_base64"]) for f in body["files"]}
        self.assertTrue(names["transcript.vtt"].startswith(b"WEBVTT"))

    def test_no_subtitles_still_returns_info(self):
        with mock.patch.dict(INFO, {"subtitles": {}, "automatic_captions": {}}):
            r = self.post(output="json")
        self.assertEqual(r.json()["transcript"], "none")
        self.assertEqual([f["filename"] for f in r.json()["files"]], ["info.json"])

    def test_blocked_subtitles_say_why(self):
        yt.cached_video(URL)
        FakeYDL.fail_with = "HTTP Error 429: Too Many Requests"
        r = self.post(output="json")
        self.assertEqual(r.json()["transcript"], "blocked")
        self.assertIn("429", r.json()["note"])

    def test_second_call_does_not_refetch(self):
        self.post()
        before = len(FakeYDL.calls)
        self.post()
        self.assertEqual(len(FakeYDL.calls), before)

    def test_only_youtube(self):
        r = self.client.post("/transcript", json={"video_url": "https://www.instagram.com/reel/X/"},
                             headers=HEADERS)
        self.assertEqual(r.status_code, 422)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2:** Run `.venv/bin/python -m unittest tests.test_transcript -v`.
  Expected: AttributeError / 404.
- [ ] **Step 3: Implement.** Append to `youtube_service.py`:

```python
def pick_subtitle_track(info: dict) -> Optional[tuple[str, bool]]:
    """(language, is_auto) of the English track to fetch. People-written subtitles beat YouTube's."""
    manual = info.get("subtitle_langs") or []
    for lang in ("en", "en-US", "en-GB", *manual):
        if lang in manual:
            return lang, False
    auto = info.get("auto_caption_langs") or []
    for lang in ("en-orig", "en"):  # en-orig is the speech itself; plain en can be a machine translation
        if lang in auto:
            return lang, True
    return None


def cached_transcript(url: str) -> tuple[Optional[str], str, str]:
    """(path of transcript.vtt or None, source, note). source: manual | auto | none | blocked."""
    folder = os.path.dirname(cached_video(url))
    with open(os.path.join(folder, "info.json")) as f:
        track = pick_subtitle_track(json.load(f))
    if track is None:
        return None, "none", "YouTube has no English subtitles for this video."
    lang, auto = track
    source = "auto" if auto else "manual"
    vtt = os.path.join(folder, "transcript.vtt")
    with _lock_for(youtube_id(url)):
        if os.path.exists(vtt):
            return vtt, source, ""
        try:
            _run_ydl(canonical_url(url), {
                "skip_download": True, "writesubtitles": not auto, "writeautomaticsub": auto,
                "subtitleslangs": [lang], "subtitlesformat": "vtt",
                "outtmpl": os.path.join(folder, "subs.%(ext)s")}, "subtitles")
        except HTTPException as e:
            return None, "blocked", e.detail
        got = os.path.join(folder, f"subs.{lang}.vtt")
        if not os.path.exists(got):
            return None, "blocked", "yt-dlp reported success but wrote no subtitle file."
        os.replace(got, vtt)
    return vtt, source, ""


class TranscriptRequest(BaseModel):
    video_url: str
    output: Literal["zip", "json"] = "zip"


@router.post("/transcript")
def transcript(req: TranscriptRequest):
    """info.json plus transcript.vtt when YouTube has English subtitles. Never fails for missing ones."""
    vid = youtube_id(req.video_url)
    if not vid:
        raise HTTPException(422, "/transcript takes YouTube video links only")
    vtt, source, note = cached_transcript(req.video_url)
    files = [("info.json", os.path.join(video_dir(vid), "info.json"))]
    if vtt:
        files.append(("transcript.vtt", vtt))
    headers = {"X-Transcript": source}
    if req.output == "json":
        return JSONResponse({"transcript": source, "note": note, "files": [
            {"filename": name, "content_base64": base64.b64encode(open(path, "rb").read()).decode()}
            for name, path in files]}, headers=headers)
    final = os.path.join(tempfile.gettempdir(), f"transcript_{uuid.uuid4().hex}.zip")
    with zipfile.ZipFile(final, "w", zipfile.ZIP_DEFLATED) as z:
        for name, path in files:
            z.write(path, name)
        if note:
            z.writestr("note.txt", note + "\n")
    return FileResponse(final, media_type="application/zip", filename="transcript.zip", headers=headers,
                        background=BackgroundTask(lambda: os.remove(final)))
```

  In `main.py`, after the analyze router line, add:

  ```python
  app.include_router(youtube_service.router, dependencies=[Depends(check_api_key)])
  ```

- [ ] **Step 4:** Run the full suite. Expected: all OK.
- [ ] **Step 5:** Commit `feat: POST /transcript returns info.json and English subtitles`.

### Task 5: Scene-change frames

**Files:**
- Create: `scene_frames.py`
- Modify: `main.py` (`FrameRequest`, `/frames`, limits)
- Test: `tests/test_scene_frames.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2:** Run `.venv/bin/python -m unittest tests.test_scene_frames -v`.
  Expected: ImportError (`scene_frames`).
- [ ] **Step 3: Implement.** Create `scene_frames.py`:

```python
"""Frames at scene changes, for long videos where a fixed interval gives hundreds of near-duplicates."""
import os
import re
import subprocess

from fastapi import HTTPException

_PTS = re.compile(r"pts_time:\s*([\d.]+)")


def select_expr(threshold: float, min_gap: float, max_gap: float) -> str:
    # The first frame always counts. After that a frame counts when the picture
    # changed and min_gap has passed since the last pick, or when max_gap passed
    # with no change at all, so talking-head stretches still get a frame now and then.
    return ("select='if(isnan(prev_selected_t),1,"
            f"gt(gte(t-prev_selected_t,{max_gap})+gt(scene,{threshold})*gte(t-prev_selected_t,{min_gap}),0))'")


def extract_scene_frames(source: str, *, start: float, threshold: float, min_gap: float, max_gap: float,
                         max_frames: int, width, quality: int, workdir: str, timeout: int
                         ) -> list[tuple[str, float]]:
    """[(jpg path, seconds into the video)] in order."""
    # 2 fps before scoring: the scene score then compares frames 0.5 s apart,
    # which makes a 30-minute video cheap and still catches every cut that lasts.
    vf = f"fps=2,{select_expr(threshold, min_gap, max_gap)},showinfo"
    if width:
        vf += f",scale={width}:-2"
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "info", "-ss", str(start), "-i", source,
           "-vf", vf, "-fps_mode", "vfr", "-frames:v", str(max_frames), "-qscale:v", str(quality),
           os.path.join(workdir, "frame_%04d.jpg")]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "ffmpeg timed out finding scene changes (raise FFMPEG_SCENE_TIMEOUT)")
    paths = sorted(os.path.join(workdir, f) for f in os.listdir(workdir) if f.startswith("frame_"))
    if not paths:
        raise HTTPException(422, f"No frames extracted: {out.stderr.strip()[-300:]}")
    times = [start + float(t) for t in _PTS.findall(out.stderr)]
    return list(zip(paths, times))
```

- [ ] **Step 4: `main.py` changes.**
  - Add `from scene_frames import extract_scene_frames`.
  - Next to `HARD_MAX_FRAMES`, add:

    ```python
    SCENE_MAX_FRAMES = int(os.getenv("SCENE_MAX_FRAMES", "600"))
    # Scene mode decodes the whole video; 30 minutes of 720p takes a few minutes on Railway's CPU.
    FFMPEG_SCENE_TIMEOUT = int(os.getenv("FFMPEG_SCENE_TIMEOUT", "1200"))
    ```

  - In `FrameRequest`:
    - change `max_frames` to `Field(60, ge=1, le=max(HARD_MAX_FRAMES, SCENE_MAX_FRAMES))`
    - add these fields:

      ```python
      mode: Literal["interval", "scene"] = "interval"
      scene_threshold: float = Field(0.3, gt=0, lt=1)
      min_gap: float = Field(3.0, ge=0.5, le=600)
      max_gap: float = Field(60.0, ge=1, le=3600)
      ```

    - update the `video_url` description to "Direct .mp4 URL, instagram.com or YouTube link".
  - In `frames()`, replace the lines from `direct = resolve_url(...)` through
    `timestamps = [...]` with:

    ```python
    limit = SCENE_MAX_FRAMES if req.mode == "scene" else HARD_MAX_FRAMES
    if req.max_frames > limit:
        raise HTTPException(422, f"max_frames is at most {limit} in {req.mode} mode")
    direct = resolve_url(req.video_url)
    if req.mode == "scene":
        picked = extract_scene_frames(
            direct, start=req.start, threshold=req.scene_threshold, min_gap=req.min_gap,
            max_gap=req.max_gap, max_frames=req.max_frames, width=req.width,
            quality=req.quality, workdir=workdir, timeout=FFMPEG_SCENE_TIMEOUT)
        paths = [p for p, _ in picked]
        timestamps = [round(t, 3) for _, t in picked]
    else:
        paths = extract_frames_from(direct, req, workdir)
        timestamps = [round(req.start + i * req.interval, 3) for i in range(len(paths))]
    ```

  - In the JSON payload, add `"mode": req.mode,` next to `"interval"`.
  - Set `version="3.5.0"` in `FastAPI(...)`.
  - Update the module docstring's endpoint list to include `/transcript` and
    scene mode.

- [ ] **Step 5:** Run the full suite. Expected: all OK. If
  `test_one_frame_per_scene` finds fewer scenes, print the `scene` scores
  with `showinfo`. Then swap the too-similar test sources in `four_scenes`
  rather than lowering the threshold.
- [ ] **Step 6:** Commit `feat: /frames scene mode picks frames at scene changes`.

### Task 6: Deno and yt-dlp's JavaScript challenge solver in the image

**Files:** Modify `Dockerfile`, `requirements.txt`

- [ ] **Step 1:** Change the `requirements.txt` line `yt-dlp` to
  `yt-dlp[default]`. That pulls in `yt-dlp-ejs`, the YouTube challenge
  scripts.
- [ ] **Step 2:** In `Dockerfile`, after `FROM`:

```dockerfile
# yt-dlp solves YouTube's JavaScript challenges with Deno; without it most formats are missing.
COPY --from=denoland/deno:bin /deno /usr/local/bin/deno
```

- [ ] **Step 3:** Update the local venv with
  `.venv/bin/pip install -U "yt-dlp[default]"`, then run the full suite.
  Expected: OK.
- [ ] **Step 4:** If `docker` is installed, run `docker build -t reel-frames .`
  and `docker run --rm reel-frames deno --version`. Expected: a version
  line. Without Docker, the Railway build log in Task 8 is the check.
- [ ] **Step 5:** Commit `build: add Deno and yt-dlp[default] for YouTube downloads`.

### Task 7: Docs for the service

**Files:** `.env.example`, `README.md`, `CHANGELOG.md`,
`docs/features/2026-09-28-youtube-to-mindmap.md`, `docs/features/INDEX.md`,
`~/Developer/README.md` (the reel-frames row)

- [ ] **Step 1:** Add to `.env.example` under `YTDLP_PROXY=`:

  ```
  YT_COOKIES_FILE=
  YT_COOKIES_B64=
  YT_CACHE_SECONDS=3600
  SCENE_MAX_FRAMES=600
  FFMPEG_SCENE_TIMEOUT=1200
  ```

- [ ] **Step 2:** README changes:
  - **Intro:** say reel or YouTube link.
  - **API table:** add the `/transcript` row. Document `/frames`
    `mode: "scene"` with `scene_threshold`, `min_gap` and `max_gap`.
  - **New section, "How YouTube videos are fetched":**
    - the one cached download per video (720p) and `YT_CACHE_SECONDS`
    - Shorts versus full videos
    - the bot check and the fixes in order (`YT_COOKIES_B64` from a
      throwaway Google account, then `YTDLP_PROXY`)
    - Deno
  - **Env vars table:** the five new variables.
  - **New subsection, "Getting `YT_COOKIES_B64`":**
    - export cookies.txt for youtube.com with a cookies.txt browser
      extension while logged in to a throwaway account
    - run `base64 -i cookies.txt | pbcopy`
    - paste the result into Railway
- [ ] **Step 3:** CHANGELOG `## [3.5.0] - 2026-09-28`, listing:
  - Added: YouTube links on every endpoint, the cached download, `/transcript`,
    scene mode, the new env vars
  - Changed: `yt-dlp[default]` and Deno in the image
  - Each entry links its commit, like 3.4.0 does
- [ ] **Step 4:** Feature doc (Status / Problem / Goals / Non-goals /
  Approach / Follow-ups), summarising the spec plus what the build found.
  Add its line to the top of `INDEX.md`.
- [ ] **Step 5:** `~/Developer/README.md` reel-frames row: "reel or YouTube
  link → frames, audio, video, transcript and scene frames for the n8n
  workflows."
- [ ] **Step 6:** Commit `docs: YouTube support, /transcript and scene frames`.
  Then commit again with the CHANGELOG commit links filled in:
  `docs: link 3.5.0 changelog entries`.

### Task 8: Deploy and live check

- [ ] **Step 1:** Run `curl -s https://reel-frames-production.up.railway.app/health`.
  Note the version: it shows whether the 11 unpushed commits (3.4.0) are
  already live.
- [ ] **Step 2:** Tell the user that the push ships everything since
  `origin/main`, then run `git push origin main`. Railway deploys from GitHub.
- [ ] **Step 3:** Poll `/health` until it shows `"version":"3.5.0"`.
- [ ] **Step 4:** Live YouTube check:

  ```bash
  curl -s -X POST https://reel-frames-production.up.railway.app/transcript \
    -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
    -d '{"video_url":"https://www.youtube.com/watch?v=reFzEtCG_m8","output":"json"}' \
    | python3 -c 'import sys,json;b=json.load(sys.stdin);print(b.get("transcript"),b.get("note","")[:200],[f["filename"] for f in b.get("files",[])])'
  ```

  The key is read from the n8n node and passed as `KEY` without being
  echoed. Expected: `manual`/`auto` plus the file list, or a 422 naming the
  bot check.
- [ ] **Step 5:** If there's a bot check, stop and tell the user. They need to
  set `YT_COOKIES_B64` in Railway (README section). Continue with Task 10
  using a local download meanwhile.

### Task 9: n8n workflow: YouTube branch and fixes

Use the n8n MCP. First `get_workflow_sdk_reference`, then
`get_workflow_details` for `B56j7gqfSRCOiYdy`. Edit the SDK code, then
`validate_workflow`, then `update_workflow`.

- [ ] **Step 1: Build Reel Items.** Replace the code with:

```js
const run = $input.first().json;
const runStamp = $now.toFormat('yyyy-MM-dd_HHmm');
const total = run.urls.length;
const ytId = u => (u.match(/(?:youtube\.com\/(?:watch\?(?:[^#]*&)?v=|shorts\/|live\/|embed\/)|youtu\.be\/)([A-Za-z0-9_-]{11})/) || [])[1];

return run.urls.map((reel_url, i) => {
  const index = i + 1;
  const yt = ytId(reel_url);
  // Shorts are reels in everything but name; only full videos need the long-video path.
  const kind = yt && !/youtube\.com\/shorts\//.test(reel_url) ? 'youtube' : 'reel';
  const ig = reel_url.match(/\/(?:reels?|p|tv)\/([A-Za-z0-9_-]+)/);
  const reel_code = yt ? 'yt-' + yt : (ig ? ig[1] : 'reel' + String(index).padStart(2, '0'));
  return { json: {
    reel_url, reel_code, kind, index, total,
    interval: run.interval, chat_id: run.chat_id, source: run.source,
    folder_name: runStamp + '_' + String(index).padStart(2, '0') + '_' + reel_code,
  } };
});
```

- [ ] **Step 2: "Is YouTube?" IF node** between Create Frames Folder and
  Download Reel. The condition is
  `{{ $('Loop Over Reels').item.json.kind }}` equals `youtube`.
  - **false** goes to the existing Download Reel, unchanged.
  - **true** goes to the new chain below. Every HTTP node in it has
    `onError: continueErrorOutput`, with the error output going to Mark
    Failure.

  | Node | Type / settings |
  |---|---|
  | YT Download | HTTP POST `/download`, body `{video_url}`, response: file, timeout 1200000 |
  | YT Upload Video | Google Drive upload, name `video.mp4`, folder `={{ $('Create Reel Folder').item.json.id }}` |
  | YT Transcript | HTTP POST `/transcript`, body `{video_url, output:'json'}`, timeout 600000 |
  | YT Transcript to Files | Code (below) |
  | YT Upload Transcript | Google Drive upload, name `={{ $json.new_name }}`, same folder |
  | YT Frames | HTTP POST `/frames`, body `{video_url, mode:'scene', min_gap:4, max_frames:400, width:720, quality:3, output:'json'}`, timeout 1200000, **executeOnce: true** (it follows a 2-item upload) |
  | → existing **Frames to Files** → **Upload Frames to Drive** | reused as is |

  YT Transcript to Files:

```js
const res = $input.first().json;
const out = [];
for (const f of res.files || []) {
  const mime = f.filename.endsWith('.json') ? 'application/json' : 'text/vtt';
  out.push({
    json: { new_name: f.filename, transcript: res.transcript, note: res.note || '' },
    binary: { data: await this.helpers.prepareBinaryData(Buffer.from(f.content_base64, 'base64'), f.filename, mime) },
    pairedItem: { item: 0 },
  });
}
if (out.length === 0) throw new Error('Transcript service returned no files');
return out;
```

- [ ] **Step 3: Ready message.** Between Upload Frames to Drive and Loop Over
  Reels, add an IF node called "YouTube via Telegram?". It checks two
  conditions (AND):
  - `$('Loop Over Reels').item.json.kind == 'youtube'`
  - `$('Loop Over Reels').item.json.source == 'telegram'`

  **true** goes to a new Telegram node, "Ready for Breakdown" (Reel Frames
  bot credential, **executeOnce: true**), then to Loop Over Reels. **false**
  goes to Loop Over Reels. The message text:

```
={{ '✅ Ready for breakdown: ' + $('Loop Over Reels').item.json.reel_url
  + '\nFolder: https://drive.google.com/drive/folders/' + $('Create Reel Folder').item.json.id
  + '\nTranscript: ' + $('YT Transcript').item.json.transcript
  + ($('YT Transcript').item.json.note ? ' (' + $('YT Transcript').item.json.note.slice(0, 200) + ')' : '')
  + '\n\nPaste the folder link into Claude Code to build the mind map.' }}
```

- [ ] **Step 4: Copy.**
  - Ask Frame Interval: add a line saying full YouTube videos take frames at
    scene changes, so the interval applies to reels and Shorts.
  - No URLs Message: "reel or YouTube links".
  - Form: title "Reel / YouTube → Frames to Drive", and the placeholder
    shows both link kinds.
  - Sticky note C: describe the YouTube branch.
  - Workflow description: mention YouTube.
- [ ] **Step 5: Fixes.** Set Report Reel Failure's credential to the trigger's
  bot (`dVePHggItpQwoJXV`, "Reel Frames to Drive Bot 28/9/26").
  - **Moving the API key:** ask the user to create an n8n **Header Auth**
    credential named "Reel Frames API" (name `X-API-Key`, value their key).
    The MCP has no tool to create credentials.
  - Once it exists (check `list_credentials`), switch every reel-frames HTTP
    node to `authentication: genericCredentialType` / `httpHeaderAuth` and
    remove the typed header.
  - Until then, the header stays and this is reported as pending.
- [ ] **Step 6:** `validate_workflow`, then `update_workflow`, then
  `publish_workflow` if the update leaves a draft.
- [ ] **Step 7: Regression test (form, one reel).** Run `execute_workflow`
  with trigger "Reel URL Form", formData `{reel_urls: "<a reel from the last
  execution>", frame_interval: "2"}`. Then `get_workflow_execution` should
  show mp4 plus frames uploaded, just as before.
- [ ] **Step 8: YouTube test (form).** Same, with
  `https://www.youtube.com/watch?v=reFzEtCG_m8`. Expected: the Drive folder
  `…_yt-reFzEtCG_m8` holds `video.mp4`, `info.json`, `transcript.vtt` (or
  none/blocked, as reported) and `frames/` with 100–400 frames. Record the
  time each node took.
- [ ] **Step 9:** Tell the user to send the YouTube link to the Telegram bot
  and confirm the "Ready for breakdown" message arrives.

### Tasks 10–13: the FigJam toolkit (revised 2026-09-28)

> Tasks 10–12 originally described a Whimsical skill with an HTML atlas. After
> live canvas tests the user chose FigJam, and asked for a deterministic
> pipeline with Sonnet only at judgment steps and minimum-to-medium tokens
> (spec, "Architecture"). The toolkit is real code with tests, so it is its
> own project: `~/Developer/ai-media/video-mindmap` (own git repo, README,
> CHANGELOG), plus a thin skillbook skill that points to it.

**Layout of `video-mindmap/`**

| File | Responsibility |
|---|---|
| `vmm/transcript.py` | `parse_vtt`, `paragraphs`, `render_markdown`: dedupe rolling auto-captions, timestamped paragraphs under chapter headings |
| `vmm/mapfile.py` | `load`, `save`, `validate`, `next_code`, `add_child`, `code_key`, `parent_of` for the map.json in the spec |
| `vmm/frames.py` | `candidate_times`, `sharpness` (variance of a Laplacian over the grey image), `pick_frames(video, map, out)` |
| `vmm/layout.py` | `layout(map) -> {code: Box}`: root on the left, each depth one column to the right, a node's children stacked vertically and centred on it. Every video node owns a row of node + frame + note |
| `vmm/render.py` | `draw_scripts(map, layout, uploads) -> [js]`: one fixed renderer function plus a compact data array, split into chunks of at most 40 nodes |
| `vmm/figjam.py` | `post_uploads(urls, files) -> {file: node_id}` (multipart POST, the `upload_assets` contract) and `record(map, returned_ids)` |
| `vmm/cli.py` | `vmm prepare / validate / frames / layout / render / upload / record / context / add` |
| `prompts/structure.md`, `prompts/expand.md` | The only model instructions, each ending in the exact JSON shape to return |
| `transcribe.py` | faster-whisper fallback (PEP 723, `uv run`) |
| `tests/` | stdlib unittest; ffmpeg-dependent tests skip without ffmpeg |

Dependencies: Python 3.12, `pillow`, `numpy` (frames only), ffmpeg on
`PATH`. `vmm prepare` uses `uvx --from "yt-dlp[default]" yt-dlp --js-runtimes node`
when there is no Drive folder.

#### Task 10: Deterministic core (TDD, one commit per module)

Each module gets its tests first. Run with `.venv/bin/python -m unittest discover -s tests`.

- **transcript:** made-up rolling auto-captions give each line once, with
  its first timestamp. `&amp;` and inline `<c>` tags are cleaned. Paragraphs
  break at 20 s and at chapter starts. Both the service's `info.json`
  (`start`) and raw yt-dlp info (`start_time`) work. No chapters gives one
  "Full video" section.
- **mapfile:** a clean sample validates. Each of these is caught:
  - a duplicate code
  - a missing parent
  - a parent that doesn't match the code
  - a quote over 15 words
  - a note over 25 words
  - a video node without a time
  - a research node without refs
  - a time beyond the video's duration

  Also: `next_code` gives `3` under root and `1.2` after `1.1`, and
  `add_child` never renumbers existing nodes.
- **frames:** `candidate_times(t)` is `[t, t+2, t+4]`, clamped to the
  duration. On a synthetic clip, `sharpness` ranks a frame above a
  gaussian-blurred copy of itself. `pick_frames` writes exactly one
  `frames/<code>.jpg` per video node with a time, 960 px wide, and sets
  `node["frame"]`.
- **layout:** for sample trees of 1, 5 and 60 nodes:
  - no two boxes overlap (node, frame and note boxes all count)
  - every child's x is greater than its parent's
  - siblings keep code order top to bottom
  - the parent is centred on its children's span
  - the same input gives the same output
- **render:** the generated JS
  - contains the data as JSON that parses back to the input rows
  - is under 50,000 characters per chunk
  - puts each node's code and title in its label
  - puts a `https://www.youtube.com/watch?v=<id>&t=<s>s` link on the time
    line
  - references every uploaded frame's node id exactly once
  - makes connectors root→node, node→frame and frame→note

  The renderer is plain Plugin API calls (`createShapeWithText`,
  `createSticky`, `createConnector`, `setRangeHyperlink`), and it returns
  `{code: {node, note, connectors}}` ids.
- **figjam:** `post_uploads` is tested against a local stub HTTP server. It
  does a multipart POST with the file name as the layer name and parses
  `placedOnNodeId`. `record` merges the returned ids into `figjam_ids`, and
  a second draw skips nodes that already have ids.

#### Task 11: CLI, prompts, skill

- `vmm` subcommands wire the modules and print one short line each. `vmm
  prepare <drive-folder-files | youtube-url>` writes `WORK/info.json`,
  `transcript.vtt`, `transcript.md` and `video.mp4`.
- `prompts/structure.md` tells the model:
  - **Input:** `transcript.md` and the video info.
  - **Output:** only a JSON array of nodes `{code, parent, title, note,
    times, quote}`.
  - **Rules:** level 1 = the real phases of her workflow (merge or split
    chapters), level 2 = steps, level 3 = techniques, tools, prompt patterns
    and problems she solved; 40–90 nodes for 30 minutes; every node has the
    time where it's shown; notes paraphrase in at most 25 words; at most one
    quote per node, under 15 words; no invented facts.
- `prompts/expand.md` is the same shape for the children of one node. It
  takes the `vmm context` window, and `source: "research"` with `refs` when
  the user asks for research.
- `~/.skillbook/skills/video-mindmap/SKILL.md` lists the steps and marks the
  two Sonnet steps. Those run as `Agent(model="sonnet")` with the prompt file
  as the whole brief. Then add it with skillbook and commit in the library.

#### Task 12: End-to-end on `reFzEtCG_m8`

Run on the new FigJam board in "My Workspace":

1. prepare
2. Sonnet structure
3. validate
4. frames
5. layout
6. `upload_assets` + `vmm upload`
7. render
8. Sonnet draw
9. record

Check:
- every node has a code, a frame, a note and a working timestamp link
- a screenshot of each top-level branch shows no overlaps
- record the tokens each Sonnet step used and the wall-clock time per step

#### Task 13: Expand, docs, ship

- Expand one node from the video and one with research. Existing nodes must
  move (same ids), not be recreated.
- Toolkit docs:
  - README: setup, every command, the pipeline diagram, the token budget
  - CHANGELOG
  - `docs/features/…` + INDEX
- Add the project to `~/Developer/README.md`, to the project list in
  `~/Developer/ai-media/CLAUDE.md`, and to `developer.code-workspace`.

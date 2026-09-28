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

### Task 10: Skill scripts (tests first)

Skill directory: `SKILL="$HOME/.skillbook/skills/video-mindmap"`. The
scripts are stdlib-only, except `frames_at.py` (Pillow) and `transcribe.py`
(faster-whisper), which use PEP 723 headers so `uv run` supplies their
dependencies. Tests run with
`python3 -m unittest discover -s "$SKILL/tests"`.

- [ ] **Step 1: `tests/test_mapfile.py`**

```python
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import mapfile  # noqa: E402


def sample():
    return {"video": {"id": "reFzEtCG_m8", "title": "A film"}, "whimsical": {}, "atlas": {},
            "nodes": [
                {"code": "0", "parent": None, "title": "A film", "source": "video", "times": []},
                {"code": "1", "parent": "0", "title": "Story", "source": "video", "times": [143]},
                {"code": "1.1", "parent": "1", "title": "Storyboards", "source": "video", "times": [180]},
                {"code": "2", "parent": "0", "title": "Characters", "source": "video", "times": [303]},
            ]}


class Validate(unittest.TestCase):
    def test_clean_map(self):
        self.assertEqual(mapfile.validate(sample()), [])

    def test_catches_each_rule(self):
        m = sample()
        m["nodes"] += [
            {"code": "1.1", "parent": "1", "title": "dup", "source": "video", "times": [1]},
            {"code": "3.1", "parent": "3", "title": "orphan", "source": "video", "times": [1]},
            {"code": "2.1", "parent": "2", "title": "q", "source": "video", "times": [1],
             "quote": " ".join(["word"] * 16)},
            {"code": "2.2", "parent": "2", "title": "r", "source": "research"},
            {"code": "2.3", "parent": "2", "title": "t", "source": "video"},
        ]
        errors = "\n".join(mapfile.validate(m))
        for needle in ("1.1: duplicate", "3.1: parent 3 is missing", "2.1: quote",
                       "2.2: research node has no source link", "2.3: video node has no timestamp"):
            self.assertIn(needle, errors)


class Codes(unittest.TestCase):
    def test_next_code(self):
        self.assertEqual(mapfile.next_code(sample(), "0"), "3")
        self.assertEqual(mapfile.next_code(sample(), "1"), "1.2")
        self.assertEqual(mapfile.next_code(sample(), "2"), "2.1")

    def test_add_child_keeps_codes_stable(self):
        m = sample()
        node = mapfile.add_child(m, "1", "Shot list", source="research", refs=["https://example.com"])
        self.assertEqual((node["code"], node["parent"]), ("1.2", "1"))
        self.assertEqual(mapfile.validate(m), [])


class Reconcile(unittest.TestCase):
    OUTLINE = ("- A film\n"
               "  - 1 Story beats · ▶ 2:23\n"
               "    - 1.1 Storyboards · [▶ 3:00](https://youtu.be/x)\n"
               "    - Thumbnail sketches\n"
               "  - 2 Characters\n")

    def test_rename_and_new_user_node(self):
        m = sample()
        changes = mapfile.reconcile(m, mapfile.parse_outline(self.OUTLINE))
        by = {n["code"]: n for n in m["nodes"]}
        self.assertEqual(by["1"]["title"], "Story beats")
        self.assertEqual((by["1.2"]["title"], by["1.2"]["source"]), ("Thumbnail sketches", "user"))
        self.assertTrue(any("1.2" in c for c in changes))

    def test_missing_nodes_are_reported_not_deleted(self):
        m = sample()
        changes = mapfile.reconcile(m, mapfile.parse_outline("- A film\n  - 1 Story\n"))
        self.assertIn("2", {n["code"] for n in m["nodes"]})
        self.assertTrue(any(c.startswith("2:") and "not in Whimsical" in c for c in changes))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: `scripts/mapfile.py`**

```python
#!/usr/bin/env python3
"""map.json, the single source of truth for one video's mind map.

  python3 mapfile.py validate MAP
  python3 mapfile.py next-code MAP PARENT
  python3 mapfile.py add MAP --parent 3.2 --title T [--summary S] [--source research]
                         [--time 982] [--quote Q] [--ref URL]
  python3 mapfile.py reconcile MAP OUTLINE_FILE     # pull hand edits made in Whimsical
  python3 mapfile.py set MAP whimsical.url VALUE     # whimsical.file_id, atlas.url, ...
"""
import argparse
import json
import re
import sys

SOURCES = {"video", "research", "user"}
MAX_QUOTE_WORDS = 15   # quotes stay short; the breakdown paraphrases the rest
MAX_FRAMES = 2         # the atlas publish is capped at 255 files
CODE = re.compile(r"^(0|[1-9]\d*(\.[1-9]\d*)*)$")
BULLET = re.compile(r"^(?P<indent>\s*)[-*]\s+(?P<text>.+?)\s*$")
LABEL = re.compile(r"^(?:🔍\s*)?(?P<code>[1-9]\d*(?:\.[1-9]\d*)*)\s+(?P<title>.+)$")


def code_key(code: str) -> tuple:
    return tuple(int(p) for p in code.split("."))


def parent_of(code: str):
    if code == "0":
        return None
    return code.rsplit(".", 1)[0] if "." in code else "0"


def load(path):
    with open(path) as f:
        return json.load(f)


def save(m, path):
    m["nodes"].sort(key=lambda n: code_key(n["code"]))
    with open(path, "w") as f:
        json.dump(m, f, indent=2, ensure_ascii=False)
        f.write("\n")


def validate(m) -> list[str]:
    errors, seen = [], set()
    for n in m["nodes"]:
        c = n.get("code", "")
        if not CODE.match(c):
            errors.append(f"{c!r}: not a valid code")
            continue
        if c in seen:
            errors.append(f"{c}: duplicate code")
        seen.add(c)
        if n.get("parent") != parent_of(c):
            errors.append(f"{c}: parent should be {parent_of(c)}, is {n.get('parent')}")
        if n.get("source") not in SOURCES:
            errors.append(f"{c}: source must be one of {sorted(SOURCES)}")
        if not n.get("title"):
            errors.append(f"{c}: no title")
        if len((n.get("quote") or "").split()) > MAX_QUOTE_WORDS:
            errors.append(f"{c}: quote is over {MAX_QUOTE_WORDS} words")
        if n.get("source") == "video" and c != "0" and not n.get("times"):
            errors.append(f"{c}: video node has no timestamp")
        if n.get("source") == "research" and not n.get("refs"):
            errors.append(f"{c}: research node has no source link")
        if len(n.get("frames") or []) > MAX_FRAMES:
            errors.append(f"{c}: more than {MAX_FRAMES} frames")
    for c in sorted(seen - {"0"}, key=code_key):
        if parent_of(c) not in seen:
            errors.append(f"{c}: parent {parent_of(c)} is missing")
    if "0" not in seen:
        errors.append("root node 0 is missing")
    return errors


def next_code(m, parent: str) -> str:
    taken = [code_key(n["code"])[-1] for n in m["nodes"] if n.get("parent") == parent]
    number = max(taken, default=0) + 1
    return str(number) if parent == "0" else f"{parent}.{number}"


def add_child(m, parent, title, summary="", source="video", times=(), quote="", refs=()):
    if parent not in {n["code"] for n in m["nodes"]}:
        raise ValueError(f"no node {parent}")
    node = {"code": next_code(m, parent), "parent": parent, "title": title, "summary": summary,
            "source": source, "times": list(times), "quote": quote, "frames": [], "refs": list(refs)}
    m["nodes"].append(node)
    return node


def _strip_time(text: str) -> str:
    for marker in (" · [▶", " · ▶"):
        text = text.split(marker)[0]
    return text.strip()


def parse_outline(text: str) -> list[dict]:
    """Indented bullets (to_outline.py's format) → [{depth, code, title}]; code is None for new nodes."""
    items = []
    for line in text.splitlines():
        b = BULLET.match(line)
        if not b:
            continue
        depth = len(b["indent"].expandtabs(2)) // 2
        label = _strip_time(b["text"])
        lab = LABEL.match(label)
        items.append({"depth": depth, "code": lab["code"] if lab else None,
                      "title": (lab["title"] if lab else label.removeprefix("🔍").strip()).strip()})
    return items


def reconcile(m, items) -> list[str]:
    """Bring hand edits from Whimsical into map.json. Renames and new nodes apply; deletions are only reported."""
    by_code = {n["code"]: n for n in m["nodes"]}
    changes, stack, present = [], [], {"0"}
    for it in items:
        while stack and stack[-1][0] >= it["depth"]:
            stack.pop()
        if not stack and it["depth"] == 0 and it["code"] is None:
            stack.append((0, "0"))  # the root node carries the video title, not a code
            continue
        parent = stack[-1][1] if stack else "0"
        node = by_code.get(it["code"]) if it["code"] else None
        if node:
            if node["title"] != it["title"]:
                changes.append(f"{node['code']}: renamed '{node['title']}' → '{it['title']}'")
                node["title"] = it["title"]
        else:
            node = add_child(m, parent, it["title"], source="user")
            by_code[node["code"]] = node
            changes.append(f"{node['code']}: new node from Whimsical '{it['title']}' under {parent}")
        present.add(node["code"])
        stack.append((it["depth"], node["code"]))
    for code in sorted(set(by_code) - present, key=code_key):
        changes.append(f"{code}: not in Whimsical any more (kept in map.json; delete by hand if intended)")
    return changes


def _set(m, dotted, value):
    head, key = dotted.split(".", 1)
    m.setdefault(head, {})[key] = value


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate").add_argument("map")
    nc = sub.add_parser("next-code")
    nc.add_argument("map")
    nc.add_argument("parent")
    add = sub.add_parser("add")
    add.add_argument("map")
    for flag in ("--parent", "--title"):
        add.add_argument(flag, required=True)
    add.add_argument("--summary", default="")
    add.add_argument("--source", default="video", choices=sorted(SOURCES))
    add.add_argument("--time", type=int, action="append", default=[])
    add.add_argument("--quote", default="")
    add.add_argument("--ref", action="append", default=[])
    rc = sub.add_parser("reconcile")
    rc.add_argument("map")
    rc.add_argument("outline")
    st = sub.add_parser("set")
    st.add_argument("map")
    st.add_argument("key")
    st.add_argument("value")
    a = ap.parse_args(argv)

    m = load(a.map)
    if a.cmd == "validate":
        errors = validate(m)
        print("\n".join(errors) or f"ok: {len(m['nodes'])} nodes")
        return 1 if errors else 0
    if a.cmd == "next-code":
        print(next_code(m, a.parent))
        return 0
    if a.cmd == "add":
        node = add_child(m, a.parent, a.title, a.summary, a.source, a.time, a.quote, a.ref)
        print(node["code"])
    elif a.cmd == "reconcile":
        with open(a.outline) as f:
            print("\n".join(reconcile(m, parse_outline(f.read()))) or "no changes")
    elif a.cmd == "set":
        _set(m, a.key, a.value)
    save(m, a.map)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: `tests/test_to_outline.py`**

```python
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import mapfile  # noqa: E402
from to_outline import outline, timestamp  # noqa: E402
from test_mapfile import sample  # noqa: E402


class Outline(unittest.TestCase):
    def test_nesting_codes_and_links(self):
        text = outline(sample())
        self.assertEqual(text.splitlines(), [
            "- A film",
            "  - 1 Story · [▶ 2:23](https://www.youtube.com/watch?v=reFzEtCG_m8&t=143s)",
            "    - 1.1 Storyboards · [▶ 3:00](https://www.youtube.com/watch?v=reFzEtCG_m8&t=180s)",
            "  - 2 Characters · [▶ 5:03](https://www.youtube.com/watch?v=reFzEtCG_m8&t=303s)",
        ])

    def test_plain_links_and_research_marker(self):
        m = sample()
        mapfile.add_child(m, "2", "Turnaround sheets", source="research", refs=["https://example.com"])
        text = outline(m, links="plain")
        self.assertIn("  - 1 Story · ▶ 2:23", text)
        self.assertIn("    - 🔍 2.1 Turnaround sheets", text)

    def test_subtree(self):
        self.assertEqual(outline(sample(), root="1", links="plain").splitlines(),
                         ["- 1 Story · ▶ 2:23", "  - 1.1 Storyboards · ▶ 3:00"])

    def test_round_trip_through_reconcile_changes_nothing(self):
        m = sample()
        self.assertEqual(mapfile.reconcile(m, mapfile.parse_outline(outline(m))), [])

    def test_timestamp(self):
        self.assertEqual((timestamp(59), timestamp(982), timestamp(3725)), ("0:59", "16:22", "1:02:05"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: `scripts/to_outline.py`**

```python
#!/usr/bin/env python3
"""map.json → indented bullet outline for Whimsical's mind map (create, or edit of one branch).

  python3 to_outline.py MAP [--links markdown|plain] [--root CODE]

▶ mm:ss marks a node taken from the video (linked to that second); 🔍 marks added research.
"""
import argparse
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mapfile import code_key, load  # noqa: E402


def timestamp(seconds) -> str:
    s = int(seconds)
    h, rest = divmod(s, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def watch_link(video_id: str, seconds) -> str:
    return f"https://www.youtube.com/watch?v={video_id}&t={int(seconds)}s"


def label(node, video_id, links) -> str:
    if node["code"] == "0":
        return node["title"]
    text = ("🔍 " if node.get("source") == "research" else "") + f"{node['code']} {node['title']}"
    if node.get("times"):
        t = node["times"][0]
        text += (f" · [▶ {timestamp(t)}]({watch_link(video_id, t)})" if links == "markdown"
                 else f" · ▶ {timestamp(t)}")
    return text


def outline(m, links="markdown", root="0") -> str:
    children = defaultdict(list)
    by_code = {}
    for n in m["nodes"]:
        by_code[n["code"]] = n
        children[n.get("parent")].append(n)
    lines = []

    def walk(node, depth):
        lines.append("  " * depth + "- " + label(node, m["video"]["id"], links))
        for child in sorted(children[node["code"]], key=lambda n: code_key(n["code"])):
            walk(child, depth + 1)

    walk(by_code[root], 0)
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("map")
    ap.add_argument("--links", choices=("markdown", "plain"), default="markdown")
    ap.add_argument("--root", default="0")
    a = ap.parse_args()
    sys.stdout.write(outline(load(a.map), a.links, a.root))
```

- [ ] **Step 5: `tests/test_transcript_md.py`** (made-up caption text only)

```python
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from transcript_md import paragraphs, parse_vtt, render  # noqa: E402

AUTO = """WEBVTT
Kind: captions
Language: en

00:00:00.000 --> 00:00:02.000 align:start position:0%
 
hello<00:00:00.500><c> and</c><00:00:01.000><c> welcome</c>

00:00:02.000 --> 00:00:02.010 align:start position:0%
hello and welcome
 

00:00:02.010 --> 00:00:04.000 align:start position:0%
hello and welcome
today<00:00:02.500><c> we</c><c> build</c> &amp; test

00:01:40.000 --> 00:01:42.000
next chapter starts
"""

INFO = {"title": "A film", "channel": "Chan", "webpage_url": "https://youtu.be/x", "duration": 200,
        "chapters": [{"start": 0, "end": 98, "title": "Welcome"}, {"start": 98, "end": 200, "title": "Story"}]}


class Vtt(unittest.TestCase):
    def test_rolling_auto_captions_keep_each_line_once(self):
        self.assertEqual(parse_vtt(AUTO), [(0.0, "hello and welcome"), (2.01, "today we build & test"),
                                           (100.0, "next chapter starts")])

    def test_paragraphs_break_at_chapters(self):
        paras = paragraphs(parse_vtt(AUTO), INFO["chapters"], every=20)
        self.assertEqual([(ch, round(t)) for ch, t, _ in paras], [(0, 0), (1, 100)])

    def test_render(self):
        md = render(parse_vtt(AUTO), INFO)
        self.assertIn("## 0:00 Welcome", md)
        self.assertIn("## 1:38 Story", md)
        self.assertIn("[1:40] next chapter starts", md)

    def test_no_chapters_gives_one_section(self):
        md = render(parse_vtt(AUTO), {**INFO, "chapters": []})
        self.assertIn("## 0:00 Full video", md)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 6: `scripts/transcript_md.py`**

```python
#!/usr/bin/env python3
"""transcript.vtt (+ info.json chapters) → transcript.md: short timestamped paragraphs under chapter headings.

  python3 transcript_md.py TRANSCRIPT.vtt INFO.json > transcript.md

YouTube's auto captions repeat every line while it scrolls; each line is kept once.
Reads the service's info.json and raw yt-dlp info (start_time/end_time) alike.
"""
import html
import json
import os
import re
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from to_outline import timestamp  # noqa: E402

CUE = re.compile(r"^(?:(\d+):)?(\d{2}):(\d{2})\.(\d{3})\s+-->")
TAG = re.compile(r"<[^>]*>")


def parse_vtt(text: str) -> list[tuple[float, str]]:
    lines, recent, start = [], deque(maxlen=3), None
    for raw in text.splitlines():
        cue = CUE.match(raw.strip())
        if cue:
            h, m, s, ms = cue.groups()
            start = int(h or 0) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000
            continue
        if start is None:
            continue  # WEBVTT header block
        line = " ".join(html.unescape(TAG.sub("", raw)).split())
        if line and line not in recent:
            lines.append((round(start, 3), line))
            recent.append(line)
    return lines


def _chapters(info) -> list[dict]:
    chapters = [{"start": c.get("start", c.get("start_time")) or 0, "title": c.get("title") or ""}
                for c in info.get("chapters") or []]
    return chapters or [{"start": 0, "title": "Full video"}]


def paragraphs(lines, chapters, every=20) -> list[tuple[int, float, str]]:
    """[(chapter index, start seconds, text)]; a new paragraph every ~`every` s and at each chapter."""
    starts = [c["start"] for c in chapters]
    out = []
    for t, text in lines:
        ch = max((i for i, s in enumerate(starts) if s <= t), default=0)
        if out and out[-1][0] == ch and t - out[-1][1] < every:
            out[-1] = (ch, out[-1][1], out[-1][2] + " " + text)
        else:
            out.append((ch, t, text))
    return out


def render(lines, info, every=20) -> str:
    chapters = _chapters(info)
    head = [f"# {info.get('title', '')}", "",
            f"{info.get('channel', '')} · {info.get('webpage_url', '')} · {timestamp(info.get('duration') or 0)}"]
    body, current = [], None
    for ch, t, text in paragraphs(lines, chapters, every):
        if ch != current:
            body += ["", f"## {timestamp(chapters[ch]['start'])} {chapters[ch]['title']}", ""]
            current = ch
        body.append(f"[{timestamp(t)}] {text}")
    return "\n".join(head + body) + "\n"


if __name__ == "__main__":
    with open(sys.argv[1]) as f:
        vtt = f.read()
    with open(sys.argv[2]) as f:
        info = json.load(f)
    sys.stdout.write(render(parse_vtt(vtt), info))
```

- [ ] **Step 7: `tests/test_render_atlas.py`**

```python
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from render_atlas import render  # noqa: E402
from test_mapfile import sample  # noqa: E402


class Atlas(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.frames = os.path.join(self.tmp.name, "candidates")
        os.makedirs(self.frames)
        open(os.path.join(self.frames, "1_143_b.jpg"), "wb").write(b"jpg")
        self.out = os.path.join(self.tmp.name, "atlas")

    def tearDown(self):
        self.tmp.cleanup()

    def payload(self):
        page = open(os.path.join(self.out, "index.html")).read()
        start = page.index('<script type="application/json" id="data">') + len(
            '<script type="application/json" id="data">')
        return page, json.loads(page[start:page.index("</script>", start)])

    def test_one_card_per_node_and_frames_copied(self):
        m = sample()
        m["nodes"][1]["frames"] = ["1_143_b.jpg"]
        stats = render(m, self.frames, self.out)
        _, data = self.payload()
        self.assertEqual([n["code"] for n in data["nodes"]], ["0", "1", "1.1", "2"])
        self.assertEqual(data["nodes"][1]["frames"], ["frames/1_143_b.jpg"])
        self.assertEqual(data["nodes"][1]["times"][0]["label"], "2:23")
        self.assertTrue(os.path.exists(os.path.join(self.out, "frames", "1_143_b.jpg")))
        self.assertEqual(stats["frames"], 1)

    def test_missing_frame_is_reported(self):
        m = sample()
        m["nodes"][2]["frames"] = ["nope.jpg"]
        self.assertEqual(render(m, self.frames, self.out)["missing"], ["1.1: nope.jpg"])

    def test_script_close_tag_in_text_cannot_break_the_page(self):
        m = sample()
        m["nodes"][1]["title"] = "</script><b>x"
        render(m, self.frames, self.out)
        page, data = self.payload()
        self.assertEqual(data["nodes"][1]["title"], "</script><b>x")

    def test_too_many_frames_refuses(self):
        m = sample()
        for i in range(126):
            name = f"f{i}.jpg"
            open(os.path.join(self.frames, name), "wb").write(b"j")
            m["nodes"].append({"code": f"2.{i + 1}", "parent": "2", "title": "t", "source": "video",
                               "times": [1], "frames": [name, name.replace(".jpg", "b.jpg")]})
            open(os.path.join(self.frames, name.replace(".jpg", "b.jpg")), "wb").write(b"j")
        with self.assertRaises(SystemExit):
            render(m, self.frames, self.out)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 8: `scripts/render_atlas.py`**

```python
#!/usr/bin/env python3
"""map.json + chosen frames → atlas/index.html and atlas/frames/, ready to publish as an Artifact.

  python3 render_atlas.py MAP CANDIDATES_DIR OUT_DIR

Publish OUT_DIR/index.html with every frames/<name> passed in the Artifact `files` map.
"""
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mapfile import code_key, load  # noqa: E402
from to_outline import timestamp, watch_link  # noqa: E402

MAX_FILES = 250  # an Artifact publish takes at most 255 files, the page included
TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "atlas_template.html")


def _node_payload(n, video_id, frame_paths):
    return {"code": n["code"], "parent": n.get("parent"), "title": n["title"],
            "summary": n.get("summary", ""), "source": n.get("source", "video"), "quote": n.get("quote", ""),
            "times": [{"label": timestamp(t), "url": watch_link(video_id, t)} for t in n.get("times") or []],
            "frames": frame_paths, "refs": n.get("refs") or []}


def render(m, candidates_dir, out_dir) -> dict:
    frames_out = os.path.join(out_dir, "frames")
    shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(frames_out)
    wanted = sorted({f for n in m["nodes"] for f in n.get("frames") or []})
    if len(wanted) > MAX_FILES:
        sys.exit(f"{len(wanted)} frames; an atlas can publish at most {MAX_FILES}. Trim frames in map.json.")
    missing, nodes = [], []
    for n in sorted(m["nodes"], key=lambda n: code_key(n["code"])):
        paths = []
        for name in n.get("frames") or []:
            src = os.path.join(candidates_dir, name)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(frames_out, name))
                paths.append(f"frames/{name}")
            else:
                missing.append(f"{n['code']}: {name}")
        nodes.append(_node_payload(n, m["video"]["id"], paths))
    data = {"video": m["video"], "whimsical_url": (m.get("whimsical") or {}).get("url"), "nodes": nodes}
    # "</" inside a JSON string would end the <script> element early.
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    with open(TEMPLATE) as f:
        page = f.read().replace("/*ATLAS_DATA*/", blob)
    with open(os.path.join(out_dir, "index.html"), "w") as f:
        f.write(page)
    return {"nodes": len(nodes), "frames": sum(len(n["frames"]) for n in nodes), "missing": missing}


if __name__ == "__main__":
    stats = render(load(sys.argv[1]), sys.argv[2], sys.argv[3])
    print(json.dumps(stats, indent=2))
```

- [ ] **Step 9: `scripts/atlas_template.html`.** Load the `artifact-design`
  skill first and follow its page contract. The page must include:
  - `<title>Frame Atlas</title>`
  - colour tokens on `:root`, with dark mode under both
    `@media (prefers-color-scheme: dark) :root:not([data-theme="light"])`
    and `:root[data-theme="dark"]`
  - an explicit `body` background
  - a system font stack, with no external scripts
  - a 16px side gutter at phone width, and no horizontal scroll

  The data goes in exactly this tag:
  `<script type="application/json" id="data">/*ATLAS_DATA*/</script>`.
  An inline script renders it into these parts:
  - **Header:** the video title linked to YouTube, the channel, the node
    count, a link to the Whimsical map when there is one, and a legend
    (`▶` from the video · `🔍` added research · `✋` added by you).
  - **Search box:** filters cards by code, title, summary or quote.
  - **Tree index:** nested `<details>` links to `#c-<code>` (dots become
    dashes).
  - **Cards, one per node,** each with id `c-<code>`:
    - a code badge, the title and a source badge
    - a breadcrumb of the parent chain
    - the summary, and the quote as a `<blockquote>`
    - timestamp chips linking to YouTube (`target=_blank`)
    - frames as `<img loading=lazy>`; clicking one opens a `<dialog>`
      lightbox with the code, title and timestamp
    - research refs
    - chips for the children
  - **Deep links:** on load and on `hashchange`, `#3.2` or `#c-3-2`
    scrolls to that card and highlights it.
  - **Empty frames:** show a quiet "no frame" note.

  Verify by running `render_atlas.py` on the test sample and opening it with
  `preview_start`, url `file://…/index.html`, in the browser pane. Check it
  at desktop width and with the `mobile` preset, in light and dark.
- [ ] **Step 10: `scripts/frames_at.py`**

```python
# /// script
# requires-python = ">=3.10"
# dependencies = ["pillow>=10"]
# ///
"""Candidate frames around each map node's timestamps, plus labelled contact sheets to choose from.

  uv run frames_at.py VIDEO MAP OUT_DIR [--spread 2] [--codes 3.2 3.3]

Writes OUT_DIR/<code>_<t>_<a|b|c>.jpg (t-spread, t, t+spread for each of a node's
first two times) and OUT_DIR/sheets/<branch>_<n>.jpg with 12 labelled tiles each.
Pick by writing the chosen file names into the node's "frames" in map.json.
"""
import argparse
import json
import os
import subprocess

from PIL import Image, ImageDraw

TILE_W, COLS, PER_SHEET = 380, 4, 12


def grab(video, seconds, out, width=960):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{seconds:.2f}",
                    "-i", video, "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "4", out], check=True)


def candidates(node, spread):
    for t in (node.get("times") or [])[:2]:
        for k, dt in zip("abc", (-spread, 0, spread)):
            yield f"{node['code']}_{int(t)}_{k}.jpg", max(0.0, t + dt)


def sheet(tiles, out):
    """tiles: [(path, label)] → one grid image with the label under each tile."""
    thumbs = []
    for path, text in tiles:
        im = Image.open(path)
        im.thumbnail((TILE_W, TILE_W))
        thumbs.append((im, text))
    tile_h = max(im.height for im, _ in thumbs) + 22
    rows = (len(thumbs) + COLS - 1) // COLS
    canvas = Image.new("RGB", (COLS * TILE_W, rows * tile_h), "white")
    draw = ImageDraw.Draw(canvas)
    for i, (im, text) in enumerate(thumbs):
        x, y = (i % COLS) * TILE_W, (i // COLS) * tile_h
        canvas.paste(im, (x, y))
        draw.text((x + 4, y + im.height + 4), text, fill="black")
    canvas.save(out, quality=80)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("map")
    ap.add_argument("out")
    ap.add_argument("--spread", type=float, default=2.0)
    ap.add_argument("--codes", nargs="*")
    a = ap.parse_args()
    with open(a.map) as f:
        nodes = [n for n in json.load(f)["nodes"] if n.get("times") and (not a.codes or n["code"] in a.codes)]
    os.makedirs(os.path.join(a.out, "sheets"), exist_ok=True)
    branches = {}
    for node in nodes:
        for name, t in candidates(node, a.spread):
            path = os.path.join(a.out, name)
            if not os.path.exists(path):
                grab(a.video, t, path)
            branches.setdefault(node["code"].split(".")[0], []).append((path, name.removesuffix(".jpg")))
    for branch, tiles in sorted(branches.items()):
        for i in range(0, len(tiles), PER_SHEET):
            sheet(tiles[i:i + PER_SHEET], os.path.join(a.out, "sheets", f"{branch}_{i // PER_SHEET + 1}.jpg"))
    print(f"{sum(len(t) for t in branches.values())} candidates, sheets in {os.path.join(a.out, 'sheets')}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 11: `scripts/transcribe.py`**

```python
# /// script
# requires-python = ">=3.10,<3.13"
# dependencies = ["faster-whisper>=1.0"]
# ///
"""Fallback when YouTube gives no subtitles: transcribe a video or audio file locally to WebVTT.

  uv run transcribe.py MEDIA OUT.vtt [--model small.en]

small.en on CPU (int8) runs at several times real time on an Apple-silicon Mac.
"""
import argparse

from faster_whisper import WhisperModel


def vtt_time(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("media")
    ap.add_argument("out")
    ap.add_argument("--model", default="small.en")
    a = ap.parse_args()
    model = WhisperModel(a.model, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(a.media, vad_filter=True)
    with open(a.out, "w") as f:
        f.write("WEBVTT\n\n")
        for seg in segments:
            f.write(f"{vtt_time(seg.start)} --> {vtt_time(seg.end)}\n{seg.text.strip()}\n\n")


if __name__ == "__main__":
    main()
```

- [ ] **Step 12:** Run `python3 -m unittest discover -s "$SKILL/tests" -v`.
  Expected: all OK (`frames_at` and `transcribe` are checked end-to-end in
  Task 12).

### Task 11: SKILL.md and schema reference

- [ ] **Step 1: `references/map-schema.md`.** It covers:
  - every map.json field (from the spec, plus `refs`)
  - the rules `mapfile.py validate` enforces
  - how to shape the tree:
    - `0` is the video
    - level 1 is the real phases of the workflow, which can merge or split
      the YouTube chapters
    - level 2 is steps
    - level 3 is techniques, tools, prompts and gotchas
    - aim for 40–90 nodes for a 30-minute video
  - the `workflow.md` template, one section per phase:
    - Goal
    - Tools
    - Steps (numbered, each with `[mm:ss]`)
    - Prompts/settings she used, paraphrased
    - Problems and how she solved them
    - Node codes covered
  - plus a closing "Her full pipeline in one screen" list
- [ ] **Step 2: `SKILL.md`.** Frontmatter `name: video-mindmap`. The
  description triggers on:
  - a "Ready for breakdown" Drive folder link or a YouTube URL, with a
    request for a breakdown, workflow or mind map
  - "expand <code>" or a screenshot of a map node

  Body sections:
  1. **Paths:**
     - `WORK="$HOME/Documents/Video Mindmaps/<video-id>"`
     - `SKILL="$HOME/.skillbook/skills/video-mindmap"`
  2. **Pull:**
     - Take `info.json` and `transcript.vtt` from the Drive folder with the
       Google Drive connector.
     - Get the video locally:
       `uvx --from "yt-dlp[default]" yt-dlp --js-runtimes node -f "bv*[height<=720]+ba/b[height<=720]" --merge-output-format mp4 -o "$WORK/video.mp4" URL`.
       The Drive video is too large for the connector.
     - With no Drive folder, add `--write-info-json` (to `$WORK/info`) and
       `--write-subs --write-auto-subs --sub-langs "en.*,en" --sub-format vtt`.
  3. **Transcript:**
     - `python3 "$SKILL/scripts/transcript_md.py" …`
     - With no subtitles, run `uv run "$SKILL/scripts/transcribe.py" "$WORK/video.mp4" "$WORK/transcript.vtt"` first.
  4. **Breakdown:**
     - Read all of `transcript.md`, then write `workflow.md` and `map.json`
       per the reference.
     - Copyright rule: paraphrase; one quote per node at most, under 15
       words; no transcript dumps.
     - Validate with `mapfile.py validate`.
  5. **Frames:**
     - Run `uv run "$SKILL/scripts/frames_at.py" "$WORK/video.mp4" "$WORK/map.json" "$WORK/candidates"`.
     - Read each sheet and pick at most 2 frames per node that show the step
       (screen, UI, result), not just the speaker.
     - Write the picks into `frames`.
  6. **Whimsical:**
     - Call `how_to` first to learn the mind map input format.
     - Run `to_outline.py`, then `create` a mind map titled
       "<video title> — workflow map".
     - Store the id and URL with `mapfile.py set`.
     - If the connector isn't available, say so and continue.
  7. **Atlas:**
     - Load `artifact-design`, then `render_atlas.py`.
     - Publish `$WORK/atlas/index.html` with a `files` map of every
       `frames/<name>`, icon `map`.
     - Store the URL with `mapfile.py set`.
  8. **Report:** the doc path, the Whimsical link, the atlas link, node and
     frame counts, and anything skipped.
  9. **Expand loop:**
     - Read the code from the screenshot.
     - `fetch` the Whimsical map, write its outline to
       `$WORK/whimsical.md`, and run `mapfile.py reconcile`. Tell the user
       what changed.
     - Choose the source:
       - **From the video:** re-read `transcript.md` from 90 s before the
         node's times to 90 s after.
       - **Research:** WebSearch, and every child gets `refs`.
       - Default: video first, then research only if the video has nothing
         more.
     - `mapfile.py add` for each child, then `validate`.
     - Whimsical `edit`: add the children under that node, and add codes to
       any user nodes that reconcile numbered.
     - `frames_at.py --codes <new codes>`, then pick frames.
     - Run `render_atlas.py` and republish to the stored atlas URL.
     - Report the new codes.
  10. **Budget notes:**
      - A sheet is roughly 1.4k image tokens.
      - Read sheets one branch at a time.
- [ ] **Step 3:** Push the skill into the skillbook library:
  - `SKILLBOOK_LOCK_LIBRARY="$HOME/.skillbook-library" skillbook add video-mindmap --project "$HOME"`
    (or `push` if `add` isn't the right verb; check `skillbook --help`)
  - commit in `~/.skillbook-library` with
    `feat: video-mindmap skill (breakdown, Whimsical map, frame atlas, expand)`
  - confirm `~/.claude/skills/video-mindmap` resolves to the edited folder

### Task 12: End-to-end on `reFzEtCG_m8`

- [ ] **Step 1:** Follow SKILL.md for the Drive folder from Task 9, Step 8.
  Record wall-clock time and image tokens per step.
- [ ] **Step 2:** Check the results:
  - `workflow.md` covers all 18 chapters
  - `mapfile.py validate` passes
  - every video node has a timestamp, and each is spot-checked against the
    video for 5 random nodes
- [ ] **Step 3:** Once the Whimsical connector is available, create the map,
  then `fetch` it back. Answer the spec's open questions:
  - are links clickable?
  - can a board hold images?
  - is there a size limit?

  Write the answers into the feature doc.
- [ ] **Step 4:** Publish the atlas. Open it and check the deep link `#3.2`,
  the lightbox and the mobile width.
- [ ] **Step 5:** Expand test:
  - hand-add a node in Whimsical (the user does this, or it's done through
    `edit`)
  - run "expand" on one node from the video and one with research
  - confirm the hand-added node survives and gets a code
- [ ] **Step 6:** Update the feature doc Follow-ups and the CHANGELOG. Commit
  `docs: video-mindmap end-to-end results`.

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

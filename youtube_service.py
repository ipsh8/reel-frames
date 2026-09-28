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

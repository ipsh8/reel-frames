"""
audio_service.py — /audio-duration endpoint for the ALY reel pipeline.

Takes base64 audio, runs ffprobe on it, returns the exact length in seconds.
Used to anchor AI-generated transcript timestamps to the real audio duration.

Install:
    1. Drop this file next to main.py in the reel-frames repo
    2. main.py: add
           from audio_service import router as audio_router
           app.include_router(audio_router)

No new dependencies — ffprobe ships with ffmpeg, which this service already uses.
"""

import base64
import json
import os
import subprocess
import tempfile

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class AudioDurationRequest(BaseModel):
    audio_b64: str


@router.post("/audio-duration")
def audio_duration(req: AudioDurationRequest):
    """Return {"duration": <seconds>}. Returns 0 on any failure rather than
    raising, so a probe failure never kills the n8n run."""
    tmp_path = None
    try:
        audio_bytes = base64.b64decode(req.audio_b64)
        if not audio_bytes:
            raise ValueError("empty audio")

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "json", tmp_path],
            capture_output=True, text=True, timeout=30,
        ).stdout

        duration = round(float(json.loads(out)["format"]["duration"]), 2)
        return {"duration": duration}

    except Exception as e:
        return {"duration": 0, "error": str(e)}

    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

"""
Reel Frame Extractor — POST a video link, get frames back at a configurable interval.

Endpoints:
  POST /frames        -> zip of JPEGs (default) or JSON with base64 frames
  GET  /health        -> liveness check

Accepts:
  - Direct video URLs (e.g. Instagram CDN .mp4 from Apify scraper output) -> ffmpeg reads directly
  - Instagram page URLs (instagram.com/reel/...) -> resolved via yt-dlp first
"""

import base64
import os
import shutil
import subprocess
import tempfile
import uuid
import zipfile
from typing import Literal, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

app = FastAPI(title="Reel Frame Extractor", version="1.0.0")


def check_api_key(x_api_key: str = Header(None)):
    """Requires header X-API-Key to match the API_KEY env var set on the server."""
    expected = os.getenv("API_KEY")
    if not expected:
        raise HTTPException(500, "Server misconfigured: API_KEY env var not set")
    if x_api_key != expected:
        raise HTTPException(401, "Invalid or missing X-API-Key header")

FFMPEG_TIMEOUT = int(os.getenv("FFMPEG_TIMEOUT", "120"))
YTDLP_TIMEOUT = int(os.getenv("YTDLP_TIMEOUT", "60"))
HARD_MAX_FRAMES = int(os.getenv("HARD_MAX_FRAMES", "300"))


class FrameRequest(BaseModel):
    video_url: str = Field(..., description="Direct .mp4 URL or instagram.com page URL")
    interval: float = Field(2.0, gt=0.05, le=60, description="Seconds between frames")
    max_frames: int = Field(60, ge=1, le=HARD_MAX_FRAMES)
    width: Optional[int] = Field(None, ge=64, le=1920, description="Resize width, keeps aspect ratio")
    quality: int = Field(2, ge=1, le=31, description="JPEG quality, 1=best 31=worst (ffmpeg qscale)")
    output: Literal["zip", "json"] = "zip"
    start: float = Field(0.0, ge=0, description="Start offset in seconds")


def resolve_url(url: str) -> str:
    """If it's an Instagram page URL, resolve to direct media URL via yt-dlp."""
    if "instagram.com" not in url:
        return url
    cmd = ["yt-dlp", "-g", "-f", "best[ext=mp4]/best", "--no-warnings", url]
    cookies = os.getenv("IG_COOKIES_FILE")  # optional cookies.txt for gated content
    if cookies and os.path.exists(cookies):
        cmd[1:1] = ["--cookies", cookies]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=YTDLP_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "yt-dlp timed out resolving Instagram URL")
    if out.returncode != 0 or not out.stdout.strip():
        raise HTTPException(422, f"Could not resolve Instagram URL: {out.stderr.strip()[:300]}")
    return out.stdout.strip().splitlines()[0]


def extract_frames(direct_url: str, req: FrameRequest, workdir: str) -> list[str]:
    vf = f"fps=1/{req.interval}"
    if req.width:
        vf += f",scale={req.width}:-2"
    pattern = os.path.join(workdir, "frame_%04d.jpg")
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-ss", str(req.start),
        "-i", direct_url,
        "-vf", vf,
        "-vframes", str(req.max_frames),
        "-qscale:v", str(req.quality),
        pattern,
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=FFMPEG_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "ffmpeg timed out")
    frames = sorted(f for f in os.listdir(workdir) if f.startswith("frame_"))
    if not frames:
        raise HTTPException(422, f"No frames extracted: {out.stderr.strip()[:300]}")
    return [os.path.join(workdir, f) for f in frames]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/frames", dependencies=[Depends(check_api_key)])
def frames(req: FrameRequest):
    workdir = tempfile.mkdtemp(prefix="frames_")
    try:
        direct = resolve_url(req.video_url)
        paths = extract_frames(direct, req, workdir)

        # timestamp of frame N = start + N * interval (fps filter grabs first frame at t=0)
        timestamps = [round(req.start + i * req.interval, 3) for i in range(len(paths))]

        if req.output == "json":
            payload = {
                "count": len(paths),
                "interval": req.interval,
                "frames": [
                    {
                        "index": i,
                        "timestamp": timestamps[i],
                        "filename": os.path.basename(p),
                        "image_base64": base64.b64encode(open(p, "rb").read()).decode(),
                    }
                    for i, p in enumerate(paths)
                ],
            }
            shutil.rmtree(workdir, ignore_errors=True)
            return JSONResponse(payload)

        # zip output
        zip_path = os.path.join(tempfile.gettempdir(), f"frames_{uuid.uuid4().hex}.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for i, p in enumerate(paths):
                z.write(p, arcname=f"frame_{i:04d}_t{timestamps[i]}s.jpg")
        shutil.rmtree(workdir, ignore_errors=True)
        return FileResponse(
            zip_path,
            media_type="application/zip",
            filename="frames.zip",
            headers={"X-Frame-Count": str(len(paths))},
            background=BackgroundTask(lambda: os.remove(zip_path)),
        )
    except HTTPException:
        shutil.rmtree(workdir, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(workdir, ignore_errors=True)
        raise HTTPException(500, str(e)[:300])

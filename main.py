"""
Reel Toolkit v3 — pure media extraction. No AI, no transcription, no analysis.

Endpoints (POST, require X-API-Key header):
  /frames    -> screenshots at intervals (JSON base64 or zip)
  /download  -> the reel video itself as an .mp4 file
  /health    -> liveness check (GET, no auth)

Env vars:
  API_KEY          required — clients must send it as X-API-Key
  IG_COOKIES_FILE  optional cookies.txt for gated Instagram content
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

app = FastAPI(title="Reel Toolkit", version="3.0.0")

FFMPEG_TIMEOUT = int(os.getenv("FFMPEG_TIMEOUT", "180"))
YTDLP_TIMEOUT = int(os.getenv("YTDLP_TIMEOUT", "60"))
HARD_MAX_FRAMES = int(os.getenv("HARD_MAX_FRAMES", "300"))


def check_api_key(x_api_key: str = Header(None)):
    expected = os.getenv("API_KEY")
    if not expected:
        raise HTTPException(500, "Server misconfigured: API_KEY env var not set")
    if x_api_key != expected:
        raise HTTPException(401, "Invalid or missing X-API-Key header")


class FrameRequest(BaseModel):
    video_url: str = Field(..., description="Direct .mp4 URL or instagram.com page URL")
    interval: float = Field(2.0, gt=0.05, le=60)
    max_frames: int = Field(60, ge=1, le=HARD_MAX_FRAMES)
    width: Optional[int] = Field(None, ge=64, le=1920)
    quality: int = Field(2, ge=1, le=31)
    output: Literal["zip", "json"] = "zip"
    start: float = Field(0.0, ge=0)


class VideoRequest(BaseModel):
    video_url: str


def resolve_url(url: str) -> str:
    """If it's an Instagram page URL, resolve to direct media URL via yt-dlp."""
    if "instagram.com" not in url:
        return url
    cmd = ["yt-dlp", "-g", "-f", "best[ext=mp4]/best", "--no-warnings", url]
    cookies = os.getenv("IG_COOKIES_FILE")
    if cookies and os.path.exists(cookies):
        cmd[1:1] = ["--cookies", cookies]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=YTDLP_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "yt-dlp timed out resolving Instagram URL")
    if out.returncode != 0 or not out.stdout.strip():
        raise HTTPException(422, f"Could not resolve Instagram URL: {out.stderr.strip()[:300]}")
    return out.stdout.strip().splitlines()[0]


def extract_frames_from(source: str, req: FrameRequest, workdir: str) -> list[str]:
    vf = f"fps=1/{req.interval}"
    if req.width:
        vf += f",scale={req.width}:-2"
    pattern = os.path.join(workdir, "frame_%04d.jpg")
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error",
           "-ss", str(req.start), "-i", source, "-vf", vf,
           "-vframes", str(req.max_frames), "-qscale:v", str(req.quality), pattern]
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
    return {"status": "ok", "version": "3.0.0"}


@app.post("/frames", dependencies=[Depends(check_api_key)])
def frames(req: FrameRequest):
    workdir = tempfile.mkdtemp(prefix="frames_")
    try:
        direct = resolve_url(req.video_url)
        paths = extract_frames_from(direct, req, workdir)
        timestamps = [round(req.start + i * req.interval, 3) for i in range(len(paths))]

        if req.output == "json":
            payload = {
                "count": len(paths),
                "interval": req.interval,
                "frames": [
                    {
                        "index": i,
                        "timestamp": timestamps[i],
                        "filename": f"frame_{i:04d}_t{timestamps[i]}s.jpg",
                        "image_base64": base64.b64encode(open(p, "rb").read()).decode(),
                    }
                    for i, p in enumerate(paths)
                ],
            }
            shutil.rmtree(workdir, ignore_errors=True)
            return JSONResponse(payload)

        zip_path = os.path.join(tempfile.gettempdir(), f"frames_{uuid.uuid4().hex}.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for i, p in enumerate(paths):
                z.write(p, arcname=f"frame_{i:04d}_t{timestamps[i]}s.jpg")
        shutil.rmtree(workdir, ignore_errors=True)
        return FileResponse(zip_path, media_type="application/zip", filename="frames.zip",
                            headers={"X-Frame-Count": str(len(paths))},
                            background=BackgroundTask(lambda: os.remove(zip_path)))
    except HTTPException:
        shutil.rmtree(workdir, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(workdir, ignore_errors=True)
        raise HTTPException(500, str(e)[:300])


@app.post("/download", dependencies=[Depends(check_api_key)])
def download(req: VideoRequest):
    workdir = tempfile.mkdtemp(prefix="dl_")
    try:
        direct = resolve_url(req.video_url)
        out_path = os.path.join(workdir, "video.mp4")
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error",
               "-i", direct, "-c", "copy", "-movflags", "+faststart", out_path]
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=FFMPEG_TIMEOUT)
        except subprocess.TimeoutExpired:
            raise HTTPException(504, "Video download timed out")
        if out.returncode != 0 or not os.path.exists(out_path):
            raise HTTPException(422, f"Could not download video: {out.stderr.strip()[:300]}")

        final = os.path.join(tempfile.gettempdir(), f"reel_{uuid.uuid4().hex}.mp4")
        shutil.move(out_path, final)
        shutil.rmtree(workdir, ignore_errors=True)
        return FileResponse(final, media_type="video/mp4", filename="reel.mp4",
                            background=BackgroundTask(lambda: os.remove(final)))
    except HTTPException:
        shutil.rmtree(workdir, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(workdir, ignore_errors=True)
        raise HTTPException(500, str(e)[:300])

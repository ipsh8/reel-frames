"""
Reel Toolkit v3.1.1 — pure media extraction. No AI, no transcription, no analysis.

Endpoints (POST, require X-API-Key header):
  /frames    -> screenshots at intervals (JSON base64 or zip)
  /audio     -> the reel's audio track as an .mp3 file
  /download  -> the reel video itself as an .mp4 file
  /health    -> liveness check (GET, no auth)

/audio downloads Instagram's audio-only stream. /download takes the pre-muxed MP4
and, if that file turns out silent, merges the video and audio streams instead.
Instagram's pre-muxed files don't say whether they carry sound, and some don't.
/frames uses the fast URL path because frames never need audio.

Env vars:
  API_KEY          required — clients must send it as X-API-Key
  IG_COOKIES_FILE  optional cookies.txt for gated Instagram content
"""
import yt_dlp
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
from mask_service import router as mask_router
from audio_service import router as audio_router

app = FastAPI(title="Reel Toolkit", version="3.1.1")

app.include_router(mask_router)
app.include_router(audio_router)

FFMPEG_TIMEOUT = int(os.getenv("FFMPEG_TIMEOUT", "180"))
YTDLP_TIMEOUT = int(os.getenv("YTDLP_TIMEOUT", "60"))
YTDLP_DOWNLOAD_TIMEOUT = int(os.getenv("YTDLP_DOWNLOAD_TIMEOUT", str(YTDLP_TIMEOUT * 4)))
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


def _ytdlp_cookies(cmd: list) -> list:
    """Insert --cookies right after the yt-dlp binary, if a cookie file is configured."""
    cookies = os.getenv("IG_COOKIES_FILE")
    if cookies and os.path.exists(cookies):
        cmd[1:1] = ["--cookies", cookies]
    return cmd


def resolve_url(url: str, fmt: str = "best[ext=mp4]/best") -> str:
    """Resolve an Instagram page URL to ONE direct stream URL. Fast, no download.

    NOTE: this cannot merge separate video/audio streams. Use it only where audio
    does not matter (i.e. /frames). For anything needing sound, use fetch_media().
    """
    if "instagram.com" not in url:
        return url
    cmd = _ytdlp_cookies(["yt-dlp", "-g", "-f", fmt, "--no-warnings", url])
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=YTDLP_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "yt-dlp timed out resolving Instagram URL")
    if out.returncode != 0 or not out.stdout.strip():
        raise HTTPException(422, f"Could not resolve Instagram URL: {out.stderr.strip()[:300]}")
    return out.stdout.strip().splitlines()[0]


# Instagram lists its pre-muxed MP4s ("b") with unknown codecs, and some of them
# have no audio track. yt-dlp can't tell, so "b" alone can hand back a silent
# file. The audio-only DASH stream ("ba") is the one format guaranteed to carry sound.
AUDIO_FORMAT = "ba/b"
# Pre-muxed first keeps the H.264 file downstream nodes already get; the merge
# (VP9 video + the audio stream) is the fallback for when that file is silent.
VIDEO_FORMAT = "b/bv*+ba"
MERGED_VIDEO_FORMAT = "bv*+ba"


def fetch_media(url: str, workdir: str, fmt: str) -> str:
    """Download an Instagram reel in the given yt-dlp format; return the local path.

    Non-Instagram URLs are returned unchanged for ffmpeg to read directly.
    """
    if "instagram.com" not in url:
        return url

    os.makedirs(workdir, exist_ok=True)
    ydl_opts = {
        'format': fmt,
        # yt-dlp picks the extension from the stream it actually gets (mp4, m4a, ...)
        'outtmpl': os.path.join(workdir, "media.%(ext)s"),
        'quiet': True,
        'no_warnings': True,
    }
    
    cookies = os.getenv("IG_COOKIES_FILE")
    if cookies and os.path.exists(cookies):
        ydl_opts['cookiefile'] = cookies

    try:
        # Execute download natively (no subprocess blocking or shell text parsing)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            
    except yt_dlp.utils.DownloadError as e:
        # Cleanly catch actual download failures (e.g., video deleted, rate limited)
        raise HTTPException(status_code=422, detail=f"Media download failed: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")

    # Each download gets its own fresh workdir, so the only finished file in it is ours.
    for f in os.listdir(workdir):
        if not f.endswith(".part") and not f.endswith(".ytdl"):
            return os.path.join(workdir, f)

    raise HTTPException(status_code=422, detail="yt-dlp finished but no file was found.")


def has_audio(path_or_url: str) -> bool:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=codec_type", "-of", "csv=p=0", path_or_url],
        capture_output=True, text=True, timeout=FFMPEG_TIMEOUT)
    return "audio" in out.stdout


def fetch_video_with_audio(url: str, workdir: str) -> str:
    """Download the reel as a video that keeps its sound whenever the reel has any."""
    muxed = fetch_media(url, os.path.join(workdir, "muxed"), VIDEO_FORMAT)
    if muxed == url or has_audio(muxed):
        return muxed
    try:
        return fetch_media(url, os.path.join(workdir, "merged"), MERGED_VIDEO_FORMAT)
    except HTTPException:
        # No separate audio stream either: the reel really is silent, so the video is all there is.
        return muxed


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
    return {"status": "ok", "version": "3.1.1"}


@app.post("/frames", dependencies=[Depends(check_api_key)])
def frames(req: FrameRequest):
    workdir = tempfile.mkdtemp(prefix="frames_")
    try:
        # frames need VIDEO only — keep the fast URL path, no download, no merge
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


@app.post("/audio", dependencies=[Depends(check_api_key)])
def audio(req: VideoRequest):
    """Extract the audio track as an mp3 file."""
    workdir = tempfile.mkdtemp(prefix="au_")
    try:
        direct = fetch_media(req.video_url, os.path.join(workdir, "src"), AUDIO_FORMAT)
        if not has_audio(direct):
            raise HTTPException(
                422,
                "REEL_HAS_NO_AUDIO: Instagram serves no audio for this reel. It was "
                "likely posted silent, or muted for unlicensed music.")
        out_path = os.path.join(workdir, "audio.mp3")
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error",
               "-i", direct, "-vn", "-ac", "1", "-b:a", "64k", out_path]
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=FFMPEG_TIMEOUT)
        except subprocess.TimeoutExpired:
            raise HTTPException(504, "Audio extraction timed out")
        if out.returncode != 0 or not os.path.exists(out_path) or os.path.getsize(out_path) < 1024:
            raise HTTPException(422, f"No audio track found or extraction failed: {out.stderr.strip()[:300]}")

        final = os.path.join(tempfile.gettempdir(), f"audio_{uuid.uuid4().hex}.mp3")
        shutil.move(out_path, final)
        shutil.rmtree(workdir, ignore_errors=True)
        return FileResponse(final, media_type="audio/mpeg", filename="audio.mp3",
                            background=BackgroundTask(lambda: os.remove(final)))
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
        direct = fetch_video_with_audio(req.video_url, workdir)
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

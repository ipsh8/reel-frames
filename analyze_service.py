"""POST /analyze — the reel's evidence pack (cuts, camera moves, beats, images) as a zip.

Deterministic measurement only; the AI breakdown happens in the
reel-reverse-engineer skill that reads the pack. main.py includes this router
behind the X-API-Key check.
"""
import os
import shutil
import tempfile
import uuid
import zipfile

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from analysis import build_pack
from analysis.probe import probe

router = APIRouter()


class AnalyzeRequest(BaseModel):
    video_url: str


def _max_seconds():
    return float(os.getenv("ANALYZE_MAX_SECONDS", "180"))


def _zip_dir(src, dest):
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(src):
            for name in sorted(files):
                path = os.path.join(root, name)
                z.write(path, os.path.relpath(path, src))


@router.post("/analyze")
def analyze(req: AnalyzeRequest):
    # Looked up at call time: main imports this module, so a top-level import would be circular.
    import main
    workdir = tempfile.mkdtemp(prefix="analyze_")
    try:
        video = main.fetch_video_with_audio(req.video_url, workdir)
        seconds = probe(video).duration
        if seconds > _max_seconds():
            raise HTTPException(422, f"Video is {seconds:.0f}s, longer than ANALYZE_MAX_SECONDS "
                                     f"({_max_seconds():.0f}s)")
        pack_dir = os.path.join(workdir, "pack")
        timeline = build_pack(video, pack_dir)
        final = os.path.join(tempfile.gettempdir(), f"analysis_{uuid.uuid4().hex}.zip")
        _zip_dir(pack_dir, final)
        cuts = sum(1 for c in timeline["cuts"] if c["type"] != "graphic")
        headers = {"X-Cut-Count": str(cuts), "X-Shot-Count": str(len(timeline["shots"])),
                   "X-Image-Tokens": str(timeline["token_estimate"]["total"])}
        return FileResponse(final, media_type="application/zip", filename="analysis.zip", headers=headers,
                            background=BackgroundTask(lambda: os.remove(final)))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Analysis failed: {str(e)[:300]}")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

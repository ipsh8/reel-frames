"""Basic facts about a video file, from ffprobe."""
import json
import subprocess
from dataclasses import asdict, dataclass


@dataclass
class VideoInfo:
    fps: float
    width: int
    height: int
    duration: float
    frames: int
    has_audio: bool

    def to_dict(self):
        return asdict(self)


def _rate(text):
    num, _, den = text.partition("/")
    return float(num) / float(den or 1) if float(den or 1) else 0.0


def probe(path) -> VideoInfo:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
        capture_output=True, text=True, check=True).stdout
    data = json.loads(out)
    video = next(s for s in data["streams"] if s.get("codec_type") == "video")
    fps = _rate(video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/1") or _rate(video["r_frame_rate"])
    duration = float(video.get("duration") or data["format"].get("duration") or 0)
    frames = int(video.get("nb_frames") or round(duration * fps))
    return VideoInfo(
        fps=round(fps, 3),
        width=int(video["width"]),
        height=int(video["height"]),
        duration=round(duration, 3),
        frames=frames,
        has_audio=any(s.get("codec_type") == "audio" for s in data["streams"]),
    )

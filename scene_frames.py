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

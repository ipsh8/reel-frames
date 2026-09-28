"""Synthetic clips with known edits, so analysis tests have ground truth.

Every clip is built from one still test pattern (not the animated testsrc2),
so the only motion in a clip is the camera move we put there.
"""
import os
import shutil
import subprocess

HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
W, H, FPS = 360, 640, 30


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def still(workdir, name=None, size="720x1280", source="testsrc2"):
    name = name or f"still_{source}_{size}.png"
    path = os.path.join(workdir, name)
    if not os.path.exists(path):
        ffmpeg("-f", "lavfi", "-i", f"{source}=size={size}:rate=1", "-frames:v", "1", path)
    return path


def static(workdir, name="static.mp4", seconds=2, src=None):
    out = os.path.join(workdir, name)
    ffmpeg("-loop", "1", "-i", src or still(workdir), "-t", str(seconds), "-r", str(FPS),
           "-vf", f"scale={W}:{H}", "-pix_fmt", "yuv420p", out)
    return out


def pan_right(workdir, name="pan.mp4", seconds=2, px_per_sec=90):
    """Camera slides right over the pattern: content moves left."""
    out = os.path.join(workdir, name)
    ffmpeg("-loop", "1", "-i", still(workdir, size="1440x1280"), "-t", str(seconds), "-r", str(FPS),
           "-vf", f"crop=720:1280:x='t*{px_per_sec * 2}':y=0,scale={W}:{H}", "-pix_fmt", "yuv420p", out)
    return out


def push_in(workdir, name="zoom.mp4", seconds=2):
    """Camera pushes in toward the centre: content expands outward."""
    out = os.path.join(workdir, name)
    frames = seconds * FPS
    ffmpeg("-loop", "1", "-i", still(workdir), "-frames:v", str(frames), "-r", str(FPS),
           "-vf", "scale=w='trunc(720*(1+0.006*n)/2)*2':h=-2:eval=frame,crop=720:1280,"
                  f"scale={W}:{H}", "-pix_fmt", "yuv420p", out)
    return out


def concat(workdir, name, parts):
    """Hard-cut the given clips together (all share size/fps/pix_fmt)."""
    out = os.path.join(workdir, name)
    inputs = []
    for p in parts:
        inputs += ["-i", p]
    graph = "".join(f"[{i}:v]" for i in range(len(parts))) + f"concat=n={len(parts)}:v=1:a=0[v]"
    ffmpeg(*inputs, "-filter_complex", graph, "-map", "[v]", "-pix_fmt", "yuv420p", out)
    return out


def two_scenes(workdir):
    """Two visibly different static scenes, 1 s each."""
    a = static(workdir, "a.mp4", 1, still(workdir, "sa.png", source="testsrc2"))
    b = static(workdir, "b.mp4", 1, still(workdir, "sb.png", source="mandelbrot"))
    return a, b


def hard_cut(workdir):
    a, b = two_scenes(workdir)
    return concat(workdir, "hardcut.mp4", [a, b])


def flash_cut(workdir):
    """Scene A, two pure-white frames, then scene B."""
    a, b = two_scenes(workdir)
    white = os.path.join(workdir, "white.mp4")
    ffmpeg("-f", "lavfi", "-i", f"color=white:size={W}x{H}:rate={FPS}", "-frames:v", "2",
           "-pix_fmt", "yuv420p", white)
    return concat(workdir, "flash.mp4", [a, white, b])


def dissolve(workdir):
    """Scene A cross-fades into scene B over 0.5 s, starting at 1.0 s."""
    a = static(workdir, "da.mp4", 1.5, still(workdir, "sa.png", source="testsrc2"))
    b = static(workdir, "db.mp4", 1.5, still(workdir, "sb.png", source="mandelbrot"))
    out = os.path.join(workdir, "dissolve.mp4")
    ffmpeg("-i", a, "-i", b, "-filter_complex", "[0:v][1:v]xfade=transition=fade:duration=0.5:offset=1.0[v]",
           "-map", "[v]", "-pix_fmt", "yuv420p", out)
    return out


def caption_pop(workdir):
    """One static shot; at 1.0 s a white caption block appears in the lower third."""
    out = os.path.join(workdir, "caption.mp4")
    ffmpeg("-loop", "1", "-i", still(workdir), "-t", "2", "-r", str(FPS),
           "-vf", f"scale={W}:{H},drawbox=enable='gte(t,1)':x=60:y=420:w=240:h=70:color=white:t=fill",
           "-pix_fmt", "yuv420p", out)
    return out


def click_track(workdir, every=0.5, seconds=4):
    """Static video with a short 1 kHz blip every `every` seconds."""
    out = os.path.join(workdir, "clicks.mp4")
    vid = static(workdir, "clickvid.mp4", seconds)
    expr = f"if(lt(mod(t\\,{every})\\,0.03)\\,0.9*sin(2*PI*1000*t)\\,0)"
    ffmpeg("-i", vid, "-f", "lavfi", "-i", f"aevalsrc={expr}:s=22050:d={seconds}",
           "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-shortest", out)
    return out

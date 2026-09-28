"""python -m analysis <video file or reel URL> [-o OUT_DIR]

Builds the evidence pack and prints where it went and what reading it costs.
"""
import argparse
import os
import sys
import tempfile
import time

from .pack import build_pack


def _local_video(source, workdir):
    if os.path.exists(source):
        return source
    # Imported late: main.py pulls in FastAPI and yt-dlp, which a local file doesn't need.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    os.environ.setdefault("API_KEY", "cli")
    from main import fetch_video_with_audio
    return fetch_video_with_audio(source, workdir)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m analysis", description=__doc__.splitlines()[0])
    parser.add_argument("source", help="path to a video, or an Instagram reel / direct mp4 URL")
    parser.add_argument("-o", "--out", default="analysis-pack", help="output folder (default: ./analysis-pack)")
    args = parser.parse_args(argv)

    started = time.time()
    with tempfile.TemporaryDirectory() as workdir:
        video = _local_video(args.source, workdir)
        timeline = build_pack(video, args.out)
    real_cuts = [c for c in timeline["cuts"] if c["type"] != "graphic"]
    print(f"pack: {os.path.abspath(args.out)}")
    print(f"{len(timeline['shots'])} shots, {len(real_cuts)} cuts, "
          f"{len(timeline['cuts']) - len(real_cuts)} overlay changes, "
          f"{len(timeline['images']['strips'])} strips, {len(timeline['images']['sheets'])} sheets")
    print(f"image tokens if every image is read: {timeline['token_estimate']['total']}")
    print(f"took {time.time() - started:.1f}s")


if __name__ == "__main__":
    main()

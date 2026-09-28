"""Images for the AI pass, sized for what they have to show and nothing more.

- contact sheets: the whole reel at 2 fps, for the big picture
- strips: every frame around one event (cut, whip, unsure caption swap)
- motion graph: every signal on one timeline, cuts and onsets marked
"""
import math
import os

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

SHEET_FPS = 2
SHEET_COLS, SHEET_ROWS = 8, 4
SHEET_TILE_W = 150
STRIP_BEFORE, STRIP_AFTER = 6, 5
STRIP_TILE_W = 110
STRIP_MAX_TILES = 24
GAP = 3
# Claude scales an image to fit 1568 px on the long edge and ~1.15 MP, then
# charges about one token per 750 px. Newer models may allow larger images;
# this estimate is the conservative one.
MAX_EDGE = 1568
MAX_PIXELS = 1_150_000

TYPE_COLOURS = {"hard": "#ff3b30", "flash": "#ffd60a", "dip": "#8e8e93", "whip": "#ff9f0a",
                "dissolve": "#30d158", "graphic": "#64d2ff", "move": "#bf5af2"}


def image_tokens(w, h):
    scale = min(1.0, MAX_EDGE / max(w, h), math.sqrt(MAX_PIXELS / (w * h)))
    return math.ceil((w * scale) * (h * scale) / 750)


def _font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:   # Pillow < 10.1
        return ImageFont.load_default()


def grab_frames(video, indices, width):
    """Read the video once, keeping only the wanted frames, resized to `width`."""
    wanted = set(indices)
    last = max(wanted) if wanted else -1
    cap = cv2.VideoCapture(video)
    frames, f = {}, 0
    while f <= last:
        ok, frame = cap.read()
        if not ok:
            break
        if f in wanted:
            h = round(width * frame.shape[0] / frame.shape[1])
            small = cv2.resize(frame, (width, h), interpolation=cv2.INTER_AREA)
            frames[f] = Image.fromarray(cv2.cvtColor(small, cv2.COLOR_BGR2RGB))
        f += 1
    cap.release()
    return frames


def _label(tile, text, colour="yellow"):
    d = ImageDraw.Draw(tile)
    font = _font(11)
    box = d.textbbox((2, 1), text, font=font)
    d.rectangle([0, 0, box[2] + 3, box[3] + 2], fill="black")
    d.text((2, 1), text, fill=colour, font=font)


def _grid(tiles, cols):
    w, h = tiles[0].size
    rows = math.ceil(len(tiles) / cols)
    sheet = Image.new("RGB", (cols * (w + GAP) - GAP, rows * (h + GAP) - GAP), "black")
    for i, tile in enumerate(tiles):
        sheet.paste(tile, ((i % cols) * (w + GAP), (i // cols) * (h + GAP)))
    return sheet


def contact_sheets(video, fps, n_frames, shot_of, out_dir):
    step = fps / SHEET_FPS
    indices = [round(i * step) for i in range(math.ceil(n_frames / step)) if round(i * step) < n_frames]
    frames = grab_frames(video, indices, SHEET_TILE_W)
    per_sheet = SHEET_COLS * SHEET_ROWS
    os.makedirs(os.path.join(out_dir, "sheets"), exist_ok=True)
    sheets = []
    for n, start in enumerate(range(0, len(indices), per_sheet), 1):
        chunk = [f for f in indices[start:start + per_sheet] if f in frames]
        tiles = []
        for f in chunk:
            tile = frames[f].copy()
            _label(tile, f"S{shot_of(f):02d} {f / fps:.1f}s f{f}")
            tiles.append(tile)
        rel = f"sheets/sheet_{n:02d}.jpg"
        _grid(tiles, SHEET_COLS).save(os.path.join(out_dir, rel), quality=82)
        sheets.append({"file": rel, "tiles": len(tiles), "from": round(chunk[0] / fps, 2),
                       "to": round(chunk[-1] / fps, 2)})
    return sheets


def transition_strips(video, events, n_frames, fps, out_dir):
    """`events`: dicts with frame, span, kind. One strip image per event."""
    os.makedirs(os.path.join(out_dir, "strips"), exist_ok=True)
    plans = []
    for ev in events:
        first, last = ev["span"]
        lo = max(0, first - (3 if last > first else STRIP_BEFORE))
        hi = min(n_frames - 1, last + (3 if last > first else STRIP_AFTER))
        if hi - lo + 1 > STRIP_MAX_TILES:
            hi = lo + STRIP_MAX_TILES - 1
        plans.append((ev, list(range(lo, hi + 1))))
    frames = grab_frames(video, {f for _, fr in plans for f in fr}, STRIP_TILE_W)
    strips = []
    for ev, frs in plans:
        tiles = []
        for f in frs:
            if f not in frames:
                continue
            tile = frames[f].copy()
            inside = ev["span"][0] <= f <= ev["span"][1]
            if inside:
                ImageDraw.Draw(tile).rectangle([0, 0, tile.width - 1, tile.height - 1],
                                               outline=TYPE_COLOURS.get(ev["kind"], "red"), width=3)
            _label(tile, f"f{f} {f / fps:.2f}s")
            tiles.append(tile)
        rel = f"strips/{ev['kind']}_{ev['frame']:05d}.jpg"
        _grid(tiles, min(12, len(tiles))).save(os.path.join(out_dir, rel), quality=82)
        strips.append({"frame": ev["frame"], "kind": ev["kind"], "file": rel, "frames": [frs[0], frs[-1]]})
    return strips


def motion_graph(sig, cuts, onsets, out_path, width=1400):
    lanes = [("change", sig.comp, (0, 0.5)), ("brightness", sig.luma, (0, 255)),
             ("sharpness", sig.sharp, (0, max(1.0, float(np.percentile(sig.sharp, 98))))),
             ("pan x (content)", sig.dx, (-0.06, 0.06)), ("pan y (content)", sig.dy, (-0.06, 0.06)),
             ("zoom", sig.zoom, (-0.06, 0.06))]
    lane_h, left, top = 80, 110, 20
    height = top + lane_h * len(lanes) + 40
    img = Image.new("RGB", (width, height), "#111")
    d = ImageDraw.Draw(img)
    font = _font(11)
    n = max(1, sig.n - 1)
    plot_w = width - left - 10

    def x_of(f):
        return left + plot_w * f / n

    for i, (name, values, (lo, hi)) in enumerate(lanes):
        y0 = top + i * lane_h
        d.rectangle([left, y0, width - 10, y0 + lane_h - 6], outline="#333")
        d.text((6, y0 + lane_h / 2 - 6), name, fill="#ccc", font=font)
        if lo < 0 < hi:
            zy = y0 + (lane_h - 6) * (hi / (hi - lo))
            d.line([left, zy, width - 10, zy], fill="#333")
        pts = [(x_of(f), y0 + (lane_h - 6) * (1 - (min(hi, max(lo, v)) - lo) / (hi - lo)))
               for f, v in enumerate(values)]
        if len(pts) > 1:
            d.line(pts, fill="#e8e8e8", width=1)
    bottom = top + lane_h * len(lanes)
    for c in cuts:
        x = x_of(c["frame"])
        d.line([x, top, x, bottom - 6], fill=TYPE_COLOURS.get(c["type"], "red"), width=1)
    for t in onsets:
        x = x_of(t * sig.fps)
        d.line([x, bottom, x, bottom + 8], fill="#ccc")
    for s in range(0, int(n / sig.fps) + 1):
        x = x_of(s * sig.fps)
        d.line([x, bottom + 10, x, bottom + 14], fill="#888")
        d.text((x - 6, bottom + 16), f"{s}s", fill="#888", font=font)
    x = left
    d.text((x, 3), "cuts:", fill="#aaa", font=font)
    x += 34
    for kind, colour in TYPE_COLOURS.items():
        if kind == "move":
            continue
        d.rectangle([x, 6, x + 10, 14], fill=colour)
        d.text((x + 14, 3), kind, fill="#aaa", font=font)
        x += 22 + d.textlength(kind, font=font)
    d.text((x + 10, 3), "· ticks under the lanes = audio onsets", fill="#aaa", font=font)
    img.save(out_path)
    return os.path.basename(out_path)

"""Split each shot into camera moves (push-in, pan-left, whip, …) and name their easing.

Labels are from the camera's point of view: content sliding left is the
camera panning right; content expanding is a push-in. The signals can't tell a
dolly push from a lens zoom; the AI pass decides that from parallax.
"""
from dataclasses import asdict, dataclass

import numpy as np

SMOOTH = 5
MIN_RUN = 4
THRESH = {"zoom": 0.004, "dx": 0.003, "dy": 0.003, "rot": 0.003}
WHIP_SPEED = 0.05        # fraction of the frame per frame
DUPLICATE_DIFF = 0.002   # a repeated frame changes essentially nothing
MAX_REPEAT_RUN = 2
SHAKE_JITTER = 0.004     # frame-to-frame wobble left after smoothing
COMMON_FPS = (12, 15, 24, 25, 30, 48, 50, 60)


@dataclass
class Move:
    type: str
    start_frame: int
    end_frame: int
    start: float
    end: float
    ease: str
    peak_speed: float    # per frame, in the move's own unit
    total: float         # zoom: scale change (0.25 = 25 % bigger); pan/tilt: frame widths/heights; roll: radians

    def to_dict(self):
        return asdict(self)


def _bridge_duplicates(values, diff):
    """Frame-rate conversion repeats single frames, which report zero motion.

    Replace those with their neighbours' average. Only runs of 1–2 repeats
    count; a longer stillness is a real hold and stays zero.
    """
    out = values.astype(np.float64).copy()
    still = diff < DUPLICATE_DIFF
    dup = np.zeros_like(still)
    f = 1
    while f < len(still):
        if still[f]:
            e = f
            while e + 1 < len(still) and still[e + 1]:
                e += 1
            if e - f + 1 <= MAX_REPEAT_RUN and f > 0 and e + 1 < len(still):
                dup[f:e + 1] = True
            f = e + 1
        else:
            f += 1
    idx = np.arange(len(out))
    if dup.any() and (~dup).sum() >= 2:
        out[dup] = np.interp(idx[dup], idx[~dup], out[~dup])
    return out


def _smooth(x):
    if len(x) < SMOOTH:
        return x
    k = np.ones(SMOOTH) / SMOOTH
    padded = np.pad(x, SMOOTH // 2, mode="edge")
    return np.convolve(padded, k, mode="valid")


def _label(channels, f):
    dx, dy = channels["dx"][f], channels["dy"][f]
    if max(abs(dx), abs(dy)) > WHIP_SPEED:
        return "whip"
    scores = {k: abs(channels[k][f]) / THRESH[k] for k in THRESH}
    best = max(scores, key=scores.get)
    if scores[best] < 1:
        return "static"
    v = channels[best][f]
    return {
        "zoom": "push-in" if v > 0 else "pull-out",
        "dx": "pan-right" if v < 0 else "pan-left",
        "dy": "tilt-down" if v < 0 else "tilt-up",
        "rot": "roll-cw" if v > 0 else "roll-ccw",
    }[best]


def _merge_short(runs):
    changed = True
    while changed and len(runs) > 1:
        changed = False
        for i, (label, s, e) in enumerate(runs):
            if e - s + 1 < MIN_RUN and label != "whip":
                j = i - 1 if i > 0 else i + 1
                ls, ss, es = runs[j]
                runs[j] = (ls, min(s, ss), max(e, es))
                del runs[i]
                changed = True
                break
        merged = []
        for run in runs:
            if merged and merged[-1][0] == run[0]:
                merged[-1] = (run[0], merged[-1][1], run[2])
            else:
                merged.append(run)
        runs[:] = merged
    return runs


def _ease(speed):
    if len(speed) < 6 or speed.max() <= 0:
        return "linear"
    third = len(speed) // 3
    first, middle, last = speed[:third].mean(), speed[third:-third].mean(), speed[-third:].mean()
    peak_at = int(np.argmax(speed))
    if third <= peak_at < len(speed) - third and first < 0.5 * speed.max() and last < 0.5 * speed.max():
        return "ease-in-out"
    if last > 1.6 * first:
        return "ease-in"
    if first > 1.6 * last:
        return "ease-out"
    return "linear"


CHANNEL_OF = {"push-in": "zoom", "pull-out": "zoom", "pan-right": "dx", "pan-left": "dx",
              "tilt-down": "dy", "tilt-up": "dy", "roll-cw": "rot", "roll-ccw": "rot"}


def camera_moves(sig, shot):
    # Index start_frame compares against the previous shot's last frame, so it's left out.
    lo, hi = shot.start_frame + 1, shot.end_frame
    if hi - lo + 1 < 2:
        return [Move("static", shot.start_frame, shot.end_frame, shot.start, shot.end, "linear", 0.0, 0.0)]
    diff = sig.diff[lo:hi + 1]
    channels = {k: _smooth(_bridge_duplicates(getattr(sig, k)[lo:hi + 1], diff)) for k in THRESH}

    runs = []
    for i in range(hi - lo + 1):
        label = _label(channels, i)
        if runs and runs[-1][0] == label:
            runs[-1] = (label, runs[-1][1], i)
        else:
            runs.append((label, i, i))
    runs = _merge_short(runs)

    moves = []
    for n, (label, s, e) in enumerate(runs):
        start_frame = shot.start_frame if n == 0 else lo + s
        end_frame = lo + e
        if label in ("static", "whip"):
            speed = np.hypot(channels["dx"][s:e + 1], channels["dy"][s:e + 1])
            total = float(np.sum(speed))
        else:
            vals = channels[CHANNEL_OF[label]][s:e + 1]
            speed = np.abs(vals)
            total = float(np.prod(1 + vals) - 1) if label in ("push-in", "pull-out") else float(np.sum(vals))
        moves.append(Move(label, start_frame, end_frame, round(start_frame / sig.fps, 3),
                          round((end_frame + 1) / sig.fps, 3), "linear" if label == "static" else _ease(speed),
                          round(float(speed.max()), 5), round(total, 4)))
    return moves


def source_cadence(sig, shot):
    """Estimate the frame rate a shot was made at from its repeated frames.

    AI video generators often render 24 fps; conformed to a 30 fps timeline,
    every fifth frame repeats. A shot with no movement repeats every frame and
    says nothing, so it reports None.
    """
    diff = sig.diff[shot.start_frame + 1:shot.end_frame + 1]
    if len(diff) < 10:
        return {"source_fps": None, "duplicate_ratio": None}
    moving = diff > DUPLICATE_DIFF
    if moving.mean() < 0.3:
        return {"source_fps": None, "duplicate_ratio": round(float(1 - moving.mean()), 3)}
    ratio = float(1 - moving.mean())
    estimate = sig.fps * (1 - ratio)
    nearest = min(COMMON_FPS, key=lambda c: abs(c - estimate))
    return {"source_fps": nearest if abs(nearest - estimate) <= 2 else round(estimate, 1),
            "duplicate_ratio": round(ratio, 3)}


def shake(sig, shot):
    """Handheld wobble: jitter left in pan/tilt after smoothing, as a fraction of the frame."""
    lo, hi = shot.start_frame + 1, shot.end_frame
    if hi - lo < SMOOTH * 2:
        return 0.0
    diff = sig.diff[lo:hi + 1]
    jitter = []
    for k in ("dx", "dy"):
        raw = _bridge_duplicates(getattr(sig, k)[lo:hi + 1], diff)
        jitter.append(float(np.std(raw - _smooth(raw))))
    return round(max(jitter), 5)

"""Find edits in the per-frame signals and name each one.

Kinds:
  hard      one frame to the next, nothing in between
  flash     a bright frame (or a white-out) bridges the cut
  dip       a near-black frame bridges the cut
  whip      the frames either side of the cut are motion-blurred / moving fast
  dissolve  several frames that are each a blend of the shot before and after
  graphic   only part of the frame changed: a caption, sticker or UI element
            swapped over the same shot. Kept because it times the captions.

Every edit carries `confidence`; "low" ones are the ones worth a look.
"""
from dataclasses import asdict, dataclass, field
from typing import Optional

import numpy as np

PEAK_MIN = 0.08          # a cut changes at least this much of the picture (mean abs, 0..1)
GRAPHIC_MIN = 0.02       # an overlay (caption, sticker) can be much smaller than a cut
PEAK_RATIO = 3.0         # ...and at least this many times the local typical change
# Busy shots (walking legs, crowds) raise the "typical change", so a clear cut
# next to one can miss the ratio. A strong change across nearly the whole frame
# is let through at a lower ratio.
WIDE_PEAK_MIN = 0.15
WIDE_SPREAD = 0.8
WIDE_RATIO = 2.0
LOCAL_RADIUS = 8
MERGE_GAP = 3            # peaks this close are one edit (e.g. into and out of a flash frame)
FLASH_RISE = 25          # luma units above the surroundings
WHITE, BLACK = 235, 12
WHIP_SHARP_DROP = 0.45   # sharpness falls below this share of the shot's typical value
WHIP_SPEED = 0.04        # or the camera moves this fraction of the frame per frame
DISSOLVE_MIN_FRAMES = 5
DISSOLVE_MAX_FRAMES = 45
DISSOLVE_STEP_MIN = 0.006
DISSOLVE_ENDS_DIFFER = 0.06
DISSOLVE_BLEND_FIT = 0.35  # residual vs |A−B|; a real cross-fade is close to 0
DISSOLVE_MAX_MOTION = 0.01
GRAPHIC_SPREAD = 0.5     # below this share of changed frame, it's an overlay change, not a cut
UNSURE_SPREAD = (0.4, 0.6)


@dataclass
class Cut:
    frame: int                 # first frame that belongs to the new shot (or the transition)
    time: float
    type: str
    score: float               # the picture change at the cut, 0..1
    span: tuple                # (first, last) frame of the transition itself
    notes: list = field(default_factory=list)
    spread: float = 1.0        # share of the frame that changed
    confidence: str = "high"

    def to_dict(self):
        d = asdict(self)
        d["span"] = list(self.span)
        return d


@dataclass
class Shot:
    index: int
    start_frame: int
    end_frame: int
    start: float
    end: float
    cut_in: Optional[Cut]

    def to_dict(self):
        d = asdict(self)
        d["cut_in"] = self.cut_in.to_dict() if self.cut_in else None
        return d


def _local_median(x, f, radius):
    lo, hi = max(1, f - radius), min(len(x), f + radius + 1)
    around = np.concatenate([x[lo:f], x[f + 1:hi]])
    return float(np.median(around)) if len(around) else 0.0


def _peaks(change, spread, minimum):
    """Frames where the camera-compensated change spikes above its surroundings."""
    found = []
    for f in range(1, len(change)):
        d = change[f]
        if d < minimum:
            continue
        if d < change[max(1, f - 3):f + 4].max():
            continue
        typical = _local_median(change, f, LOCAL_RADIUS)
        clear_spike = d >= PEAK_RATIO * typical + 0.02
        wide_cut = d >= WIDE_PEAK_MIN and spread[f] >= WIDE_SPREAD and d >= WIDE_RATIO * typical
        if clear_spike or wide_cut:
            found.append(f)
    return found


def _group(peaks):
    groups = []
    for f in peaks:
        if groups and f - groups[-1][-1] <= MERGE_GAP:
            groups[-1].append(f)
        else:
            groups.append([f])
    return groups


def _classify(sig, first, last):
    n = len(sig.luma)
    bridge = sig.luma[first:min(n, last + 2)]
    before = sig.luma[max(0, first - 6):first - 1]
    after = sig.luma[min(n, last + 3):min(n, last + 8)]
    before_level = float(np.median(before)) if len(before) else float(bridge[0])
    after_level = float(np.median(after)) if len(after) else float(bridge[-1])
    # A flash/dip must stand out from BOTH shots; a cut into a darker or
    # brighter scene is just a cut.
    if bridge.max() >= WHITE or bridge.max() - max(before_level, after_level) > FLASH_RISE:
        return "flash", [f"luma peak {bridge.max():.0f} vs {before_level:.0f} before / {after_level:.0f} after"]
    if bridge.min() <= BLACK and min(before_level, after_level) > 3 * BLACK:
        return "dip", [f"luma dip {bridge.min():.0f} vs {before_level:.0f} before / {after_level:.0f} after"]

    # A whip smears BOTH sides of the cut. Motion values at index f compare
    # f-1 with f, so `first` itself straddles the cut and is ignored.
    def side_evidence(frames):
        frames = [f for f in frames if 0 < f < n]
        speed = max((max(abs(sig.dx[f]), abs(sig.dy[f])) for f in frames), default=0.0)
        blur = min((sig.sharp[f] for f in frames), default=np.inf)
        return speed, blur

    typical_sharp = float(np.median(sig.sharp[max(0, first - 15):min(n, last + 15)]))
    before_speed, before_blur = side_evidence((first - 2, first - 1))
    after_speed, after_blur = side_evidence((last + 1, last + 2))

    def smeared(speed, blur):
        return speed > WHIP_SPEED or (typical_sharp > 0 and blur < WHIP_SHARP_DROP * typical_sharp)

    if smeared(before_speed, before_blur) and smeared(after_speed, after_blur):
        return "whip", [f"speed {before_speed:.3f}/{after_speed:.3f}, sharpness "
                        f"{before_blur:.0f}/{after_blur:.0f} vs {typical_sharp:.0f} typical"]
    return "hard", []


def _blend_residual(thumbs, s, e):
    """How far frames s..e are from a straight cross-fade between frame s-1 and frame e+1."""
    a = thumbs[s - 1].astype(np.float32)
    b = thumbs[e + 1].astype(np.float32)
    ab = b - a
    denom = float((ab * ab).sum()) or 1.0
    worst = 0.0
    for f in range(s, e + 1):
        x = thumbs[f].astype(np.float32) - a
        alpha = float((x * ab).sum() / denom)
        resid = np.linalg.norm(x - alpha * ab) / (np.sqrt(denom) or 1.0)
        worst = max(worst, float(resid))
    return worst


def _dissolves(sig, taken):
    """Runs of steady moderate change that are a cross-fade, not a camera move."""
    n, found, f = len(sig.diff), [], 1
    moving = np.maximum.reduce([np.abs(sig.dx), np.abs(sig.dy), np.abs(sig.zoom)])
    while f < n:
        if sig.diff[f] < DISSOLVE_STEP_MIN or f in taken:
            f += 1
            continue
        e = f
        while e + 1 < n - 1 and sig.diff[e + 1] >= DISSOLVE_STEP_MIN and (e + 1) not in taken:
            e += 1
        length = e - f + 1
        if (DISSOLVE_MIN_FRAMES <= length <= DISSOLVE_MAX_FRAMES and f >= 1 and e + 1 < n
                and np.median(moving[f:e + 1]) < DISSOLVE_MAX_MOTION):
            ends = float(np.abs(sig.thumbs[e + 1].astype(np.float32) - sig.thumbs[f - 1]).mean() / 255)
            if ends > DISSOLVE_ENDS_DIFFER:
                fit = _blend_residual(sig.thumbs, f, e)
                if fit < DISSOLVE_BLEND_FIT:
                    found.append(Cut(f, round(f / sig.fps, 3), "dissolve", round(ends, 3), (f, e),
                                     [f"{length} frames, blend residual {fit:.2f}"]))
        f = e + 1
    return found


def detect_cuts(sig):
    cuts = []
    taken = set()
    for group in _group(_peaks(sig.comp, sig.spread, GRAPHIC_MIN)):
        first, last = group[0], group[-1]
        spread = float(max(sig.spread[f] for f in group))
        score = float(max(sig.comp[f] for f in group))
        if score < PEAK_MIN and spread >= GRAPHIC_SPREAD:
            continue   # weak but frame-wide: motion noise, not an edit
        kind, notes = _classify(sig, first, last)
        if spread < GRAPHIC_SPREAD and kind == "hard":
            kind, notes = "graphic", [f"only {spread:.0%} of the frame changed"]
        elif score < PEAK_MIN:
            kind, notes = "graphic", [f"small change ({score:.3f}) over {spread:.0%} of the frame"]
        unsure = UNSURE_SPREAD[0] <= spread <= UNSURE_SPREAD[1]
        cuts.append(Cut(first, round(first / sig.fps, 3), kind, round(score, 3), (first, last), notes,
                        round(spread, 2), "low" if unsure else "high"))
        taken.update(range(first - 1, last + 2))
    cuts += _dissolves(sig, taken)
    return sorted(cuts, key=lambda c: c.frame)


def shots_from_cuts(cuts, n_frames, fps):
    cuts = [c for c in cuts if c.type != "graphic"]   # an overlay change doesn't start a new shot
    starts = [0] + [c.frame for c in cuts]
    ends = [c.frame - 1 for c in cuts] + [n_frames - 1]
    cut_in = [None] + list(cuts)
    return [Shot(i + 1, s, e, round(s / fps, 3), round((e + 1) / fps, 3), c)
            for i, (s, e, c) in enumerate(zip(starts, ends, cut_in))]

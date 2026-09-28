"""One low-resolution pass over a video → per-frame numbers everything else is built on.

Motion sign convention: dx/dy/zoom/rot describe how the *image content* moves
from the previous frame. Content moving left (dx < 0) means the camera panned
right; content expanding (zoom > 0) means a push-in or zoom-in.
"""
from dataclasses import dataclass

import cv2
import numpy as np

ANALYSIS_WIDTH = 180   # camera motion is about direction and rhythm, not detail
DIFF_WIDTH = 72
MAX_CORNERS = 300
MIN_TRACKED = 8


@dataclass
class Signals:
    fps: float
    diff: np.ndarray    # 0..1 mean abs colour change vs previous frame
    luma: np.ndarray    # 0..255 mean brightness
    sharp: np.ndarray   # Laplacian variance; drops under motion blur
    dx: np.ndarray      # content shift, fraction of width per frame
    dy: np.ndarray      # content shift, fraction of height per frame
    zoom: np.ndarray    # relative scale change per frame (+ = expanding)
    rot: np.ndarray     # radians per frame (+ = clockwise in image coords)
    resid: np.ndarray   # motion the camera fit can't explain (subject/parallax), fraction of width

    @property
    def n(self):
        return len(self.diff)

    def to_lists(self, digits=5):
        names = ("diff", "luma", "sharp", "dx", "dy", "zoom", "rot", "resid")
        return {k: [round(float(v), digits) for v in getattr(self, k)] for k in names}


def _camera_motion(prev_gray, gray):
    """Track textured corners and RANSAC-fit a similarity transform.

    Dense flow on flat areas (sky, solid backgrounds) reports zero motion and
    outvotes the textured parts, so only trackable corners get a say. Returns
    (dx_px, dy_px, zoom, rot, resid_px), or None when too few corners track.
    """
    pts = cv2.goodFeaturesToTrack(prev_gray, maxCorners=MAX_CORNERS, qualityLevel=0.01, minDistance=5)
    if pts is None or len(pts) < MIN_TRACKED:
        return None
    nxt, status, _ = cv2.calcOpticalFlowPyrLK(prev_gray, gray, pts, None, winSize=(21, 21), maxLevel=3)
    good = status.ravel() == 1
    if good.sum() < MIN_TRACKED:
        return None
    p0, p1 = pts[good].reshape(-1, 2), nxt[good].reshape(-1, 2)
    M, _ = cv2.estimateAffinePartial2D(p0, p1, method=cv2.RANSAC, ransacReprojThreshold=1.5)
    if M is None:
        return None
    scale = float(np.hypot(M[0, 0], M[1, 0]))
    rot = float(np.arctan2(M[1, 0], M[0, 0]))
    h, w = gray.shape
    centre = np.array([w / 2, h / 2])
    shift = M[:, :2] @ centre + M[:, 2] - centre   # how the frame centre moved
    predicted = p0 @ M[:, :2].T + M[:, 2]
    resid = float(np.median(np.linalg.norm(p1 - predicted, axis=1)))
    return float(shift[0]), float(shift[1]), scale - 1, rot, resid


def measure(path, info) -> Signals:
    cap = cv2.VideoCapture(path)
    aw = ANALYSIS_WIDTH
    ah = max(2, round(aw * info.height / info.width))
    dw = DIFF_WIDTH
    dh = max(2, round(dw * info.height / info.width))

    rows = []
    prev_gray = prev_small = None
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        gray = cv2.cvtColor(cv2.resize(frame, (aw, ah), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
        small = cv2.resize(frame, (dw, dh), interpolation=cv2.INTER_AREA).astype(np.float32)
        luma = float(gray.mean())
        sharp = float(cv2.Laplacian(gray, cv2.CV_32F).var())
        if prev_gray is None:
            rows.append((0.0, luma, sharp, 0.0, 0.0, 0.0, 0.0, 0.0))
        else:
            diff = float(np.abs(small - prev_small).mean() / 255)
            motion = _camera_motion(prev_gray, gray)
            if motion is None:   # flat frame: nothing to track, report no camera motion
                rows.append((diff, luma, sharp, 0.0, 0.0, 0.0, 0.0, 0.0))
            else:
                tx, ty, zoom, rot, resid = motion
                rows.append((diff, luma, sharp, tx / aw, ty / ah, zoom, rot, resid / aw))
        prev_gray, prev_small = gray, small
    cap.release()

    cols = np.array(rows, dtype=np.float64).T if rows else np.zeros((8, 0))
    return Signals(info.fps, *cols)

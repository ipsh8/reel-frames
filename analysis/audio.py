"""Where the sound hits: onsets, a tempo estimate, and how the cuts sit against them.

Editors cut on the beat or on a sound effect ("whoosh", impact). Offsets are
reported per cut in frames: negative means the onset comes that many frames
before the cut (the sound leads the picture).
"""
import subprocess

import numpy as np

RATE = 22050
WINDOW = 1024
HOP = 512
PEAK_RADIUS = 3          # hops (~70 ms) either side
LOCAL_WINDOW = 43        # hops (~1 s) for the adaptive threshold
PEAK_SIGMA = 1.5
MIN_GAP_S = 0.1
ON_ONSET_FRAMES = 2
TEMPO_RANGE = (60, 200)
TEMPO_OCTAVE_SHARE = 0.85


def _pcm(path):
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(RATE), "-f", "s16le", "-"],
        capture_output=True)
    if proc.returncode != 0 or not proc.stdout:
        return None
    return np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768


def _flux(samples):
    """Positive log-magnitude spectral flux per hop: how much new energy each hop brings.

    The signal is front-padded by one window so a hit at 0 s still registers.
    """
    samples = np.concatenate([np.zeros(WINDOW, dtype=np.float32), samples])
    n = 1 + (len(samples) - WINDOW) // HOP
    frames = np.lib.stride_tricks.as_strided(
        samples, shape=(n, WINDOW), strides=(samples.strides[0] * HOP, samples.strides[0]))
    mag = np.log1p(100 * np.abs(np.fft.rfft(frames * np.hanning(WINDOW), axis=1)))
    flux = np.maximum(np.diff(mag, axis=0), 0).sum(axis=1)
    return np.concatenate([[0.0], flux])


def _onsets(flux):
    hop_s = HOP / RATE
    found = []
    for i in range(1, len(flux)):
        lo, hi = max(0, i - PEAK_RADIUS), i + PEAK_RADIUS + 1
        if flux[i] < flux[lo:hi].max() or flux[i] <= 0:
            continue
        win = flux[max(0, i - LOCAL_WINDOW):i + LOCAL_WINDOW]
        if flux[i] < win.mean() + PEAK_SIGMA * win.std():
            continue
        t = i * hop_s
        if found and t - found[-1] < MIN_GAP_S:
            continue
        found.append(t)
    # Hop i's window starts at i·HOP; a hit shows most when it reaches the
    # window's centre, so the hit is half a window after the hop start. The
    # front padding (one full window) comes back off.
    return [round(max(0.0, t + (WINDOW / 2) / RATE - WINDOW / RATE), 3) for t in found]


def _tempo(flux):
    if len(flux) < 64:
        return None
    x = flux - flux.mean()
    ac = np.correlate(x, x, mode="full")[len(x) - 1:]
    hop_s = HOP / RATE
    lags = np.arange(len(ac))
    lo = int(60 / TEMPO_RANGE[1] / hop_s)
    hi = min(len(ac) - 1, int(60 / TEMPO_RANGE[0] / hop_s))
    if hi <= lo:
        return None
    # A pulse every 0.5 s also lines up every 1 s; take the shortest lag that
    # is nearly as strong as the best, or tempo comes out half the real one.
    window = ac[lo:hi + 1]
    peaks = [i for i in range(1, len(window) - 1) if window[i] >= window[i - 1] and window[i] >= window[i + 1]]
    if not peaks:
        return None
    strongest = max(window[i] for i in peaks)
    best = lo + min(i for i in peaks if window[i] >= TEMPO_OCTAVE_SHARE * strongest)
    # parabolic refinement for sub-hop precision
    if 0 < best < len(ac) - 1:
        a, b, c = ac[best - 1], ac[best], ac[best + 1]
        shift = 0.5 * (a - c) / (a - 2 * b + c) if (a - 2 * b + c) else 0
        best = lags[best] + shift
    return round(60 / (best * hop_s), 1)


def analyze_audio(path, fps, cuts):
    samples = _pcm(path)
    if samples is None or not np.any(samples):
        return {"available": False, "onsets": [], "tempo_bpm": None,
                "cut_offsets_frames": {}, "cuts_on_onset_ratio": None, "chance_ratio": None}
    flux = _flux(samples)
    onsets = _onsets(flux)
    offsets = {}
    for cut in cuts:
        if not onsets:
            break
        nearest = min(onsets, key=lambda t: abs(t - cut.time))
        offsets[str(cut.frame)] = int(round((nearest - cut.time) * fps))
    on = sum(abs(v) <= ON_ONSET_FRAMES for v in offsets.values())
    # With dense audio (voiceover is ~3 onsets/s) many cuts land near an onset
    # by luck; this is the share expected if cuts were placed at random.
    duration = len(samples) / RATE
    chance = min(1.0, len(onsets) / duration * (2 * ON_ONSET_FRAMES + 1) / fps) if duration else None
    return {
        "available": True,
        "onsets": onsets,
        "tempo_bpm": _tempo(flux),
        "cut_offsets_frames": offsets,
        "cuts_on_onset_ratio": round(on / len(offsets), 2) if offsets else None,
        "chance_ratio": round(chance, 2) if chance is not None else None,
    }

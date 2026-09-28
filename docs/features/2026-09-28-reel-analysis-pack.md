# Reel analysis evidence pack

- **Status:** Shipped 2026-09-28, v3.4.0 (commits `fb3b6a4`, `a209707`,
  `6e5c54e`, `7d54f35`, `3898e57`, and the `/analyze` endpoint commit)
- **Design:** `docs/specs/2026-09-28-reel-reverse-engineer-design.md`

## Problem

We want to rebuild reels we admire. That means knowing every cut, transition,
camera move and caption beat. The existing `/frames` endpoint samples every
0.5–2 s, but transitions last 4–12 frames, so they fall between samples.
Sending every frame to a vision model instead costs about 1.5 M tokens for a
30 s reel, and the model still has to guess timings a program can measure
exactly.

## Goals

- Measure everything that can be measured without AI: cuts and their type,
  camera moves and their easing, source frame rate, audio onsets, and cut timing.
- Produce images an AI can read cheaply, and only where it needs to look:
  contact sheets for the overview, every-frame strips at each transition.
- Report the token cost of reading the pack.
- One implementation, usable locally (CLI) and from n8n (`POST /analyze`).

## Non-goals

- No AI inside the service. Naming effects and writing build recipes happens
  in the `reel-reverse-engineer` skill.
- No true 3D camera solve. The motion is a 2D similarity fit, so it gives the
  direction, size, rhythm and easing of a move, not a camera path in metres.
- No transcription.

## Approach

**One pass, low resolution (180 px).** That's enough for motion and cuts,
and a 32 s reel takes about 14 s on a laptop.

**Camera motion from tracked corners, not dense flow.** The first version used
Farneback dense flow with a median fit. On a synthetic pan over a colour-bar
test pattern it measured zero, because flat areas report no motion and outvote
the textured ones. Real reels have the same flat areas: solid backgrounds, sky,
the purple UI space in the reference reel. The shipped version tracks
Shi–Tomasi corners with Lucas–Kanade and RANSAC-fits a similarity transform.

**Motion-compensated cut detection.** Plain frame difference missed the
reference reel's 0.50 s cut, because the crash zoom before it changes the
picture just as much every frame. Warping the previous frame by the measured
camera move first makes in-shot motion cancel out: the cut scored 4.5× its
surroundings afterwards.

**Cut typing:**
- flash and dip must stand out from *both* neighbouring shots. The first
  version called a cut into a dark scene a "dip".
- whip must be smeared on *both* sides. The first version called a UI card
  sliding in fast after a hard cut a "whip".
- dissolve requires the in-between frames to be a linear blend of the frames
  before and after, which a camera move never is.

**Overlay changes (`graphic`).** Caption swaps over a still shot looked like
cuts. Measuring what share of the frame changed ("spread") separates them:
caption swaps come in at 0.42–0.48, most cuts at 0.65–1.0. But two real cuts
scored 0.52, so the boundary is thin. Anything between 0.4 and 0.6 is marked
`unsure` and gets a strip, so the AI pass settles it by looking. Overlay
changes are kept, not dropped, because they time the captions.

**Source frame rate.** On the reference reel, every fifth frame of the
AI-generated shots repeats: 24 fps clips conformed to 30. The same repeats
would break a camera move into jitter, so single repeats are bridged, while
real holds (longer runs) are left alone.

**Audio chance baseline.** The reference reel lands 54 % of its cuts on an
onset, which sounds beat-synced. But voiceover gives about 3 onsets/s, so
chance alone gives 52 %. The pack reports both numbers. This reel is cut to
the words, not the music.

**Token estimate.** Each image's cost is `ceil(w·h/750)` after Claude's
resize (1568 px long edge, about 1.15 MP). The reference reel's full pack is
about 11.3 k image tokens.

## Follow-ups

- Speed ramps aren't labelled; they show up as a change in motion speed
  within a move in `motion.png`.
- The first Railway deploy is the first time the Docker image is built with
  OpenCV. There was no Docker daemon locally to test it.
- The thresholds were tuned on synthetic clips and one real reel. Check them
  against a few more reels with different styles (talking head, fast-cut
  montage).

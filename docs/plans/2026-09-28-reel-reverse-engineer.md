# Reel reverse-engineering implementation plan

> **For agentic workers:** executed inline (superpowers:executing-plans). Steps use `- [ ]`.

**Goal:** Turn a reel into a measured evidence pack (free), then into an AI
breakdown with starter After Effects and Blender build files.

**Architecture:** `reel-frames/analysis/` does one low-resolution pass over the
video to get per-frame signals. From those it types the cuts, finds the camera
moves and the audio onsets, and renders token-cheap images. It is exposed as
`python -m analysis` and as `POST /analyze`. The `reel-reverse-engineer` skill
consumes the pack in three budgeted AI passes and runs two generator scripts.

**Tech stack:** Python 3.12+, ffmpeg/ffprobe, numpy, opencv-python-headless,
Pillow, FastAPI; ExtendScript (AE); bpy (Blender 5.2).

**Spec:** `docs/specs/2026-09-28-reel-reverse-engineer-design.md`

---

## File map

| File | Responsibility |
|---|---|
| `analysis/__init__.py` | exports `build_pack` |
| `analysis/probe.py` | `probe(path) -> VideoInfo` (ffprobe) |
| `analysis/signals.py` | `measure(path, info) -> Signals`: one pass, per-frame `diff, luma, sharp, dx, dy, zoom, rot, resid` |
| `analysis/cuts.py` | `detect_cuts(sig, fps) -> list[Cut]`, `shots_from_cuts(cuts, n, fps) -> list[Shot]` |
| `analysis/moves.py` | `camera_moves(sig, shot, fps) -> list[Move]` (segments with ease) |
| `analysis/audio.py` | `analyze_audio(path, fps, cuts) -> AudioInfo` |
| `analysis/render.py` | `contact_sheets`, `transition_strips`, `motion_graph` |
| `analysis/pack.py` | `build_pack(video, out_dir) -> dict`: writes `timeline.json`, `summary.md`, images |
| `analysis/__main__.py` | CLI: path or URL, `-o out_dir` |
| `analyze_service.py` | `POST /analyze` → zip of the pack |
| `tests/clips.py` | ffmpeg helpers that synthesise test clips |
| `tests/test_analysis_*.py` | unit tests per module |

Skill (`~/.skillbook/skills/reel-reverse-engineer/`): `SKILL.md`,
`references/effects-catalog.md`, `references/tool-routing.md`,
`references/rebuild-schema.md`, `scripts/make_ae_jsx.py`,
`scripts/make_blender_py.py`, `scripts/token_ledger.py`.

## Tasks

### Task 1: probe + signals
- [ ] Tests (`tests/test_analysis_signals.py`), using synthetic clips:
  - A 2 s testsrc clip that pans right via `crop=x='t*40'` gives a `dx`
    median that is **negative** for scene content moving left, which is the
    camera panning right. Assert the sign and that `|dx| > 0.002` (as a
    fraction of the width per frame).
  - A `zoompan` zoom-in clip gives a `zoom` median > 0.
  - A static clip gives `|dx|`, `|dy|`, `|zoom|` < 0.001.
- [ ] Implement `probe.py` (ffprobe JSON → `VideoInfo(fps, width, height,
      duration, frames, has_audio)`).
- [ ] Implement `signals.py`: read frames with OpenCV, downscale to 180 px
      wide, compute:
  - `diff`: mean absolute RGB difference at 72 px, scaled 0–1
  - `luma`: mean Y, 0–255
  - `sharp`: variance of the Laplacian
  - Farneback flow, with a similarity fit `u = a·x − b·y + tx`,
    `v = b·x + a·y + ty` on a grid (one outlier-rejecting refit), giving
    `zoom=a`, `rot=b`, `dx=tx/W`, `dy=ty/H`, `resid` (the subject's motion
    relative to the camera)
- [ ] Run the tests (they pass), then commit `feat: per-frame video signals for reel analysis`.

### Task 2: cuts + shots
- [ ] Tests: synthetic clips for:
  - a hard cut at frame 30 → one cut, `type=="hard"`, `frame==30`
  - a white flash (a 2-frame white clip between two sources) → `type=="flash"`
  - `xfade=fade:duration=0.5` → one `dissolve` whose span covers the fade
  - a static clip → no cuts, one shot
- [ ] Implement:
  - A peak cut is a frame where `diff[f]` is a local max over ±3 frames and
    `diff[f] > max(0.12, 4 × rolling median)`.
  - `flash`: the max luma over `f..f+2` exceeds the median of the 5 frames
    before and after by more than 25, or a neighbouring frame has luma > 235
    or < 12.
  - `whip`: the sharpness near the cut drops below 45 % of the shot median,
    or `|dx|`/`|dy|` next to the cut is more than 0.04.
  - `dissolve`: an 8-frame window where each `diff` is between 0.015 and the
    peak threshold, and `diff(first, last)` is more than 0.12. Scored against
    the actual frames, so no peak cut falls inside it.
- [ ] Run the tests, then commit `feat: typed cut detection (hard/flash/whip/dissolve)`.

### Task 3: camera moves
- [ ] Tests: the pan clip → one `pan-right` move covering most of the shot; the
      zoom clip → `push-in`; a clip that is static then pans → a `static` move
      followed by a `pan-*` move.
- [ ] Implement: 5-frame moving average per channel. Each frame gets the label
      of its dominant channel above its threshold (zoom 0.004, pan 0.003,
      rot 0.003 rad), or `static`. A speed above 0.05 of the width per frame
      is labelled `whip`. Runs shorter than 4 frames are merged into their
      neighbour. For each move, `ease` is:
  - `ease-in` if the mean speed of the last third is more than 1.6 × that of
    the first third
  - `ease-out` if it is the reverse
  - `ease-in-out` if the peak is in the middle third with both ends under 50 %
  - otherwise `linear`
- [ ] Run the tests, then commit `feat: camera move segmentation with easing`.

### Task 4: audio
- [ ] Tests: a click track (sine bursts every 0.5 s) → onsets every 0.5 s,
      ±1 frame; tempo 120 ±3; a video without audio → `available=False`.
- [ ] Implement: ffmpeg → mono 22 050 Hz s16. STFT with a 1024 window and a
      512 hop, then log-magnitude spectral flux. Peaks are local maxima over
      ±3 hops above a moving mean + 1.5 × std. Tempo comes from the
      autocorrelation of the flux over the 60–200 BPM range. For each cut,
      store the offset to the nearest onset in frames, plus
      `cuts_on_onset_ratio` (the share within ±2 frames).
- [ ] Run the tests, then commit `feat: audio onsets, tempo and cut alignment`.

### Task 5: render + pack + CLI
- [ ] Tests: `build_pack` on a synthetic 4 s clip with one hard cut writes:
  - `timeline.json` (with keys `version, source, cuts, shots, audio, frames, images, token_estimate`)
  - `summary.md`
  - at least 1 sheet
  - exactly 1 strip
  - `motion.png`

  It also checks that `token_estimate.total` equals the sum of
  `ceil(w·h/750)` over the images.
- [ ] Implement `render.py` in Pillow only, without matplotlib:
  - sheets: 2 fps, 8×4 tiles 150 px wide, labelled `S<shot> <t>s f<frame>`
  - strips: cut frame −6 to +5 (or the dissolve span ±3), 110 px tiles, with
    the cut frame outlined in red
  - `motion.png`: lanes for diff, luma, sharp, pan x, pan y and zoom, cut
    lines and onset ticks
- [ ] Implement `pack.py` and `__main__.py`. For a URL, the CLI uses
      `main.fetch_video_with_audio`. The CLI prints the pack path and the
      token estimate.
- [ ] Run `python -m analysis <reference reel> -o /tmp/pack` and check the
      known cuts: 0.50 s flash, 4.90, 5.27, 29.00, plus the push-in at
      5.4–5.9 s.
- [ ] Commit `feat: evidence pack builder and CLI`.

### Task 6: `/analyze` endpoint
- [ ] Test (FastAPI TestClient, with `fetch_video_with_audio` monkeypatched to
      return a synthetic clip) → 200, a zip containing `timeline.json`; a
      missing key → 401; over `ANALYZE_MAX_SECONDS` → 422.
- [ ] Implement the router. Include it in `main.py`, add
      `opencv-python-headless` to the requirements, add
      `ANALYZE_MAX_SECONDS` to `.env.example`, and bump the version to 3.4.0.
- [ ] Update the README (API table + an Analysis section), the CHANGELOG, the
      feature doc and the feature-docs INDEX. Commit `feat: POST /analyze returns the evidence pack`.

### Task 7: skill + generators
- [ ] `references/rebuild-schema.md`: the `rebuild.json` the AI writes, with
      `sections[]`, `shots[]` (`source`, `tool`, `prompt`), `captions[]`
      (`text`, `start`, `end`, `style`) and `ui_assets[]`.
- [ ] `scripts/make_ae_jsx.py timeline.json rebuild.json -o rebuild.jsx`
      creates:
  - a 1080×1920 comp at the source fps
  - comp markers at the cuts
  - a guide layer holding the reference video
  - a placeholder solid per shot, with scale and position keyframes from the
    measured moves
  - caption text layers with a pop (scale 0→112→100 over 4 frames, easy ease)
    and a glow

  Verify by running it in After Effects (Beta) via `osascript`, then
  reading back the layer count.
- [ ] `scripts/make_blender_py.py timeline.json rebuild.json -o rebuild_scene.py`
      creates:
  - a 1080×1920 scene at the source fps
  - a pattern backdrop
  - an image plane per UI asset (a placeholder card if there's no PNG)
  - a camera keyed from the cumulative zoom/pan of the moves in each
    `3d-ui` section

  Verify with `blender -b -P rebuild_scene.py -- --render-frame N`.
- [ ] `scripts/token_ledger.py`: image token maths plus ledger append.
- [ ] `SKILL.md`: the procedure (pack → pass 1/2/3 → rebuild.json →
      generators → breakdown), budgets, and output layout.
- [ ] Register with skillbook (`skillbook push`), commit to the library.

### Task 8: n8n
- [ ] Workflow **REEL FRAMES to Drive**:
  - a form dropdown "Analyze for rebuild" (no/yes)
  - Telegram: if the message contains `analyze` or `rebuild`, the flag is on
  - after the frames are uploaded, an IF on the flag → **Create Analysis
    Folder** → **Analyze Reel** (POST `/analyze`, returning a file) →
    **Unzip** → **Split Files** → **Upload Analysis** → back to the loop
  - the done message names the skill command
- [ ] Validate, then test with the reference reel once `/analyze` is deployed.

### Task 9: run it on the reference reel
- [ ] Run the skill end to end on `DdjzUhwM0sV` and record the token ledger.
- [ ] Publish the breakdown as an Artifact.

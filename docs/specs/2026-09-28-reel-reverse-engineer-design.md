# Reel reverse-engineering: design

- **Status:** Approved design, 2026-09-28
- **Scope:** `reel-frames` (new `analysis` package + `/analyze` endpoint),
  a new `reel-reverse-engineer` skill (skillbook), and an opt-in branch in the
  n8n workflow **REEL FRAMES to Drive**.

## Problem

We want to take a finished reel and work out how it was made: every cut,
transition, camera move, text effect and graphic. Then rebuild it with our own
tools: After Effects, Blender, CapCut, and Higgsfield used sparingly. DaVinci
Resolve is not available.

The existing pipeline samples frames at a fixed 0.5–2 s interval. That's fine
for mood boards, but it can't reverse-engineer an edit. A transition lasts
4–12 frames (0.15–0.4 s at 30 fps), so fixed sampling usually steps right over
it. Sending every frame to a vision model is also out: a 32 s reel is 959 frames,
about 1.5 M image tokens.

## Goals

1. Measure everything a program can measure for free: cuts, camera motion,
   flashes, beats. Do this before any AI looks at the reel.
2. Give the AI only what it needs to *name* what was measured. That means
   contact sheets for the big picture and every-frame strips around each
   transition. Target: a full 30 s reel breakdown in about 60 k tokens.
3. Count the tokens. Every analysis writes a ledger of what each pass cost.
4. Output a build plan, not just a description:
   - a shot-by-shot table
   - for each effect: how to spot it, how to build it in After Effects, how to
     build it in Blender, and whether it's an AI job
   - starter build files: an AE `.jsx` scaffold and a Blender `.py` scaffold
5. One implementation, two ways in: a local command for the skill and an HTTP
   endpoint for n8n.

## Non-goals

- No AI inside `reel-frames`. It stays deterministic, cheap and testable.
- No Claude API call inside n8n yet. With the hybrid choice, the AI passes run
  in Claude Code on the subscription. The pass prompts live in the skill, so an
  n8n Claude node can reuse them later.
- No transcription. Caption words are read off the frames in the AI pass, and
  their timings come from the strips.
- The Blender camera is an approximation. It is rebuilt from 2D optical flow,
  not true 3D camera tracking. It gets the rhythm and direction of each move
  right. The polish is manual.

## Architecture

```
reel URL / mp4
   │
   ▼
reel-frames/analysis  (python -m analysis, or POST /analyze)     FREE, no AI
   ├─ probe        fps, size, duration, audio present?
   ├─ cuts         per-frame scene score + luma → shots, each cut typed:
   │               hard | flash | dissolve | whip (motion-blur spike)
   ├─ motion       Farneback optical flow at 180×320 → per-frame
   │               dx, dy, zoom (radial divergence), rotation, blur
   ├─ audio        PCM via ffmpeg → spectral-flux onsets, tempo estimate,
   │               cut↔onset alignment
   └─ render       contact sheets (2 fps, 32 tiles), transition strips
                   (every frame ±6 around each cut), motion.png graph
   │
   ▼
evidence pack/  timeline.json · sheets/*.jpg · strips/*.jpg · motion.png
   │
   ▼
skill: reel-reverse-engineer  (Claude Code)                       AI, budgeted
   pass 1  sheets + motion.png        → sections / visual worlds
   pass 2  each strip + its numbers   → transition & effect names
   pass 3  per section                → build recipe + tool routing
   ledger  image tokens per pass (ceil(w·h/750) after 1568px resize)
   │
   ▼
breakdown.md · timeline.enriched.json · build/rebuild.jsx · build/rebuild_scene.py
```

n8n: the form gets an "Analyze for rebuild" checkbox, and Telegram asks a
yes/no question. When it's yes, the workflow calls `/analyze` after the frames
are uploaded. It then saves the unzipped pack to an `analysis/` subfolder of the
reel's Drive folder and messages the command to run in Claude Code.

## Components

| Unit | Does | Depends on |
|---|---|---|
| `analysis/cuts.py` | scene scores → typed cuts and shots | numpy, ffmpeg |
| `analysis/motion.py` | optical flow → per-frame camera motion | opencv-headless |
| `analysis/audio.py` | onsets, tempo estimate, cut alignment | numpy, ffmpeg |
| `analysis/render.py` | sheets, strips, motion graph | Pillow, opencv |
| `analysis/pack.py` | runs the above and writes the pack | all of the above |
| `analysis/__main__.py` | CLI | pack |
| `analyze_service.py` | `POST /analyze` → zip of the pack | pack, `main.fetch_media` |
| skill `SKILL.md` | 3-pass procedure, budgets, output format | the pack |
| skill `references/` | effect catalog (signal → name → AE/Blender/AI recipe), tool routing, Higgsfield budget rules | — |
| skill `scripts/make_ae_jsx.py` | enriched timeline → AE scaffold | — |
| skill `scripts/make_blender_py.py` | enriched timeline → Blender scaffold | — |

## Error handling

- A reel with no audio still gets a pack. `audio.available=false`, and the
  beat fields are left empty. Instagram sometimes serves Railway a muted copy,
  a known issue covered in the README.
- A reel with no cuts (a single take) gets one shot, and the motion analysis
  carries the breakdown.
- `/analyze` refuses reels longer than `ANALYZE_MAX_SECONDS` (default 180).
  Flow runs at low resolution, so a typical reel takes seconds on Railway CPU.

## Testing

- Unit tests build synthetic clips with ffmpeg:
  - a hard cut
  - a white flash frame
  - a pan (`crop` moving over a test pattern)
  - a zoom (`zoompan`)
  - a click track for onsets

  They assert that the cut is found at the right frame with the right type,
  that motion has the right sign, and that the onsets land within ±1 frame. No
  network access, like the existing tests.
- End-to-end: the Invideo reel `DdjzUhwM0sV` is the reference. Its known cuts
  are 0.50 s (flash), 4.90 s, 5.27 s, 29.00 s, and there's a push-in at 5.4–5.9 s.
- Build files: the `.jsx` runs in After Effects (Beta) on this Mac through
  `osascript`. The `.py` runs in Blender headless (`blender -b -P`).

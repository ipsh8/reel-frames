# Video → mind map with frames: design

- **Status:** Approved design, 2026-09-28. Revised the same day: the canvas
  moved from Whimsical to FigJam, and the breakdown became a deterministic
  pipeline with two narrow model steps.
- **Scope:**
  - `reel-frames`: YouTube support, a long-video mode, and a new
    `/transcript` endpoint
  - a YouTube branch in the n8n workflow **REEL FRAMES to Drive**
  - a new `video-mindmap` toolkit (scripts plus a thin skill) that turns a
    fetched video into a FigJam mind map, with frames and notes beside each
    node

## Problem

Learning from a long tutorial video, such as the 28-minute Higgsfield +
Blender short-film breakdown (`reFzEtCG_m8`), is slow. Everything is linear,
and nothing connects an idea to the moment it's shown on screen.

What we want instead:

- a mind map that grows outward (film → phase → step → technique)
- for every node, the frame that shows it, a short note beside it, and a link
  to that second of the video
- the ability to ask for any node to be expanded later, either from the video
  or from outside research

The fetch step already exists for Instagram reels, but it doesn't work for
YouTube:

- `resolve_url` and `fetch_media` only recognised `instagram.com`. A YouTube
  page link fell through to ffmpeg as if it were a direct file, and failed.
- The reel settings don't scale to a 28-minute video:
  - a 0.5–2 s interval gives 840+ frames
  - `HARD_MAX_FRAMES=300` cuts the frames off around minute 10
  - n8n's HTTP timeout is 300 s
- YouTube blocks data-centre IPs such as Railway's, and yt-dlp now needs a
  JavaScript runtime (Deno) for YouTube.
- Nothing produces a transcript.

## Why FigJam

The user's hard requirement is real video frames on the canvas, beside the
node they illustrate, with notes, all joined by lines. Each canvas was tested
live on 2026-09-28:

| | Whimsical | Miro | FigJam |
|---|---|---|---|
| Place images through the connector | ❌ no image type, no upload | ✅ | ✅ `upload_assets` |
| Notes and shapes | ✅ | ✅ | ✅ stickies, shapes with text |
| Lines attached to images | n/a | ✅ | ✅ |
| Clickable timestamp links in nodes | ✅ | ✅ | ✅ `setRangeHyperlink` |
| Exact control of layout and styling | limited | through Miro's own SVG format | full Figma Plugin API |

FigJam was chosen for the full Plugin API. The cost is a paid seat: only the
user's "My Workspace" team (`team::1633067439777456635`) has one. None of the
three has a built-in mind-map item reachable through its connector, so the
map is drawn as shapes and connectors.

## Goals

1. **One way in.** The Telegram bot and the n8n form accept Instagram reels,
   YouTube Shorts and full YouTube videos, mixed in the same message.
2. **Reels keep working unchanged.** Reels and Shorts go through today's
   path, byte for byte.
3. **Full YouTube videos land in Drive with:**
   - `video.mp4` (720p max)
   - `info.json` (title, channel, duration, description, chapters)
   - `transcript.vtt`
   - `frames/` taken at scene changes, not at fixed intervals
4. **The hand-off is a Telegram message:** "Ready for breakdown → <folder
   link>". The user pastes that link into Claude Code.
5. **Deterministic by default.** Code does every step that has one right
   answer: cleaning the transcript, choosing frames, laying out the tree,
   generating the drawing code, uploading. A model is used only where the
   step needs understanding (see below), and each model step has a fixed
   input, a fixed output format and a validator.
6. **Cheap.** It runs on Sonnet 5, at about 15–20k tokens for a 30-minute
   video, and no image is ever sent to a model.
7. **"Expand node X" works from a screenshot or a code.** Every node shows
   where it came from:
   - A timestamp (`▶ mm:ss`) marks a node taken from the video.
   - `🔍` marks added research.

## Non-goals

- No Claude API call inside n8n. The model steps run in Claude Code on the
  subscription, as Sonnet subagents.
- No transcription on Railway. The fallback is faster-whisper on the Mac.
- No `/analyze` evidence pack for long videos. It stays reel-only
  (≤ `ANALYZE_MAX_SECONDS`).
- No playlists. Any `list=` parameter is stripped and one video is fetched.
- No model looks at frames. Frames are picked by a measurable score. The
  trade-off is that a talking-head shot sometimes wins over the screen, and
  an optional image check can be added later if that happens a lot.
- No verbatim transcript in any output. Node notes paraphrase, and a node
  carries at most one short quote (under 15 words).

## Architecture

```
Telegram / form: any mix of IG reel, YT Short, YT video links
   │
   ▼
n8n  Build Reel Items → kind = reel | youtube   (by URL; /shorts/ counts as reel)
   │                     folder = <run>_<nn>_<ig-code | yt-id>
   ├─ reel ──── existing path, unchanged
   │
   └─ youtube ─ /download (720p, cached) → upload video.mp4
                /transcript  → upload info.json, transcript.vtt   (no subtitles is not fatal)
                /frames mode=scene (from cache) → upload frames/
                Telegram: "Ready for breakdown → <this video's folder>"
   │
   ▼  user pastes folder link (or a YouTube URL) into Claude Code
video-mindmap                                       WORK = ~/Documents/Video Mindmaps/<yt-id>/
   1 prepare   script   info.json + transcript.vtt (from Drive, or yt-dlp locally)
                        → transcript.md: deduped, timestamped, grouped by chapter
                        (no subtitles → faster-whisper first)
   2 structure 🤖 Sonnet  transcript.md → map.json nodes, following the prompt
                        and schema in the toolkit; `vmm validate` must pass
   3 frames    script   3 candidate frames per node → keep the sharpest
                        (Laplacian variance), resized to 960 px
   4 layout    script   tidy-tree layout (root left, branches right); each
                        node gets a frame and a note beside it
   5 render    script   → figjam/manifest.json (frames to upload) and
                        figjam/draw_*.js (compact data + one fixed renderer)
   6 draw      🤖 Sonnet  mechanical only: upload_assets → `vmm upload` →
                        use_figma with each draw_*.js → `vmm record` stores
                        the returned FigJam node ids in map.json
   │
   ▼  later: "expand 3.2" (or a screenshot showing the code)
   7 expand    script   `vmm context 3.2` prints the transcript around the node
               🤖 Sonnet  writes the children as JSON (video, or research with refs)
               script   `vmm add` → re-layout → draw_update.js moves existing
                        nodes and adds the new ones → 🤖 runs it → `vmm record`
```

The model steps are the only points where one step's output needs judgment
to become the next step's input. Everything else is a script with tests.

### Node codes

Nodes are numbered by their place in the tree: `3`, `3.2`, `3.2.1`. A node's
code never changes once it's given. A new child always gets the next free
number under its parent. The code is printed on every FigJam node, so reading
it off a screenshot finds exactly one node.

### map.json (per video)

```json
{
  "video": {"id": "reFzEtCG_m8", "url": "...", "title": "...", "channel": "...", "duration": 1685},
  "figjam": {"file_key": null, "url": null},
  "nodes": [
    {"code": "3.2", "parent": "3", "title": "Video prompting",
     "note": "≤ 25 words, paraphrased", "source": "video | research | user",
     "times": [982], "quote": "≤ 15 words", "frame": "frames/3.2.jpg",
     "refs": ["https://… (research nodes only)"],
     "figjam_ids": {"node": "1:8", "frame": "1:2", "note": "1:16"}}
  ]
}
```

## Changes by component

| Unit | Change |
|---|---|
| `reel-frames/youtube_service.py` (new) | `classify_url()` (`instagram`, `youtube` or `direct`), `canonical_url()` that strips `list=`, `index=` and `t=`, YouTube cookies (`YT_COOKIES_FILE` / `YT_COOKIES_B64`, separate from the IG cookies), the download cache, and `/transcript`. For YouTube, `YTDLP_PROXY` is applied on every endpoint. Format is 720p max, merged to mp4. |
| download cache | The first fetch of a YouTube URL is kept in `/tmp` for `YT_CACHE_SECONDS` (default 3600). `/download`, `/frames`, `/audio` and `/transcript` reuse it, so YouTube is hit once per video. |
| `/frames` | New `mode: "scene"` with `scene_threshold` (default 0.3), `min_gap` (default 3 s), `max_gap` (default 60 s) and `max_frames` up to `SCENE_MAX_FRAMES` (600). `mode: "interval"` stays the default. |
| `/transcript` (new) | Returns `info.json`, plus `transcript.vtt` when English subtitles exist, as a zip or as JSON (`output`). The `X-Transcript` header says `manual`, `auto`, `none` or `blocked`. Missing subtitles are never an error, because n8n needs `info.json` either way. |
| `Dockerfile` | Adds Deno (`COPY --from=denoland/deno:bin /deno /usr/local/bin/deno`) and `yt-dlp[default]` for YouTube's JS challenges. |
| n8n **REEL FRAMES to Drive** | Detects the kind in Build Reel Items. An IF node sends each link to the reel path or the YouTube path. The YouTube path has longer timeouts. The ready message links each video's own folder. |
| n8n fixes (found in review) | Report Reel Failure uses the wrong Telegram bot (Navvya instead of Reel Frames), so it now uses the trigger's bot. The service API key moves out of the node parameters into an n8n Header Auth credential. |
| `video-mindmap` toolkit | A `vmm` command with subcommands (`prepare`, `validate`, `frames`, `layout`, `render`, `upload`, `record`, `context`, `add`), stdlib-only except the frame scorer (Pillow + numpy via `uv run`) and the faster-whisper fallback. |
| `video-mindmap` prompts | `prompts/structure.md` and `prompts/expand.md`: the only instructions a model gets. Each fixes the output JSON shape. |
| `video-mindmap` skill | A thin `SKILL.md` that lists the steps, which ones are scripts and which are a Sonnet subagent, and the copyright rules. |

## Error handling

- **YouTube blocks Railway** ("confirm you're not a bot", 429):
  - The error is passed through word for word and reported per video in
    Telegram.
  - The fix, in order: `YT_COOKIES_B64`, then `YTDLP_PROXY`.
  - If Railway still can't get through, `vmm prepare <YouTube URL>` fetches
    everything on the Mac.
- **No subtitles:** the workflow carries on, and `vmm prepare` runs
  faster-whisper.
- **Video too big for n8n:** the upload is capped at 720p. If a run still
  fails on size, the YouTube path skips uploading `video.mp4`, and
  `vmm prepare` downloads it locally.
- **The model's JSON is invalid:** `vmm validate` lists every problem, and
  the subagent gets one retry with that list. After that the step stops and
  reports.
- **A draw script fails part-way:** each `draw_*.js` returns the ids it
  created, and `vmm record` stores them. Re-running skips nodes that already
  have ids.
- **The user edited the board by hand:** before an expand, `vmm` reads the
  board's node ids back through `get_figjam`. A deleted node is reported, not
  recreated. Hand-added stickies are left alone.

## Testing

- **reel-frames unit tests** (no network, yt-dlp stubbed like the existing
  tests):
  - `classify_url` on reel, Shorts, `watch?v=`, `youtu.be`, `&list=` and `&t=`
    links
  - a cache hit skips the second fetch
  - scene mode on a synthetic clip with 3 hard cuts returns one frame per
    scene and respects `min_gap` and `max_gap`
  - `/transcript` picks manual subtitles over auto ones, and still returns
    `info.json` when there are none
- **Regression:** one Instagram reel through the updated workflow gives the
  same folder contents as today.
- **Toolkit unit tests** (stdlib unittest):
  - transcript cleaning on made-up rolling auto-captions
  - map validation rules
  - node codes stay stable
  - layout has no overlaps and children stay to the right of their parent
  - the generated draw data round-trips
  - the frame scorer prefers a sharp frame over a blurred copy of it
- **End-to-end:** `reFzEtCG_m8` through Telegram, then `vmm`, gives:
  - the Drive folder with all four outputs
  - a FigJam board where every node has a code, a frame, a note and a working
    timestamp link
  - a token count for each model step
- **The expand loop:** expand one node from the video and one with research,
  then check that the existing nodes moved without being recreated.

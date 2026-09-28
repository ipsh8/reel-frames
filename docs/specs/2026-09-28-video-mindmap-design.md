# Video → mind map with frames: design

- **Status:** Draft design, 2026-09-28. Waiting for review.
- **Scope:**
  - `reel-frames`: YouTube support, a long-video mode, and a new
    `/transcript` endpoint
  - a YouTube branch in the n8n workflow **REEL FRAMES to Drive**
  - a new `video-mindmap` skill (skillbook) that does the breakdown, builds
    the Whimsical map and publishes the frame atlas

## Problem

Learning from a long tutorial video, such as the 28-minute Higgsfield +
Blender short-film breakdown (`reFzEtCG_m8`), is slow. Everything is linear,
and nothing connects an idea to the moment it's shown on screen.

What we want instead:

- a detailed written breakdown of the person's workflow
- a mind map that grows outward (film → phase → step → technique)
- for every node, the frames that show it, plus a link to that second of the
  video
- the ability to ask for any node to be expanded later, either from the video
  itself or from outside research

The fetch step already exists for Instagram reels, but it doesn't work for
YouTube:

- `resolve_url` and `fetch_media` only recognise `instagram.com`
  (`main.py:185`, `main.py:226`). A YouTube page link falls through to ffmpeg
  as if it were a direct file, and fails.
- The reel settings don't scale to a 28-minute video:
  - a 0.5–2 s interval gives 840+ frames
  - `HARD_MAX_FRAMES=300` cuts the frames off around minute 10
  - n8n's HTTP timeout is 300 s
- YouTube blocks data-centre IPs such as Railway's, and yt-dlp now needs a
  JavaScript runtime (Deno) for YouTube.
- Nothing produces a transcript, even though the Drive folder is called
  "Transcripts".

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
   link>". The user pastes that link into Claude Code, and the `video-mindmap`
   skill takes it from there.
5. **The skill produces:**
   - `workflow.md`, the detailed breakdown
   - `map.json`, the single source of truth for the map
   - a Whimsical mind map with a code and a timestamp link on every node
   - a private "frame atlas" artifact with one card per node code
6. **"Expand node X" works from a screenshot.** Edits the user made by hand
   in Whimsical are kept, and every node shows where it came from:
   - A timestamp (`▶ mm:ss`) marks a node taken from the video.
   - `🔍` marks added research.

## Non-goals

- No Claude API call inside n8n. The breakdown runs in Claude Code on the
  subscription (the user chose the Telegram hand-off).
- No transcription on Railway. The fallback is faster-whisper on the Mac,
  inside the skill.
- No `/analyze` evidence pack for long videos. It stays reel-only
  (≤ `ANALYZE_MAX_SECONDS`).
- No playlists. Any `list=` parameter is stripped and one video is fetched.
- The atlas is not public. It's a private artifact, and sharing it is the
  user's call.
- No verbatim transcript in any output. `workflow.md` summarises, and each
  node carries at most one short quote (under 15 words).

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
                /transcript  → upload info.json, transcript.vtt   (422 NO_SUBTITLES is not fatal)
                /frames mode=scene (from cache) → upload frames/
                Telegram: "Ready for breakdown → <this video's folder>"
   │
   ▼  user pastes folder link into Claude Code
skill video-mindmap
   1 pull     Drive folder → ~/Documents/Video Mindmaps/<yt-id>/
   2 text     transcript.vtt (or faster-whisper on audio) → segments by chapter
   3 read     Claude reads all segments → workflow.md + map.json
   4 frames   ffmpeg at each node's timestamps (3 candidates) → Claude looks,
              keeps the frames that actually show the step
   5 map      map.json → indented outline → Whimsical create (mind map)
   6 atlas    map.json + frames → atlas.html → private Artifact
   7 record   Whimsical file id + atlas URL saved into map.json
   │
   ▼  later: screenshot + "expand 3.2"
   fetch Whimsical → reconcile manual edits into map.json → add children
   → Whimsical edit → re-render atlas → republish to the same URL
```

### Node codes

Nodes are numbered by their place in the tree: `3`, `3.2`, `3.2.1`. A node's
code never changes once it's given. A new child always gets the next free
number under its parent. The code shows in every Whimsical node and on every
atlas card, so reading it off a screenshot finds exactly one node.

### map.json (per video)

```json
{
  "video": {"id": "reFzEtCG_m8", "url": "...", "title": "...", "channel": "...", "duration": 1685},
  "whimsical": {"file_id": null, "url": null},
  "atlas": {"url": null},
  "nodes": [
    {"code": "3.2", "parent": "3", "title": "Video prompting",
     "summary": "…", "source": "video | research | user",
     "times": [982, 1010], "quote": "≤15 words", "frames": ["frames/3.2_a.jpg"],
     "refs": ["https://… (research nodes only)"]}
  ]
}
```

## Changes by component

| Unit | Change |
|---|---|
| `reel-frames/main.py` | `classify_url()` returns `instagram`, `youtube` or `direct`, and strips `list=`, `index=` and `t=`. The YouTube branch goes into `resolve_url` and `fetch_media`, which uses `noplaylist`. |
| `reel-frames/youtube_service.py` (new) | `YT_COOKIES` / `YT_COOKIES_FILE` are kept separate from the IG cookies. For YouTube, `YTDLP_PROXY` is applied on every endpoint. Format is `bv*[height<=720]+ba/b[height<=720]`, merged to mp4. |
| download cache | The first fetch of a YouTube URL is kept in `/tmp` for `YT_CACHE_SECONDS` (default 3600). `/download`, `/frames` and `/transcript` reuse it, so YouTube is hit once per video. |
| `/frames` | New `mode: "scene"` with `scene_threshold` (default 0.3), `min_gap` (default 3 s) and `max_frames`. `HARD_MAX_FRAMES` is raised to 600 for scene mode. `mode: "interval"` stays the default. |
| `/transcript` (new) | Returns `info.json`, plus `transcript.vtt` when English subtitles exist, as a zip or as JSON (`output`). The `X-Transcript` header says `manual`, `auto`, `none` or `blocked`. Missing subtitles are never an error, because n8n needs `info.json` either way. |
| `Dockerfile` | Adds Deno (`COPY --from=denoland/deno:bin /deno /usr/local/bin/deno`) for yt-dlp's YouTube JS challenges. |
| n8n **REEL FRAMES to Drive** | Detects the kind in Build Reel Items. A Switch sends each link to the reel path or the YouTube path. The YouTube path has a 900 s timeout. The ready message links each video's own folder. |
| n8n fixes (found in review) | Report Reel Failure uses the wrong Telegram bot (Navvya instead of Reel Frames), so it now uses the trigger's bot. The service API key moves out of the node parameters into an n8n Header Auth credential. |
| skill `video-mindmap` | `SKILL.md` covers steps 1–7, the expand loop, the quote and copyright rules, and the node-code rules. |
| skill `scripts/frames_at.py` | ffmpeg frames at given timestamps, plus a contact sheet for choosing between them |
| skill `scripts/to_outline.py` | map.json → the indented outline Whimsical accepts, with a code and a `mm:ss ↗` link on each node |
| skill `scripts/render_atlas.py` | map.json + frames → `atlas.html` (frames published as separate artifact files, not base64) |
| skill `scripts/transcribe.py` | faster-whisper fallback, only used when there's no `transcript.vtt` |

## Error handling

- **YouTube blocks Railway** ("confirm you're not a bot", 429):
  - The error is passed through word for word and reported per video in
    Telegram.
  - The fix, in order: `YT_COOKIES`, then `YTDLP_PROXY`.
  - If Railway still can't get through, the skill can fetch the video itself
    on the Mac given just the YouTube URL.
- **No subtitles:** the workflow carries on, and Telegram says the transcript
  will be made at breakdown time. The skill then runs `transcribe.py`.
- **Video too big for n8n** (it holds binary data in memory): the upload is
  capped at 720p. If a run still fails on size, the YouTube path skips
  uploading `video.mp4`, and the skill downloads it locally instead.
- **Whimsical not connected, or the call fails:** the skill still writes
  `workflow.md`, `map.json` and the atlas, and says the map step is waiting on
  the connector.
- **The user edited the map in Whimsical:** before every expand, the skill
  fetches the map and diffs it against map.json.
  - New nodes are added with `source: "user"` and the next free code.
  - Renamed nodes keep their code and take the new title.

## Open questions, checked once Whimsical is connected

1. Are links inside mind-map node text clickable?
   - If not, the timestamp goes into the node as plain text, and the atlas
     card carries the link.
2. Can a Whimsical board hold images next to a mind map?
   - If it can, frames could go straight onto the canvas and the atlas
     becomes optional.
3. How big a mind map will `create` accept in one call?
   - If there's a limit, build the top two levels first, then add each
     branch with `edit`.

## Testing

- **reel-frames unit tests** (no network, yt-dlp stubbed like the existing
  tests):
  - `classify_url` on reel, Shorts, `watch?v=`, `youtu.be`, `&list=` and `&t=`
    links
  - a cache hit skips the second fetch
  - scene mode on a synthetic clip with 3 hard cuts returns 3–4 frames and
    respects `min_gap`
  - `/transcript` picks manual subtitles over auto ones, and returns 422 when
    there are none
- **Regression:** one Instagram reel through the updated workflow gives the
  same folder contents as today.
- **End-to-end:** `reFzEtCG_m8` through Telegram, then the skill, gives:
  - the Drive folder with all four outputs
  - `workflow.md` covering all 18 chapters
  - a Whimsical map where every node has a code
  - an atlas where every card has at least one frame that was checked by eye
- **Skill scripts:** unit tests for `to_outline.py` (codes, nesting, links)
  and `render_atlas.py` (one card per node, missing frames flagged).
- **The expand loop:** expand one 🎬 node and one 🔍 node. Hand-edit a node
  in Whimsical first, and confirm the edit survives.

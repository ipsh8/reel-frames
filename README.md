# Reel Toolkit (reel-frames)

Send an Instagram reel link, a YouTube link (Shorts or full videos) or a
direct video URL and get back frames, the audio track, the video file, a
YouTube video's info and subtitles, or an **evidence pack** that measures how
a reel was edited (cuts, transitions, camera moves, beats). FastAPI + ffmpeg + yt-dlp
+ OpenCV, no AI. The n8n
reel workflows (e.g. **REEL INTELLI A**, **REEL FRAMES to Drive**) call it on Railway at
`https://reel-frames-production.up.railway.app`.

## Run locally

Needs Python 3.12+ and ffmpeg (which includes ffprobe) on `PATH`.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
API_KEY=dev .venv/bin/uvicorn main:app --port 8000
```

Or with Docker, which is also what Railway builds:

```bash
docker build -t reel-frames .
docker run -p 8000:8000 -e API_KEY=dev reel-frames
```

Deploys as-is to Railway / Render / Fly.io (Dockerfile detected automatically).

## Tests

```bash
.venv/bin/python -m unittest discover -s tests
```

They stand in for yt-dlp, so they never contact Instagram or YouTube. They need ffmpeg
and ffprobe on `PATH` to build the small test clips; without them the tests
are skipped.

## API

Every `POST` needs the `X-API-Key` header set to the `API_KEY` env var.

| Endpoint | Body | Returns |
|---|---|---|
| `POST /frames` | see below | frames as a zip, or JSON with base64 frames |
| `POST /audio` | `{"video_url": "..."}` | the reel's sound as `audio.mp3` (mono, 64 kbps) |
| `POST /download` | `{"video_url": "..."}` | the reel as `reel.mp4`, with its sound (YouTube: `video.mp4`, 720p max) |
| `POST /transcript` | `{"video_url": "...", "output": "zip"\|"json"}` | YouTube only: `info.json` (title, channel, duration, description, chapters) plus `transcript.vtt` when English subtitles exist. `X-Transcript` header: `manual`, `auto`, `none` or `blocked`. Missing subtitles are not an error |
| `POST /audio-duration` | `{"audio_b64": "..."}` | `{"duration": <seconds>}` via ffprobe |
| `POST /analyze` | `{"video_url": "..."}` | the evidence pack as `analysis.zip` (see [Reel analysis](#reel-analysis-evidence-pack)) |
| `GET /health` | — | `{"status": "ok", "version": ...}`, no key needed |

`/frames` body:

```json
{
  "video_url": "https://.../video.mp4",   // direct mp4 (Apify output) OR instagram.com/reel/... URL
  "interval": 2.0,                        // seconds between frames
  "max_frames": 60,
  "width": 720,                           // optional resize, keeps aspect ratio
  "quality": 2,                           // 1=best, 31=worst
  "start": 0,                             // start offset in seconds
  "output": "zip",                        // "zip" (JPEGs) or "json" (base64 frames + timestamps)
  "mode": "interval"                      // or "scene": see below
}
```

`mode: "scene"` is for long videos, where a fixed interval gives hundreds of
near-identical frames. It keeps a frame when the picture changes, and ignores
`interval`:

- `scene_threshold` (default 0.3): how big a change counts
- `min_gap` (default 3 s): the shortest time between two frames
- `max_gap` (default 60 s): a frame is taken anyway after this long without
  a change, so talking-head stretches are still covered
- `max_frames`: up to `SCENE_MAX_FRAMES` (600) in this mode, and up to
  `HARD_MAX_FRAMES` (300) in interval mode

- `output: "zip"` → `frames.zip`, filenames include timestamps (`frame_0003_t6.0s.jpg`), `X-Frame-Count` header
- `output: "json"` → `{count, frames: [{index, timestamp, filename, image_base64}]}` — use this from n8n (HTTP Request node → split out `frames`)

### Errors worth knowing

- `422 REEL_HAS_NO_AUDIO` from `/audio`: Instagram gave the server no sound
  for that reel. The reel may be silent, but Instagram can also give the server
  a muted copy of a reel that plays with sound in a browser. The message lists
  the formats the server was offered (`id=audio codec`, where `none` means no
  audio and `?` means unknown), and the same line is in the Railway logs as
  `[fetch_media]`. For some reels Instagram sends this server a muted copy
  (every audio codec `none`) that a phone or home connection gets with sound —
  logged in or not, in any Railway region. Set `YTDLP_PROXY` (below) so
  `/audio` and `/download` reach Instagram through a home connection.
  `cookies on (IG_COOKIES, but no sessionid…)` means what was pasted as
  `IG_COOKIES` isn't a login.
- `422 Media download failed: ...`: yt-dlp couldn't fetch the reel. It was
  deleted, it's private, or Instagram rate-limited the server. See
  `IG_COOKIES` below.

## Examples

```bash
curl -X POST http://localhost:8000/audio \
  -H "X-API-Key: dev" -H "Content-Type: application/json" \
  -d '{"video_url":"https://www.instagram.com/reel/ABC123/"}' -o audio.mp3

curl -X POST http://localhost:8000/frames \
  -H "X-API-Key: dev" -H "Content-Type: application/json" \
  -d '{"video_url":"https://instagram.com/reel/ABC123/","interval":3,"output":"json","width":480}'
```

## Reel analysis (evidence pack)

`analysis/` measures a reel's edit so an AI (the `reel-reverse-engineer`
skill) only has to *name* what was measured, not hunt for it frame by frame.
Same code, two ways in:

```bash
.venv/bin/python -m analysis https://www.instagram.com/reel/ABC123/ -o pack/   # or a local .mp4
curl -X POST http://localhost:8000/analyze -H "X-API-Key: dev" \
  -H "Content-Type: application/json" -d '{"video_url":"https://www.instagram.com/reel/ABC123/"}' -o analysis.zip
```

What's in the pack:

| File | What it is |
|---|---|
| `summary.md` | The compact view: shot table (cut type, source fps, camera moves with easing), overlay changes, audio, image list with token costs. **This is what the AI reads.** |
| `timeline.json` | Everything, including per-frame arrays (`diff, luma, sharp, dx, dy, zoom, rot, resid, comp, spread`) |
| `sheets/` | The reel at 2 fps, 32 labelled tiles per sheet |
| `strips/` | Every frame around each cut, each hidden whip inside a shot, and each unsure overlay change; the transition frames are outlined |
| `motion.png` | All signals on one timeline, cuts coloured by type, audio onsets as ticks |

How it measures, in one pass at 180 px wide:

- **Camera motion**: textured corners are tracked (Lucas–Kanade) and a
  similarity transform is RANSAC-fitted per frame → pan, tilt, zoom, roll.
  Dense optical flow was tried first and rejected: flat areas (solid
  backgrounds, sky) report zero motion and outvote the moving parts.
- **Cuts**: the previous frame is warped by that camera move before comparing,
  so a crash zoom inside a shot doesn't hide (or fake) a cut. Each edit is
  typed `hard`, `flash`, `dip`, `whip`, `dissolve` (frames that really are a
  blend of before/after), or `graphic` (only part of the frame changed: a
  caption or sticker swap, kept because it times the captions).
- **Camera moves**: each shot is split into push-in / pull-out / pan / tilt /
  roll / whip / static runs with `ease-in`, `ease-out`, `ease-in-out` or `linear`.
- **Source frame rate**: single repeated frames reveal the rate a shot was
  made at. AI video is usually 24 fps and shows up as 24 on a 30 fps timeline.
- **Audio**: spectral-flux onsets, a tempo estimate, and each cut's offset to
  the nearest onset, next to the share of cuts that would land "on beat" by
  chance (voiceover is dense, so the raw ratio alone misleads).

Known limits: in flat UI/motion-graphics sections, the "camera" can be UI
elements moving; the strips settle it. Borderline cut-vs-overlay calls are
marked `(unsure)`. A 32 s reel takes about 15 s on a laptop.

## How Instagram media is fetched

Instagram offers each reel in two forms: separate DASH streams (video-only and
audio-only), and a few pre-muxed MP4s. yt-dlp lists the pre-muxed files with
unknown codecs because Instagram doesn't say what's in them, and some of them
have **no audio track**. So:

- `/frames` resolves one stream URL and reads it directly. It's fast, and
  frames don't need sound.
- `/audio` downloads the audio-only stream (`ba`), which is small and always
  has sound. It only falls back to a pre-muxed file if Instagram offers no
  separate audio.
- `/download` takes a pre-muxed MP4 (H.264). If ffprobe finds it silent, it
  downloads the video and audio streams and merges them instead (VP9 + AAC).

Direct CDN `.mp4` URLs (what the Apify Instagram scraper returns in
`videoUrl`) skip yt-dlp and go straight to ffmpeg.

## How YouTube videos are fetched

- **One download per video.** The first request for a YouTube link downloads
  the video once, at 720p max, as an mp4 with sound. `/download`, `/frames`,
  `/audio` and `/transcript` all reuse that copy for `YT_CACHE_SECONDS`
  (default one hour), so a whole n8n run asks YouTube for the video once and
  for the subtitles once. Old copies are deleted automatically.
- **Exactly one video.** Every link shape works (`watch?v=`, `youtu.be/`,
  `/shorts/`, `/live/`, `/embed/`). Playlist and time parameters are dropped,
  so a `&list=` link can never pull a whole playlist.
- **Shorts** go through the same cache. The n8n workflow treats them like
  reels.
- **Subtitles.** `/transcript` prefers people-written English subtitles, then
  YouTube's automatic ones for the spoken language (`en-orig`), then the
  automatic English track.
- **Deno.** yt-dlp needs a JavaScript runtime to solve YouTube's challenges.
  The Docker image includes Deno. Run locally without it, and some formats go
  missing.

**YouTube bot checks.** YouTube often refuses data-centre servers like
Railway's with "Sign in to confirm you're not a bot" or `HTTP Error 429`.
Those errors come back word for word as a 422. Fix it in this order:

1. Set `YT_COOKIES_B64` (below).
2. Set `YTDLP_PROXY`. For YouTube, every endpoint uses it.

## Env vars

See `.env.example`.

| Var | Default | |
|---|---|---|
| `API_KEY` | — | **required**; clients send it as `X-API-Key` |
| `PORT` | — | **Railway only; set it to `8000`.** The app always listens on 8000 (Dockerfile), but Railway's `/health` healthcheck (`railway.json`) probes `PORT`. Without it every deploy failed the healthcheck and Railway kept the old version |
| `IG_COOKIES` | — | optional; the `Cookie` header from a logged-in instagram.com request, pasted as one line (`sessionid=…; csrftoken=…`). Logs the server in, so Instagram stops withholding audio. Use a throwaway account |
| `IG_COOKIES_FILE` | — | optional path to a Netscape `cookies.txt`; used instead of `IG_COOKIES` when both are set |
| `YTDLP_PROXY` | — | optional; `http://user:pass@host:port`. `/audio` and `/download` reach Instagram through it, so reels Instagram mutes for this server come back with sound, and every YouTube request goes through it. Use a **residential** proxy; `/frames` never uses it for Instagram |
| `YT_COOKIES_B64` | — | optional; a YouTube `cookies.txt`, base64-encoded (see below). Use when YouTube bot-checks the server |
| `YT_COOKIES_FILE` | — | optional path to a YouTube `cookies.txt`; used instead of `YT_COOKIES_B64` when both are set |
| `YT_CACHE_SECONDS` | 3600 | how long a downloaded YouTube video is kept for reuse |
| `FFMPEG_TIMEOUT` | 180 | seconds per ffmpeg/ffprobe run |
| `YTDLP_TIMEOUT` | 60 | seconds for yt-dlp to resolve a URL (`/frames`) |
| `HARD_MAX_FRAMES` | 300 | server-side cap on `max_frames` in interval mode |
| `SCENE_MAX_FRAMES` | 600 | server-side cap on `max_frames` in scene mode |
| `FFMPEG_SCENE_TIMEOUT` | 1200 | seconds scene mode may take (it decodes the whole video) |
| `ANALYZE_MAX_SECONDS` | 180 | `/analyze` refuses longer videos (422) |

### Getting `IG_COOKIES`

1. Log in to instagram.com in Chrome **with a throwaway account** — automated
   downloading can get an account flagged.
2. Open DevTools (Cmd+Option+I) → **Network** tab → reload the page.
3. Click the first request to `www.instagram.com`, then under **Request
   Headers** copy the value of `cookie`.
4. In Railway → this service → **Variables**, add `IG_COOKIES` with that value.
5. Don't log out in that browser — logging out cancels the session the server
   is using. Just close the tab.

The value is a login. Keep it out of git, chat and logs. When Instagram
eventually ends the session, errors say `cookies on` but audio disappears again;
repeat the steps with a fresh copy.

### Getting `YT_COOKIES_B64`

1. In Chrome, log in to youtube.com **with a throwaway Google account**.
   Automated downloading can get an account flagged.
2. Export the cookies for youtube.com as `cookies.txt` with a cookies.txt
   exporter extension (Netscape format).
3. On the Mac, run `base64 -i cookies.txt | pbcopy`.
4. In Railway → this service → **Variables**, add `YT_COOKIES_B64` and paste.
5. Delete the local `cookies.txt`. It's a login, so keep it out of git, chat
   and logs.

### Getting `YTDLP_PROXY`

Instagram sends a data-centre server muted copies of some reels. A residential
proxy makes the server's requests arrive from a home connection instead.

1. Sign up with a provider that sells **residential** proxies with Indian IPs
   (IPRoyal, Decodo/Smartproxy and Bright Data all do). Datacenter proxies won't
   help — that is the problem being worked around. Billing is per GB; a reel's
   audio is under 1 MB and a video a few MB.
2. In their dashboard pick **India** as the location and, if offered, a
   **sticky** session, so one download keeps one IP.
3. Copy the address in this form: `http://USERNAME:PASSWORD@HOST:PORT`.
4. In Railway → this service → **Variables**, add `YTDLP_PROXY` with it.

It contains a password. Errors and logs say only `proxy on` or `proxy off`, and
strip the address and credentials out of anything yt-dlp reports.

`yt-dlp` is unpinned in `requirements.txt`, so each Railway rebuild picks up
the latest release. Instagram changes often, so if fetching breaks, redeploying
is the first thing to try.

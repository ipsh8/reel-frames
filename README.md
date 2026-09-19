# Reel Toolkit (reel-frames)

Send an Instagram reel link (or a direct video URL) and get back frames, the
audio track, or the video file. FastAPI + ffmpeg + yt-dlp, no AI. The n8n
reel workflows (e.g. **REEL INTELLI A**) call it on Railway at
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

They stand in for yt-dlp, so they never contact Instagram. They need ffmpeg
and ffprobe on `PATH` to build the small test clips; without them the tests
are skipped.

## API

Every `POST` needs the `X-API-Key` header set to the `API_KEY` env var.

| Endpoint | Body | Returns |
|---|---|---|
| `POST /frames` | see below | frames as a zip, or JSON with base64 frames |
| `POST /audio` | `{"video_url": "..."}` | the reel's sound as `audio.mp3` (mono, 64 kbps) |
| `POST /download` | `{"video_url": "..."}` | the reel as `reel.mp4`, with its sound |
| `POST /audio-duration` | `{"audio_b64": "..."}` | `{"duration": <seconds>}` via ffprobe |
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
  "output": "zip"                         // "zip" (JPEGs) or "json" (base64 frames + timestamps)
}
```

- `output: "zip"` → `frames.zip`, filenames include timestamps (`frame_0003_t6.0s.jpg`), `X-Frame-Count` header
- `output: "json"` → `{count, frames: [{index, timestamp, filename, image_base64}]}` — use this from n8n (HTTP Request node → split out `frames`)

### Errors worth knowing

- `422 REEL_HAS_NO_AUDIO` from `/audio`: Instagram serves no sound for that
  reel. It was posted silent or muted for unlicensed music. Retrying won't help.
- `422 Media download failed: ...`: yt-dlp couldn't fetch the reel. It was
  deleted, it's private, or Instagram rate-limited the server. See
  `IG_COOKIES_FILE` below.

## Examples

```bash
curl -X POST http://localhost:8000/audio \
  -H "X-API-Key: dev" -H "Content-Type: application/json" \
  -d '{"video_url":"https://www.instagram.com/reel/ABC123/"}' -o audio.mp3

curl -X POST http://localhost:8000/frames \
  -H "X-API-Key: dev" -H "Content-Type: application/json" \
  -d '{"video_url":"https://instagram.com/reel/ABC123/","interval":3,"output":"json","width":480}'
```

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

## Env vars

See `.env.example`.

| Var | Default | |
|---|---|---|
| `API_KEY` | — | **required**; clients send it as `X-API-Key` |
| `IG_COOKIES_FILE` | — | optional path to a Netscape `cookies.txt` for yt-dlp, for gated/private reels |
| `FFMPEG_TIMEOUT` | 180 | seconds per ffmpeg/ffprobe run |
| `YTDLP_TIMEOUT` | 60 | seconds for yt-dlp to resolve a URL (`/frames`) |
| `HARD_MAX_FRAMES` | 300 | server-side cap on `max_frames` |

`yt-dlp` is unpinned in `requirements.txt`, so each Railway rebuild picks up
the latest release. Instagram changes often, so if fetching breaks, redeploying
is the first thing to try.

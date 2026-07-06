# Reel Frame Extractor

Send a video link → get frames back at a configurable interval. FastAPI + ffmpeg + yt-dlp.

## Run

```bash
docker build -t reel-frames .
docker run -p 8000:8000 reel-frames
```

Deploys as-is to Railway / Render / Fly.io (Dockerfile detected automatically).

## API

`POST /frames`

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

## Examples

```bash
# zip
curl -X POST http://localhost:8000/frames \
  -H "Content-Type: application/json" \
  -d '{"video_url":"https://scontent.cdninstagram.com/....mp4","interval":2}' \
  -o frames.zip

# json for n8n
curl -X POST http://localhost:8000/frames \
  -d '{"video_url":"https://instagram.com/reel/ABC123/","interval":3,"output":"json","width":480}'
```

## Instagram URLs

Direct CDN `.mp4` URLs (what the Apify Instagram scraper returns in `videoUrl`) are read by ffmpeg directly — fastest path, use these when you have them. Page URLs (`instagram.com/reel/...`) are resolved via yt-dlp first; for gated/private content mount a `cookies.txt` and set `IG_COOKIES_FILE=/path/cookies.txt`.

## Env vars

| Var | Default | |
|---|---|---|
| `FFMPEG_TIMEOUT` | 120 | seconds |
| `YTDLP_TIMEOUT` | 60 | seconds |
| `HARD_MAX_FRAMES` | 300 | server-side cap |
| `IG_COOKIES_FILE` | — | optional cookies.txt for yt-dlp |

# Changelog

All notable changes to this project. Format follows
[Keep a Changelog](https://keepachangelog.com); dates are ISO 8601.

## [3.5.0] - 2026-09-28

### Added
- YouTube links work on every endpoint: full videos, Shorts, `youtu.be`,
  live and embed links. Playlist and time parameters are dropped, so one link
  always means one video. ([20a2648](https://github.com/ipsh8/reel-frames/commit/20a2648))
- Each YouTube video is downloaded once (720p max, mp4 with sound) and reused
  by `/download`, `/frames`, `/audio` and `/transcript` for `YT_CACHE_SECONDS`,
  so YouTube's bot checks see one request per video. YouTube requests use
  `YTDLP_PROXY` and optional `YT_COOKIES_B64` / `YT_COOKIES_FILE`.
  ([a7bc121](https://github.com/ipsh8/reel-frames/commit/a7bc121))
- `POST /transcript`: a YouTube video's `info.json` (title, chapters,
  description) plus English subtitles when they exist. It prefers
  people-written subtitles and reports `manual`, `auto`, `none` or `blocked`
  instead of failing. ([511801c](https://github.com/ipsh8/reel-frames/commit/511801c))
- `/frames` `mode: "scene"`: frames at scene changes, spaced by `min_gap`, with
  one at least every `max_gap`, for long videos where a fixed interval gives
  hundreds of near-duplicates. New `SCENE_MAX_FRAMES` and
  `FFMPEG_SCENE_TIMEOUT`. ([181124c](https://github.com/ipsh8/reel-frames/commit/181124c))
- Feature doc: `docs/features/2026-09-28-youtube-videos.md`.

### Changed
- The Docker image includes Deno, and the requirements use `yt-dlp[default]`,
  which YouTube downloads now need. ([2e8f33f](https://github.com/ipsh8/reel-frames/commit/2e8f33f))

## [3.4.0] - 2026-09-28

### Added
- Reel analysis: `python -m analysis` and `POST /analyze` build an evidence
  pack for reverse-engineering a reel's edit — typed cuts (hard, flash, dip,
  whip, dissolve, caption/overlay changes), camera moves with easing, each
  shot's source frame rate, audio onsets and cut timing, plus contact sheets,
  every-frame transition strips and a motion graph sized to be cheap for an AI
  to read (~11k image tokens for a 32 s reel instead of ~1.5M for every frame).
  Feature doc: `docs/features/2026-09-28-reel-analysis-pack.md`.
  ([fb3b6a4](https://github.com/ipsh8/reel-frames/commit/fb3b6a4),
  [a209707](https://github.com/ipsh8/reel-frames/commit/a209707),
  [6e5c54e](https://github.com/ipsh8/reel-frames/commit/6e5c54e),
  [7d54f35](https://github.com/ipsh8/reel-frames/commit/7d54f35),
  [3898e57](https://github.com/ipsh8/reel-frames/commit/3898e57),
  [10c3cab](https://github.com/ipsh8/reel-frames/commit/10c3cab))
- `ANALYZE_MAX_SECONDS` (default 180).

### Fixed
- A clear cut right after a busy shot (walking legs, crowds) was missed
  because that shot's own motion raised the bar. A strong change across nearly
  the whole frame now counts at a lower ratio.
  ([7fd6b73](https://github.com/ipsh8/reel-frames/commit/7fd6b73))
- Dependency: `opencv-python-headless`.

## [3.3.0] - 2026-09-19

### Added
- `YTDLP_PROXY`: `/audio` and `/download` reach Instagram through a proxy.
  Instagram sent this server a muted copy of a reel — `has_audio: false`, no
  audio stream offered — logged in via `IG_COOKIES` or not, and after moving the
  service from its original region to Singapore. The same code, on the same
  yt-dlp route, from a home connection in India gets the sound. What differs is
  that Railway is a data centre; a residential proxy removes that difference.
  `/frames` stays direct: it never needs audio, and proxies bill per byte.
- Errors and logs report `proxy on`/`off` and never the proxy address or its
  password.

### Changed
- The 3.2.0 note that logging in fixes missing audio was wrong for this case.
  `IG_COOKIES` stays useful for gated reels.

## [3.2.0] - 2026-09-19

### Added
- `IG_COOKIES`: paste the `Cookie` header from a logged-in instagram.com
  request into a Railway variable and the server downloads as that account.
  Logged out, Instagram withheld the audio stream from Railway for a reel that
  has sound — the same reel, same yt-dlp version, fetched logged-out from a
  home connection, was offered it — so `/audio` failed with
  `REEL_HAS_NO_AUDIO`. `IG_COOKIES_FILE` needed a file on the server's disk,
  which a Railway deploy has no way to receive without committing a login.
- Errors and logs now say where cookies came from, and flag cookies with no
  `sessionid` — what a logged-out browser has — as not a login.

## [3.1.2] - 2026-09-19

Shipped in [5211ae5](https://github.com/ipsh8/reel-frames/commit/5211ae5).

### Changed
- `REEL_HAS_NO_AUDIO` no longer claims the reel is silent. After 3.1.1 went
  live, Railway got no audio for a reel that has sound when fetched from
  elsewhere, so the error (and a `[fetch_media]` log line) now lists the
  formats Instagram offered the server, whether cookies were used, and the
  yt-dlp version. That shows what the server is actually offered.

## [3.1.1] - 2026-09-19

Shipped in [37426a0](https://github.com/ipsh8/reel-frames/commit/37426a0).

### Fixed
- `/audio` failed with `422 No audio track found ... Output file does not
  contain any stream` on reels that do have sound. The service downloaded
  Instagram's pre-muxed MP4, and some of those have no audio track. `/audio`
  now downloads the separate audio-only stream instead.
- `/download` could return a silent video for the same reason. It now checks
  the file with ffprobe and, if it's silent, merges the video and audio
  streams.
- A reel that really has no sound now returns a plain
  `422 REEL_HAS_NO_AUDIO` from `/audio` instead of an ffmpeg error.

### Added
- Tests for `/audio` and `/download` that simulate Instagram's formats
  offline, plus a README covering every endpoint, env var and test command,
  and a `.env.example`.

## [3.1.0] - 2026-07-29

### Changed
- `/audio` and `/download` download the media with yt-dlp instead of reading a
  single resolved stream URL.

Earlier history is in `git log`.

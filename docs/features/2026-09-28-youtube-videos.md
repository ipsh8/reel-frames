# YouTube videos in the reel toolkit

- **Status:** Shipped 2026-09-28, v3.5.0 (commits `20a2648`, `a7bc121`,
  `511801c`, `181124c`, `2e8f33f`)
- **Design:** `docs/specs/2026-09-28-video-mindmap-design.md`. This feature
  is the service half of that design; the FigJam mind map is built on top
  of it.

## Problem

We want to break long YouTube tutorials down into mind maps with frames. The
toolkit only understood Instagram:

- Any other link went straight to ffmpeg as if it were a video file, so a
  YouTube page failed.
- Fixed-interval frames don't scale. A 28-minute video at 2 s is 840 frames,
  and the 300-frame cap cut it off around minute 10.
- Nothing returned a transcript or the video's chapters.

## Goals

- Every endpoint accepts YouTube links, and one link always means one video.
- YouTube is asked for each video as few times as possible, because it
  bot-checks data-centre servers.
- The video's info, chapters and subtitles are available to n8n.
- Frames for long videos are meaningful, not fixed-interval duplicates.

## Non-goals

- No transcription on the server. When a video has no subtitles, the Mac
  transcribes it with faster-whisper.
- No `/analyze` for long videos. The evidence pack stays reel-sized.
- No playlists.

## Approach

**A cache instead of repeated downloads.** n8n calls `/download`,
`/transcript` and `/frames` for the same video, one after another. The first
call downloads the video (720p, mp4 with sound) to `/tmp/yt-cache/<id>/` and
writes a trimmed `info.json` next to it. The rest reuse that copy.

- A per-video lock stops two requests downloading the same video at once.
- Copies unused for `YT_CACHE_SECONDS` are deleted on the next request,
  because Railway's disk is small.
- `/download` serves the cached file directly instead of copying 300 MB again.

**Subtitles never fail the request.** n8n needs `info.json` even when a video
has no English subtitles. So `/transcript` always returns it, and says in
`X-Transcript` whether the subtitles were `manual`, `auto`, `none` or
`blocked` (for example a 429). The track order is people-written English,
then YouTube's automatic track for the spoken language (`en-orig`), then the
automatic English track, which can be a machine translation.

**Scene frames in one ffmpeg pass.** A `select` expression keeps:

- the first frame
- any frame whose scene score passes the threshold, if at least `min_gap`
  has passed
- a frame after `max_gap` with no change, so talking-head stretches still
  get covered

It scores at 2 fps, which makes a 30-minute video affordable on Railway's
CPU, and reads timestamps from `showinfo`.

**Deno in the image.** Current yt-dlp needs a JavaScript runtime for
YouTube's challenges. Without one, formats go missing.

## Follow-ups

- Confirm on Railway that YouTube lets the server download. If it bot-checks,
  set `YT_COOKIES_B64`, then `YTDLP_PROXY` (README → How YouTube videos are
  fetched).
- The Docker image was not built locally (the Docker daemon wasn't running).
  The Railway build is the first real check of the Deno copy.

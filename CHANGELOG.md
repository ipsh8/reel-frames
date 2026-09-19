# Changelog

All notable changes to this project. Format follows
[Keep a Changelog](https://keepachangelog.com); dates are ISO 8601.

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

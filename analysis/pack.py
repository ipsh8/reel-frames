"""Run every measurement and write the evidence pack the AI pass reads.

Layout of `out_dir`:
  timeline.json   everything, machine-readable (per-frame arrays included)
  summary.md      the compact text view; the AI reads this, not timeline.json
  motion.png      all signals on one timeline
  sheets/         the reel at 2 fps
  strips/         every frame around each cut, whip and unsure caption swap
"""
import json
import os

from PIL import Image

from . import render
from .audio import analyze_audio
from .cuts import detect_cuts, shots_from_cuts
from .moves import SHAKE_JITTER, WHIP_SPEED, camera_moves, shake, source_cadence
from .probe import probe
from .signals import measure

VERSION = 1


def _strip_events(cuts, shots_moves):
    events = [{"frame": c.frame, "span": c.span, "kind": c.type}
              for c in cuts if c.type != "graphic" or c.confidence == "low"]
    cut_frames = {c.frame for c in cuts}
    for moves in shots_moves:
        for m in moves:
            # A fast whip inside a shot is often a hidden transition (blur-whip between two clips).
            near_cut = any(m.start_frame - 3 <= f <= m.end_frame + 3 for f in cut_frames)
            if m.type == "whip" and m.peak_speed > WHIP_SPEED and not near_cut:
                events.append({"frame": m.start_frame, "span": (m.start_frame, m.end_frame), "kind": "move"})
    return sorted(events, key=lambda e: e["frame"])


def _moves_text(moves):
    parts = []
    for m in moves:
        ease = "" if m.ease == "linear" else f" {m.ease}"
        amount = f" {m.total:+.0%}" if m.type in ("push-in", "pull-out") else ""
        parts.append(f"{m.start:.2f} {m.type}{amount}{ease}")
    return " → ".join(parts)


def _summary(info, shots, cuts, audio, images, tokens):
    lines = [
        "# Evidence pack",
        "",
        f"{info.width}×{info.height}, {info.fps:g} fps, {info.duration:.2f} s, {info.frames} frames, "
        f"audio {'yes' if info.has_audio else 'no'}.",
        "Motion is from the camera's point of view. `src fps` is the rate the shot was made at, from repeated "
        "frames (24 on a 30 fps timeline = typical AI video). UI/graphic sections: 'camera' motion may be "
        "elements moving, not a camera — check the strips.",
        "",
        "## Shots",
        "",
        "| Shot | Time | Cut in | src fps | Shake | Camera |",
        "|---|---|---|---|---|---|",
    ]
    for shot in shots:
        c = shot["cut_in"]
        cut = "—" if c is None else f"{c['type']}" + (" (unsure)" if c["confidence"] == "low" else "")
        lines.append(f"| S{shot['index']:02d} | {shot['start']:.2f}–{shot['end']:.2f} | {cut} | "
                     f"{shot['source_fps'] or '?'} | {'yes' if shot['shake'] > SHAKE_JITTER else 'no'} | "
                     f"{shot['moves_text']} |")
    graphics = [c for c in cuts if c["type"] == "graphic"]
    if graphics:
        lines += ["", "## Overlay changes (captions, stickers, UI swaps)", "",
                  ", ".join(f"{c['time']:.2f}s" + ("?" if c["confidence"] == "low" else "") for c in graphics)]
    lines += ["", "## Audio", ""]
    if audio["available"]:
        lines.append(f"{len(audio['onsets'])} onsets, tempo ≈ {audio['tempo_bpm']} bpm. "
                     f"{audio['cuts_on_onset_ratio']:.0%} of cuts within ±2 frames of an onset "
                     f"(chance would give {audio['chance_ratio']:.0%}).")
        offsets = ", ".join(f"f{k}:{v:+d}" for k, v in audio["cut_offsets_frames"].items())
        lines.append(f"Cut → nearest onset (frames, − = sound first): {offsets}")
    else:
        lines.append("No audio track (or Instagram served a muted copy).")
    lines += ["", "## Images", "", f"Estimated image tokens if all are read: {tokens['total']}", ""]
    for s in images["sheets"]:
        lines.append(f"- `{s['file']}` {s['from']:.1f}–{s['to']:.1f}s ({tokens['per_image'][s['file']]} tok)")
    for s in images["strips"]:
        lines.append(f"- `{s['file']}` {s['kind']} at f{s['frame']} ({tokens['per_image'][s['file']]} tok)")
    lines.append(f"- `{images['motion_graph']}` ({tokens['per_image'][images['motion_graph']]} tok)")
    return "\n".join(lines) + "\n"


def build_pack(video, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    info = probe(video)
    sig = measure(video, info)
    n = sig.n
    cuts = detect_cuts(sig)
    shots = shots_from_cuts(cuts, n, info.fps)
    shots_moves = [camera_moves(sig, s) for s in shots]
    audio = analyze_audio(video, info.fps, [c for c in cuts if c.type != "graphic"])

    def shot_of(frame):
        return next((s.index for s in shots if s.start_frame <= frame <= s.end_frame), shots[-1].index)

    images = {
        "sheets": render.contact_sheets(video, info.fps, n, shot_of, out_dir),
        "strips": render.transition_strips(video, _strip_events(cuts, shots_moves), n, info.fps, out_dir),
    }
    cut_dicts = [c.to_dict() for c in cuts]
    images["motion_graph"] = render.motion_graph(sig, cut_dicts, audio["onsets"], os.path.join(out_dir, "motion.png"))

    per_image = {}
    for rel in [s["file"] for s in images["sheets"]] + [s["file"] for s in images["strips"]] + [images["motion_graph"]]:
        with Image.open(os.path.join(out_dir, rel)) as im:
            per_image[rel] = render.image_tokens(*im.size)
    tokens = {"per_image": per_image, "total": sum(per_image.values()),
              "rule": "ceil(w*h/750) after fitting 1568px long edge and 1.15MP"}

    shot_dicts = []
    for shot, moves in zip(shots, shots_moves):
        d = shot.to_dict()
        d.update(source_cadence(sig, shot))
        d["shake"] = shake(sig, shot)
        d["moves"] = [m.to_dict() for m in moves]
        d["moves_text"] = _moves_text(moves)
        shot_dicts.append(d)

    timeline = {
        "version": VERSION,
        "source": {"file": os.path.basename(video), **info.to_dict()},
        "cuts": cut_dicts,
        "shots": shot_dicts,
        "audio": audio,
        "frames": sig.to_lists(),
        "images": images,
        "token_estimate": tokens,
    }
    with open(os.path.join(out_dir, "timeline.json"), "w") as f:
        json.dump(timeline, f, indent=1)
    with open(os.path.join(out_dir, "summary.md"), "w") as f:
        f.write(_summary(info, shot_dicts, cut_dicts, audio, images, tokens))
    return timeline


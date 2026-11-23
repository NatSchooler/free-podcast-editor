#!/usr/bin/env python3
"""Slice 'HH:MM:SS - HH:MM:SS | mode | optional hook text' lines from <ep>_clean.mp4. Frame-accurate (re-encoded), so shorts never
start mid-word. Used by both watch_youtube.sh and the dashboard.  Usage: slice_clips.py EPISODE FILE"""
import os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ai_common import HUB, parse_range, s2ts, status, set_hook_text

YT_OUT = os.path.join(HUB, "youtube_long/output")
SPLIT_IN = os.path.join(HUB, "split_screen/input")
SHORTS_IN = os.path.join(HUB, "shorts_daily/input")
PODCAST_OUT = os.path.join(HUB, "podcast_audio/output")


def slice_text(ep, text, job=None):
    src = os.path.join(YT_OUT, f"{ep}_clean.mp4")
    if not os.path.isfile(src):
        return 0
    todo = []
    for line in text.replace("\r", "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("|")
        r = parse_range(parts[0])
        if not r:
            continue
        mode = parts[1].strip().lower() if len(parts) > 1 and parts[1].strip() else "split"
        hook = parts[2].strip() if len(parts) > 2 else ""
        todo.append((r, mode, hook))
    job = job or re.sub(r"[^A-Za-z0-9._-]", "_", f"clips_{ep}")
    n = 0
    for i, ((s, e), mode, hook) in enumerate(todo, 1):
        status(job, "clips", i, len(todo), f"Slicing {mode} clip {i}/{len(todo)} ({s2ts(s)})", "running",
               sum(b - a for (a, b), _, _ in todo) if i == 1 else None)
        tag = s2ts(s).replace(":", "")
        base = ["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-ss", f"{s:.3f}", "-i", src, "-t", f"{e - s:.3f}"]
        if mode in ("audio", "mp3"):
            out = os.path.join(PODCAST_OUT, f"{ep}_audio_clip_{tag}.mp3")
            cmd = base + ["-vn", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:a", "libmp3lame", "-b:a", "192k",
                          "-f", "mp3"]
        else:
            if mode in ("solo", "short"):
                out, crf = os.path.join(SHORTS_IN, f"{ep}_clip_{tag}.mp4"), "16"
            elif mode in ("wide", "youtube"):
                out, crf = os.path.join(YT_OUT, f"{ep}_wide_clip_{tag}.mp4"), "20"
            else:
                out, crf = os.path.join(SPLIT_IN, f"{ep}_clip_{tag}.mp4"), "16"
            cmd = base + ["-c:v", "libx264", "-crf", crf, "-preset", "veryfast", "-pix_fmt", "yuv420p",
                          "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-f", "mp4"]
        if mode not in ("audio", "mp3", "wide", "youtube"):
            set_hook_text(os.path.splitext(os.path.basename(out))[0], hook)
        part = os.path.join(os.path.dirname(out), "." + os.path.basename(out) + ".partial")
        if subprocess.run(cmd + [part]).returncode == 0 and os.path.isfile(part):
            os.replace(part, out)  # watcher only sees the finished file
            n += 1
        else:
            try:
                os.remove(part)
            except OSError:
                pass
    status(job, "clips", len(todo), len(todo), f"Sliced {n} clip(s) from {ep}", "done" if n else "error")
    return n


if __name__ == "__main__":
    print(slice_text(sys.argv[1], open(sys.argv[2], encoding="utf-8", errors="ignore").read()))

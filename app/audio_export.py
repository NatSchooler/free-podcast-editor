#!/usr/bin/env python3
"""Export chosen passages of an episode as one podcast-ready MP3 (runs on its own, separate from episode jobs).
Usage: audio_export.py EPISODE "Title" RANGES_JSON [--intro on|off] [--job ID]
  - passages joined in time order with 0.5 s crossfades (no hard jumps)
  - optional intro on the front: Z:\\brand\\audio_intro.(mp3|wav|m4a) if present, else the podcast intro
  - levelled to podcast standard (-16 LUFS, exact two-pass), MP3 192k with title/artist tags
  - saved to Z:\\podcast_audio\\output\\<Title>.mp3"""
import argparse, json, os, re, subprocess, sys, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ai_common import HUB, status, safe_name, shm_dir, conf

ap = argparse.ArgumentParser()
ap.add_argument("ep")
ap.add_argument("title")
ap.add_argument("ranges")
ap.add_argument("--intro", default="on")
ap.add_argument("--job", default="")
a = ap.parse_args()

SRC = os.path.join(HUB, "youtube_long/output", f"{a.ep}_clean.mp4")
OUT_DIR = os.path.join(HUB, "podcast_audio/output")
ranges = sorted((float(s), float(e)) for s, e in json.loads(a.ranges) if float(e) > float(s))
job = a.job or safe_name("audio_" + a.title)[:80]
name = safe_name(a.title.strip() or f"{a.ep}_audio")[:90]
total = sum(e - s for s, e in ranges)


def ff(args):
    return subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error"] + args, capture_output=True, text=True)


def find_intro():
    for d, base in ((os.path.join(HUB, "brand"), "audio_intro"), (os.path.join(HUB, "youtube_long"), "intro"),
                    (os.path.join(HUB, "podcast_audio"), "intro")):
        for ext in ("mp3", "wav", "m4a", "aac", "flac", "MP3", "WAV", "M4A"):
            p = os.path.join(d, f"{base}.{ext}")
            if os.path.isfile(p):
                return p
    return None


tmp = shm_dir("mh_audio_", total * 48000 * 2 * 2 * 3)  # audio scratch in RAM, removed when done
try:
    if not os.path.isfile(SRC) or not ranges:
        status(job, "audio", 1, 3, "Audio export: nothing to export", "error")
        sys.exit(1)
    status(job, "audio", 1, 3, f"Audio export: joining {len(ranges)} passage(s) ({total / 60:.1f} min)", "running", total)
    XF = 0.5
    fc, last = "", None
    for i, (s, e) in enumerate(ranges):
        fc += f"[0:a]atrim={s:.3f}:{e:.3f},asetpts=PTS-STARTPTS,aformat=sample_rates=48000:channel_layouts=stereo[p{i}];"
    if len(ranges) == 1:
        fc += "[p0]anull[body]"
    else:
        last = "p0"
        for i in range(1, len(ranges)):
            d = min(XF, (ranges[i - 1][1] - ranges[i - 1][0]) / 3, (ranges[i][1] - ranges[i][0]) / 3)
            out = "body" if i == len(ranges) - 1 else f"x{i}"
            fc += f"[{last}][p{i}]acrossfade=d={d:.2f}:c1=tri:c2=tri[{out}];"
            last = out
        fc = fc.rstrip(";")
    body = os.path.join(tmp, "body.wav")
    r = ff(["-i", SRC, "-filter_complex", fc, "-map", "[body]", "-c:a", "pcm_s16le", body])
    if r.returncode != 0:
        status(job, "audio", 1, 3, "Audio export failed while joining: " + r.stderr[-120:], "error")
        sys.exit(1)

    joined = body
    intro = find_intro() if a.intro == "on" else None
    if intro:
        status(job, "audio", 2, 3, "Audio export: adding your intro")
        joined = os.path.join(tmp, "with_intro.wav")
        r = ff(["-i", intro, "-i", body, "-filter_complex",
                "[0:a]aformat=sample_rates=48000:channel_layouts=stereo,loudnorm=I=-16:TP=-1.5:LRA=11[i];"
                "[1:a]aformat=sample_rates=48000:channel_layouts=stereo[b];[i][b]acrossfade=d=0.4:c1=tri:c2=tri[o]",
                "-map", "[o]", "-c:a", "pcm_s16le", joined])
        if r.returncode != 0:
            joined = body
    elif a.intro == "on":
        print("No intro file found (Z:\\brand\\audio_intro.mp3 or Z:\\youtube_long\\intro.mp3); exporting without one")

    status(job, "audio", 3, 3, "Audio export: levelling to podcast standard and saving MP3")
    af = subprocess.run(["python3", os.path.join(os.path.dirname(os.path.abspath(__file__)), "audio_polish.py"),
                         joined, "-16", "--light"], capture_output=True, text=True).stdout.strip() \
        or "loudnorm=I=-16:TP=-1.5:LRA=11"
    os.makedirs(OUT_DIR, exist_ok=True)
    final = os.path.join(OUT_DIR, name + ".mp3")
    part = os.path.join(OUT_DIR, "." + name + ".mp3.partial")
    r = ff(["-i", joined, "-af", af, "-c:a", "libmp3lame", "-b:a", "192k", "-ar", "44100", "-ac", "2",
            "-metadata", f"title={a.title}", "-metadata", f"artist={conf('MH_ARTIST', '')}", "-metadata", f"album={a.ep.replace('_', ' ')}",
            "-id3v2_version", "3", "-f", "mp3", part])
    if r.returncode != 0:
        status(job, "audio", 3, 3, "Audio export failed while saving: " + r.stderr[-120:], "error")
        sys.exit(1)
    os.replace(part, final)
    status(job, "audio", 3, 3, f"Audio ready: {name}.mp3 ({total / 60:.1f} min{' + intro' if intro else ''})", "done")
    print(final)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

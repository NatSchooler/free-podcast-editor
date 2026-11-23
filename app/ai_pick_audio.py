#!/usr/bin/env python3
"""AI picks the passages of an episode that are about a TOPIC, adding up to about TARGET minutes.
Usage: ai_pick_audio.py SRT "topic" TARGET_MINUTES [--range "HH:MM:SS - HH:MM:SS"]
Prints JSON: [{"start": s, "end": e, "score": n, "why": "..."}...] in time order."""
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ai_common import read_srt, ask_json, extract_list, ts2s, s2ts, parse_range, windows, blocks_by_time, snap_start, snap_end

ap = argparse.ArgumentParser()
ap.add_argument("srt")
ap.add_argument("topic")
ap.add_argument("minutes", type=float)
ap.add_argument("--range")
a = ap.parse_args()

segs = read_srt(a.srt)
if a.range:
    r = parse_range(a.range)
    if r:
        segs = [x for x in segs if x[0] >= r[0] - 1 and x[1] <= r[1] + 1]
if not segs:
    print("[]")
    sys.exit(0)

target = a.minutes * 60
cands = []
blocks = blocks_by_time(segs, 480)
for i, b in enumerate(blocks):
    lines = "\n".join(f"[{s2ts(s)}] {t}" for s, e, t in windows(b, 12))
    prompt = (
        f"TOPIC: {a.topic}\n\n"
        "Below is part of a podcast interview transcript; each line starts with [HH:MM:SS].\n"
        "Find every passage that is clearly about the TOPIC and would make good listening on its own: "
        "a complete thought that starts at the beginning of a sentence and ends after the point is made. "
        "Passages should usually be 30 seconds to 4 minutes long. Ignore passages that only mention the topic in passing.\n"
        "Score each 1 to 10 for how relevant and compelling it is for the TOPIC.\n"
        'Reply with JSON only: {"passages":[{"start":"HH:MM:SS","end":"HH:MM:SS","score":8,"why":"one short sentence"}]}\n'
        'If nothing is about the topic reply {"passages":[]}.\n\nTRANSCRIPT:\n' + lines
    )
    try:
        d = ask_json(prompt, keep="0" if i == len(blocks) - 1 else "20s")
    except Exception as ex:
        print(f"part {i} failed: {ex}", file=sys.stderr)
        continue
    for c in extract_list(d, ("passages", "clips", "segments", "results"))[:6]:
        if not isinstance(c, dict):
            continue
        s, e = ts2s(c.get("start", "")), ts2s(c.get("end", ""))
        if s is None or e is None or e <= s or s < b[0][0] - 5 or s > b[-1][1]:
            continue
        s, e = snap_start(segs, s), snap_end(segs, e)
        if e - s < 15:
            continue
        try:
            score = max(1.0, min(10.0, float(c.get("score") or 5)))
        except (TypeError, ValueError):
            score = 5.0
        cands.append({"start": round(s, 2), "end": round(e, 2), "score": score, "why": str(c.get("why") or "")[:200]})

cands.sort(key=lambda c: -c["score"])
picked, total = [], 0.0
for c in cands:
    if any(c["start"] < p["end"] and p["start"] < c["end"] for p in picked):
        continue
    length = c["end"] - c["start"]
    if total + length > target * 1.1 and total >= target * 0.6:
        continue
    picked.append(c)
    total += length
    if total >= target * 0.95:
        break
picked.sort(key=lambda c: c["start"])
print(json.dumps(picked))

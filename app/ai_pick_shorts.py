#!/usr/bin/env python3
"""Pick the strongest shorts from the WHOLE episode (not just the first 15 minutes).
Usage: ai_pick_shorts.py SRT [mode] [--count N] [--range "HH:MM:SS - HH:MM:SS"] [--json OUT]
Prints 'HH:MM:SS - HH:MM:SS | mode' lines; --json also saves title, score and reason."""
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ai_common import (read_srt, ask_json, extract_list, ts2s, s2ts, ts_floor, ts_ceil, parse_range,
                       windows, blocks_by_time, fit_clip, text_between, conf)

ap = argparse.ArgumentParser()
ap.add_argument("srt")
ap.add_argument("mode", nargs="?", default="split")
ap.add_argument("--count", type=int, default=int(conf("MH_SHORTS_COUNT", "3")))
ap.add_argument("--range")
ap.add_argument("--json")
a = ap.parse_args()

segs = read_srt(a.srt)
if a.range:
    r = parse_range(a.range)
    if r:
        segs = [x for x in segs if x[0] >= r[0] - 1 and x[1] <= r[1] + 1]
if not segs:
    sys.exit(0)

blocks = blocks_by_time(segs, 480)
cands = []
for i, b in enumerate(blocks):
    lines = "\n".join(f"[{s2ts(s)}] {t}" for s, e, t in windows(b, 10))
    prompt = (
        "You are an expert short-form video editor. Below is one part of a podcast transcript; "
        "each line starts with its timestamp [HH:MM:SS].\n"
        "Pick up to 2 moments that would make a strong standalone vertical short of 30 to 60 seconds: "
        "a bold claim, a surprising fact, clear practical advice, a story with a payoff, or a strong emotional line. "
        "It must make sense without any context, start at the beginning of a sentence and end after a complete point. "
        "Skip greetings, introductions, plugs and goodbyes.\n"
        "Score each 1 to 10 for viral potential. Be strict: 8 or more only for genuinely gripping moments.\n"
        "Titles: UK English, no contractions, maximum 8 words.\n"
        'Reply with JSON only: {"clips":[{"start":"HH:MM:SS","end":"HH:MM:SS","title":"...","score":7,"reason":"one sentence"}]}\n'
        'If nothing qualifies reply {"clips":[]}.\n\nTRANSCRIPT:\n' + lines
    )
    try:
        d = ask_json(prompt, keep="0" if i == len(blocks) - 1 else "20s")
    except Exception as ex:
        print(f"block {i} failed: {ex}", file=sys.stderr)
        continue
    for c in extract_list(d)[:3]:
        if not isinstance(c, dict):
            continue
        s = ts2s(c.get("start") or c.get("start_time") or c.get("begin") or "")
        e = ts2s(c.get("end") or c.get("end_time") or c.get("stop") or "")
        if s is None:
            continue
        if s < b[0][0] - 5 or s > b[-1][1]:
            continue  # hallucinated timestamp outside this block
        if e is None or e <= s:
            e = s + 45
        s, e = fit_clip(segs, s, e)
        if s is None:
            continue
        try:
            score = max(1.0, min(10.0, float(c.get("score") or 5)))
        except (TypeError, ValueError):
            score = 5.0
        cands.append({"start": s, "end": e, "score": score,
                      "title": str(c.get("title") or "").strip()[:90],
                      "reason": str(c.get("reason") or "").strip()[:240]})

cands.sort(key=lambda c: -c["score"])
picked = []
for c in cands:
    if any(c["start"] < p["end"] and p["start"] < c["end"] for p in picked):
        continue
    picked.append(c)
    if len(picked) >= a.count:
        break
if not picked:
    sys.exit(0)

out = []
for p in picked:
    p["range"] = f"{ts_floor(p['start'])} - {ts_ceil(p['end'])}"
    p["text"] = text_between(segs, p["start"], p["end"])[:400]
    out.append(f"{p['range']} | {a.mode}")
if a.json:
    with open(a.json, "w", encoding="utf-8") as f:
        json.dump(picked, f, indent=1)
print("\n".join(out))

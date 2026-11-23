#!/usr/bin/env python3
"""Per-episode content pack: AI hook, titles, description, YouTube chapters (on the EDITED timeline), quotes, shorts.
Usage: ai_content_pack.py SRT OUT_TXT --meta PREFIX [--cuts CUTS_FILE] [--name EPISODE]
The slow AI analysis is cached in PREFIX.analysis.json, so re-cuts only re-map chapters (seconds, no AI)."""
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ai_common import (read_srt, ask_json, ts2s, s2ts, ts_floor, ts_ceil, yt_time, windows, blocks_by_time,
                       snap_start, snap_end, text_between, read_cuts, timeline, map_time, status, effective_cuts)

ap = argparse.ArgumentParser()
ap.add_argument("srt")
ap.add_argument("out")
ap.add_argument("--meta", required=True)
ap.add_argument("--cuts")
ap.add_argument("--name", default="")
ap.add_argument("--job", default="")
a = ap.parse_args()

segs = read_srt(a.srt)
if not segs:
    sys.exit(0)
dur = segs[-1][1]
sig = f"{len(segs)}:{int(dur)}"
apath = a.meta + ".analysis.json"
an = None
try:
    an = json.load(open(apath))
    if an.get("sig") != sig:
        an = None
except (OSError, ValueError):
    an = None

if an is None:
    size = max(240, min(600, dur / 8))
    blocks = blocks_by_time(segs, size)
    out_blocks = []
    for i, b in enumerate(blocks):
        if a.job:
            pass  # progress is reported by the calling job step
        lines = "\n".join(f"[{s2ts(s)}] {t}" for s, e, t in windows(b, 10))
        prompt = (
            "Below is one part of a podcast interview transcript; each line starts with [HH:MM:SS].\n"
            "Return JSON only:\n"
            '{"chapter":"YouTube chapter title for this part, 2 to 6 words",'
            '"summary":"one sentence on what is discussed",'
            '"quote":"the single most quotable line, copied exactly from the transcript",'
            '"hook_start":"HH:MM:SS","hook_end":"HH:MM:SS","hook_strength":7}\n'
            "The hook is the 5 to 12 seconds in this part that would make the most gripping cold open "
            "for the whole episode; strength is 1 to 10. Use UK English and no contractions.\n\n" + lines
        )
        try:
            d = ask_json(prompt, keep="20s")
        except Exception as ex:
            print(f"part {i} failed: {ex}", file=sys.stderr)
            d = {}
        d = d if isinstance(d, dict) else {}
        hs, he = ts2s(d.get("hook_start", "")), ts2s(d.get("hook_end", ""))
        hook = None
        if hs is not None and b[0][0] - 5 <= hs <= b[-1][1]:
            hs = snap_start(segs, hs)
            he = snap_end(segs, he if he and he > hs else hs + 8)
            if he - hs > 14:
                he = snap_end(segs, hs + 10)
            if 3 <= he - hs <= 15:
                try:
                    strength = float(d.get("hook_strength") or 5)
                except (TypeError, ValueError):
                    strength = 5.0
                hook = [hs, he, strength]
        out_blocks.append({"start": b[0][0], "end": b[-1][1],
                           "chapter": str(d.get("chapter") or "").strip()[:60],
                           "summary": str(d.get("summary") or "").strip(),
                           "quote": str(d.get("quote") or "").strip(), "hook": hook})
    summaries = "\n".join(f"- {x['summary']}" for x in out_blocks if x["summary"])
    try:
        g = ask_json(
            "Here are summaries of each part of a podcast episode, in order:\n" + summaries + "\n\n"
            "Write 5 YouTube title options (maximum 70 characters each, curiosity-driven but honest, no emojis) "
            "and a YouTube description of two short paragraphs. UK English, no contractions.\n"
            'Reply with JSON only: {"titles":["..."],"description":"..."}')
    except Exception as ex:
        print(f"titles failed: {ex}", file=sys.stderr)
        g = {}
    g = g if isinstance(g, dict) else {}
    an = {"sig": sig, "blocks": out_blocks,
          "titles": [str(t) for t in (g.get("titles") or []) if str(t).strip()][:5],
          "description": str(g.get("description") or "").strip()}
    json.dump(an, open(apath, "w"), indent=1)

# ----- chapters mapped onto the edited timeline -----
hook_cut, keeps = (effective_cuts(a.meta) if a.cuts and os.path.isfile(a.cuts) else (None, []))
pieces = timeline(hook_cut, keeps) if keeps else None
chapters = []
if hook_cut:
    chapters.append((0.0, "Cold open"))
for b in an["blocks"]:
    t = b["start"]
    if pieces:
        m = map_time(pieces, t)
        if m is None:
            nxt = [s for s, e in keeps if b["start"] <= s < b["end"]]
            m = map_time(pieces, nxt[0]) if nxt else None
        t = m
    if t is None:
        continue
    title = b["chapter"] or "Discussion"
    if chapters and t - chapters[-1][0] < 10:
        continue
    chapters.append((t, title))
if chapters:
    chapters[0] = (0.0, chapters[0][1])

hooks = [b["hook"] for b in an["blocks"] if b.get("hook")]
best = max(hooks, key=lambda h: h[2]) if hooks else None
hook_range = f"{ts_floor(best[0])} - {ts_ceil(best[1])}" if best else ""

shorts = []
try:
    shorts = json.load(open(a.meta + ".shorts.json"))
except (OSError, ValueError):
    pass

L = [f"CONTENT PACK: {a.name or os.path.basename(a.meta)}", "=" * 60, ""]
if best:
    L += ["SUGGESTED COLD-OPEN HOOK (paste into the Hook box):", f"HOOK: {hook_range}",
          f'"{text_between(segs, best[0], best[1])}"', ""]
if an["titles"]:
    L += ["TITLE OPTIONS:"] + [f"{i}. {t}" for i, t in enumerate(an["titles"], 1)] + [""]
if an["description"]:
    L += ["DESCRIPTION:", an["description"], ""]
if chapters:
    L += ["CHAPTERS (" + ("edited video timeline" if pieces else "full master timeline") + "):"]
    L += [f"{yt_time(t)} {title}" for t, title in chapters]
    if len(chapters) < 3:
        L += ["(YouTube needs at least 3 chapters; add one by hand)"]
    L += [""]
quotes = [b["quote"] for b in an["blocks"] if b.get("quote")]
if quotes:
    L += ["QUOTABLE LINES:"] + [f'- "{q}"' for q in quotes[:6]] + [""]
if shorts:
    L += ["AI SHORT PICKS (master timeline):"]
    for i, s in enumerate(shorts, 1):
        L += [f"{i}. [{s.get('score', '?')}/10] {s.get('title', '')}", f"   {s.get('range', '')}",
              f"   Why: {s.get('reason', '')}"]
    L += [""]
open(a.out, "w", encoding="utf-8").write("\n".join(L))
json.dump({"hook": hook_range}, open(a.meta + ".pack.json", "w"))
print(a.out)

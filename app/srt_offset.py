#!/usr/bin/env python3
"""Shift the master transcript onto the edited video's timeline (ready to upload to YouTube).
Usage: srt_offset.py MASTER.srt CUTS_FILE OUT.srt [META_PREFIX]
Uses the edit as actually built (after um/pause removal) and word timings when available, so captions stay exact."""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ai_common import read_srt, write_srt, read_cuts, timeline, effective_cuts

master, cuts, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
meta = sys.argv[4] if len(sys.argv) > 4 else None
hook, keeps = effective_cuts(meta) if meta else read_cuts(cuts)
if not keeps:
    sys.exit(0)
words_path = master.replace("_transcript.srt", "_words.srt")
pieces = timeline(hook, keeps)
if os.path.isfile(words_path):
    words = read_srt(words_path, drop_noise=True)
    mapped = []
    for s0, e0, o, _ in pieces:
        for s, e, t in words:
            mid = (s + e) / 2
            if s0 <= mid < e0:
                mapped.append((o + max(s, s0) - s0, o + min(e, e0) - s0, t.strip()))
    mapped.sort(key=lambda x: x[0])
    out, cur = [], []
    for w in mapped:
        if cur and (w[0] - cur[-1][1] > 0.6 or len(cur) >= 10 or re.search(r"[.?!]$", cur[-1][2])):
            out.append((cur[0][0], cur[-1][1], " ".join(x[2] for x in cur)))
            cur = []
        cur.append(w)
    if cur:
        out.append((cur[0][0], cur[-1][1], " ".join(x[2] for x in cur)))
else:
    segs = read_srt(master, drop_noise=True)
    out = []
    for s0, e0, o, _ in pieces:
        for s, e, t in segs:
            lo, hi = max(s, s0), min(e, e0)
            if hi - lo > 0.05:
                out.append((o + lo - s0, o + hi - s0, t))
    out.sort(key=lambda x: x[0])
write_srt(out_path, out)

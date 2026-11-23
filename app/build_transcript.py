#!/usr/bin/env python3
"""Turn whisper's word-by-word SRT into a readable sentence-level transcript (.srt + .txt).
Usage: build_transcript.py WORDS.srt OUT_PREFIX     -> OUT_PREFIX.srt, OUT_PREFIX.txt
One whisper pass gives both: word timings (filler removal, text editing) and the normal transcript."""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ai_common import read_srt, write_srt

words = read_srt(sys.argv[1], drop_noise=False)
segs, cur = [], []
for i, (s, e, t) in enumerate(words):
    t = t.strip()
    if not t or re.fullmatch(r"[\[\(].*[\]\)]", t):
        continue
    if cur and (s - cur[-1][1] > 0.8 or len(cur) >= 14):
        segs.append(cur)
        cur = []
    cur.append((s, e, t))
    if re.search(r"[.?!]$", t) and len(cur) >= 3:
        segs.append(cur)
        cur = []
if cur:
    segs.append(cur)
out = [(c[0][0], c[-1][1], re.sub(r"\s+", " ", " ".join(w for _, _, w in c)).strip()) for c in segs]
write_srt(sys.argv[2] + ".srt", out)
open(sys.argv[2] + ".txt", "w", encoding="utf-8").write("\n".join(t for _, _, t in out) + "\n")

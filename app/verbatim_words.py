#!/usr/bin/env python3
"""Verbatim word transcript (v2.9.7). Whisper tidies retakes away when it hears them together
("once essential... once essential services..." comes out as one clean sentence), so the recording is
split at the pauses and each piece is transcribed on its own, in ONE whisper run.
  verbatim_words.py split IN_16k.wav DIR      -> DIR/chunk_000.wav ... and DIR/list.txt
  verbatim_words.py merge DIR OUT.srt         -> one word-by-word .srt on the original timeline, no phantom words"""
import json, os, re, sys, wave
import numpy as np

SR = 16000


def levels(x):
    n = len(x) // 160
    return 10 * np.log10((x[:n * 160].astype(np.float64).reshape(n, 160) ** 2).mean(1) + 1e-10) if n else np.zeros(0)


def runs(mask):
    out, s = [], None
    for k, v in enumerate(np.append(mask, False)):
        if v and s is None:
            s = k
        elif not v and s is not None:
            out.append((s, k))
            s = None
    return out


def split(inp, d):
    w = wave.open(inp, "rb")
    x = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
    w.close()
    db = levels(x)
    if not len(db):
        sys.exit(1)
    fl, sp = float(np.percentile(db, 10)), float(np.percentile(db, 90))
    thr = max(fl + (sp - fl) * 0.3, sp - 30)   # relative to your speaking level, so breaths and digital silence do not confuse it
    # speech regions, split wherever there is a pause of 0.45 s or more
    talk = runs(db > thr)
    regions = []
    for s, e in talk:
        if regions and s - regions[-1][1] < 45:
            regions[-1][1] = e
        else:
            regions.append([s, e])
    regions = [r for r in regions if r[1] - r[0] >= 8]
    # long pieces (over 10 s) are split again at their longest short pause
    out = []
    stack = regions[::-1]
    while stack:
        s, e = stack.pop()
        if e - s <= 1000:
            out.append([s, e])
            continue
        q = runs(db[s + 150:e - 150] <= thr)
        if not q:
            out.append([s, e])
            continue
        a, b = max(q, key=lambda r: r[1] - r[0])
        m = s + 150 + (a + b) // 2
        stack += [[m, e], [s, m]]
    # tiny pieces (under 0.4 s) join the next piece when it is close, so whisper has enough to go on
    merged = []
    for r in out:
        if merged and (merged[-1][1] - merged[-1][0] < 40) and r[0] - merged[-1][1] < 100 and r[1] - merged[-1][0] <= 1000:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    os.makedirs(d, exist_ok=True)
    lines = []
    for k, (s, e) in enumerate(merged):
        a, b = max(0, (s - 15) * 160), min(len(x), (e + 15) * 160)
        p = os.path.join(d, f"chunk_{k:03d}.wav")
        o = wave.open(p, "wb")
        o.setnchannels(1)
        o.setsampwidth(2)
        o.setframerate(SR)
        o.writeframes((np.clip(x[a:b], -1, 1) * 32767).astype(np.int16).tobytes())
        o.close()
        lines.append(f"{p}\t{a / SR:.3f}")
    open(os.path.join(d, "list.txt"), "w").write("\n".join(lines) + "\n")
    json.dump({"thr": thr, "floor": fl, "speech": sp}, open(os.path.join(d, "meta.json"), "w"))
    print(f"{len(lines)} pieces")


def ts(t):
    t = max(0.0, t)
    return f"{int(t // 3600):02d}:{int(t % 3600 // 60):02d}:{int(t % 60):02d},{int(round(t % 1 * 1000)) % 1000:03d}"


def read(p):
    out = []
    for b in re.split(r"\n\s*\n", open(p, encoding="utf-8", errors="ignore").read().strip()):
        l = b.strip().split("\n")
        t = re.findall(r"(\d+):(\d+):(\d+)[,.](\d+)", " ".join(l[:2]))
        if len(t) < 2:
            continue
        f = lambda h, m, s, ms: int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000
        txt = " ".join(x for x in l if "-->" not in x and not x.strip().isdigit()).strip()
        out.append((f(*t[0]), f(*t[1]), txt))
    return out


def merge(d, outp):
    meta = json.load(open(os.path.join(d, "meta.json")))
    words, dropped = [], 0
    for line in open(os.path.join(d, "list.txt")):
        if not line.strip():
            continue
        p, off = line.rstrip("\n").split("\t")
        off = float(off)
        srt = next((c for c in (p + ".srt", p[:-4] + ".srt") if os.path.isfile(c)), None)
        if not srt:
            continue
        w = wave.open(p, "rb")
        db = levels(np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768)
        w.close()
        for s, e, t in read(srt):
            t = t.strip()
            if not t or re.fullmatch(r"[\[\(].*[\]\)]", t):
                continue
            i0, i1 = max(0, int(s * 100) - 5), min(len(db), int(e * 100) + 6)
            if i1 <= i0 or float(db[i0:i1].max()) < meta["thr"]:
                dropped += 1          # whisper "heard" a word over silence: leave it out
                continue
            words.append((s + off, max(e, s + 0.02) + off, t))
    words.sort()
    with open(outp, "w", encoding="utf-8") as f:
        for k, (s, e, t) in enumerate(words, 1):
            f.write(f"{k}\n{ts(s)} --> {ts(e)}\n{t}\n\n")
    print(f"{len(words)} words, {dropped} phantom words left out")
    sys.exit(0 if words else 1)


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "split":
        split(sys.argv[2], sys.argv[3])
    elif len(sys.argv) == 4 and sys.argv[1] == "merge":
        merge(sys.argv[2], sys.argv[3])
    else:
        print(__doc__)
        sys.exit(2)

#!/usr/bin/env python3
"""Build burn-in ASS captions for 9:16 shorts.
  words  WORD_SRT  OUT_ASS OUT_EDITABLE_SRT --layout solo|split   (from whisper -ml 1 -sow, real word timing)
  chunks EDIT_SRT  OUT_ASS                 --layout solo|split   (re-burn from your edited .srt)
Style 'pop' = white ALL CAPS words, the word being spoken turns MH_BRAND_COLOUR and bounces.
Style 'classic' = the old all-orange look. Set MH_CAPTION_STYLE in ~/mediahub.conf."""
import argparse, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ai_common import read_srt, write_srt, conf

ap = argparse.ArgumentParser()
ap.add_argument("kind", choices=["words", "chunks"])
ap.add_argument("src")
ap.add_argument("out_ass")
ap.add_argument("out_srt", nargs="?")
ap.add_argument("--layout", default="solo")
ap.add_argument("--hook-file", help="text file holding the 2-second slam hook; *word* = orange")
a = ap.parse_args()

STYLE = conf("MH_CAPTION_STYLE", "pop")
SIZE = int(conf("MH_CAPTION_SIZE", "120"))
PER = max(1, int(conf("MH_WORDS_PER_CAPTION", "2")))
from ai_common import ass_colour
ORANGE, WHITE = ass_colour(conf("MH_BRAND_COLOUR", "#FFFFFF")), "&H00FFFFFF"
FONT = conf("MH_FONT", "DejaVu Sans")
HL = "&H" + ORANGE[4:] + "&"  # inline colour tag form
align, marginv = (5, 0) if a.layout == "split" else (2, int(conf("MH_CAPTION_MARGIN_V", "430")))


def clean(w):
    return re.sub(r"[{}\\]", "", w).strip().upper()


def ass_t(s):
    cs = int(round(max(0, s) * 100))
    return f"{cs // 360000}:{cs % 360000 // 6000:02d}:{cs % 6000 // 100:02d}.{cs % 100:02d}"


# ----- build chunks: list of (start, end, [(word, ws, we), ...]) -----
chunks = []
if a.kind == "words":
    words = []
    for s, e, t in read_srt(a.src):
        for w in t.split():
            w = clean(w)
            if w:
                words.append((w, s, e))
    cur = []
    for i, (w, s, e) in enumerate(words):
        if cur and (len(cur) >= PER or s - cur[-1][2] > 0.6 or re.search(r"[.?!]$", cur[-1][0])):
            chunks.append(cur)
            cur = []
        cur.append((w, s, e))
    if cur:
        chunks.append(cur)
    chunks = [(c[0][1], c[-1][2], c) for c in chunks]
    if a.out_srt:
        write_srt(a.out_srt, [(s, e, " ".join(w for w, _, _ in c)) for s, e, c in chunks])
else:
    for s, e, t in read_srt(a.src):
        ws = [clean(w) for w in t.split() if clean(w)]
        if not ws:
            continue
        total = sum(len(w) + 1 for w in ws)
        c, pos = [], s
        for w in ws:
            d = (e - s) * (len(w) + 1) / total
            c.append((w, pos, pos + d))
            pos += d
        chunks.append((s, e, c))

# ----- write ASS -----
primary = WHITE if STYLE == "pop" else ORANGE
out = [
    "[Script Info]", "ScriptType: v4.00+", "PlayResX: 1080", "PlayResY: 1920", "WrapStyle: 0",
    "ScaledBorderAndShadow: yes", "",
    "[V4+ Styles]",
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
    "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
    "MarginR, MarginV, Encoding",
    f"Style: Main,{FONT},{SIZE},{primary},&H000000FF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,8,3,"
    f"{align},60,60,{marginv},1",
    "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
]
for i, (cs, ce, c) in enumerate(chunks):
    nxt = chunks[i + 1][0] if i + 1 < len(chunks) else ce + 0.3
    ce = max(ce, min(nxt, ce + 0.25))  # hold the last word a moment unless the next caption starts
    if STYLE != "pop":
        out.append(f"Dialogue: 11,{ass_t(cs)},{ass_t(ce)},Main,,0,0,0,,{' '.join(w for w, _, _ in c)}")
        continue
    for j, (w, ws, we) in enumerate(c):
        st = cs if j == 0 else ws
        en = ce if j == len(c) - 1 else c[j + 1][1]
        if en - st < 0.04:
            continue
        txt = " ".join(
            ("{\\c" + HL + r"\fscx100\fscy100\t(0,90,\fscx114\fscy114)}" + x + r"{\r}") if k == j else x
            for k, (x, _, _) in enumerate(c))
        out.append(f"Dialogue: 11,{ass_t(st)},{ass_t(en)},Main,,0,0,0,,{txt}")


# ----- 2-second slam hook over the start of the short -----
def hook_events(text, layout):
    raw = re.sub(r"[{}\\]", "", " ".join(text.split())).upper()
    words = raw.split()
    if not words:
        return []
    if "*" not in raw:
        words[-1] = "*" + words[-1].strip("*") + "*"  # no *marked* word: last word goes orange
    size = 165 if layout == "solo" else 128
    maxc = 11 if layout == "solo" else 14
    lines, cur = [], ""
    for w in words:
        plain = w.replace("*", "")
        if cur and len(cur.replace("*", "")) + 1 + len(plain) > maxc:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    lines.append(cur)
    if len(lines) > 3:
        size = int(size * 0.8)
    body = r"\N".join(lines)
    body = re.sub(r"\*([^*]+)\*", lambda m: "{\\c" + HL + "}" + m.group(1) + r"{\c&HFFFFFF&}", body)
    y = 640 if layout == "solo" else 330
    rect = "m 0 0 l 1080 0 l 1080 1920 l 0 1920"
    pre = r"\an5\fn" + FONT + r"\fs%d\c&HFFFFFF&\3c&H000000&\bord12\shad5\b1" % size
    ev = [
        # darken the picture so the words punch, then a white impact flash
        f"Dialogue: 8,{ass_t(0)},{ass_t(2.0)},Main,,0,0,0,,{{\\an7\\pos(0,0)\\p1\\bord0\\shad0\\1c&H000000&\\1a&H70&\\fad(0,220)}}{rect}",
        f"Dialogue: 9,{ass_t(0)},{ass_t(0.26)},Main,,0,0,0,,{{\\an7\\pos(0,0)\\p1\\bord0\\shad0\\1c&HFFFFFF&\\1a&H30&\\t(0,260,\\1a&HFF&)}}{rect}",
        # slam in from 170% with a fast fade-up
        f"Dialogue: 10,{ass_t(0)},{ass_t(0.14)},Main,,0,0,0,,{{{pre}\\pos(540,{y})\\fscx175\\fscy175\\alpha&HFF&\\t(0,50,\\alpha&H00&)\\t(0,140,\\fscx100\\fscy100)}}{body}",
    ]
    # impact shake
    for t0, t1, dx, dy in ((0.14, 0.19, 10, -7), (0.19, 0.24, -8, 6), (0.24, 0.29, 4, -3)):
        ev.append(f"Dialogue: 10,{ass_t(t0)},{ass_t(t1)},Main,,0,0,0,,{{{pre}\\pos({540 + dx},{y + dy})}}{body}")
    # hold with a slow push-in, then fade out at 2 seconds
    ev.append(f"Dialogue: 10,{ass_t(0.29)},{ass_t(2.0)},Main,,0,0,0,,{{{pre}\\pos(540,{y})\\t(0,1710,\\fscx107\\fscy107)\\fad(0,200)}}{body}")
    return ev


if a.hook_file and os.path.isfile(a.hook_file):
    txt = open(a.hook_file, encoding="utf-8", errors="ignore").read().strip()
    if txt:
        i = out.index("[Events]") + 2
        out[i:i] = hook_events(txt, a.layout)

open(a.out_ass, "w", encoding="utf-8").write("\n".join(out) + "\n")

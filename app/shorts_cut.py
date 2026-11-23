#!/usr/bin/env python3
"""Shorts cutter (v2.9.7): from the framed 9:16 video to the finished short in ONE encode.
Removes long pauses, ums, repeated words and false starts ("the new digital ID, that the new EU digital..."),
then burns the word-by-word captions and the logo in the same pass.
  shorts_cut.py BASE --layout solo|split --out OUT.mp4 --srt-out OUT.srt --words WORDS.srt   new short: decide the cuts
  shorts_cut.py BASE --layout solo|split --out OUT.mp4 --srt-out OUT.srt                      rebuild after Shorts Editor changes
  shorts_cut.py BASE --layout solo|split --out OUT.mp4 --reburn EDITED.srt                    your edited captions, same cuts
Everything it needs is kept in .meta/shorts/BASE.json and BASE.framed.mp4, so edits never need a new transcription."""
import argparse, json, math, os, re, shutil, subprocess, sys, time, wave
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ai_common import read_srt, write_srt, META, HUB, status, conf, shm_dir

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
SD = os.path.join(META, "shorts")
ap = argparse.ArgumentParser()
ap.add_argument("base")
ap.add_argument("--layout", default="solo")
ap.add_argument("--out", required=True)
ap.add_argument("--srt-out")
ap.add_argument("--words")
ap.add_argument("--reburn")
ap.add_argument("--job", default="")
ap.add_argument("--pipe", default="shorts")
a = ap.parse_args()

FRAMED = os.path.join(SD, a.base + ".framed.mp4")
STATE = os.path.join(SD, a.base + ".json")
NEW = bool(a.words)
JOB = a.job or (("short_" if a.layout == "solo" else "split_") + a.base)
PIPE = a.pipe if NEW else a.pipe + "_edit"
TOTAL = 4 if NEW else 1
_last = [0.0]


def say(step, label, state="running", frac=None, media=None):
    if frac is not None:
        if time.time() - _last[0] < 3:
            return
        _last[0] = time.time()
    status(JOB, PIPE, step if NEW else 1, TOTAL, label, state, media, frac)
    if frac is None:
        print(label, flush=True)


def fail(msg):
    say(4, f"{msg}: {a.base}", "error")
    sys.exit(1)


def probe(path, entries, stream=None):
    cmd = ["ffprobe", "-v", "error"] + (["-select_streams", stream] if stream else []) + \
          ["-show_entries", entries, "-of", "csv=p=0", path]
    return subprocess.run(cmd, capture_output=True, text=True).stdout.strip()


if not os.path.isfile(FRAMED):
    fail("Framed video missing")
try:
    DUR = float(probe(FRAMED, "format=duration") or 0)
    n_, d_ = (probe(FRAMED, "stream=r_frame_rate", "v:0") or "30/1").split("/")
    FPS = float(n_) / float(d_ or 1)
except (ValueError, ZeroDivisionError):
    FPS = 30.0
if DUR <= 0:
    fail("Could not read the framed video")

# ---------------- audio (in RAM) ----------------
tmp = shm_dir("mh_short_", DUR * 48000 * 2 * 2 * 3)
master = os.path.join(tmp, "master.wav")
if subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", FRAMED, "-vn", "-ac", "2", "-ar", "48000",
                   "-c:a", "pcm_s16le", master]).returncode != 0:
    shutil.rmtree(tmp, ignore_errors=True)
    fail("Could not read the audio")


def db_levels(hop_s):
    w = wave.open(master, "rb")
    sr, ch = w.getframerate(), w.getnchannels()
    hop = int(sr * hop_s)
    out = []
    while True:
        buf = w.readframes(hop * 1000)
        if not buf:
            break
        x = np.frombuffer(buf, np.int16).reshape(-1, ch).astype(np.float32).mean(1)
        n = len(x) // hop
        if n:
            out.append(10 * np.log10((x[:n * hop].reshape(n, hop) ** 2).mean(1) + 1e-6))
    w.close()
    return np.concatenate(out) if out else np.zeros(0)


FILLER = re.compile(r"^(u+m+|u+h+m*|e+r+m+|e+r+|a+h+|a+r+m*|h+m+|m+h*m+|mhm|mm+)$", re.I)
KEEP_DOUBLE = {"very", "really", "so", "no", "yes", "yeah", "bye", "ha", "well", "now", "many", "much", "more",
               "long", "far", "again", "ok", "okay", "go", "come", "on", "that", "had", "is"}


def clean(w):
    return re.sub(r"[^\w']", "", w).lower()


def decide():
    """First pass on a new short: which words to cut automatically, and where the long pauses are."""
    words = []
    for s, e, t in read_srt(a.words, drop_noise=False):
        for w in t.split():
            w = w.strip()
            if w and not re.fullmatch(r"[\[\(].*[\]\)]", w):
                words.append([round(s, 3), round(max(e, s + 0.02), 3), w])
    n = len(words)
    db = db_levels(0.01)
    floor, speech = (np.percentile(db, 10), np.percentile(db, 90)) if len(db) else (0, 0)
    gap = max(floor + (speech - floor) * 0.35, speech - 30)   # v2.9.7: relative to the voice, digital silence no longer skews it

    def quiet(t0, t1):
        i0, i1 = max(0, int(t0 / 0.01)), min(len(db), int(t1 / 0.01) + 1)
        return i1 > i0 and float(db[i0:i1].min()) <= gap

    removed, hidden = {}, []
    stumbles = conf("MH_SHORTS_CUT_STUMBLES", "on").lower() == "on"
    for i, (s, e, w) in enumerate(words):
        c = clean(w)
        prev_e = words[i - 1][1] if i else s - 1
        next_s = words[i + 1][0] if i + 1 < n else e + 1
        if FILLER.match(c):
            if quiet(max(prev_e - 0.03, s - 0.15), s + 0.06) and quiet(e - 0.06, min(next_s + 0.03, e + 0.15)):
                removed[str(i)] = "um"
            else:
                hidden.append(i)  # could not cut it cleanly: keep the sound, but leave it out of the captions
        elif stumbles and i + 1 < n and c and c == clean(words[i + 1][2]) and c not in KEEP_DOUBLE and next_s - e < 0.6:
            removed[str(i)] = "repeat"  # "I I think" -> "I think"
    # phantom words (v2.9.7): whisper "heard" a word where the recording is silent
    for i, (s, e, w) in enumerate(words):
        i0, i1 = max(0, int(s / 0.01) - 5), min(len(db), int(e / 0.01) + 6)
        if str(i) not in removed and i1 > i0 and float(db[i0:i1].max()) < gap - 3:
            removed[str(i)] = "phantom"
    if stumbles:
        # false starts and retakes (v2.9.7): the speaker stops, then starts again with the same words.
        # The earlier attempt is cut and the last take is kept. A whole sentence said again counts too.
        i = 0
        while i < n - 1:
            hit = None
            ci = clean(words[i][2])
            if ci and str(i) not in removed:
                for j in range(i + 1, min(n, i + 30)):
                    if words[j][0] - words[i][0] > 20:
                        break
                    k = 0
                    while i + k < j and j + k < n and clean(words[i + k][2]) and \
                            clean(words[i + k][2]) == clean(words[j + k][2]):
                        k += 1
                    if not k:
                        continue
                    lone = j - i == 1 and ci not in KEEP_DOUBLE and words[j][0] - words[i][1] >= 0.35
                    if k >= (2 if j - i <= 8 else 4) or lone:
                        hes = any(words[m][2][-1:] in ",.-…—?!" for m in range(i, j)) or \
                              any(words[m + 1][0] - words[m][1] >= 0.25 for m in range(i, j))
                        if hes:
                            hit = j
                        break
            if hit:
                for m in range(i, hit):
                    removed.setdefault(str(m), "stumble")
                i = hit
            else:
                i += 1
    # long pauses, measured against this recording's own background level
    db2 = db_levels(0.02)
    pauses = []
    if len(db2):
        fl, sp = np.percentile(db2, 10), np.percentile(db2, 90)
        if sp - fl >= 10:
            thr = max(fl + max(6.0, (sp - fl) * 0.3), sp - 30)
            mx = float(conf("MH_SHORTS_MAX_PAUSE", "0.45"))
            kp = float(conf("MH_SHORTS_KEEP_PAUSE", "0.25"))
            start = None
            for k, q in enumerate(np.append(db2 < thr, False)):
                if q and start is None:
                    start = k
                elif not q and start is not None:
                    if (k - start) * 0.02 >= mx:
                        pauses.append([round(start * 0.02 + kp / 2, 3), round(k * 0.02 - kp / 2, 3)])
                    start = None
    return {"words": words, "removed": removed, "hidden": hidden, "fix": {}, "pauses": pauses,
            "layout": a.layout, "dur": DUR, "fps": FPS}


def keep_ranges(st):
    words, rem, n = st["words"], st["removed"], len(st["words"])
    cuts = [tuple(p) for p in st["pauses"]]
    kept = [i for i in range(n) if str(i) not in rem]
    if kept:
        cuts.append((0.0, max(0.0, words[kept[0]][0] - 0.15)))
        cuts.append((words[kept[-1]][1] + 0.35, DUR))
    i = 0
    while i < n:
        if str(i) not in rem:
            i += 1
            continue
        j = i
        while j + 1 < n and str(j + 1) in rem:
            j += 1
        prev_e = words[i - 1][1] if i else 0.0
        next_s = words[j + 1][0] if j + 1 < n else DUR
        cs = prev_e + min(0.06, max(0.0, words[i][0] - prev_e) / 2) if i else 0.0
        ce = next_s - min(0.06, max(0.0, next_s - words[j][1]) / 2) if j + 1 < n else DUR
        if ce > cs:
            cuts.append((cs, ce))
        i = j + 1
    pieces = [(0.0, DUR)]
    for cs, ce in sorted(cuts):
        nxt = []
        for ps, pe in pieces:
            if ce <= ps or cs >= pe:
                nxt.append((ps, pe))
                continue
            if cs > ps:
                nxt.append((ps, cs))
            if ce < pe:
                nxt.append((ce, pe))
        pieces = nxt
    fine = [(math.floor(s * FPS) / FPS, min(DUR, math.ceil(e * FPS) / FPS)) for s, e in pieces]
    out = []
    for s, e in fine:
        if e - s < 0.1:
            continue
        if out and s - out[-1][1] < 0.5 / FPS:
            out[-1] = (out[-1][0], e)
        else:
            out.append((s, e))
    return out


def map_t(keeps, t):
    o = 0.0
    for s, e in keeps:
        if s <= t < e:
            return o + t - s
        o += e - s
    return None


# ---------------- edit decision ----------------
if NEW:
    say(3, "Finding pauses, ums and stumbles")
    st = decide()
    st.update({"out": os.path.abspath(a.out), "srt_out": os.path.abspath(a.srt_out) if a.srt_out else ""})
else:
    try:
        st = json.load(open(STATE))
    except (OSError, ValueError):
        shutil.rmtree(tmp, ignore_errors=True)
        fail("No editing data for this short")
    say(1, "Rebuilding short: " + a.base)
keeps = keep_ranges(st)
if not keeps:
    shutil.rmtree(tmp, ignore_errors=True)
    fail("Nothing left to keep")
st["keeps"] = [[round(s, 4), round(e, 4)] for s, e in keeps]
cut_n = {}
for r in st["removed"].values():
    cut_n[r] = cut_n.get(r, 0) + 1
saved = DUR - sum(e - s for s, e in keeps)
os.makedirs(SD, exist_ok=True)
with open(STATE + ".tmp", "w") as f:
    json.dump(st, f)
os.replace(STATE + ".tmp", STATE)
print(f"Cuts: {cut_n.get('um', 0)} ums, {cut_n.get('repeat', 0)} repeats, {cut_n.get('stumble', 0)} stumble words, "
      f"{cut_n.get('manual', 0)} by hand, {len(st['pauses'])} long pauses ({saved:.1f}s tighter)", flush=True)

# ---------------- captions ----------------
ass = os.path.join(tmp, "subs.ass")
hook = os.path.join(META, "hooks", a.base + ".txt")
wc = ["python3", os.path.join(SCRIPTS, "word_captions.py")]
if a.reburn:
    r = subprocess.run(wc + ["chunks", a.reburn, ass, "--layout", a.layout, "--hook-file", hook])
else:
    hid = set(st.get("hidden", []))
    mw = []
    for i, (s, e, w) in enumerate(st["words"]):
        if str(i) in st["removed"] or i in hid:
            continue
        mid = map_t(keeps, (s + e) / 2)
        if mid is None:
            continue
        ms, me = map_t(keeps, s), map_t(keeps, max(s, e - 0.001))
        ms = mid - min(mid - ms, 2) if ms is not None else max(0.0, mid - 0.1)
        me = me if me is not None and me > ms else mid + 0.1
        mw.append((ms, me, st["fix"].get(str(i), w)))
    wsrt = os.path.join(tmp, "words.srt")
    write_srt(wsrt, mw)
    r = subprocess.run(wc + ["words", wsrt, ass] + ([st["srt_out"]] if st.get("srt_out") else []) +
                       ["--layout", a.layout, "--hook-file", hook])
if r.returncode != 0 or not os.path.isfile(ass):
    shutil.rmtree(tmp, ignore_errors=True)
    fail("Caption build failed")

# ---------------- sound: sample-exact joins with tiny fades ----------------
edited = os.path.join(tmp, "edited.wav")
src = wave.open(master, "rb")
sr, ch = src.getframerate(), src.getnchannels()
dst = wave.open(edited, "wb")
dst.setnchannels(ch)
dst.setsampwidth(2)
dst.setframerate(sr)
fade = int(0.008 * sr)
for s, e in keeps:
    a0, b0 = int(round(s * sr)), int(round(e * sr))
    src.setpos(max(0, min(a0, src.getnframes())))
    x = np.frombuffer(src.readframes(max(0, b0 - a0)), np.int16).reshape(-1, ch).astype(np.float32)
    m = min(fade, len(x) // 2)
    if m:
        x[:m] *= np.linspace(0, 1, m)[:, None]
        x[len(x) - m:] *= np.linspace(1, 0, m)[:, None]
    if len(x) < b0 - a0:
        x = np.vstack([x, np.zeros((b0 - a0 - len(x), ch), np.float32)])
    dst.writeframes(np.clip(x, -32768, 32767).astype(np.int16).tobytes())
src.close()
dst.close()

# ---------------- picture: cut + captions + logo in one encode ----------------
eps = 0.5 / FPS
sel = "+".join(f"between(t,{s - eps:.4f},{e - eps:.4f})" for s, e in keeps)
graph = f"[0:v]select='{sel}',setpts=N/FRAME_RATE/TB,ass=filename={ass}[v0];"
inputs = ["-i", FRAMED, "-i", edited]
logo = os.path.join(HUB, "brand", conf("MH_LOGO_FILE", "logo.png"))
if conf("MH_LOGO_ON_SHORTS", "on").lower() == "on" and os.path.isfile(logo):
    pos = conf("MH_LOGO_POSITION", "top-right")
    x = "W-w-50" if "right" in pos else "50"
    y = "H-h-60" if "bottom" in pos else "60"
    inputs += ["-i", logo]
    graph += (f"[2:v]format=rgba,colorchannelmixer=aa={conf('MH_LOGO_OPACITY', '0.85')},"
              f"scale={conf('MH_LOGO_SHORTS_WIDTH', '180')}:-1[lg];[v0][lg]overlay={x}:{y}:format=auto[v]")
else:
    graph += "[v0]null[v]"
gfile = os.path.join(tmp, "graph.txt")
open(gfile, "w").write(graph)
try:
    major = int(re.search(r"version n?(\d+)", subprocess.run(["ffmpeg", "-version"], capture_output=True,
                                                              text=True).stdout).group(1))
except Exception:
    major = 6
fc = "-/filter_complex" if major >= 7 else "-filter_complex_script"
total = sum(e - s for s, e in keeps)
os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
part = os.path.join(os.path.dirname(os.path.abspath(a.out)), "." + os.path.basename(a.out) + ".partial")
cmd = ["ffmpeg", "-nostdin", "-y", "-v", "error", "-progress", "pipe:1", "-nostats"] + inputs + \
      [fc, gfile, "-map", "[v]", "-map", "1:a", "-c:v", "libx264", "-crf", "18", "-preset",
       conf("MH_SHORTS_PRESET", "veryfast"), "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
       "-movflags", "+faststart", "-f", "mp4", part]
say(4, f"Cutting and burning captions ({total:.0f}s short)", media=total if not NEW else None)
p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
for line in p.stdout:
    if line.startswith(("out_time_us=", "out_time_ms=")):
        try:
            t = int(line.split("=")[1]) / 1e6
        except ValueError:
            continue
        say(4, f"Cutting and burning captions {int(min(0.99, t / max(1, total)) * 100)}%", frac=min(0.99, t / max(1, total)))
err = p.stderr.read()
ok = p.wait() == 0 and os.path.isfile(part)
if ok:
    got = float(probe(part, "format=duration") or 0)
    ok = abs(got - total) < 1.0
    if not ok:
        err = f"length check failed ({got:.1f}s vs {total:.1f}s)"
shutil.rmtree(tmp, ignore_errors=True)
if not ok:
    try:
        os.remove(part)
    except OSError:
        pass
    print(err[-400:], file=sys.stderr)
    fail("Short build failed")
os.replace(part, a.out)
say(4, f"Ready: {os.path.basename(a.out)} ({total:.0f}s, {saved:.0f}s of pauses, ums and stumbles cut)", "done")

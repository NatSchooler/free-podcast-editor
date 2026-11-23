#!/usr/bin/env python3
"""Sound only (v2.9.8): house sound, breaths turned down in place, levels evened out, MP3 out.
Nothing is cut except the breath before the first word.
  sound_only.py IN.wav|IN.m4a OUT.mp3 --words WORDS.srt [--job JOB]"""
import argparse, json, os, re, shutil, subprocess, sys, time
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ai_common import read_srt, status, conf, shm_dir

DEFAULT_CHAIN = "highpass=f=70"
ap = argparse.ArgumentParser()
ap.add_argument("inp")
ap.add_argument("out")
ap.add_argument("--words", default="")
ap.add_argument("--job", default="")
a = ap.parse_args()
BASE = os.path.splitext(os.path.basename(a.inp))[0]
JOB = a.job or "sound_" + BASE
SR = 48000
HOP = SR // 100            # 10 ms frames
_last = [0.0]


def say(step, label, state="running", frac=None, media=None):
    if frac is not None:
        if time.time() - _last[0] < 3:
            return
        _last[0] = time.time()
    status(JOB, "sound", step, 3, label, state, media, frac)
    if frac is None:
        print(label, flush=True)


tmp = None


def fail(msg):
    if tmp:
        shutil.rmtree(tmp, ignore_errors=True)
    say(3, f"{msg}: {BASE}", "error")
    sys.exit(1)


def probe(path, entries, stream=None):
    cmd = ["ffprobe", "-v", "error"] + (["-select_streams", stream] if stream else []) + \
          ["-show_entries", entries, "-of", "csv=p=0", path]
    return subprocess.run(cmd, capture_output=True, text=True).stdout.strip().split("\n")[0].strip(",")


try:
    DUR = float(probe(a.inp, "format=duration") or 0)
    CH = max(1, min(2, int(probe(a.inp, "stream=channels", "a:0") or 1)))
except ValueError:
    DUR, CH = 0.0, 1
if DUR <= 0:
    fail("Could not read the audio")

# ---------------- decode to float in RAM ----------------
tmp = shm_dir("mh_sound_", DUR * SR * CH * 4 * 2.2)
raw = os.path.join(tmp, "in.f32")
if subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", a.inp, "-vn", "-ac", str(CH), "-ar", str(SR),
                   "-f", "f32le", raw]).returncode != 0 or not os.path.getsize(raw):
    fail("Could not read the audio")
x = np.memmap(raw, np.float32, "r+")
x = x[:len(x) // CH * CH].reshape(-1, CH)
N = len(x)
NF = max(1, N // HOP)

say(2, "Finding the breaths (nothing is cut)")
db = np.full(NF, -100.0)
STEP = 30000
for f0 in range(0, NF, STEP):
    f1 = min(NF, f0 + STEP)
    seg = np.asarray(x[f0 * HOP:f1 * HOP]).mean(1).reshape(-1, HOP)
    db[f0:f1] = 10 * np.log10((seg.astype(np.float64) ** 2).mean(1) + 1e-10)
floor, speech = float(np.percentile(db, 10)), float(np.percentile(db, 90))

words = []
if a.words and os.path.isfile(a.words):
    for s, e, t in read_srt(a.words, drop_noise=False):
        if any(w.strip() and not re.fullmatch(r"[\[\(].*[\]\)]", w.strip()) for w in t.split()):
            words.append((float(s), float(max(e, s + 0.02))))
words.sort()

BDB = float(conf("MH_SOUND_ONLY_BREATH_DB", "12"))
fr = lambda t: max(0, min(NF, int(t * 100)))
lead, breaths = 0.0, 0
gain_db = np.zeros(NF)
if words and speech - floor >= 10:
    # the opening breath: everything up to just before the first word, but never into speech-level sound
    cut = words[0][0] - 0.12
    if cut > 0.1:
        loud = np.where(db[:fr(cut)] >= speech - 6)[0]
        if len(loud):
            cut = loud[0] / 100 - 0.12
        lead = round(max(0.0, cut), 3) if cut > 0.1 else 0.0
    # breaths between words (and after the last one): turned down where they sit
    gaps = [(lead, words[0][0])] + [(words[k][1], words[k + 1][0]) for k in range(len(words) - 1)] + [(words[-1][1], DUR)]
    for gs, ge in gaps:
        i0, i1 = fr(gs + 0.08), fr(ge - 0.08)
        if i1 - i0 < 12:
            continue
        seg = db[i0:i1]
        if seg.max() > speech - 3:        # probably a word whisper missed, or a laugh: leave it alone
            continue
        idx = np.where(seg > floor + 6)[0]
        if len(idx) < 8:                  # under 80 ms of sound: just room tone
            continue
        gain_db[i0 + idx[0]:i0 + idx[-1] + 1] = -BDB
        breaths += 1

if breaths:
    lin = np.convolve(10 ** (gain_db / 20), np.ones(5) / 5, "same")   # 50 ms soft edges, no clicks
    centres = (np.arange(NF) + 0.5) * HOP
    CH_S = 2_000_000
    for s0 in range(0, N, CH_S):
        s1 = min(N, s0 + CH_S)
        f0, f1 = s0 // HOP, min(NF, s1 // HOP + 1)
        if lin[f0:f1].min() > 0.999:
            continue
        x[s0:s1] *= np.interp(np.arange(s0, s1), centres, lin).astype(np.float32)[:, None]
    x.flush()
del x

# ---------------- house sound + even levels, MP3 out ----------------
# v2.9.8: the house sound comes from audio_polish.py, the same chain your episodes use (MH_AUDIO_PRESET),
# so the two always match. MH_SOUND_ONLY_CHAIN in house_style.txt overrides it if ever set.
lufs = conf("MH_SOUND_ONLY_LUFS", "-16")
own = conf("MH_SOUND_ONLY_CHAIN", "").strip()
staged = os.path.join(tmp, "clean.wav")
if subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "f32le", "-ar", str(SR), "-ac", str(CH), "-i", raw,
                   "-af", f"atrim=start={lead},asetpts=PTS-STARTPTS,afade=t=in:d=0.02", "-c:a", "pcm_f32le", staged]).returncode != 0:
    fail("Could not prepare the audio")
os.remove(raw)
say(3, "Applying your house sound and measuring loudness")
af, used = None, "house sound"
polish = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audio_polish.py")
if not own and os.path.isfile(polish):
    r = subprocess.run(["python3", polish, staged, str(lufs)], capture_output=True, text=True)
    out = [l for l in r.stdout.strip().split("\n") if l.strip()]
    if r.returncode == 0 and out and "loudnorm" in out[-1]:
        af = out[-1].strip()
if af is None:
    chain = own or DEFAULT_CHAIN
    used = "own chain" if own else "fallback chain"
    r = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-y", "-i", staged,
                        "-af", f"{chain},loudnorm=I={lufs}:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True)
    try:
        m = json.loads(r.stderr[r.stderr.rindex("{"):r.stderr.rindex("}") + 1])
        ln = (f"loudnorm=I={lufs}:TP=-1.5:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
              f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    except (ValueError, KeyError):
        ln = f"loudnorm=I={lufs}:TP=-1.5:LRA=11"
    af = f"{chain},{ln}"
total = DUR - lead
os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
part = os.path.join(os.path.dirname(os.path.abspath(a.out)), "." + os.path.basename(a.out) + ".partial")
p = subprocess.Popen(["ffmpeg", "-nostdin", "-y", "-v", "error", "-progress", "pipe:1", "-nostats", "-i", staged,
                      "-af", af, "-ar", "44100", "-c:a", "libmp3lame", "-b:a", "192k",
                      "-id3v2_version", "3", "-f", "mp3", part],
                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
for line in p.stdout:
    if line.startswith(("out_time_us=", "out_time_ms=")):
        try:
            t = int(line.split("=")[1]) / 1e6
        except ValueError:
            continue
        say(3, f"House sound and levels {int(min(0.99, t / max(1, total)) * 100)}%", frac=min(0.99, t / max(1, total)))
err = p.stderr.read()
ok = p.wait() == 0 and os.path.isfile(part)
if ok:
    got = float(probe(part, "format=duration") or 0)
    ok = abs(got - total) < 0.5
    if not ok:
        err = f"length check failed ({got:.1f}s vs {total:.1f}s)"
shutil.rmtree(tmp, ignore_errors=True)
tmp = None
if not ok:
    try:
        os.remove(part)
    except OSError:
        pass
    print(err[-400:], file=sys.stderr)
    fail("Sound build failed")
os.replace(part, a.out)
extra = f", opening breath ({lead:.1f}s) removed" if lead else ""
say(3, f"Ready: {os.path.basename(a.out)} ({breaths} breath{'' if breaths == 1 else 's'} turned down{extra}, no words cut, {used})", "done")

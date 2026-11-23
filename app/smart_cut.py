#!/usr/bin/env python3
"""Build the edited episode from <base>_clean.mp4 and a cuts file.
Usage: smart_cut.py SOURCE CUTS_FILE OUT.mp4 [--words WORDS.srt] [--meta PREFIX] [--outro FILE] [--job ID --step N --total T]

Cuts file lines:  HOOK: a - b   |   keep ranges  a - b   |   CLEAN: on  (remove fillers/stumbles/long pauses)
  - Few cuts: long sections are COPIED untouched, only the few seconds at each cut are rendered (fast).
  - Many cuts (filler/pause clean-up) or a burned-in logo: one single-pass render of the whole edit.
  - Every cut is snapped to a video frame and the audio is rebuilt sample-exact with tiny fades at each
    join, so there are no clicks and no lip-sync drift even after hundreds of cuts.
  - The finished file is test-decoded at every join; anything odd triggers a clean full render."""
import argparse, json, math, os, re, subprocess, sys, tempfile, shutil, wave
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ai_common import read_cuts, read_srt, META, HUB, status, conf, cuts_flag, shm_dir, vaapi_device

ap = argparse.ArgumentParser()
ap.add_argument("src")
ap.add_argument("cuts")
ap.add_argument("out")
ap.add_argument("--job", default="")
ap.add_argument("--step", type=int, default=1)
ap.add_argument("--total", type=int, default=3)
ap.add_argument("--full", action="store_true", help="always do a single-pass render")
ap.add_argument("--outro")
ap.add_argument("--words", help="word-level transcript (for filler removal)")
ap.add_argument("--meta", help="meta prefix to save the final edit decision (for chapters, captions, text editing)")
a = ap.parse_args()


def ff(cmd):
    return subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error"] + cmd, capture_output=True, text=True)


def _ffmpeg_major():
    try:
        out = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True).stdout
        return int(re.search(r"version n?(\d+)", out).group(1))
    except Exception:
        return 6


FC_OPT = "-/filter_complex" if _ffmpeg_major() >= 7 else "-filter_complex_script"


class _R:
    def __init__(self, rc, err):
        self.returncode, self.stderr = rc, err


def ff_script(pre, script_text, post, tmp, progress=None):
    """Run ffmpeg with a (possibly huge) filter graph from a file. progress=(label, seconds) shows a live %."""
    path = os.path.join(tmp, "graph.txt")
    open(path, "w").write(script_text)
    cmd = ["ffmpeg", "-nostdin", "-y", "-loglevel", "error"] + pre + [FC_OPT, path] + post
    if not progress:
        return subprocess.run(cmd, capture_output=True, text=True)
    label, total_s = progress
    p = subprocess.Popen(cmd[:5] + ["-progress", "pipe:1", "-nostats"] + cmd[5:], stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True)
    for line in p.stdout:
        if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
            try:
                t = int(line.split("=")[1]) / 1e6
            except ValueError:
                continue
            frac = max(0.0, min(0.99, t / max(1.0, total_s)))
            say(f"{label} {int(frac * 100)}%", frac=frac, quiet=True)
    err = p.stderr.read()
    p.wait()
    return _R(p.returncode, err)


def pj(path, args):
    r = subprocess.run(["ffprobe", "-v", "error", "-of", "json"] + args + [path], capture_output=True, text=True)
    try:
        return json.loads(r.stdout or "{}")
    except ValueError:
        return {}


_last_say = [0.0]


def say(label, frac=None, quiet=False):
    import time as _t
    if frac is not None and _t.time() - _last_say[0] < 3:
        return
    _last_say[0] = _t.time()
    if a.job:
        status(a.job, "youtube", a.step, a.total, label, frac=frac)
    if not quiet:
        print(label, flush=True)


# ---------------- source facts ----------------
v = (pj(a.src, ["-select_streams", "v:0", "-show_entries",
                "stream=codec_name,width,height,r_frame_rate,pix_fmt,profile,time_base,start_time"]).get("streams") or [{}])[0]
au = (pj(a.src, ["-select_streams", "a:0", "-show_entries", "stream=sample_rate"]).get("streams") or [{}])[0]
W, H = v.get("width", 1920), v.get("height", 1080)
FPS_S = v.get("r_frame_rate", "30/1")
try:
    n_, d_ = FPS_S.split("/")
    FPS = float(n_) / float(d_ or 1)
except (ValueError, ZeroDivisionError):
    FPS = 30.0
VST = float(v.get("start_time") or 0)
PIX = v.get("pix_fmt") if v.get("pix_fmt") in ("yuv420p", "yuvj420p") else "yuv420p"
PROF = {"High": "high", "Main": "main", "Constrained Baseline": "baseline", "Baseline": "baseline"}.get(v.get("profile", ""), "high")
TS = (v.get("time_base") or "1/90000").split("/")[-1]
SR = int(au.get("sample_rate", 48000))
VAAPI_DEV = vaapi_device()
USE_GPU = [conf("MH_ENCODER", "cpu").lower() == "gpu" and os.path.exists(VAAPI_DEV)]


def enc_args():
    if USE_GPU[0]:
        return ["-c:v", "h264_vaapi", "-qp", conf("MH_GPU_QP", "19"), "-profile:v", "high", "-g", "60", "-r", FPS_S,
                "-bsf:v", "h264_mp4toannexb", "-an", "-f", "mpegts"]
    return ["-c:v", "libx264", "-crf", "18", "-preset", conf("MH_CPU_PRESET", "fast"), "-pix_fmt", PIX,
            "-profile:v", PROF, "-r", FPS_S, "-bsf:v", "h264_mp4toannexb", "-an", "-f", "mpegts"]


def snap(t):
    return VST + round((t - VST) * FPS) / FPS


# ---------------- edit decision ----------------
hook, keeps = read_cuts(a.cuts)
if hook and not 0 < hook[1] - hook[0] <= 25:
    print(f"Hook skipped: a cold open must be 25 seconds or less (was {hook[1] - hook[0]:.0f}s)", flush=True)
    hook = None
if not keeps:
    sys.exit("No keep-ranges in the cuts file")
OUTRO = a.outro if a.outro and os.path.isfile(a.outro) else None
LOGO = os.path.join(HUB, "brand", conf("MH_LOGO_FILE", "logo.png"))
LOGO_LONG = conf("MH_LOGO_ON_LONGFORM", "off").lower() == "on" and os.path.isfile(LOGO)

tmp = tempfile.mkdtemp(prefix="mh_cut_", dir="/tmp")  # video parts stay on disk (they can be many GB)
_dur = float((pj(a.src, ["-show_entries", "format=duration"]).get("format") or {}).get("duration") or 0)
atmp = shm_dir("mh_cutaudio_", _dur * SR * 2 * 2 * 2)  # master + edited audio buffers in RAM
master_wav = os.path.join(atmp, "master.wav")
say("Edit: reading the audio")
r = ff(["-i", a.src, "-vn", "-ac", "2", "-ar", str(SR), "-c:a", "pcm_s16le", master_wav])
if r.returncode != 0:
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(atmp, ignore_errors=True)
    sys.exit("Could not read the audio: " + r.stderr[-200:])

FILLER = re.compile(r"^(u+m+|u+h+m*|e+r+m+|e+r+|a+h+|a+r+m*|h+m+|m+h*m+|mhm|mm+)$", re.I)
KEEP_DOUBLE = {"very", "really", "so", "no", "yes", "yeah", "bye", "ha", "well", "now", "many", "much", "more",
               "long", "far", "again", "ok", "okay", "go", "come", "on", "that", "had", "is"}
stats = {"fillers": 0, "repeats": 0, "pauses": 0}


def subtract(ranges, cut):
    cut = sorted(cut)
    out = []
    for s, e in ranges:
        pieces = [(s, e)]
        for cs, ce in cut:
            if ce <= s or cs >= e:
                continue
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
        out += pieces
    return out


_DB = []


def levels():
    """Loudness of the recording in 10 ms steps (computed once)."""
    if _DB:
        return _DB[0]
    w = wave.open(master_wav, "rb")
    sr, ch = w.getframerate(), w.getnchannels()
    hop = int(sr * 0.01)
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
    _DB.append(np.concatenate(out) if out else np.zeros(0))
    return _DB[0]


def quietest(t0, t1):
    """(time, level) of the quietest 10 ms moment between t0 and t1, or (None, None)."""
    db = levels()
    i0, i1 = max(0, int(t0 / 0.01)), min(len(db), int(t1 / 0.01) + 1)
    if i1 - i0 < 1:
        return None, None
    i = i0 + int(np.argmin(db[i0:i1]))
    return (i + 0.5) * 0.01, float(db[i])


def gap_level():
    """A level that only the gaps between words reach: anything above it is inside a word."""
    db = levels()
    if not len(db):
        return -999
    floor, speech = np.percentile(db, 10), np.percentile(db, 90)
    return floor + (speech - floor) * 0.35


def find_pauses(min_len):
    """Pauses relative to THIS recording's own background level (not a fixed dB), in 20 ms steps."""
    w = wave.open(master_wav, "rb")
    sr, ch = w.getframerate(), w.getnchannels()
    hop = int(sr * 0.02)
    levels = []
    while True:
        buf = w.readframes(hop * 500)
        if not buf:
            break
        x = np.frombuffer(buf, np.int16).reshape(-1, ch).astype(np.float32).mean(1)
        n = len(x) // hop
        if n:
            levels.append(10 * np.log10((x[:n * hop].reshape(n, hop) ** 2).mean(1) + 1e-6))
    w.close()
    if not levels:
        return []
    db = np.concatenate(levels)
    floor, speech = np.percentile(db, 10), np.percentile(db, 90)
    if speech - floor < 10:
        return []  # no clear gap between talk and background: do not guess
    thr = floor + max(6.0, (speech - floor) * 0.3)
    quiet = db < thr
    out, start = [], None
    for i, q in enumerate(np.append(quiet, False)):
        if q and start is None:
            start = i
        elif not q and start is not None:
            if (i - start) * 0.02 >= min_len:
                out.append((start * 0.02, i * 0.02))
            start = None
    return out


def clean_ranges(keeps):
    rem = []
    words = []
    if a.words and os.path.isfile(a.words) and conf("MH_REMOVE_FILLERS", "on").lower() == "on":
        for s, e, t in read_srt(a.words, drop_noise=False):
            for w in t.split():
                words.append((s, e, re.sub(r"[^\w']", "", w).lower()))
        gl = gap_level()
        repeats = conf("MH_REMOVE_REPEATS", "off").lower() == "on"

        def safe_cut(a0, a1, b0, b1):
            """Cut only between the quietest points near each edge, and only if both really are gaps
            between words; otherwise leave the um in rather than clip a word."""
            ta, la = quietest(a0, a1)
            tb, lb = quietest(b0, b1)
            if ta is None or tb is None or la > gl or lb > gl or tb - ta < 0.08:
                return None
            return ta, tb

        for i, (s, e, w) in enumerate(words):
            prev_e = words[i - 1][1] if i else s - 1
            next_s = words[i + 1][0] if i + 1 < len(words) else e + 1
            if FILLER.match(w):
                c = safe_cut(max(prev_e - 0.03, s - 0.15), s + 0.06, e - 0.06, min(next_s + 0.03, e + 0.15))
                if c:
                    rem.append(c)
                    stats["fillers"] += 1
            elif repeats and i + 1 < len(words) and w and w == words[i + 1][2] and w not in KEEP_DOUBLE and next_s - e < 0.6:
                c = safe_cut(max(prev_e - 0.03, s - 0.15), s + 0.06, next_s - 0.15, next_s + 0.03)
                if c:
                    rem.append(c)  # stumble: "I I think" -> "I think"
                    stats["repeats"] += 1
    if conf("MH_REMOVE_PAUSES", "on").lower() == "on":
        mx = float(conf("MH_MAX_PAUSE", "0.9"))
        kp = float(conf("MH_KEEP_PAUSE", "0.45"))
        for ss, se in find_pauses(mx):
            rem.append((ss + kp / 2, se - kp / 2))
            stats["pauses"] += 1
    fine = subtract(keeps, rem)
    # round each kept section OUTWARDS to whole video frames, so a frame edge never shaves a word
    fine = [(VST + math.floor((s - VST) * FPS) / FPS, VST + math.ceil((e - VST) * FPS) / FPS) for s, e in fine]
    merged = []
    for s, e in fine:
        if e - s < 0.2:
            continue
        if merged and s - merged[-1][1] < 0.5 / FPS:
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))
    return merged


before = sum(e - s for s, e in keeps)
if cuts_flag(a.cuts, "CLEAN"):
    say("Edit: finding ums, stumbles and long pauses")
    keeps = clean_ranges(keeps)
    saved = before - sum(e - s for s, e in keeps)
    say(f"Edit: removing {stats['fillers']} fillers, {stats['repeats']} stumbles, {stats['pauses']} long pauses "
        f"({saved:.0f}s tighter)")
else:
    keeps = [(snap(s), snap(e)) for s, e in keeps]
if hook:
    hook = (snap(hook[0]), snap(hook[1]))


# ---------------- mid-roll advert (Z:\brand\midroll.mp4, or midroll.mp3 shown over a branded card) ----------------
def find_midroll():
    b = os.path.join(HUB, "brand")
    for ext in ("mp4", "mov", "MP4", "MOV"):
        p = os.path.join(b, "midroll." + ext)
        if os.path.isfile(p):
            return p, True
    for ext in ("mp3", "wav", "m4a", "MP3", "WAV", "M4A"):
        p = os.path.join(b, "midroll." + ext)
        if os.path.isfile(p):
            return p, False
    return None, False


MID, MID_IS_VIDEO = find_midroll() if conf("MH_MIDROLL", "on").lower() == "on" else (None, False)
MID_DUR = float((pj(MID, ["-show_entries", "format=duration"]).get("format") or {}).get("duration") or 0) if MID else 0
MID_AFTER = None  # index of the keep-range the advert follows


def place_midroll():
    """First natural pause at or after MH_MIDROLL_AT seconds of the edited episode (default 6 minutes)."""
    global keeps, MID_AFTER
    at = float(conf("MH_MIDROLL_AT", "360"))
    total = (hook[1] - hook[0] if hook else 0) + sum(e - s for s, e in keeps)
    if not MID or MID_DUR <= 0 or total < at + 120:
        return
    cum = hook[1] - hook[0] if hook else 0
    for i, (s, e) in enumerate(keeps):
        end = cum + (e - s)
        if at <= end <= at + 90 and i < len(keeps) - 1:
            MID_AFTER = i  # an existing join (a removed um or pause) is a natural spot
            return
        if end > at + 90 or (end > at and i == len(keeps) - 1):
            # split this section at the first real pause between words after the target time
            m = s + max(0.0, at - cum)
            p = None
            if a.words and os.path.isfile(a.words):
                ws = [(ws_, we_) for ws_, we_, _ in read_srt(a.words, drop_noise=False) if s <= ws_ < e]
                for (s1, e1), (s2, e2) in zip(ws, ws[1:]):
                    if e1 >= m and s2 - e1 >= 0.25 and s2 < e - 1:
                        p = (e1 + s2) / 2
                        break
            p = snap(p if p else min(m, e - 1))
            if p - s < 1 or e - p < 1:
                MID_AFTER = max(0, i - 1) if i else None
                return
            keeps = keeps[:i] + [(s, p), (p, e)] + keeps[i + 1:]
            MID_AFTER = i
            return
        cum = end


place_midroll()
if MID_AFTER is not None:
    say(f"Edit: mid-roll advert ({MID_DUR:.0f}s) goes in at a pause after "
        f"{int(((hook[1] - hook[0]) if hook else 0) + sum(e - s for s, e in keeps[:MID_AFTER + 1])) // 60} min")


def midroll_video(td):
    """The advert as a video clip: midroll.mp4 as it is, or the mp3 over a plain card with the logo."""
    if MID_IS_VIDEO:
        return MID
    out = os.path.join(td, "midroll_card.mp4")
    if os.path.isfile(out):
        return out
    logo = os.path.join(HUB, "brand", conf("MH_LOGO_FILE", "logo.png"))
    bg = conf("MH_MIDROLL_CARD_COLOUR", "#000000").lstrip("#")
    cmd = ["-f", "lavfi", "-i", f"color=c=0x{bg}:s={W}x{H}:r={FPS_S}:d={MID_DUR:.3f}"]
    if os.path.isfile(logo):
        cmd += ["-i", logo, "-filter_complex", f"[1:v]scale={int(W * 0.35)}:-1[lg];[0:v][lg]overlay=(W-w)/2:(H-h)/2[v]",
                "-map", "[v]"]
    else:
        cmd += ["-map", "0:v"]
    ff(cmd + ["-t", f"{MID_DUR:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", out])
    return out


if not keeps:
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(atmp, ignore_errors=True)
    sys.exit("Nothing left after clean-up")


# ---------------- video ----------------
def logo_chain(label_in, label_out, width):
    if not LOGO_LONG:
        return f"[{label_in}]null[{label_out}]"
    pos = conf("MH_LOGO_POSITION", "top-right")
    m = 40
    x = f"W-w-{m}" if "right" in pos else str(m)
    y = f"H-h-{m}" if "bottom" in pos else str(m)
    op = conf("MH_LOGO_OPACITY", "0.85")
    lp = LOGO.replace("\\", "/").replace(":", "\\\\:").replace("'", "")
    return (f"movie='{lp}',format=rgba,colorchannelmixer=aa={op},scale={width}:-1[lg];"
            f"[{label_in}][lg]overlay={x}:{y}:format=auto[{label_out}]")


LW = int(conf("MH_LOGO_LONGFORM_WIDTH", "200"))


def nframes(d):
    return str(max(1, int(round(d * FPS))))


def enc_part(out, src_args, vf, frames=None, progress=None):
    graph = f"[0:v]{vf}[v0];" + logo_chain("v0", "v1", LW)
    graph += ";[v1]format=nv12,hwupload[v]" if USE_GPU[0] else ";[v1]null[v]"
    pre = (["-vaapi_device", VAAPI_DEV] if USE_GPU[0] else []) + src_args
    return ff_script(pre, graph, ["-map", "[v]"] + (["-frames:v", frames] if frames else []) + enc_args() + [out],
                     tmp, progress)


def keyframes():
    st = os.stat(a.src)
    cache = os.path.join(META, os.path.basename(a.src) + ".keyframes.json")
    try:
        c = json.load(open(cache))
        if c.get("sig") == [st.st_size, int(st.st_mtime)]:
            return c["kf"]
    except (OSError, ValueError):
        pass
    say("Edit: reading keyframes (first time only for this episode)")
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-skip_frame", "nokey", "-show_entries",
                        "frame=pts_time,best_effort_timestamp_time", "-of", "csv=p=0", a.src], capture_output=True, text=True)
    kf = []
    for line in r.stdout.splitlines():
        for x in line.split(","):
            try:
                kf.append(float(x))
                break
            except ValueError:
                continue
    kf = sorted(set(round(x, 3) for x in kf))
    try:
        os.makedirs(META, exist_ok=True)
        json.dump({"sig": [st.st_size, int(st.st_mtime)], "kf": kf}, open(cache, "w"))
    except OSError:
        pass
    return kf


def make_plan(mode):
    plan = [("hook", hook[0], hook[1])] if hook else []
    if mode == "render":
        if MID_AFTER is None:
            plan.append(("body", 0, len(keeps)))
        else:
            plan += [("body", 0, MID_AFTER + 1), ("midroll", 0.0, MID_DUR), ("body", MID_AFTER + 1, len(keeps))]
    else:
        kf = keyframes() if v.get("codec_name") == "h264" else []
        for ki, (s, e) in enumerate(keeps):
            k1 = next((k for k in kf if k >= s + 0.04), None)
            k2 = next((k for k in reversed(kf) if k <= e - 0.04), None)
            if not kf or k1 is None or k2 is None or k2 - k1 < 4:
                plan.append(("enc", s, e))
                if ki == MID_AFTER:
                    plan.append(("midroll", 0.0, MID_DUR))
                continue
            if k1 - s > 0.5 / FPS:
                plan.append(("enc", s, k1))
            plan.append(("copy", k1, k2))
            if e - k2 > 0.5 / FPS:
                plan.append(("enc", k2, e))
            if ki == MID_AFTER:
                plan.append(("midroll", 0.0, MID_DUR))
    if OUTRO:
        od = float((pj(OUTRO, ["-show_entries", "format=duration"]).get("format") or {}).get("duration", 0))
        plan.append(("outro", 0.0, od))
    return plan


def build_video(plan, td):
    parts, joins, t = [], [], 0.0
    body_len = sum(e - s for s, e in keeps)
    eps = 0.5 / FPS
    for i, (kind, s, e) in enumerate(plan):
        out = os.path.join(td, f"p{i:03d}.ts")
        if kind == "copy":
            say(f"Edit: copying part {i + 1}/{len(plan)}")
            r = ff(["-ss", f"{s:.4f}", "-i", a.src, "-map", "0:v:0", "-frames:v", nframes(e - s), "-c", "copy",
                    "-bsf:v", "h264_mp4toannexb", "-an", "-f", "mpegts", out])
        elif kind == "hook":
            say("Edit: rendering the cold open")
            r = enc_part(out, ["-ss", f"{s:.4f}", "-i", a.src],
                         f"scale=trunc(iw*1.06/2)*2:trunc(ih*1.06/2)*2,crop={W}:{H},setsar=1,fade=t=in:st=0:d=0.25",
                         nframes(e - s))
        elif kind == "outro":
            say("Edit: rendering the outro")
            r = enc_part(out, ["-i", OUTRO],
                         f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,fps={FPS_S},setsar=1")
            e = s + e  # duration
        elif kind == "midroll":
            say("Edit: adding the mid-roll advert")
            r = enc_part(out, ["-i", midroll_video(td)],
                         f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,fps={FPS_S},setsar=1",
                         nframes(e - s))
        elif kind == "body":
            part = keeps[int(s):int(e)]
            plen = sum(e0 - s0 for s0, e0 in part)
            say(f"Edit: rendering the episode in one pass ({len(part)} sections)")
            sel = "+".join(f"between(t,{s0 - eps:.4f},{e0 - eps:.4f})" for s0, e0 in part)
            r = enc_part(out, ["-i", a.src], f"select='{sel}',setpts=N/FRAME_RATE/TB,setsar=1",
                         progress=(f"Edit: rendering ({'graphics card' if USE_GPU[0] else 'CPU'})", plen))
            s, e = 0.0, plen
        else:
            say(f"Edit: rendering cut edge {i + 1}/{len(plan)}")
            r = enc_part(out, ["-ss", f"{s:.4f}", "-i", a.src], "setsar=1", nframes(e - s))
        if r.returncode != 0:
            return None, f"{kind} part failed: {r.stderr[-300:]}"
        parts.append(out)
        t += e - s
        joins.append(t)
    lst = os.path.join(td, "list.txt")
    open(lst, "w").write("".join(f"file '{p}'\n" for p in parts))
    vid = os.path.join(td, "video.ts")
    r = ff(["-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", vid])
    if r.returncode != 0:
        return None, "join failed: " + r.stderr[-200:]
    return (vid, joins), None


# ---------------- audio: sample-exact, 8 ms fades at every join ----------------
def build_audio(td):
    say("Edit: rebuilding the audio track")
    out_wav = os.path.join(atmp, f"edit_{os.path.basename(td)}.wav")
    src = wave.open(master_wav, "rb")
    sr, ch = src.getframerate(), src.getnchannels()
    dst = wave.open(out_wav, "wb")
    dst.setnchannels(ch)
    dst.setsampwidth(2)
    dst.setframerate(sr)
    fade = int(0.012 * sr)
    total = src.getnframes()

    def copy_range(reader, a0, b0, f_in, f_out):
        reader.setpos(max(0, min(a0, reader.getnframes())))
        n = max(0, min(b0, reader.getnframes()) - max(0, a0))
        pos = 0
        chunk = sr * 10
        while pos < n:
            k = min(chunk, n - pos)
            x = np.frombuffer(reader.readframes(k), np.int16).reshape(-1, ch).astype(np.float32)
            if f_in and pos == 0:
                m = min(fade, len(x))
                x[:m] *= np.linspace(0, 1, m)[:, None]
            if f_out and pos + k >= n:
                m = min(fade, len(x))
                x[len(x) - m:] *= np.linspace(1, 0, m)[:, None]
            dst.writeframes(np.clip(x, -32768, 32767).astype(np.int16).tobytes())
            pos += k
        want = b0 - a0
        if n < want:  # past the end of the source: pad with silence to keep sync
            dst.writeframes(np.zeros((want - n, ch), np.int16).tobytes())

    def insert_clip(path, dur, name, fade_out=True):
        w = os.path.join(atmp, name)
        has_a = bool(pj(path, ["-select_streams", "a:0", "-show_entries", "stream=index"]).get("streams"))
        if has_a:
            ff(["-i", path, "-vn", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-ac", str(ch), "-ar", str(sr),
                "-c:a", "pcm_s16le", "-t", f"{dur:.3f}", w])
        if has_a and os.path.isfile(w):
            o = wave.open(w, "rb")
            copy_range(o, 0, int(round(dur * sr)), True, fade_out)
            o.close()
            os.remove(w)
        else:
            dst.writeframes(np.zeros((int(round(dur * sr)), ch), np.int16).tobytes())

    if hook:
        copy_range(src, int(round(hook[0] * sr)), int(round(hook[1] * sr)), True, True)
    for ki, (s, e) in enumerate(keeps):
        copy_range(src, int(round(s * sr)), int(round(e * sr)), True, True)
        if ki == MID_AFTER:
            insert_clip(MID, MID_DUR, "midroll.wav")
    src.close()
    if OUTRO:
        ow = os.path.join(atmp, "outro.wav")
        od = float((pj(OUTRO, ["-show_entries", "format=duration"]).get("format") or {}).get("duration", 0))
        has_a = bool(pj(OUTRO, ["-select_streams", "a:0", "-show_entries", "stream=index"]).get("streams"))
        if has_a:
            ff(["-i", OUTRO, "-vn", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-ac", str(ch), "-ar", str(sr),
                "-c:a", "pcm_s16le", "-t", f"{od:.3f}", ow])
        if has_a and os.path.isfile(ow):
            o = wave.open(ow, "rb")
            copy_range(o, 0, int(round(od * sr)), True, False)
            o.close()
        else:
            dst.writeframes(np.zeros((int(round(od * sr)), ch), np.int16).tobytes())
    dst.close()
    aac = os.path.join(td, "audio.m4a")
    r = ff(["-i", out_wav, "-c:a", "aac", "-b:a", "192k", aac])
    try:
        os.remove(out_wav)  # free the RAM straight away
    except OSError:
        pass
    return (aac if r.returncode == 0 else None), (None if r.returncode == 0 else r.stderr[-200:])


def verify(path, joins, expected):
    say("Edit: checking every join")
    dur = float((pj(path, ["-show_entries", "format=duration"]).get("format") or {}).get("duration", 0))
    if abs(dur - expected) > 0.5 + 0.02 * len(joins):
        return f"length check failed ({dur:.1f}s vs {expected:.1f}s)"
    for j in [0.0] + joins[:-1]:
        r = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{max(0, j - 1.5):.3f}", "-i", path, "-t", "3",
                            "-map", "0:v:0", "-f", "null", "-"], capture_output=True, text=True)
        if r.returncode != 0 or r.stderr.strip():
            return f"join at {j:.1f}s did not decode cleanly"
    return None


def attempt(mode):
    td = os.path.join(tmp, mode)
    os.makedirs(td, exist_ok=True)
    plan = make_plan(mode)
    res, err = build_video(plan, td)
    if err:
        return err
    vid, joins = res
    aac, err = build_audio(td)
    if err:
        return "audio failed: " + err
    r = ff(["-fflags", "+genpts", "-i", vid, "-i", aac, "-map", "0:v:0", "-map", "1:a:0", "-c", "copy",
            "-video_track_timescale", TS, a.out])
    if r.returncode != 0:
        return "mux failed: " + r.stderr[-200:]
    expected = (hook[1] - hook[0] if hook else 0) + sum(e - s for s, e in keeps) + (MID_DUR if MID_AFTER is not None else 0)
    if OUTRO:
        expected += float((pj(OUTRO, ["-show_entries", "format=duration"]).get("format") or {}).get("duration", 0))
    if mode == "smart":
        print(f"Smart cut: {sum(1 for p in plan if p[0] == 'copy')} long section(s) copied without re-rendering", flush=True)
    return verify(a.out, joins, expected)


try:
    if a.meta:
        json.dump({"hook": list(hook) if hook else None, "keeps": [list(k) for k in keeps], "stats": stats,
                   "midroll": [MID_AFTER, MID_DUR] if MID_AFTER is not None else None},
                  open(a.meta + ".final.json", "w"))
    many = len(keeps) > 40
    first = "render" if (a.full or many or LOGO_LONG) else "smart"
    err = attempt(first)
    if err and USE_GPU[0]:
        print(f"Graphics-card encode failed ({err}); retrying on the CPU", flush=True)
        USE_GPU[0] = False
        err = attempt(first)
    if err and first == "smart":
        print(f"Smart cut not used ({err}); doing a full render instead", flush=True)
        err = attempt("render")
    if err:
        sys.exit("Edit failed: " + err)
    print("Edit OK", flush=True)
finally:
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(atmp, ignore_errors=True)

"""Shared helpers for the Media Hub AI and caption scripts (v2)."""
import json, math, os, re, sys, tempfile, time, urllib.request

HUB = os.environ.get("MH_HUB", os.path.expanduser("~/media_hub"))
CONF = os.environ.get("MH_CONF", os.path.expanduser("~/mediahub.conf"))
JOBS = os.path.join(HUB, ".jobs")
META = os.path.join(HUB, ".meta")


STYLE = os.environ.get("MH_STYLE", os.path.join(HUB, "brand", "house_style.txt"))


def conf(key, default=""):
    """Settings: environment, then the house-style file (editable from Windows at Z:\\brand), then ~/mediahub.conf."""
    if os.environ.get(key):
        return os.environ[key]
    for path in (STYLE, CONF):
        v = _read_setting(path, key)
        if v is not None:
            return v
    return default


def _read_setting(path, key):
    try:
        for line in open(path, encoding="utf-8-sig", errors="ignore"):
            line = line.split(" #")[0].strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == key:
                return v.strip().strip('"').strip("'")
    except OSError:
        pass
    return None


def ass_colour(hex_rgb, default="&H00008CFF"):
    """#FF8C00 -> ASS &H00BBGGRR"""
    h = str(hex_rgb).strip().lstrip("#")
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", h):
        return default
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}".upper()


class Keeps(list):
    """Keep-ranges of a built edit; .mid = (index of the keep it follows, seconds) when a mid-roll was inserted."""
    mid = None


def effective_cuts(meta_prefix):
    """(hook, keep-ranges) of the edit as actually built, including filler/pause removal and any mid-roll."""
    cuts = meta_prefix + ".last_cuts.txt"
    final = meta_prefix + ".final.json"
    hook, keeps = read_cuts(cuts)
    try:
        if os.path.getmtime(final) >= os.path.getmtime(cuts) - 1:
            d = json.load(open(final))
            k = Keeps(tuple(x) for x in d["keeps"])
            if d.get("midroll"):
                k.mid = (int(d["midroll"][0]), float(d["midroll"][1]))
            return (tuple(d["hook"]) if d.get("hook") else None), k
    except (OSError, ValueError, KeyError):
        pass
    return hook, keeps


def cuts_flag(path, name):
    try:
        for line in open(path, encoding="utf-8", errors="ignore"):
            if line.strip().upper().startswith(name.upper() + ":"):
                return line.split(":", 1)[1].strip().lower() in ("on", "yes", "1", "true")
    except OSError:
        pass
    return False


OLLAMA = conf("MH_OLLAMA", "http://127.0.0.1:11434")
MODEL = conf("MH_LLM", "llama3:latest")
NUM_CTX = int(conf("MH_NUM_CTX", "8192"))
# Is Ollama running on the graphics card? (set automatically by the installer). On the CPU it never competes
# with whisper for VRAM, so it skips the GPU queue and keeps the model loaded between calls.
LLM_ON_GPU = conf("MH_LLM_ON_GPU", "off").lower() == "on"


def ask_json(prompt, keep="0", timeout=420, num_ctx=None):
    """Ask Ollama for JSON. num_ctx stops silent prompt truncation; on the GPU keep_alive=0 frees VRAM for whisper,
    on the CPU the model stays loaded (MH_LLM_KEEP) so the next AI step starts instantly."""
    if not LLM_ON_GPU:
        keep = conf("MH_LLM_KEEP", "10m")
    payload = {"model": MODEL, "prompt": prompt, "stream": False, "format": "json",
               "keep_alive": keep, "options": {"num_ctx": int(num_ctx or NUM_CTX), "temperature": 0.3}}
    req = urllib.request.Request(OLLAMA + "/api/generate", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = json.loads(r.read().decode("utf-8")).get("response", "")
    try:
        return json.loads(raw)
    except ValueError:
        m = re.search(r"\{.*\}", raw, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except ValueError:
                pass
    return {}


def extract_list(d, keys=("clips", "segments", "shorts", "highlights", "results", "moments")):
    if isinstance(d, list):
        return d
    if isinstance(d, dict):
        for k in keys:
            if isinstance(d.get(k), list):
                return d[k]
        for v in d.values():
            if isinstance(v, list):
                return v
    return []


# ---------- time helpers ----------
def ts2s(t):
    t = str(t).strip().replace(",", ".")
    m = re.search(r"\d{1,2}(?::\d{1,2}){1,2}(?:\.\d+)?", t)
    if not m:
        return None
    p = m.group(0).split(":")
    try:
        if len(p) == 3:
            return int(p[0]) * 3600 + int(p[1]) * 60 + float(p[2])
        return int(p[0]) * 60 + float(p[1])
    except ValueError:
        return None


def s2ts(s):
    s = max(0, int(s))
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def ts_floor(s):
    return s2ts(math.floor(s))


def ts_ceil(s):
    return s2ts(math.ceil(s))


def s2srt(s):
    s = max(0.0, s)
    ms = int(round(s * 1000))
    return f"{ms // 3600000:02d}:{ms % 3600000 // 60000:02d}:{ms % 60000 // 1000:02d},{ms % 1000:03d}"


def yt_time(s):
    s = max(0, int(s))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def parse_range(text):
    found = re.findall(r"\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?", str(text))
    if len(found) < 2:
        return None
    s, e = ts2s(found[0]), ts2s(found[1])
    if s is None or e is None or e <= s:
        return None
    return s, e


# ---------- SRT ----------
def is_noise(t):
    return bool(re.fullmatch(r"\s*[\[\(].*[\]\)]\s*", t)) or not t.strip()


def read_srt(path, drop_noise=True):
    segs = []
    try:
        data = open(path, encoding="utf-8", errors="ignore").read().replace("\r", "")
    except OSError:
        return segs
    for b in re.split(r"\n\s*\n", data.strip()):
        lines = [l.strip() for l in b.splitlines() if l.strip()]
        for i, l in enumerate(lines):
            if "-->" in l:
                a, c = l.split("-->", 1)
                s, e = ts2s(a), ts2s(c.strip().split(" ")[0])
                txt = " ".join(lines[i + 1:])
                if s is not None and e is not None and txt and not (drop_noise and is_noise(txt)):
                    segs.append((s, max(e, s + 0.05), txt))
                break
    segs.sort(key=lambda x: x[0])
    return segs


def write_srt(path, segs):
    with open(path, "w", encoding="utf-8") as f:
        for i, (s, e, t) in enumerate(segs, 1):
            f.write(f"{i}\n{s2srt(s)} --> {s2srt(e)}\n{t}\n\n")


def windows(segs, size):
    out, cur = [], None
    for s, e, t in segs:
        if cur is None:
            cur = [s, e, [t]]
        elif e - cur[0] > size:
            out.append((cur[0], cur[1], " ".join(cur[2])))
            cur = [s, e, [t]]
        else:
            cur[1] = e
            cur[2].append(t)
    if cur:
        out.append((cur[0], cur[1], " ".join(cur[2])))
    return out


def blocks_by_time(segs, size):
    blocks, cur = [], []
    for x in segs:
        if cur and x[1] - cur[0][0] > size:
            blocks.append(cur)
            cur = []
        cur.append(x)
    if cur:
        if blocks and cur[-1][1] - cur[0][0] < size * 0.3:
            blocks[-1].extend(cur)
        else:
            blocks.append(cur)
    return blocks


def snap_start(segs, t):
    return min((s for s, _, _ in segs), key=lambda s: abs(s - t))


def snap_end(segs, t):
    return min((e for _, e, _ in segs), key=lambda e: abs(e - t))


def fit_clip(segs, s, e, lo=25, hi=70, target=60):
    """Snap a clip to sentence boundaries and force it into lo..hi seconds."""
    s = snap_start(segs, s)
    e = snap_end(segs, e)
    if e - s < lo:
        later = [x[1] for x in segs if x[1] >= s + lo]
        e = later[0] if later else e
    if e - s > hi:
        ok = [x[1] for x in segs if s + lo <= x[1] <= s + target]
        e = ok[-1] if ok else s + target
    if e - s < lo * 0.6:
        return None, None
    return s, e


def text_between(segs, s, e):
    return " ".join(t for a, b, t in segs if b > s and a < e)


# ---------- edit timeline (cuts file) ----------
def read_cuts(path):
    hook, keeps = None, []
    try:
        lines = open(path, encoding="utf-8", errors="ignore").read().replace("\r", "").splitlines()
    except OSError:
        return None, []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.upper().startswith("HOOK:"):
            r = parse_range(line[5:])
            if r and hook is None:
                hook = r
        else:
            r = parse_range(line)
            if r:
                keeps.append(r)
    return hook, keeps


def timeline(hook, keeps):
    pieces, out = [], 0.0
    mid = getattr(keeps, "mid", None)
    if hook:
        pieces.append((hook[0], hook[1], 0.0, True))
        out += hook[1] - hook[0]
    for i, (s, e) in enumerate(keeps):
        pieces.append((s, e, out, False))
        out += e - s
        if mid and i == mid[0]:
            out += mid[1]  # the mid-roll advert sits here in the edited video
    return pieces


def map_time(pieces, t):
    for s, e, o, is_hook in pieces:
        if not is_hook and s <= t < e:
            return o + (t - s)
    return None


def vaapi_device():
    """The RX 580's video-encoding device. This machine also has an Intel chip, so pick the AMD render node
    (vendor 0x1002) instead of assuming renderD128. MH_VAAPI_DEV in house_style.txt overrides it."""
    dev = conf("MH_VAAPI_DEV", "")
    if dev:
        return dev
    try:
        for n in sorted(os.listdir("/dev/dri")):
            if n.startswith("renderD"):
                v = open(f"/sys/class/drm/{n}/device/vendor").read().strip().lower()
                if v == "0x1002":
                    return "/dev/dri/" + n
    except OSError:
        pass
    return "/dev/dri/renderD128"


def shm_dir(prefix, need_bytes=0):
    """Scratch folder in RAM (/dev/shm/mediahub) for temporary audio; falls back to /tmp on disk if RAM is short.
    The caller removes it when the job finishes; a reboot clears /dev/shm anyway."""
    base = conf("MH_SHM", "/dev/shm/mediahub")
    try:
        os.makedirs(base, exist_ok=True)
        st = os.statvfs(base)
        if st.f_bavail * st.f_frsize > need_bytes * 1.3 + 1.5e9:
            return tempfile.mkdtemp(prefix=prefix, dir=base)
    except OSError:
        pass
    return tempfile.mkdtemp(prefix=prefix, dir="/tmp")


def safe_name(name):
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


def set_hook_text(basename, text):
    """Store the 2-second slam hook for a short (looked up by the shorts/split watchers)."""
    d = os.path.join(META, "hooks")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, safe_name(basename) + ".txt")
    text = " ".join((text or "").split())[:120]
    if text:
        open(p, "w", encoding="utf-8").write(text)
    elif os.path.isfile(p):
        os.remove(p)


# ---------- live job status + learned timings (drives the dashboard progress dial) ----------
TIMINGS = os.path.join(META, "timings.json")


def _atomic_json(path, obj):
    with open(path + ".tmp", "w") as f:
        json.dump(obj, f)
    os.replace(path + ".tmp", path)


def load_timings():
    try:
        return json.load(open(TIMINGS))
    except (OSError, ValueError):
        return {}


def _learn(pipeline, total, step, secs, media):
    """Remember how long a step took, per second of media, as a moving average."""
    if secs <= 0.05 or secs > 8 * 3600:
        return
    t = load_timings()
    k = f"{pipeline}:{total}:{step}"
    e = t.get(k) or {"secs": secs, "rate": None, "n": 0}
    w = 0.4 if e["n"] else 1.0
    e["secs"] = e["secs"] * (1 - w) + secs * w
    if media and media > 0:
        r = secs / media
        e["rate"] = r if not e.get("rate") else e["rate"] * (1 - w) + r * w
    e["n"] += 1
    t[k] = e
    try:
        _atomic_json(TIMINGS, t)
    except OSError:
        pass


def status(job, pipeline, step, total, label, state="running", media=None, frac=None):
    try:
        os.makedirs(JOBS, exist_ok=True)
        os.makedirs(META, exist_ok=True)
        jid = re.sub(r"[^A-Za-z0-9._-]", "_", job)
        p = os.path.join(JOBS, jid + ".json")
        step, total, now = int(step), int(total), time.time()
        try:
            prev = json.load(open(p))
        except (OSError, ValueError):
            prev = None
        new_job = (prev is None or prev.get("state") != "running" or prev.get("pipeline") != pipeline
                   or prev.get("total") != total or step < prev.get("step", 0))
        if new_job:
            start = step_start = now
            media = float(media or 0)
        else:
            start = prev.get("start", now)
            media = float(media) if media else prev.get("media", 0)
            if step != prev.get("step"):
                _learn(pipeline, total, prev["step"], now - prev.get("step_start", now), media)
                step_start = now
            else:
                step_start = prev.get("step_start", now)
            if state == "done":
                _learn(pipeline, total, step, now - step_start, media)
        rec = {"id": jid, "pipeline": pipeline, "step": step, "total": total, "label": label,
               "state": state, "ts": int(now), "start": start, "step_start": step_start, "media": media}
        if frac is not None:
            rec["frac"] = max(0.0, min(1.0, float(frac)))
        _atomic_json(p, rec)
    except (OSError, ValueError, KeyError):
        pass


def estimate(job, timings=None, now=None):
    """Percent done and seconds left for a job, from learned timings (None = still learning)."""
    timings = load_timings() if timings is None else timings
    now = now or time.time()
    total, step = max(1, int(job.get("total", 1))), int(job.get("step", 1))
    if job.get("state") != "running":
        return 100, 0
    media = job.get("media") or 0
    ests = []
    for s in range(1, total + 1):
        e = timings.get(f"{job.get('pipeline')}:{total}:{s}")
        ests.append(None if not e else (e["rate"] * media if media and e.get("rate") else e["secs"]))
    in_step = max(0.0, now - job.get("step_start", now))
    frac = job.get("frac")
    if frac is not None and frac > 0.02:
        # live progress from inside the step (e.g. a render reporting its own percentage)
        cur_left = in_step * (1 - frac) / frac
        left = int(cur_left + sum(x or 0 for x in ests[step:]))
        known = [x for x in ests if x is not None]
        if len(known) == len(ests) and sum(known) > 0:
            # whole-job progress weighted by how long each step really takes
            done_t = sum(ests[:step - 1]) + ests[step - 1] * frac
            return round(min(99, 100 * done_t / sum(ests))), left
        # first run: the step reporting live progress is the long one, so show its own percentage
        return round(min(99, frac * 100)), left
    if any(x is None for x in ests[step - 1:]) or not sum(x or 0 for x in ests):
        return round(100 * (step - 1 + 0.5) / total), None
    done_t = sum(x or 0 for x in ests[:step - 1])
    cur = ests[step - 1]
    left = max(sum(ests[step - 1:]) - in_step, cur * 0.05 + sum(ests[step:]))
    pct = 100 * (done_t + min(in_step, cur * 0.95)) / max(1, done_t + min(in_step, cur * 0.95) + left)
    return round(min(99, pct)), int(left)


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "vaapi":
    print(vaapi_device())

if __name__ == "__main__" and len(sys.argv) > 2 and sys.argv[1] == "conf":
    print(conf(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else ""))

if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "status":
    a = sys.argv[2:] + [""] * 7
    status(a[0], a[1], a[2] or 1, a[3] or 1, a[4], a[5] or "running", a[6] or None)

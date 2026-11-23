#!/usr/bin/env python3
"""9:16 framing with face detection (v2.9.2: reports live progress, so the dashboard shows time left).
  auto_split_crop.py INPUT OUTPUT          two speakers, head sizes matched, stacked top/bottom (1080x1920)
  auto_split_crop.py --solo INPUT OUTPUT   one person on screen, the frame cuts to whoever is talking
Output is a high-quality intermediate (CRF 16, veryfast preset) that is encoded again when captions are burned in."""
import cv2, os, subprocess, sys, time

solo = "--solo" in sys.argv
args = [x for x in sys.argv[1:] if x != "--solo"]
input_path, output_path = args[0], args[1]

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import speaker_crop as sc
from ai_common import status, conf

cap = cv2.VideoCapture(input_path)
W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
SRC_FPS = cap.get(cv2.CAP_PROP_FPS) or 30.0
# Shorts are made at MH_SHORTS_FPS (default 30): a 60 fps recording is halved, so every later step is ~2x faster too
try:
    TARGET_FPS = float(conf("MH_SHORTS_FPS", "30"))
except ValueError:
    TARGET_FPS = 30.0
FPSF = f",fps={TARGET_FPS:g}" if TARGET_FPS > 0 and SRC_FPS > TARGET_FPS + 1 else ""
detect = sc.load_detector()
print("Face detector:", getattr(detect, "kind", "none (centre framing)"))

# ----- live progress for the dashboard dial (same job card the watcher opened) -----
NAME = os.path.basename(input_path)
BASE = os.path.splitext(NAME)[0]
JOB, PIPE = (f"short_{BASE}", "shorts") if solo else (f"split_{BASE}", "split")
try:
    DUR = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", input_path],
                               capture_output=True, text=True).stdout.strip() or 0)
except ValueError:
    DUR = 0.0
_last = [0.0]


def report(frac, phase):
    now = time.time()
    if now - _last[0] < 3:
        return
    _last[0] = now
    frac = max(0.0, min(0.99, frac))
    status(JOB, PIPE, 1, 4, f"{phase} {int(frac * 100)}%: {NAME}", "running", frac=frac)


def run_ff(cmd, lo, hi, phase):
    """ffmpeg with live progress mapped onto lo..hi of this step."""
    cmd = cmd[:1] + ["-progress", "pipe:1", "-nostats"] + cmd[1:]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True)
    for line in p.stdout:
        if line.startswith(("out_time_us=", "out_time_ms=")) and DUR > 0:
            try:
                t = int(line.split("=")[1]) / 1e6
            except ValueError:
                continue
            report(lo + (hi - lo) * min(1.0, t / DUR), phase)
    if p.wait() != 0:
        sys.exit(p.returncode or 1)


def analyze(x_offset, region_w, samples=25):
    centers_x, centers_y, heights = [], [], []
    if detect is None:
        return x_offset + region_w / 2.0, H / 2.0, H * 0.25
    step = max(1, total_frames // samples)
    for f_idx in range(0, max(1, total_frames), step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
        ret, frame = cap.read()
        if not ret:
            break
        region = frame[:, x_offset:x_offset + region_w]
        s = 360.0 / min(region.shape[:2]) if min(region.shape[:2]) > 360 else 1.0  # detect at 360p
        if s < 1.0:
            region = cv2.resize(region, (int(region.shape[1] * s), int(region.shape[0] * s)), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        faces = [(x / s, y / s, w / s, h / s) for (x, y, w, h) in detect(gray)]  # back to source pixels
        faces = [f for f in faces if f[2] >= 40]
        if len(faces) > 0:
            x, y, w, h = max(faces, key=lambda b: b[2] * b[3])
            centers_x.append(x_offset + x + w / 2.0)
            centers_y.append(y + h / 2.0)
            heights.append(h)
    if not heights:
        return x_offset + region_w / 2.0, H / 2.0, H * 0.25
    centers_x.sort(); centers_y.sort(); heights.sort()
    mid = len(heights) // 2
    return centers_x[mid], centers_y[mid], heights[mid]


# Sound: full voice chain for raw uploads; loudness-only for clips cut from an already-polished episode master
_light = ["--light"] if "_clip_" in os.path.basename(input_path) else []
_af = subprocess.run(["python3", os.path.join(os.path.dirname(os.path.abspath(__file__)), "audio_polish.py"), input_path, "-14"]
                     + _light, capture_output=True, text=True).stdout.strip() or "highpass=f=80,loudnorm=I=-14:TP=-1.5:LRA=11"
AUDIO = ["-af", _af, "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
VIDEO = ["-c:v", "libx264", "-crf", "16", "-preset", "veryfast", "-pix_fmt", "yuv420p"]

if solo:
    # Single-person short that follows whoever is talking (see speaker_crop.py)
    cap.release()
    cw = int(H * 9 / 16) // 2 * 2
    if cw > W:
        cw = W // 2 * 2
    ch = H // 2 * 2
    samples, _, _ = sc.sample(input_path, detect, progress=lambda f: report(0.03 + f * 0.17, "Finding the speaker"))
    cuts = sc.plan(samples, W, cw)
    print(f"Speaker framing: {len(cuts)} shot(s) " + ", ".join(f"{t:.1f}s@x{x}" for t, x in cuts[:12]))
    cmd = ["ffmpeg", "-nostdin", "-y", "-i", input_path, "-vf", sc.crop_filter(cuts, cw, ch) + ",scale=1080:1920,setsar=1" + FPSF,
           "-map", "0:v:0", "-map", "0:a?"] + VIDEO + AUDIO + [output_path, "-loglevel", "error"]
    run_ff(cmd, 0.2, 1.0, "Framing 9:16")
    sys.exit(0)

left_cx, left_cy, left_fh = analyze(0, W // 2)
right_cx, right_cy, right_fh = analyze(W // 2, W - (W // 2))
cap.release()


def compute_crop(cx, cy, fh, min_x, max_x):
    crop_h = int(fh / 0.28)
    crop_h = max(360, min(H, crop_h))
    crop_w = int(crop_h * (1080.0 / 960.0))
    if crop_w > (max_x - min_x):
        crop_w = max_x - min_x
        crop_h = int(crop_w * (960.0 / 1080.0))
    x1 = int(cx - crop_w / 2.0)
    y1 = int(cy - crop_h * 0.42)
    x1 = max(min_x, min(max_x - crop_w, x1))
    y1 = max(0, min(H - crop_h, y1))
    crop_w -= crop_w % 2
    crop_h -= crop_h % 2
    return crop_w, crop_h, x1, y1


lw, lh, lx, ly = compute_crop(left_cx, left_cy, left_fh, 0, W // 2)
rw, rh, rx, ry = compute_crop(right_cx, right_cy, right_fh, W // 2, W)
fc = (f"[0:v]crop={lw}:{lh}:{lx}:{ly},scale=1080:960,setsar=1[top];"
      f"[0:v]crop={rw}:{rh}:{rx}:{ry},scale=1080:960,setsar=1[bot];[top][bot]vstack=inputs=2{FPSF}[v]")
cmd = ["ffmpeg", "-nostdin", "-y", "-i", input_path, "-filter_complex", fc, "-map", "[v]", "-map", "0:a?"] + VIDEO + AUDIO + \
      [output_path, "-loglevel", "error"]
run_ff(cmd, 0.05, 1.0, "Stacking 9:16")

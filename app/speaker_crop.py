"""Active-speaker framing for single-person 9:16 shorts.
Samples the video ~5 times a second, finds faces, and decides who to show:
  - one face on screen (speaker view): follow it, only moving for a real shift (no jitter)
  - two or more faces (side-by-side / gallery): show the one whose mouth is moving, cutting like a camera switch,
    holding each shot at least MIN_HOLD seconds so it never flickers
Returns a list of (time, crop_x) cuts and the ffmpeg crop filter that plays them."""
import os
import cv2

SAMPLE_FPS = 5
MIN_HOLD = 1.5      # seconds a shot stays before it may switch
SWITCH_AFTER = 0.6  # the other person must be clearly talking this long before we cut to them
SWITCH_RATIO = 1.3  # ...and moving their mouth this much more than the person on screen


MODEL = os.path.expanduser(os.environ.get("MH_FACE_MODEL", "~/models/face_detection_yunet_2023mar.onnx"))


def load_detector():
    """YuNet (neural, handles turned heads, small faces, low light); old Haar detector only as a fallback."""
    if os.path.isfile(MODEL):
        try:
            yn = cv2.FaceDetectorYN.create(MODEL, "", (320, 320), 0.6, 0.3, 5000)

            def detect(gray):
                img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR) if gray.ndim == 2 else gray
                yn.setInputSize((img.shape[1], img.shape[0]))
                _, faces = yn.detect(img)
                return [] if faces is None else [tuple(int(v) for v in f[:4]) for f in faces]
            detect.kind = "YuNet"
            return detect
        except Exception as ex:
            print(f"YuNet unavailable ({ex}); using the basic detector")
    try:
        c = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        if not c.empty():
            detect = lambda g: c.detectMultiScale(g, scaleFactor=1.1, minNeighbors=5, minSize=(28, 28))
            detect.kind = "Haar"
            return detect
    except Exception:
        pass
    return None


def sample(path, detect, progress=None):
    """-> samples [(t, [(cx, face_w, mouth_motion), ...])], W, H"""
    cap = cv2.VideoCapture(path)
    W, H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    nfr = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    step = max(1, round(fps / SAMPLE_FPS))
    # Detect on a 360p copy (shorter side 360 px); boxes are scaled back to source pixels below (/ sc)
    sc = 360.0 / min(W, H) if min(W, H) > 360 else 1.0
    out, prev, idx = [], None, 0
    while True:
        if not cap.grab():
            break
        if idx % step == 0:
            ok, frame = cap.retrieve()
            if not ok:
                break
            g = cv2.cvtColor(cv2.resize(frame, (int(W * sc), int(H * sc)), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
            faces = []
            for (x, y, w, h) in (detect(g) if detect else []):
                if w < g.shape[1] * 0.04:
                    continue
                y0, y1 = int(y + h * 0.62), min(g.shape[0], int(y + h * 1.05))
                x0, x1 = int(x + w * 0.2), int(x + w * 0.8)
                motion = 0.0
                if prev is not None and y1 > y0 and x1 > x0:
                    motion = float(cv2.absdiff(g[y0:y1, x0:x1], prev[y0:y1, x0:x1]).mean())
                faces.append(((x + w / 2.0) / sc, w / sc, motion))
            faces.sort(key=lambda f: -f[1])
            out.append((idx / fps, faces[:3]))
            prev = g
        idx += 1
        if progress and nfr and idx % 150 == 0:
            progress(min(1.0, idx / nfr))
    cap.release()
    return out, W, H


def slots_from(samples, W):
    """Where the people sit when more than one is on screen (left/right), from all multi-face samples."""
    xs = sorted(f[0] for t, fs in samples if len(fs) >= 2 for f in fs)
    if len(xs) < 4:
        return []
    gaps = [(xs[i + 1] - xs[i], i) for i in range(len(xs) - 1)]
    g, i = max(gaps)
    if g < W * 0.15:
        return []
    left, right = xs[:i + 1], xs[i + 1:]
    return [left[len(left) // 2], right[len(right) // 2]]


def plan(samples, W, crop_w):
    """-> [(t, x)] crop positions (x = left edge), switching like a camera operator."""
    half = crop_w / 2.0
    clamp = lambda cx: int(max(0, min(W - crop_w, cx - half))) // 2 * 2
    slots = slots_from(samples, W)
    ema = [0.0] * len(slots)
    cuts, cur_x, cur_slot, shot_start, pending_since = [], None, None, 0.0, None
    for t, faces in samples:
        if len(faces) >= 2 and slots:
            for k in range(len(slots)):
                m = max((f[2] for f in faces if min(range(len(slots)), key=lambda j: abs(slots[j] - f[0])) == k), default=0.0)
                ema[k] = ema[k] * 0.6 + m * 0.4
            best = max(range(len(slots)), key=lambda k: ema[k])
            if (cur_slot is None or cur_x is None) and t < 1.0 and max(ema) - min(ema) < 0.5:
                continue  # wait up to a second to see who is actually talking first
            if cur_slot is None or cur_x is None:
                cur_slot, cur_x, shot_start = best, clamp(slots[best]), t
                cuts.append((t, cur_x))
            elif best != cur_slot and ema[best] > ema[cur_slot] * SWITCH_RATIO + 0.2:
                pending_since = t if pending_since is None else pending_since
                if t - pending_since >= SWITCH_AFTER and t - shot_start >= MIN_HOLD:
                    # planned after recording, so cut back to when they actually started talking
                    ct = max(shot_start + 0.8, pending_since - 0.5)
                    cur_slot, cur_x, shot_start, pending_since = best, clamp(slots[best]), ct, None
                    cuts.append((ct, cur_x))
            else:
                pending_since = None
        elif faces:
            if slots and any(abs(faces[0][0] - sl) < W * 0.12 for sl in slots):
                continue  # one of the two people briefly missed by the detector: not a reason to cut
            x = clamp(faces[0][0])
            if cur_x is None:
                cur_x, shot_start = x, t
                cuts.append((t, cur_x))
            elif abs(x - cur_x) > W * 0.06:
                pending_since = t if pending_since is None else pending_since
                if t - pending_since >= 0.4 and t - shot_start >= 0.8:
                    cur_x, shot_start, pending_since, cur_slot = x, t, None, None
                    cuts.append((t, cur_x))
            else:
                pending_since = None
    if not cuts:
        return [(0.0, clamp(W / 2.0))]
    cuts[0] = (0.0, cuts[0][1])
    merged = []
    for t, x in cuts:
        if not merged or merged[-1][1] != x:
            merged.append((t, x))
    return merged


def crop_filter(cuts, crop_w, crop_h):
    """Piecewise crop x as a flat sum (no deep nesting, safe for hundreds of cuts)."""
    x0 = cuts[0][1]
    expr = str(x0)
    prev = x0
    for t, x in cuts[1:]:
        expr += f"+({x - prev})*gte(t\\,{t:.3f})"
        prev = x
    return f"crop={crop_w}:{crop_h}:x='{expr}':y=0"

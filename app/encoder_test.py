#!/usr/bin/env python3
"""Side-by-side quality test: renders the same 30 seconds with the CPU and with the RX 580 graphics card.
Usage: encoder_test.py EPISODE [start_seconds]   -> <EPISODE>_TEST_cpu.mp4 and <EPISODE>_TEST_gpu.mp4 in youtube_long/output"""
import os, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ai_common import HUB, conf, vaapi_device

ep = sys.argv[1]
start = float(sys.argv[2]) if len(sys.argv) > 2 else 600.0
out_dir = os.path.join(HUB, "youtube_long/output")
src = os.path.join(out_dir, f"{ep}_clean.mp4")
if not os.path.isfile(src):
    sys.exit(f"Not found: {src}")
dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", src],
                           capture_output=True, text=True).stdout or 0)
if start + 30 > dur:
    start = max(0.0, dur / 2 - 15)
base = ["ffmpeg", "-nostdin", "-y", "-loglevel", "error"]
tests = {
    "cpu": base + ["-ss", str(start), "-i", src, "-t", "30", "-c:v", "libx264", "-crf", "18",
                   "-preset", conf("MH_CPU_PRESET", "fast"), "-pix_fmt", "yuv420p", "-c:a", "copy"],
    "gpu": base + ["-vaapi_device", vaapi_device(), "-ss", str(start), "-i", src, "-t", "30",
                   "-vf", "format=nv12,hwupload", "-c:v", "h264_vaapi", "-qp", conf("MH_GPU_QP", "19"),
                   "-profile:v", "high", "-c:a", "copy"],
}
for name, cmd in tests.items():
    out = os.path.join(out_dir, f"{ep}_TEST_{name}.mp4")
    t0 = time.time()
    r = subprocess.run(cmd + [out], capture_output=True, text=True)
    took = time.time() - t0
    if r.returncode != 0:
        print(f"{name.upper()}: FAILED - {r.stderr.strip()[-200:]}")
        continue
    mb = os.path.getsize(out) / 1e6
    print(f"{name.upper()}: {took:5.1f} s to render 30 s of video   ({mb:.0f} MB)   -> Z:\\youtube_long\\output\\{os.path.basename(out)}")
print("Watch both full screen and compare. If the GPU one looks fine to you, set MH_ENCODER=gpu in Z:\\brand\\house_style.txt")

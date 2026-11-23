#!/usr/bin/env python3
"""Broadcast voice chain + exact two-pass loudness. Prints the ffmpeg -af filter to use for a file.
Usage: audio_polish.py INPUT TARGET_LUFS [--light]
  off (default):    rumble cut and exact loudness only. Plain on purpose: build your own sound.
  studio:           rumble cut, AI noise removal, de-mud, presence lift, de-esser, gentle compression,
                    speaker levelling, then measured two-pass loudness.
  --light:          loudness only (for clips cut from an already-polished master, so nothing is done twice).
Choose with MH_AUDIO_PRESET in house_style.txt, or write your own chain in MH_SOUND_ONLY_CHAIN."""
import json, os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ai_common import conf

src, target = sys.argv[1], float(sys.argv[2])
light = "--light" in sys.argv
preset = conf("MH_AUDIO_PRESET", "off")
MODEL = os.path.expanduser(conf("MH_NOISE_MODEL", "~/models/rnnoise_std.rnnn"))
TP, LRA = -1.5, 11

if preset == "off":
    print(f"highpass=f=80,loudnorm=I={target:g}:TP={TP}:LRA={LRA}")
    sys.exit(0)


def have(f):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True)
    return re.search(rf"\s{f}\s", r.stdout) is not None


chain = []
if not light and preset == "studio":
    chain.append("highpass=f=75")
    if os.path.isfile(MODEL) and have("arnndn"):
        chain.append(f"arnndn=m='{MODEL}':mix=0.85")              # AI noise removal (hum, fans, room hiss)
    else:
        chain.append("afftdn=nr=10:nf=-45:tn=1")                   # classic noise reduction fallback
    chain += [
        "equalizer=f=250:t=q:w=1.2:g=-2.5",                         # less boxy / muddy
        "equalizer=f=3200:t=q:w=1.4:g=2.5",                         # clarity and presence
        "equalizer=f=11000:t=h:w=0.7:g=1",                          # a touch of air
    ]
    if have("deesser"):
        chain.append("deesser=i=0.35:m=0.5:f=0.5")                  # tame harsh S sounds
    chain += [
        "acompressor=threshold=-21dB:ratio=3:attack=8:release=160:makeup=2:knee=4",
        "dynaudnorm=f=400:g=21:p=0.9:m=8:r=0.5",                    # evens out loud host / quiet guest
    ]
pre = ",".join(chain)

# Pass 1: measure loudness after the chain, so pass 2 lands exactly on target with no pumping
measure = (pre + "," if pre else "") + f"loudnorm=I={target:g}:TP={TP}:LRA={LRA}:print_format=json"
r = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-i", src, "-vn", "-af", measure, "-f", "null", "-"],
                   capture_output=True, text=True)
m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr, re.S)
if m:
    d = json.loads(m.group(0))
    ln = (f"loudnorm=I={target:g}:TP={TP}:LRA={LRA}:measured_I={d['input_i']}:measured_TP={d['input_tp']}:"
          f"measured_LRA={d['input_lra']}:measured_thresh={d['input_thresh']}:offset={d['target_offset']}:linear=true")
else:
    ln = f"loudnorm=I={target:g}:TP={TP}:LRA={LRA}"
print((pre + "," if pre else "") + ln + ",aresample=48000")

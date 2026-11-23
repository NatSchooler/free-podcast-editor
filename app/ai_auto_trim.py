#!/usr/bin/env python3
"""Find where the real show starts and ends. Prints 'HH:MM:SS - HH:MM:SS' then a reason line.
The AI picks numbered LINES (far more reliable for llama3 than inventing timestamps), and if it lazily
answers 'the very first line' while an obvious welcome/introduction appears later, the welcome line wins."""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ai_common import read_srt, ask_json, s2ts, ts_floor, ts_ceil

segs = read_srt(sys.argv[1])
if not segs:
    sys.exit(0)
dur = segs[-1][1]
WIN = 300  # first and last 5 minutes only: smaller prompt, faster answer
head = [x for x in segs if x[0] < WIN]
tail = [x for x in segs if x[1] > dur - WIN]
tail_off = len(segs) - len(tail)

WELCOME = re.compile(
    r"\b(welcome (to|back)|hello and welcome|hi,? (and )?welcome|good (morning|afternoon|evening),? (and )?welcome|"
    r"today (i am|i'm|we are|we're) (joined|talking|speaking|here)|my (guest|special guest) today|"
    r"on today'?s (show|episode)|this is (the|my|our) (show|podcast)|i'?m (joined|here) (by|with)|"
    r"it'?s (a|my) (pleasure|great pleasure|real pleasure) to)\b", re.I)
PRESHOW = re.compile(
    r"\b(can you hear|hear me|are we (recording|live|rolling)|is it recording|hit record|press record|mic|"
    r"microphone|sound check|test(ing)?,? (one|1)|three,? two,? one|3,? 2,? 1|countdown|are you ready|ready when|"
    r"let me (just )?(check|share|adjust)|you'?re on mute|unmute|camera|lighting|headphones)\b", re.I)
# Host cue that the real show starts on the NEXT line ("I'm going to introduce this. Okay. All right." -> cold open)
CUE = re.compile(
    r"\b(i'?m going to (introduce this|introduce it|kick (this|it) off)|i'?ll introduce (this|it)|let me introduce (this|it)|"
    r"here we go|we'?re (rolling|recording) now|start(ing)? (the )?recording)\b", re.I)
FILLER = re.compile(r"^\W*((okay|ok|all right|alright|right|so|um+|uh+|er+|good|great|cool|yeah|yes)\W*)+$", re.I)
POSTSHOW = re.compile(
    r"\b(stop (the )?recording|stopped recording|that was (great|brilliant|fantastic|amazing)|we'?re off|"
    r"off air|end the recording|i'?ll send you|edit (that|this) out|cut that)\b", re.I)


def numbered(xs, off=0):
    return "\n".join(f"{i + off}: [{s2ts(s)}] {t}" for i, (s, e, t) in enumerate(xs))


prompt = (
    "You are a video editor reading the numbered lines of a podcast/interview recording transcript.\n"
    "START: give the number of the FIRST line of the real show, usually the host's welcome or introduction "
    "of the guest, or a strong cold-open statement straight after the host says something like 'I am going to "
    "introduce this' or 'okay, all right'. Lines before it are mic checks, chat about tools or screens, 'can you hear me', 'are we recording', countdowns, tech talk "
    "or small talk and must be cut. Only answer 0 if line 0 itself is the welcome.\n"
    "END: give the number of the LAST line of the real show, usually the final thank-you/goodbye to the audience, "
    "before any 'stop the recording', 'that was great' or after-show chatter.\n"
    'Reply with JSON only: {"start_line": 12, "end_line": 950, "reason": "one short sentence"}\n\n'
    f"OPENING LINES:\n{numbered(head)}\n\nCLOSING LINES:\n{numbered(tail, tail_off)}\n"
)

try:
    d = ask_json(prompt, num_ctx=4096)
except Exception as ex:
    print(f"AI trim failed: {ex}", file=sys.stderr)
    d = {}
d = d if isinstance(d, dict) else {}


def as_int(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


si, ei = as_int(d.get("start_line")), as_int(d.get("end_line"))
reason = str(d.get("reason") or "").strip()
if si is None or not 0 <= si < len(head):
    si = 0
if ei is None or not tail_off <= ei < len(segs):
    ei = len(segs) - 1

welcome = next((i for i, (s, e, t) in enumerate(head) if WELCOME.search(t)), None)
pre_talk = any(PRESHOW.search(t) for s, e, t in head[:max(1, (welcome or 0))])
if si == 0 and welcome and segs[welcome][0] > 5 and (pre_talk or segs[welcome][0] < 180):
    si = welcome
    reason = (reason + " " if reason else "") + "(starts at the host's welcome)"
elif PRESHOW.search(segs[si][2]) and welcome and welcome > si:
    si = welcome

# host's start cue ("I'm going to introduce this") -> the show starts at the next real line
cue = max((i for i, (s, e, t) in enumerate(head) if CUE.search(t)), default=None)
# only before any welcome line and within the first 3 minutes, so it can never cut into a show that already started
if cue is not None and si <= cue and segs[cue][0] < 180 and (welcome is None or welcome > cue):
    nxt = next((i for i in range(cue + 1, len(head)) if not FILLER.match(segs[i][2].strip())), None)
    if nxt is not None:
        si = nxt
        reason = (reason + " " if reason else "") + "(starts after the host's intro cue)"

while ei > tail_off and POSTSHOW.search(segs[ei][2]):
    ei -= 1

s = max(0.0, segs[si][0] - 0.3)
e = segs[ei][1] + 0.4
if e - s < 60:
    s, e = segs[0][0], dur
print(f"{ts_floor(s)} - {ts_ceil(min(e, dur + 1))}")
print(reason)

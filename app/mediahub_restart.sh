#!/bin/bash
# Restart all Media Hub services. Refuses while a job is mid-render unless you add --force.
if [ "$1" != "--force" ] && { pgrep -x ffmpeg >/dev/null || pgrep -f whisper-cli >/dev/null; }; then
  echo "A render or transcription is still running. Re-run when it finishes, or: bash ~/mediahub/mediahub_restart.sh --force"
  exit 1
fi
pkill -f watch_youtube.sh; pkill -f watch_split.sh; pkill -f watch_shorts.sh; pkill -f media_dashboard.py
if [ "$1" == "--force" ]; then
  # stop the hub's own render/AI work too, so nothing is left running as an orphan
  pkill -f "ffmpeg.*(media_hub|/tmp/)"; pkill -f whisper-cli; pkill -f auto-editor
  pkill -f "(smart_cut|slice_clips|auto_split_crop|ai_auto_trim|ai_pick_shorts|ai_content_pack|audio_export)\.py"
  rm -rf /dev/shm/mediahub/* 2>/dev/null
fi
pkill -f "inotifywait.*media_hub"
sleep 1
# Jobs that were cut off by this restart: mark them "Stopped" so their cards do not hang at "running"
python3 - <<'PYEOF'
import glob, json, os, time
for f in glob.glob(os.path.expanduser("~/media_hub/.jobs/*.json")):
    try:
        d = json.load(open(f))
        if d.get("state") == "running":
            d["state"], d["label"], d["ts"] = "error", "Stopped by restart: " + d.get("label", ""), int(time.time())
            json.dump(d, open(f, "w"))
    except Exception:
        pass
PYEOF
S="${MH_SCRIPTS:-$HOME/mediahub}"; L="$HOME/media_hub/.jobs"; mkdir -p "$L"; cd "$S"
nohup bash "$S/watch_youtube.sh" >> "$L/youtube.log" 2>&1 &
nohup bash "$S/watch_split.sh" >> "$L/split.log" 2>&1 &
nohup bash "$S/watch_shorts.sh" >> "$L/shorts.log" 2>&1 &
nohup bash "$S/watch_sound.sh" >> "$L/sound.log" 2>&1 &
nohup python3 "$S/media_dashboard.py" >> "$L/dashboard.log" 2>&1 &
sleep 3
echo "---- running ----"
pgrep -af "watch_youtube|watch_split|watch_shorts|watch_sound|media_dashboard" | grep -v pgrep
curl -s -m 5 http://127.0.0.1:8080/api/episodes > /dev/null && echo "Dashboard OK: http://localhost:8080" || echo "Dashboard did not answer; check: tail ~/media_hub/.jobs/dashboard.log"

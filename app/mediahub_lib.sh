#!/bin/bash
# Shared helpers for the Media Hub watchers (v2)
HUB="${MH_HUB:-$HOME/media_hub}"
SCRIPTS="${MH_SCRIPTS:-$HOME/mediahub}"
MODEL="${MH_MODEL:-$HOME/mediahub/whisper.cpp/models/ggml-large-v3-turbo.bin}"
WHISPER="${MH_WHISPER:-$HOME/mediahub/whisper.cpp/build/bin/whisper-cli}"
AUTO_EDITOR="${MH_AUTO_EDITOR:-$HOME/.local/bin/auto-editor}"
GPU_LOCK="/tmp/mediahub_gpu.lock"
JOBS="$HUB/.jobs"
META="$HUB/.meta"
MH_SHORTS_COUNT=3
MH_SHORTS_MODE=split
[ -f "$HOME/mediahub.conf" ] && . "$HOME/mediahub.conf"
# whisper on the RX 580 only (not the Intel chip): index written by the installer
[ -n "$MH_VK_DEVICE" ] && export GGML_VK_VISIBLE_DEVICES="$MH_VK_DEVICE"
mkdir -p "$JOBS" "$META" "$META/hooks"

# Trim spaces and Windows line endings
trim() { local s="${1//$'\r'/}"; s="${s#"${s%%[![:space:]]*}"}"; s="${s%"${s##*[![:space:]]}"}"; printf '%s' "$s"; }

# Live progress card + learned timings for the dashboard dial:
# status <job> <pipeline> <step> <total> <label> [running|done|error] [media seconds]
status() { python3 "$SCRIPTS/ai_common.py" status "$@"; }

# Length of a media file in seconds (0 if unknown)
media_secs() { ffprobe -v error -show_entries format=duration -of csv=p=0 "$1" 2>/dev/null | cut -d. -f1 | grep -E '^[0-9]+$' || echo 0; }

# Seconds in HH:MM:SS (or MM:SS); -1 if not a time
to_secs() { awk -F: '{ if (NF==3) print $1*3600+$2*60+$3; else if (NF==2) print $1*60+$2; else print -1 }' <<< "$1"; }

# One GPU job at a time on the RX 580 (whisper; Ollama too, but only if it actually runs on the card)
gpu() { flock "$GPU_LOCK" "$@"; }
# AI (Ollama) steps: queue for the card only when Ollama uses it (MH_LLM_ON_GPU=on), otherwise run straight away
ai() { if [ "$(mhconf MH_LLM_ON_GPU off)" == "on" ]; then flock "$GPU_LOCK" "$@"; else "$@"; fi; }

# Temporary audio lives in RAM: /dev/shm/mediahub (cleared per job, and on every reboot)
SHM="${MH_SHM:-/dev/shm/mediahub}"
mkdir -p "$SHM" 2>/dev/null || SHM="/tmp"

# New media files with spaces/quotes break ffmpeg concat lists: rename once, the rename re-triggers the watcher
needs_rename() {
  local dir="$1" f="$2" s
  s=$(printf '%s' "$f" | sed 's/[^A-Za-z0-9._-]/_/g')
  if [ "$s" != "$f" ]; then
    mv -n "$dir/$f" "$dir/$s" && echo "Renamed '$f' -> '$s'"
    return 0
  fi
  return 1
}

# House-style setting (house_style.txt on Z:\brand, then ~/mediahub.conf): mhconf KEY DEFAULT
mhconf() { python3 "$SCRIPTS/ai_common.py" conf "$1" "$2"; }

# Burn ASS captions (+ house logo watermark on shorts). burn_ass <in.mp4> <subs.ass> <out.mp4>
burn_ass() {
  local tmp="$(dirname "$3")/.$(basename "$3").partial" logo pos op lw x y
  logo="$HUB/brand/$(mhconf MH_LOGO_FILE logo.png)"
  if [ "$(mhconf MH_LOGO_ON_SHORTS on)" == "on" ] && [ -f "$logo" ]; then
    pos=$(mhconf MH_LOGO_POSITION top-right); op=$(mhconf MH_LOGO_OPACITY 0.85); lw=$(mhconf MH_LOGO_SHORTS_WIDTH 180)
    x=50; y=60; [[ "$pos" == *right* ]] && x="W-w-50"; [[ "$pos" == *bottom* ]] && y="H-h-60"
    ffmpeg -nostdin -y -i "$1" -i "$logo" -filter_complex \
      "[0:v]ass=$2[v0];[1:v]format=rgba,colorchannelmixer=aa=${op},scale=${lw}:-1[lg];[v0][lg]overlay=${x}:${y}:format=auto[v]" \
      -map "[v]" -map "0:a?" -c:v libx264 -crf 18 -preset veryfast -pix_fmt yuv420p -c:a copy -f mp4 "$tmp" -loglevel error \
      && mv -f "$tmp" "$3"
  else
    ffmpeg -nostdin -y -i "$1" -vf "ass=$2" -c:v libx264 -crf 18 -preset veryfast -pix_fmt yuv420p -c:a copy -f mp4 "$tmp" -loglevel error \
      && mv -f "$tmp" "$3"
  fi
}

is_video() { [[ "$1" =~ \.(mp4|mov|mkv|avi|webm|MP4|MOV|MKV|AVI|WEBM)$ ]]; }

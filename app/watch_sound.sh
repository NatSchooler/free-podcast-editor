#!/bin/bash
# Sound-only engine (v2.9.6): WAV or M4A in, MP3 out. House sound, breaths turned down where they sit,
# levels evened out. No words are cut; only the breath before the first word is removed.
. "${MH_SCRIPTS:-$HOME/mediahub}/mediahub_lib.sh"
INPUT_DIR="$HUB/sound_only/input"
OUTPUT_DIR="$HUB/sound_only/output"
ORIG_DIR="$HUB/sound_only/originals"
mkdir -p "$INPUT_DIR" "$OUTPUT_DIR" "$ORIG_DIR" "$META/sound"
# only ever one sound-only watcher: an older copy (from before a restart) is stopped first
for P in $(pgrep -f "watch_sound.sh"); do [ "$P" != "$$" ] && kill "$P" 2>/dev/null; done
pkill -f "inotifywait.*sound_only" 2>/dev/null

echo "Watching $INPUT_DIR (v2.9.6 sound only)..."
while IFS= read -r FILENAME <&3; do
  FILEPATH="$INPUT_DIR/$FILENAME"
  [[ "$FILENAME" == .* ]] && continue
  [ -f "$FILEPATH" ] || continue
  case "${FILENAME,,}" in *.wav|*.m4a) ;; *) continue ;; esac
  sleep 2
  needs_rename "$INPUT_DIR" "$FILENAME" && continue
  BASENAME="${FILENAME%.*}"
  JOB="sound_${BASENAME}"
  WORDS="$META/sound/${BASENAME}.words"
  WAV="$SHM/sound_${BASENAME}_16k.wav"

  status "$JOB" sound 1 3 "Finding the words, so breaths can be told apart: $FILENAME" running "$(media_secs "$FILEPATH")"
  ffmpeg -nostdin -y -i "$FILEPATH" -vn -ar 16000 -ac 1 -c:a pcm_s16le "$WAV" -loglevel error
  gpu "$WHISPER" -m "$MODEL" -f "$WAV" -ml 1 -sow -osrt -of "$WORDS"
  rm -f "$WAV"

  if python3 "$SCRIPTS/sound_only.py" "$FILEPATH" "$OUTPUT_DIR/${BASENAME}.mp3" --words "$WORDS.srt" --job "$JOB"; then
    mv -f "$FILEPATH" "$ORIG_DIR/"   # your original is kept, never deleted
    echo "Ready: ${BASENAME}.mp3"
  fi
done 3< <(inotifywait -m -e close_write -e moved_to --format '%f' "$INPUT_DIR")

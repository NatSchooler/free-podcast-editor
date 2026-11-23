#!/bin/bash
# 2-person 9:16 split-screen engine (v2.9.4): frame 9:16, verbatim word transcript, then ONE encode that cuts pauses/ums/stumbles
# and burns the word-by-word captions. Fix anything it missed in the dashboard Shorts Editor.
. "${MH_SCRIPTS:-$HOME/mediahub}/mediahub_lib.sh"
INPUT_DIR="$HUB/split_screen/input"
OUTPUT_DIR="$HUB/split_screen/output"

echo "Watching $INPUT_DIR (v2.9.7 one-pass shorts, retakes found piece by piece)..."
while IFS= read -r FILENAME <&3; do
  FILEPATH="$INPUT_DIR/$FILENAME"
  [[ "$FILENAME" == .* ]] && continue
  [ -f "$FILEPATH" ] || continue
  sleep 2

  # RE-BURN MODE: edited .srt dropped back into input
  if [[ "$FILENAME" == *.srt ]]; then
    BASENAME="${FILENAME%.srt}"
    JOB="split_${BASENAME}"
    if [ -f "$META/shorts/${BASENAME}.json" ]; then
      tr '[:lower:]' '[:upper:]' < "$FILEPATH" | tr -d '\r' > "$OUTPUT_DIR/${BASENAME}.srt"
      python3 "$SCRIPTS/shorts_cut.py" "$BASENAME" --layout split --out "$OUTPUT_DIR/${BASENAME}_9x16_split.mp4" \
        --reburn "$OUTPUT_DIR/${BASENAME}.srt" --job "$JOB" --pipe split
      rm -f "$FILEPATH"
      continue
    fi
    BASE_CUT="$OUTPUT_DIR/${BASENAME}_9x16_nocaptions.mp4"   # shorts made before v2.9.4
    [ -f "$BASE_CUT" ] || continue
    status "$JOB" split_reburn 1 1 "Re-burning edited captions: $BASENAME"
    tr '[:lower:]' '[:upper:]' < "$FILEPATH" | tr -d '\r' > "$OUTPUT_DIR/${BASENAME}.srt"
    python3 "$SCRIPTS/word_captions.py" chunks "$OUTPUT_DIR/${BASENAME}.srt" /tmp/split_reburn.ass --layout split --hook-file "$META/hooks/${BASENAME}.txt"
    if burn_ass "$BASE_CUT" /tmp/split_reburn.ass "$OUTPUT_DIR/${BASENAME}_9x16_split.mp4"; then
      status "$JOB" split_reburn 1 1 "Captions updated: ${BASENAME}_9x16_split.mp4" done
    else
      status "$JOB" split_reburn 1 1 "Caption re-burn failed: $BASENAME" error
    fi
    rm -f "$FILEPATH" /tmp/split_reburn.ass
    continue
  fi

  is_video "$FILENAME" || continue
  needs_rename "$INPUT_DIR" "$FILENAME" && continue
  BASENAME="${FILENAME%.*}"
  JOB="split_${BASENAME}"
  SD="$META/shorts"; mkdir -p "$SD"
  FRAMED="$SD/${BASENAME}.framed.mp4"
  WAV="$SHM/split_${BASENAME}_16k.wav"

  status "$JOB" split 1 4 "Detecting faces, matching head sizes, stacking 9:16: $FILENAME" running "$(media_secs "$FILEPATH")"
  if ! python3 "$SCRIPTS/auto_split_crop.py" "$FILEPATH" "$FRAMED"; then
    rm -f "$FRAMED"
  fi
  if [ ! -s "$FRAMED" ]; then status "$JOB" split 1 4 "Framing failed: $BASENAME" error; continue; fi

  status "$JOB" split 2 4 "Transcribing word by word, ums and stumbles included (RX 580)"
  ffmpeg -nostdin -y -i "$FRAMED" -vn -ar 16000 -ac 1 -c:a pcm_s16le "$WAV" -loglevel error
  # v2.9.7: whisper tidies retakes away when it hears them together, so each piece between pauses is transcribed
  # on its own (one whisper run for all pieces). Every take is written down with its own timing, so it can be cut.
  PIECES="$SHM/split_${BASENAME}_pieces"; rm -rf "$PIECES"
  PROMPT="Umm, so, uh, I was like, hmm, you know, er, I I think, the the thing is."
  rm -f "$SD/${BASENAME}.words.srt"
  if python3 "$SCRIPTS/verbatim_words.py" split "$WAV" "$PIECES"; then
    PARGS=(); while IFS=$'\t' read -r PF _; do [ -n "$PF" ] && PARGS+=(-f "$PF"); done < "$PIECES/list.txt"
    gpu "$WHISPER" -m "$MODEL" "${PARGS[@]}" -ml 1 -sow --prompt "$PROMPT" -osrt
    python3 "$SCRIPTS/verbatim_words.py" merge "$PIECES" "$SD/${BASENAME}.words.srt" || rm -f "$SD/${BASENAME}.words.srt"
  fi
  if [ ! -s "$SD/${BASENAME}.words.srt" ]; then   # fall back to the old single pass
    gpu "$WHISPER" -m "$MODEL" -f "$WAV" -ml 1 -sow --prompt "$PROMPT" -osrt -of "$SD/${BASENAME}.words"
  fi
  rm -rf "$WAV" "$PIECES"
  if [ ! -s "$SD/${BASENAME}.words.srt" ]; then status "$JOB" split 2 4 "Transcription failed: $BASENAME" error; continue; fi

  # Steps 3 and 4 in one go: cut pauses, ums and stumbles, burn captions + logo, ONE encode
  if python3 "$SCRIPTS/shorts_cut.py" "$BASENAME" --layout split --words "$SD/${BASENAME}.words.srt" \
       --out "$OUTPUT_DIR/${BASENAME}_9x16_split.mp4" --srt-out "$OUTPUT_DIR/${BASENAME}.srt" --job "$JOB" --pipe split; then
    rm -f "$FILEPATH"   # the upload is only removed once the short is made
    echo "Ready: ${BASENAME}_9x16_split.mp4 (fix anything in the dashboard Shorts Editor)"
  fi
done 3< <(inotifywait -m -e close_write -e moved_to --format '%f' "$INPUT_DIR")

#!/bin/bash
# Solo 9:16 daily shorts engine (v2.9.5): frame 9:16, verbatim word transcript, then ONE encode that cuts pauses/ums/stumbles
# and burns the word-by-word captions. Fix anything it missed in the dashboard Shorts Editor.
. "${MH_SCRIPTS:-$HOME/mediahub}/mediahub_lib.sh"
INPUT_DIR="$HUB/shorts_daily/input"
OUTPUT_DIR="$HUB/shorts_daily/output"

echo "Watching $INPUT_DIR (v2.9.7 one-pass shorts, retakes found piece by piece)..."
while IFS= read -r FILENAME <&3; do
  FILEPATH="$INPUT_DIR/$FILENAME"
  [[ "$FILENAME" == .* ]] && continue
  [ -f "$FILEPATH" ] || continue
  sleep 2

  # RE-BURN MODE: edited .srt dropped back into input
  if [[ "$FILENAME" == *.srt ]]; then
    BASENAME="${FILENAME%.srt}"
    JOB="short_${BASENAME}"
    if [ -f "$META/shorts/${BASENAME}.json" ]; then
      tr '[:lower:]' '[:upper:]' < "$FILEPATH" | tr -d '\r' > "$OUTPUT_DIR/${BASENAME}.srt"
      python3 "$SCRIPTS/shorts_cut.py" "$BASENAME" --layout solo --out "$OUTPUT_DIR/${BASENAME}_final.mp4" \
        --reburn "$OUTPUT_DIR/${BASENAME}.srt" --job "$JOB" --pipe shorts
      rm -f "$FILEPATH"
      continue
    fi
    BASE_CUT="$OUTPUT_DIR/${BASENAME}_nocaptions.mp4"   # shorts made before v2.9.4
    [ -f "$BASE_CUT" ] || continue
    status "$JOB" shorts_reburn 1 1 "Re-burning edited captions: $BASENAME"
    tr '[:lower:]' '[:upper:]' < "$FILEPATH" | tr -d '\r' > "$OUTPUT_DIR/${BASENAME}.srt"
    python3 "$SCRIPTS/word_captions.py" chunks "$OUTPUT_DIR/${BASENAME}.srt" /tmp/shorts_reburn.ass --layout solo --hook-file "$META/hooks/${BASENAME}.txt"
    if burn_ass "$BASE_CUT" /tmp/shorts_reburn.ass "$OUTPUT_DIR/${BASENAME}_final.mp4"; then
      status "$JOB" shorts_reburn 1 1 "Captions updated: ${BASENAME}_final.mp4" done
    else
      status "$JOB" shorts_reburn 1 1 "Caption re-burn failed: $BASENAME" error
    fi
    rm -f "$FILEPATH" /tmp/shorts_reburn.ass
    continue
  fi

  is_video "$FILENAME" || continue
  needs_rename "$INPUT_DIR" "$FILENAME" && continue
  BASENAME="${FILENAME%.*}"
  JOB="short_${BASENAME}"
  SD="$META/shorts"; mkdir -p "$SD"
  FRAMED="$SD/${BASENAME}.framed.mp4"
  WAV="$SHM/shorts_${BASENAME}_16k.wav"

  # v2.9.5: is the upload already vertical 9:16? (phone rotation tags are taken into account)
  DIMS=$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height:stream_side_data=rotation -of default=nw=1 "$FILEPATH")
  VW=$(printf '%s\n' "$DIMS" | sed -n 's/^width=//p' | head -1)
  VH=$(printf '%s\n' "$DIMS" | sed -n 's/^height=//p' | head -1)
  ROT=$(printf '%s\n' "$DIMS" | sed -n 's/^rotation=//p' | head -1); ROT="${ROT#-}"; [ "$ROT" = "0" ] && ROT=""
  case "$ROT" in 90|270) T="$VW"; VW="$VH"; VH="$T";; esac
  VERTICAL=0
  if [[ "$VW" =~ ^[0-9]+$ && "$VH" =~ ^[0-9]+$ ]] && [ "$VH" -gt "$VW" ]; then
    R=$(( VW * 1000 / VH )); [ "$R" -ge 540 ] && [ "$R" -le 585 ] && VERTICAL=1   # 9:16 = 562
  fi

  if [ "$VERTICAL" -eq 1 ]; then
    status "$JOB" shorts 1 4 "Already 9:16, keeping your framing: $FILENAME" running "$(media_secs "$FILEPATH")"
    if [ "$VW" = "1080" ] && [ "$VH" = "1920" ] && [ -z "$ROT" ]; then
      VOPT=(-c:v copy)   # picture untouched, only the sound is levelled
    else
      VOPT=(-vf "scale=1080:1920:flags=lanczos,setsar=1" -c:v libx264 -crf 16 -preset veryfast -pix_fmt yuv420p)
    fi
    ffmpeg -nostdin -y -i "$FILEPATH" -map 0:v:0 -map "0:a:0?" "${VOPT[@]}" -af "highpass=f=80,loudnorm=I=-14:TP=-1.5:LRA=11" \
      -c:a aac -b:a 192k -movflags +faststart "$FRAMED" -loglevel error || rm -f "$FRAMED"
  else
  status "$JOB" shorts 1 4 "Framing 9:16 on the speaker's face: $FILENAME" running "$(media_secs "$FILEPATH")"
  if ! python3 "$SCRIPTS/auto_split_crop.py" --solo "$FILEPATH" "$FRAMED"; then
    echo "Face crop failed, using centre crop"
    ffmpeg -nostdin -y -i "$FILEPATH" -vf "crop=ih*9/16:ih,scale=1080:1920,setsar=1,fps=30" -af "highpass=f=80,loudnorm=I=-14:TP=-1.5:LRA=11" \
      -c:v libx264 -crf 16 -preset veryfast -pix_fmt yuv420p -c:a aac -b:a 192k "$FRAMED" -loglevel error
  fi
  fi
  if [ ! -s "$FRAMED" ]; then status "$JOB" shorts 1 4 "Framing failed: $BASENAME" error; continue; fi

  status "$JOB" shorts 2 4 "Transcribing word by word, ums and stumbles included (RX 580)"
  ffmpeg -nostdin -y -i "$FRAMED" -vn -ar 16000 -ac 1 -c:a pcm_s16le "$WAV" -loglevel error
  # v2.9.7: whisper tidies retakes away when it hears them together, so each piece between pauses is transcribed
  # on its own (one whisper run for all pieces). Every take is written down with its own timing, so it can be cut.
  PIECES="$SHM/shorts_${BASENAME}_pieces"; rm -rf "$PIECES"
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
  if [ ! -s "$SD/${BASENAME}.words.srt" ]; then status "$JOB" shorts 2 4 "Transcription failed: $BASENAME" error; continue; fi

  # Steps 3 and 4 in one go: cut pauses, ums and stumbles, burn captions + logo, ONE encode
  if python3 "$SCRIPTS/shorts_cut.py" "$BASENAME" --layout solo --words "$SD/${BASENAME}.words.srt" \
       --out "$OUTPUT_DIR/${BASENAME}_final.mp4" --srt-out "$OUTPUT_DIR/${BASENAME}.srt" --job "$JOB" --pipe shorts; then
    rm -f "$FILEPATH"   # the upload is only removed once the short is made
    echo "Ready: ${BASENAME}_final.mp4 (fix anything in the dashboard Shorts Editor)"
  fi
done 3< <(inotifywait -m -e close_write -e moved_to --format '%f' "$INPUT_DIR")

#!/bin/bash
# Master long-form video + podcast engine (v2)
. "${MH_SCRIPTS:-$HOME/mediahub}/mediahub_lib.sh"
INPUT_DIR="$HUB/youtube_long/input"
OUTPUT_DIR="$HUB/youtube_long/output"
PODCAST_OUT="$HUB/podcast_audio/output"
BASE_DIR="$HUB/youtube_long"
OUTRO_FILE="$BASE_DIR/outro.mp4"
ENC=(-c:v libx264 -crf 20 -preset fast -pix_fmt yuv420p -c:a aac -b:a 192k -ar 48000 -ac 2)

find_audio_intro() {
  for dir in "$BASE_DIR" "$HUB/podcast_audio"; do
    for ext in mp3 wav m4a aac flac MP3 WAV M4A; do
      if [ -f "$dir/intro.$ext" ]; then echo "$dir/intro.$ext"; return; fi
    done
  done
}

build_podcast_mp3() {
  local BODY_AUDIO="$1" FINAL_MP3="$2" INTRO_FILE
  INTRO_FILE=$(find_audio_intro)
  if [ -z "$INTRO_FILE" ]; then
    # exact two-pass loudness to the podcast standard (-16 LUFS); the voice was already polished in the master
    local AF; AF=$(python3 "$SCRIPTS/audio_polish.py" "$BODY_AUDIO" -16 --light)
    [ -z "$AF" ] && AF="loudnorm=I=-16:TP=-1.5:LRA=11"
    ffmpeg -nostdin -y -i "$BODY_AUDIO" -vn -af "$AF" -c:a libmp3lame -b:a 192k -ar 44100 -ac 2 "$FINAL_MP3" -loglevel error
  else
    ffmpeg -nostdin -y -i "$INTRO_FILE" -i "$BODY_AUDIO" \
      -filter_complex "[0:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo,loudnorm=I=-16:TP=-1.5:LRA=11[a0];[1:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo,loudnorm=I=-16:TP=-1.5:LRA=11[a1];[a0][a1]concat=n=2:v=0:a=1[out]" \
      -map "[out]" -c:a libmp3lame -b:a 192k "$FINAL_MP3" -loglevel error
  fi
}

append_video_outro() {
  local MAIN_VID="$1" FINAL_VID="$2" W H FPS
  if [ ! -f "$OUTRO_FILE" ]; then mv "$MAIN_VID" "$FINAL_VID"; return; fi
  W=$(ffprobe -v error -select_streams v:0 -show_entries stream=width -of csv=p=0 "$MAIN_VID")
  H=$(ffprobe -v error -select_streams v:0 -show_entries stream=height -of csv=p=0 "$MAIN_VID")
  FPS=$(ffprobe -v error -select_streams v:0 -show_entries stream=r_frame_rate -of csv=p=0 "$MAIN_VID")
  local TMP_OUTRO="/tmp/norm_outro.mp4"
  ffmpeg -nostdin -y -i "$OUTRO_FILE" -vf "scale=${W}:${H}:force_original_aspect_ratio=decrease,pad=${W}:${H}:(ow-iw)/2:(oh-ih)/2,fps=${FPS},setsar=1" \
    -af "loudnorm=I=-14:TP=-1.5:LRA=11" "${ENC[@]}" "$TMP_OUTRO" -loglevel error
  ffmpeg -nostdin -y -i "$MAIN_VID" -i "$TMP_OUTRO" -filter_complex "[0:v]setsar=1[v0];[v0][0:a][1:v][1:a]concat=n=2:v=1:a=1[v][a]" \
    -map "[v]" -map "[a]" "${ENC[@]}" "$FINAL_VID" -loglevel error
  rm -f "$MAIN_VID" "$TMP_OUTRO"
}

# cut_both_from_timestamps <cuts file> <base> <yes|no outro> <job id> [first step number - 1] [total steps]
cut_both_from_timestamps() {
  local CUT_FILE="$1" BASE="$2" ADD_OUTRO="$3" JOB="${4:-cut_$2}" SB="${5:-0}" ST="${6:-3}"
  local SOURCE_VID="$OUTPUT_DIR/${BASE}_clean.mp4"
  tr -d '\r' < "$CUT_FILE" > "$META/${BASE}.last_cuts.txt"
  rm -f "$CUT_FILE"   # taken now, so a newer edit saved while this one renders is never deleted

  status "$JOB" youtube $((SB+1)) "$ST" "Cutting edited episode: $BASE" running "$(media_secs "$SOURCE_VID")"
  # The slow AI part of the content pack needs only the transcript, so it runs NOW, alongside the cut.
  # The per-episode lock makes the final chapter step below wait for it (and reuse its cached analysis).
  ( ai flock "$META/${BASE}.pack.lock" python3 "$SCRIPTS/ai_content_pack.py" "$OUTPUT_DIR/${BASE}_transcript.srt" \
      "$OUTPUT_DIR/${BASE}_content_pack.txt" --meta "$META/$BASE" --name "$BASE" > /dev/null 2>&1 & )
  echo "$ADD_OUTRO" > "$META/${BASE}.last_outro"
  local TMP_VID="/tmp/${BASE}_edited_raw.mp4"
  # Frame-exact cuts; long sections copied, only cut edges + hook rendered; joins verified, auto full-render fallback.
  # smart_cut.py also refuses any HOOK longer than 25 seconds.
  local OUTRO_ARGS=(); [ "$ADD_OUTRO" == "yes" ] && [ -f "$OUTRO_FILE" ] && OUTRO_ARGS=(--outro "$OUTRO_FILE")
  if ! python3 "$SCRIPTS/smart_cut.py" "$SOURCE_VID" "$META/${BASE}.last_cuts.txt" "$TMP_VID" --job "$JOB" --step $((SB+1)) --total "$ST" "${OUTRO_ARGS[@]}" \
       --words "$OUTPUT_DIR/${BASE}_words.srt" --meta "$META/$BASE" \
       || [ ! -s "$TMP_VID" ]; then
    status "$JOB" youtube $((SB+1)) "$ST" "Cut failed for $BASE (check the timestamps)" error
    rm -f "$TMP_VID"
    return 1
  fi

  status "$JOB" youtube $((SB+2)) "$ST" "Building edited podcast MP3"
  local TMP_AUD="$SHM/${BASE}_edited_body.wav"
  ffmpeg -nostdin -y -i "$TMP_VID" -vn -ar 44100 -ac 2 -c:a pcm_s16le "$TMP_AUD" -loglevel error
  build_podcast_mp3 "$TMP_AUD" "$PODCAST_OUT/${BASE}_podcast_edited.mp3"

  local FINAL_NAME="${BASE}_edited"
  [ "$ADD_OUTRO" == "yes" ] && FINAL_NAME="${BASE}_edited_with_outro"
  mv "$TMP_VID" "$OUTPUT_DIR/${FINAL_NAME}.mp4"   # outro (if ticked) is already joined on by smart_cut.py

  status "$JOB" youtube $((SB+3)) "$ST" "Captions + chapters for the edited cut (finishing the AI content pack)"
  python3 "$SCRIPTS/srt_offset.py" "$OUTPUT_DIR/${BASE}_transcript.srt" "$META/${BASE}.last_cuts.txt" "$OUTPUT_DIR/${FINAL_NAME}.srt" "$META/$BASE"
  ai flock "$META/${BASE}.pack.lock" python3 "$SCRIPTS/ai_content_pack.py" "$OUTPUT_DIR/${BASE}_transcript.srt" "$OUTPUT_DIR/${BASE}_content_pack.txt" \
    --meta "$META/$BASE" --cuts "$META/${BASE}.last_cuts.txt" --name "$BASE" --job "$JOB" > /dev/null
  status "$JOB" youtube $((SB+3)) "$ST" "Ready: ${FINAL_NAME}.mp4 + .srt + podcast MP3 + content pack" done
  rm -f "$TMP_AUD"
}

echo "Watching $INPUT_DIR (Video -> $OUTPUT_DIR | Audio -> $PODCAST_OUT)..."
while IFS= read -r FILENAME <&3; do
  FILEPATH="$INPUT_DIR/$FILENAME"
  [[ "$FILENAME" == .* ]] && continue
  [ -f "$FILEPATH" ] || continue
  sleep 2

  if [[ "$FILENAME" == *.clips.txt ]]; then
    BASE="${FILENAME%.clips.txt}"
    [ -f "$OUTPUT_DIR/${BASE}_clean.mp4" ] || continue
    echo "Slicing custom clips from $BASE..."
    python3 "$SCRIPTS/slice_clips.py" "$BASE" "$FILEPATH"
    rm -f "$FILEPATH"

  elif [[ "$FILENAME" == *.outro.cuts.txt ]]; then
    BASE="${FILENAME%.outro.cuts.txt}"
    [ -f "$OUTPUT_DIR/${BASE}_clean.mp4" ] || continue
    cut_both_from_timestamps "$FILEPATH" "$BASE" "yes" "cut_$BASE"

  elif [[ "$FILENAME" == *.cuts.txt ]]; then
    BASE="${FILENAME%.cuts.txt}"
    [ -f "$OUTPUT_DIR/${BASE}_clean.mp4" ] || continue
    cut_both_from_timestamps "$FILEPATH" "$BASE" "no" "cut_$BASE"

  elif [[ "$FILENAME" == *.outro.txt ]]; then
    BASE="${FILENAME%.outro.txt}"
    SOURCE_VID="$OUTPUT_DIR/${BASE}_clean.mp4"
    [ -f "$SOURCE_VID" ] || continue
    status "outro_$BASE" outro 1 1 "Attaching outro to $BASE" running "$(media_secs "$SOURCE_VID")"
    cp "$SOURCE_VID" "/tmp/${BASE}_copy.mp4"
    append_video_outro "/tmp/${BASE}_copy.mp4" "$OUTPUT_DIR/${BASE}_with_outro.mp4"
    rm -f "$FILEPATH"
    status "outro_$BASE" outro 1 1 "Ready: ${BASE}_with_outro.mp4" done

  else
    is_video "$FILENAME" || continue
    needs_rename "$INPUT_DIR" "$FILENAME" && continue
    BASENAME="${FILENAME%.*}"
    JOB="yt_${BASENAME}"
    CLEAN_OUT="$OUTPUT_DIR/${BASENAME}_clean.mp4"
    TMP_WAV="$SHM/${BASENAME}_16k.wav"
    SRT="$OUTPUT_DIR/${BASENAME}_transcript.srt"

    status "$JOB" youtube 1 8 "Polishing sound (noise removal, voice EQ, speaker levelling) + building master: $FILENAME" running "$(media_secs "$FILEPATH")"
    AF=$(python3 "$SCRIPTS/audio_polish.py" "$FILEPATH" -14)
    [ -z "$AF" ] && AF="highpass=f=80,loudnorm=I=-14:TP=-1.5:LRA=11"
    ffmpeg -nostdin -y -i "$FILEPATH" -map 0:v:0 -map "0:a:0?" -c:v copy -af "$AF" -c:a aac -b:a 192k -ar 48000 -ac 2 "$CLEAN_OUT" -loglevel error
    if [ ! -s "$CLEAN_OUT" ]; then status "$JOB" youtube 1 8 "Could not read $FILENAME" error; continue; fi

    status "$JOB" youtube 2 8 "Full podcast MP3"
    build_podcast_mp3 "$CLEAN_OUT" "$PODCAST_OUT/${BASENAME}_podcast_full.mp3"

    status "$JOB" youtube 3 8 "Transcribing on the RX 580"
    ffmpeg -nostdin -y -i "$CLEAN_OUT" -vn -ar 16000 -ac 1 -c:a pcm_s16le "$TMP_WAV" -loglevel error
    # One pass, word-by-word timing. The prompt nudges whisper to keep ums/uhs so they can be cut out.
    gpu "$WHISPER" -m "$MODEL" -f "$TMP_WAV" -ml 1 -sow --prompt "Umm, so, uh, I was like, hmm, you know, er, thinking." \
      -osrt -of "$OUTPUT_DIR/${BASENAME}_words"
    python3 "$SCRIPTS/build_transcript.py" "$OUTPUT_DIR/${BASENAME}_words.srt" "$OUTPUT_DIR/${BASENAME}_transcript"
    rm -f "$FILEPATH" "$TMP_WAV"
    if [ ! -s "$SRT" ]; then status "$JOB" youtube 3 8 "Transcription failed: $BASENAME" error; continue; fi

    status "$JOB" youtube 4 8 "AI finding the real start and end"
    AUTO_RANGE=$(ai python3 "$SCRIPTS/ai_auto_trim.py" "$SRT" | head -n1)
    [ -n "$AUTO_RANGE" ] && echo "$AUTO_RANGE" > "$META/${BASENAME}.range"

    AUTO_SHORTS=""
    if [ "$(mhconf MH_AUTO_SHORTS off)" == "on" ]; then
      status "$JOB" youtube 5 8 "AI picking the best shorts from the whole episode"
      RANGE_ARGS=(); [ -n "$AUTO_RANGE" ] && RANGE_ARGS=(--range "$AUTO_RANGE")
      AUTO_SHORTS=$(ai python3 "$SCRIPTS/ai_pick_shorts.py" "$SRT" "$MH_SHORTS_MODE" --count "$MH_SHORTS_COUNT" \
        --json "$META/${BASENAME}.shorts.json" "${RANGE_ARGS[@]}")
    fi

    if [ -n "$AUTO_RANGE" ]; then
      echo "AI auto-trim: $AUTO_RANGE"
      { [ "$(mhconf MH_REMOVE_FILLERS on)$(mhconf MH_REMOVE_PAUSES on)" != "offoff" ] && echo "CLEAN: on"; echo "$AUTO_RANGE"; } > "/tmp/${BASENAME}_auto.cuts.txt"
      cut_both_from_timestamps "/tmp/${BASENAME}_auto.cuts.txt" "$BASENAME" "no" "$JOB" 5 8
    else
      status "$JOB" youtube 8 8 "Writing content pack"
      ai flock "$META/${BASENAME}.pack.lock" python3 "$SCRIPTS/ai_content_pack.py" "$SRT" "$OUTPUT_DIR/${BASENAME}_content_pack.txt" \
        --meta "$META/$BASENAME" --name "$BASENAME" --job "$JOB" > /dev/null
      status "$JOB" youtube 8 8 "Ready: master, transcript, podcast MP3, content pack" done
    fi
    if [ -n "$AUTO_SHORTS" ]; then
      echo "AI shorts: $AUTO_SHORTS"
      printf '%s\n' "$AUTO_SHORTS" > "$INPUT_DIR/${BASENAME}.clips.txt"
    fi
    echo "Ready: Video in youtube_long/output | Audio in podcast_audio/output"
  fi
done 3< <(inotifywait -m -e close_write -e moved_to --format '%f' "$INPUT_DIR")

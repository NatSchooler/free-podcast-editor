#!/bin/bash
# Run before every release: stops if any personal detail, key or private address is left in the pack.
cd "$(dirname "$0")/.."
PAT='/home/nat|192\.168\.|natha|Schooler|Influential Visions|Future Proofed|Monday Influencer|Network First|CATAPULT|riverside\.com/studio|sk-[A-Za-z0-9]{10,}|sk-or-|api[_-]?key *= *[A-Za-z0-9]|password *= *[A-Za-z0-9]'
if grep -rInEi "$PAT" app config 2>/dev/null; then echo; echo "RELEASE CHECK FAILED: personal details found above."; exit 1; fi
find app config -type f \( -iname '*.mp3' -o -iname '*.mp4' -o -iname '*.wav' -o -iname '*.png' -o -iname '*.jpg' -o -iname '*.mov' \) | grep . && { echo "RELEASE CHECK FAILED: media files in the pack."; exit 1; }
echo "Release check passed: no personal details, keys or media found."

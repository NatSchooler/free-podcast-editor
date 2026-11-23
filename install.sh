#!/bin/bash
# Media Hub: Free Podcast Editing Software - installer for Ubuntu 22.04 / 24.04 (also inside Windows WSL)
# MIT licence. No support is provided: if something breaks, it is yours to fix.
PACK="$(cd "$(dirname "$0")" && pwd)"
APP="$HOME/mediahub"
HUB="$HOME/media_hub"
APT="sudo DEBIAN_FRONTEND=noninteractive apt-get -y"
say()  { printf '\n\033[1;33m==> %s\033[0m\n' "$1"; }
warn() { printf '\033[1;31mNOTE: %s\033[0m\n' "$1"; }

if [ "$(id -u)" = "0" ]; then echo "Please run this as your normal user, not as root (it asks for your password when needed)."; exit 1; fi
grep -qi ubuntu /etc/os-release 2>/dev/null || warn "this was made for Ubuntu 22.04 or 24.04. Carrying on, but it may not work."

say "1/7 System tools (ffmpeg, Python, build tools, fonts)"
echo "ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true" | sudo debconf-set-selections
$APT update
$APT install ffmpeg python3 python3-numpy python3-opencv inotify-tools util-linux curl git build-essential cmake \
  pkg-config pipx mesa-va-drivers vainfo fontconfig || warn "some system packages did not install"
$APT install ttf-mscorefonts-installer >/dev/null 2>&1 || warn "Arial Black font not installed (captions use a fallback font)"
for p in libvulkan-dev glslc mesa-vulkan-drivers vulkan-tools; do $APT install "$p" >/dev/null 2>&1 || echo "note: $p not available on this Ubuntu"; done
fc-cache -f >/dev/null 2>&1
sudo usermod -aG render,video "$USER" 2>/dev/null || true

say "2/7 auto-editor (pause cutting for shorts)"
[ -x "$HOME/.local/bin/auto-editor" ] || pipx install auto-editor || pip3 install --user --break-system-packages auto-editor || warn "auto-editor did not install"

say "3/7 whisper.cpp (transcription) + large-v3-turbo model"
mkdir -p "$APP"
W="$APP/whisper.cpp"
[ -d "$W" ] || git clone --depth 1 https://github.com/ggml-org/whisper.cpp "$W"
if [ ! -x "$W/build/bin/whisper-cli" ]; then
  if ! (cd "$W" && cmake -B build -DGGML_VULKAN=1 -DCMAKE_BUILD_TYPE=Release && cmake --build build -j"$(nproc)" --config Release); then
    rm -rf "$W/build"
    (cd "$W" && cmake -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build -j"$(nproc)" --config Release) \
      && warn "whisper was built for the processor only (no graphics card build); transcription will be slower" \
      || warn "whisper.cpp did not build"
  fi
fi
[ -s "$W/models/ggml-large-v3-turbo.bin" ] || bash "$W/models/download-ggml-model.sh" large-v3-turbo || warn "whisper model did not download"

say "4/7 Ollama + llama3 (the local AI)"
command -v ollama >/dev/null || curl -fsSL https://ollama.com/install.sh | sh || warn "Ollama did not install"
sudo systemctl enable --now ollama >/dev/null 2>&1 || ( nohup ollama serve >/dev/null 2>&1 & )
for i in $(seq 1 30); do curl -s -m 2 http://127.0.0.1:11434/api/tags >/dev/null && break; sleep 2; done
ollama list 2>/dev/null | grep -q '^llama3:latest' || ollama pull llama3:latest || warn "llama3 did not download (run: ollama pull llama3:latest)"

say "5/7 Face and noise-removal models"
mkdir -p "$HOME/models"
[ -s "$HOME/models/face_detection_yunet_2023mar.onnx" ] || curl -fL -o "$HOME/models/face_detection_yunet_2023mar.onnx" \
  https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx || warn "face model did not download"
[ -s "$HOME/models/rnnoise_std.rnnn" ] || curl -fL -o "$HOME/models/rnnoise_std.rnnn" \
  https://raw.githubusercontent.com/richardpl/arnndn-models/master/std.rnnn || warn "noise model did not download"
[ "$(stat -c %s "$HOME/models/face_detection_yunet_2023mar.onnx" 2>/dev/null || echo 0)" -gt 100000 ] || { rm -f "$HOME/models/face_detection_yunet_2023mar.onnx"; warn "face model looks wrong; the basic face detector will be used"; }

say "6/7 Media Hub app, folders and settings"
cp -r "$PACK/app/." "$APP/"
chmod +x "$APP"/*.py "$APP"/*.sh
mkdir -p "$HUB"/{youtube_long/input,youtube_long/output,podcast_audio/output,split_screen/input,split_screen/output} \
         "$HUB"/{shorts_daily/input,shorts_daily/output,sound_only/input,sound_only/output,sound_only/originals,brand,.jobs,.meta/hooks}
[ -f "$HUB/brand/house_style.txt" ] || cp "$PACK/config/house_style.example.txt" "$HUB/brand/house_style.txt"
[ -f "$HOME/mediahub.conf" ] || cp "$PACK/config/mediahub.conf.example" "$HOME/mediahub.conf"
grep -q 'MH_SCRIPTS=' "$HOME/.bashrc" || printf '\n# Media Hub\nexport MH_SCRIPTS="%s"\nexport MH_HUB="%s"\n' "$APP" "$HUB" >> "$HOME/.bashrc"
export MH_SCRIPTS="$APP" MH_HUB="$HUB"
# Start Media Hub again after a reboot (Ubuntu); on Windows, run the restart line below when you need it
( crontab -l 2>/dev/null | grep -v mediahub_restart.sh; echo "@reboot MH_SCRIPTS=$APP MH_HUB=$HUB bash $APP/mediahub_restart.sh --force >/dev/null 2>&1" ) | crontab - 2>/dev/null || true

say "7/7 Starting Media Hub"
bash "$APP/mediahub_restart.sh" --force

cat <<'MSG'

=====================================================================
 Media Hub is installed.  Open:  http://localhost:8080
 Your files:    ~/media_hub          Your settings: ~/media_hub/brand/house_style.txt
 Restart it:    bash ~/mediahub/mediahub_restart.sh

 NO SUPPORT IS PROVIDED. This software is free and given as it is.
 If something breaks, it is yours to fix. Keep copies of your originals.

 Want to say thank you? Get my book, CATAPULT PROTOCOL(TM):
   https://natschooler.com/cat/
 Subscribe to Influential Visions:
   https://www.youtube.com/@influentialvisions?sub_confirmation=1
                                                       - Nat Schooler
=====================================================================
MSG

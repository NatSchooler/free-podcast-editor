# Media Hub: Free Podcast Editing Software

**Free, open-source podcast and video editing software that runs on your own computer.**
Drop in a recording, and Media Hub trims the warm-up chat, removes fillers and long pauses, cleans up the sound, writes the transcript, builds titles, chapters and show notes, and cuts vertical shorts with captions. Everything runs locally. No subscriptions, no uploads to anyone's cloud.

Version 2.9.8. Built by [Nat Schooler](https://natschooler.com) for the [Influential Visions](https://influentialvisions.com) podcast, and given away free.

---

## ⚠️ No support is provided

This software is free and given as it is. I do not offer help installing it, fixing it or answering questions about it. If something breaks, it is yours to fix. Use it at your own risk, and always keep a copy of your original recordings.

---

## Want to say thank you? Get my book.

**CATAPULT PROTOCOL™: The Career Playbook for the AI and Superintelligence Shift**
$7.99 launch price for the first 1,000 copies only.
👉 [GET THE BOOK](https://natschooler.com/cat/)


Subscribe to [Influential Visions on YouTube](https://www.youtube.com/@influentialvisions?sub_confirmation=1) and follow the podcast.

---

## What it does

- **Long-form episodes:** automatic start trim (skips the pre-show chat), filler and pause removal, text-based editing in the browser, finished video for YouTube and an MP3 for your podcast feed.
- **Transcripts:** word-accurate transcripts and subtitles with whisper.cpp.
- **AI content pack:** titles, chapters, descriptions and show notes from a local AI model (Ollama). Nothing leaves your machine.
- **Shorts:** vertical 9:16 clips that follow whoever is speaking, with word-by-word captions.
- **Sound only:** WAV or M4A in, MP3 out. Breaths are turned down, levels are evened out, and no words are cut.
- **Dashboard:** a simple web page to upload files, watch progress and download results.

## What you need

- **Ubuntu 22.04 or 24.04**, either on its own computer, or on **Windows 10 or 11 through WSL** (Windows Subsystem for Linux). The Windows installer sets WSL up for you.
- 16 GB of memory or more is recommended. A graphics card speeds things up but is not required.
- About 15 GB of free disk space for the AI models.

## Install

### On Ubuntu

```bash
cd free-podcast-editor
bash install.sh
```

### On Windows

Right-click `windows/INSTALL-ON-WINDOWS.bat` and choose **Run as administrator**. If Windows asks you to restart, restart and run it once more.

When the installer finishes, open **http://localhost:8080** in your browser.

## Your own style

Out of the box Media Hub is deliberately plain: basic sound, white captions, no logo and no intro or outro. You make it yours. Your settings live in `~/media_hub/brand/house_style.txt` (created from `config/house_style.example.txt`). Add your name, your logo and your own intro, outro and mid-roll clips (uploaded once from the dashboard) to make every episode yours.

## Licence

MIT. See `LICENSE`. Free to use, change and share. Please keep the credit.

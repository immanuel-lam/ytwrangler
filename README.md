# ytwrangler

A cross-platform GUI wrapper around **yt-dlp** + **ffmpeg** for batch and
single downloads. Built with PySide6 (Qt).

## Features

- **Batch tab** — paste many links, set each one's mode, pick an output
  folder, hit Start. Modes:
  - **both** — video + audio combined into one MP4
  - **video** — video only, no audio track (MP4)
  - **audio** — audio only (MP3)
  - The queue and settings are saved automatically, so you can close the app
    and pick up where you left off.
  - Configurable parallelism (1–5 at a time; default 1 to stay friendly with
    rate limits).
- **Single tab** — fetch a URL's available formats and fine-tune exactly which
  one you download.
- **Smart compatibility** for video: if the source is already H.264 it just
  remuxes into MP4 (instant). If it's AV1/VP9 it re-encodes to H.264 using
  hardware acceleration so files play on anything. There's also a per-link
  **Force H.264** toggle.
- **Tested encoder picker** — on first run the app actually *runs* each
  candidate H.264 encoder (VideoToolbox / NVENC / QuickSync / AMF) and only
  offers the ones that work on your hardware, since `ffmpeg -encoders` lists
  encoders even when the GPU can't use them. Pick one from the dropdown, or
  hit **Re-detect**. If a hardware encoder fails mid-conversion it
  automatically falls back to software libx264.
- Audio always normalized to AAC inside MP4 (fixes the "Opus in MP4" error),
  and audio-only downloads come out as MP3.
- Runs yt-dlp with `--js-runtimes node` as requested.

## Requirements

- **Python 3.9+**
- **ffmpeg** (and ffprobe) on your PATH
  - macOS: `brew install ffmpeg`
  - Windows: `choco install ffmpeg` (or download a build and add it to PATH)
  - Linux: `sudo apt install ffmpeg` (or your distro's equivalent)
- **Node.js** on your PATH (for `--js-runtimes node`)

## Install & run

```bash
cd ytwrangler
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

`yt-dlp` is installed via `requirements.txt`. If you'd rather use a
system-installed ffmpeg/yt-dlp at a custom location, set the paths under
**Settings…** in the app (blank = auto-detect from PATH).

## Notes

- The session file lives in your OS config dir
  (`~/Library/Application Support/ytwrangler/session.json` on macOS,
  `%APPDATA%\ytwrangler\` on Windows, `~/.config/ytwrangler/` on Linux).
- "Both" downloads the video once and extracts the MP3 from that file, so it
  doesn't download twice.

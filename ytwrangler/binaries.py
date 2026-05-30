"""Locate external binaries (yt-dlp, ffmpeg, ffprobe) and pick a hardware
H.264 encoder appropriate for the current platform."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path

# Quality/codec args per H.264 encoder. Chosen to need no device setup so they
# work out of the box on a typical machine.
ENCODER_ARGS: dict[str, list[str]] = {
    "h264_videotoolbox": ["-q:v", "60"],                       # macOS
    "h264_nvenc": ["-rc", "vbr", "-cq", "23", "-preset", "medium"],  # Nvidia
    "h264_qsv": ["-global_quality", "23"],                     # Intel QuickSync
    "h264_amf": ["-quality", "balanced"],                      # AMD
    "libx264": ["-crf", "20", "-preset", "medium"],            # software fallback
}

# Common install locations to probe if a binary isn't on PATH.
_EXTRA_PATHS = [
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "/usr/bin",
    str(Path.home() / ".local" / "bin"),
]


def find_binary(name: str, override: str | None = None) -> str | None:
    """Return a usable path to `name`, honoring an explicit override first."""
    if override:
        p = Path(override).expanduser()
        if p.exists():
            return str(p)

    found = shutil.which(name)
    if found:
        return found
    if os.name == "nt":
        found = shutil.which(name + ".exe")
        if found:
            return found

    exe = name + (".exe" if os.name == "nt" else "")
    for d in _EXTRA_PATHS:
        cand = Path(d) / exe
        if cand.exists():
            return str(cand)
    return None


def ffprobe_for(ffmpeg_path: str | None) -> str | None:
    """ffprobe usually sits next to ffmpeg; fall back to PATH."""
    if ffmpeg_path:
        p = Path(ffmpeg_path)
        cand = p.with_name("ffprobe" + p.suffix)
        if cand.exists():
            return str(cand)
    return find_binary("ffprobe")


def detect_h264_encoder(ffmpeg_path: str | None) -> str:
    """Pick the best available hardware H.264 encoder, else libx264."""
    if not ffmpeg_path:
        return "libx264"
    try:
        out = subprocess.run(
            [ffmpeg_path, "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=15,
        ).stdout
    except Exception:
        return "libx264"

    system = platform.system()
    if system == "Darwin":
        priority = ["h264_videotoolbox"]
    elif system == "Windows":
        priority = ["h264_nvenc", "h264_qsv", "h264_amf"]
    else:  # Linux / other — only auto-pick encoders that need no device setup
        priority = ["h264_nvenc"]

    for enc in priority:
        if enc in out:
            return enc
    return "libx264"

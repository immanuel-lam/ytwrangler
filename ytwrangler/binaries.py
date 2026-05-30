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

# Human-friendly names for the encoder picker.
ENCODER_LABELS: dict[str, str] = {
    "h264_videotoolbox": "VideoToolbox (Apple)",
    "h264_nvenc": "NVENC (Nvidia)",
    "h264_qsv": "QuickSync (Intel HD)",
    "h264_amf": "AMF (AMD)",
    "libx264": "Software (libx264)",
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


def _platform_priority() -> list[str]:
    system = platform.system()
    if system == "Darwin":
        return ["h264_videotoolbox"]
    if system == "Windows":
        return ["h264_nvenc", "h264_qsv", "h264_amf"]
    return ["h264_nvenc", "h264_qsv"]  # Linux / other


def _listed_encoders(ffmpeg_path: str) -> str:
    try:
        return subprocess.run(
            [ffmpeg_path, "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=15,
        ).stdout
    except Exception:
        return ""


def _encoder_works(ffmpeg_path: str, encoder: str) -> bool:
    """Actually try a tiny encode. `ffmpeg -encoders` lists hardware encoders
    even when the GPU can't use them (e.g. NVENC on a GeForce 930MX), so the
    only reliable check is to run one."""
    cmd = [
        ffmpeg_path, "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=black:s=128x72:d=0.1",
        "-frames:v", "1", "-c:v", encoder, "-f", "null", "-",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=25,
                           **_run_kwargs())
        return r.returncode == 0
    except Exception:
        return False


def _run_kwargs() -> dict:
    # Don't pop a console window on Windows.
    if os.name == "nt":
        return {"creationflags": 0x08000000}
    return {}


def test_h264_encoders(ffmpeg_path: str | None) -> list[str]:
    """Return the H.264 encoders that actually work on this machine, best
    first. libx264 is always included as a guaranteed fallback."""
    if not ffmpeg_path:
        return ["libx264"]
    listed = _listed_encoders(ffmpeg_path)
    candidates = [e for e in _platform_priority() if e in listed]
    candidates.append("libx264")
    working = [e for e in candidates if _encoder_works(ffmpeg_path, e)]
    if "libx264" not in working:
        working.append("libx264")  # last-resort, assume software always works
    return working


def detect_h264_encoder(ffmpeg_path: str | None) -> str:
    """Best working H.264 encoder (tests them), else libx264."""
    return test_h264_encoders(ffmpeg_path)[0]

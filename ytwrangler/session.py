"""App state: binary discovery, encoder choice, and JSON persistence so the
queue/settings survive a relaunch."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .binaries import ffprobe_for, find_binary, test_h264_encoders


def config_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    d = base / "ytwrangler"
    d.mkdir(parents=True, exist_ok=True)
    return d


SESSION_FILE = config_dir() / "session.json"


class AppState:
    """Holds binary paths, encoder, and the persisted session document."""

    def __init__(self) -> None:
        self.data: dict = {
            "ytdlp_path": "",
            "ffmpeg_path": "",
            "out_dir": str(Path.home() / "Desktop" / "ytdownloader"),
            "concurrency": 1,
            "allow_playlist": False,
            "items": [],          # [{url, mode, force_h264}]
            "encoder": "",                 # chosen H.264 encoder id
            "available_encoders": [],      # tested-working encoders
        }
        self.load()
        self.refresh_binaries()

    # -- binaries ---------------------------------------------------------- #
    def refresh_binaries(self) -> None:
        """Cheap: locate paths only. Encoder testing is separate (detect_encoders)
        because it runs ffmpeg and is slower."""
        self.ytdlp = find_binary("yt-dlp", self.data.get("ytdlp_path") or None)
        self.ffmpeg = find_binary("ffmpeg", self.data.get("ffmpeg_path") or None)
        self.ffprobe = ffprobe_for(self.ffmpeg)
        # Use the saved choice if any; otherwise a safe default until detection.
        self.encoder = self.data.get("encoder") or "libx264"

    def detect_encoders(self) -> list[str]:
        """Test which H.264 encoders actually work and remember the result.
        Returns the working list (best first)."""
        working = test_h264_encoders(self.ffmpeg)
        self.data["available_encoders"] = working
        if self.data.get("encoder") not in working:
            self.data["encoder"] = working[0]
        self.encoder = self.data["encoder"]
        self.save()
        return working

    def set_encoder(self, encoder: str) -> None:
        self.data["encoder"] = encoder
        self.encoder = encoder
        self.save()

    def binaries_ok(self) -> tuple[bool, str]:
        missing = []
        if not self.ytdlp:
            missing.append("yt-dlp")
        if not self.ffmpeg:
            missing.append("ffmpeg")
        if not self.ffprobe:
            missing.append("ffprobe")
        if missing:
            return False, "Missing: " + ", ".join(missing)
        return True, (f"yt-dlp ✓  ffmpeg ✓  encoder: {self.encoder}")

    def ctx(self, out_dir: str) -> dict:
        """Build the context dict the pipeline expects."""
        return {
            "ytdlp": self.ytdlp,
            "ffmpeg": self.ffmpeg,
            "ffmpeg_dir": str(Path(self.ffmpeg).parent) if self.ffmpeg else "",
            "ffprobe": self.ffprobe,
            "encoder": self.encoder,
            "out_dir": out_dir,
            "allow_playlist": self.data.get("allow_playlist", False),
        }

    # -- persistence ------------------------------------------------------- #
    def load(self) -> None:
        if SESSION_FILE.exists():
            try:
                self.data.update(json.loads(SESSION_FILE.read_text("utf-8")))
            except Exception:
                pass

    def save(self) -> None:
        try:
            SESSION_FILE.write_text(json.dumps(self.data, indent=2), "utf-8")
        except Exception:
            pass

    def export_to(self, path: str) -> None:
        Path(path).write_text(json.dumps(self.data, indent=2), "utf-8")

    def import_from(self, path: str) -> None:
        self.data.update(json.loads(Path(path).read_text("utf-8")))

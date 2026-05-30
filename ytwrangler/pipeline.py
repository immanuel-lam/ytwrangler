"""Pure (Qt-free) download + convert logic.

Each public function takes callbacks so a GUI can show progress/log without this
module knowing anything about the UI. The same code path is used by both the
batch and single-download tabs.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from .binaries import ENCODER_ARGS

_PERCENT_RE = re.compile(r"\[download\]\s+([\d.]+)%")
_CREATE_NO_WINDOW = 0x08000000  # Windows: don't pop a console window

ProgressCb = Callable[[float, str], None]
LogCb = Callable[[str], None]
CancelCb = Callable[[], bool]


class CancelledError(Exception):
    """Raised when the user stops a running job."""


def _popen_kwargs() -> dict:
    if os.name == "nt":
        return {"creationflags": _CREATE_NO_WINDOW}
    return {}


def _quote(s: str) -> str:
    return f'"{s}"' if " " in s else s


def run_stream(cmd: list[str], on_line: Callable[[str], None],
               should_cancel: CancelCb, on_log: LogCb | None = None) -> int:
    """Run `cmd`, feeding each output line to `on_line`. Honors cancellation."""
    if on_log:
        on_log("$ " + " ".join(_quote(c) for c in cmd))
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, **_popen_kwargs(),
    )
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            if should_cancel():
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                raise CancelledError()
            on_line(line.rstrip("\n"))
    finally:
        if proc.stdout:
            proc.stdout.close()
    return proc.wait()


# --------------------------------------------------------------------------- #
# ffprobe helpers
# --------------------------------------------------------------------------- #

def probe_codecs(ffprobe: str, path: Path) -> tuple[str | None, str | None]:
    """Return (video_codec, audio_codec) for the first stream of each type."""
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries",
             "stream=codec_type,codec_name", "-of", "json", str(path)],
            capture_output=True, text=True, **_popen_kwargs(),
        ).stdout
        data = json.loads(out)
    except Exception:
        return None, None
    v = a = None
    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and v is None:
            v = s.get("codec_name")
        elif s.get("codec_type") == "audio" and a is None:
            a = s.get("codec_name")
    return v, a


def probe_duration(ffprobe: str, path: Path) -> float:
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "json", str(path)],
            capture_output=True, text=True, **_popen_kwargs(),
        ).stdout
        return float(json.loads(out)["format"]["duration"])
    except Exception:
        return 0.0


def fetch_info(ctx: dict, url: str) -> dict:
    """Run `yt-dlp -J` and return {title, duration, formats:[...]}."""
    cmd = [ctx["ytdlp"], "--js-runtimes", "node", "--no-playlist", "-J", url]
    res = subprocess.run(cmd, capture_output=True, text=True, **_popen_kwargs())
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or "yt-dlp failed to fetch info")
    info = json.loads(res.stdout)
    formats = []
    for f in info.get("formats", []):
        formats.append({
            "format_id": f.get("format_id", ""),
            "ext": f.get("ext", ""),
            "resolution": f.get("resolution") or (
                f"{f.get('width')}x{f.get('height')}" if f.get("height") else "audio only"),
            "fps": f.get("fps") or "",
            "vcodec": f.get("vcodec", ""),
            "acodec": f.get("acodec", ""),
            "filesize": f.get("filesize") or f.get("filesize_approx") or 0,
            "note": f.get("format_note", ""),
        })
    return {"title": info.get("title", url), "duration": info.get("duration", 0),
            "formats": formats}


# --------------------------------------------------------------------------- #
# filesystem helpers
# --------------------------------------------------------------------------- #

def _collision_free(out_dir: Path, name: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / name
    if not dest.exists():
        return dest
    stem, suf = Path(name).stem, Path(name).suffix
    i = 1
    while dest.exists():
        dest = out_dir / f"{stem} ({i}){suf}"
        i += 1
    return dest


def _newest_output(tmp: Path) -> Path:
    files = [p for p in tmp.iterdir()
             if p.is_file() and not p.name.endswith(".part")]
    if not files:
        raise RuntimeError("yt-dlp produced no output file")
    return max(files, key=lambda p: p.stat().st_mtime)


# --------------------------------------------------------------------------- #
# core steps
# --------------------------------------------------------------------------- #

def _ytdlp_download(ctx: dict, url: str, fmt: str, extra: list[str], tmp: Path,
                    on_progress: ProgressCb, on_log: LogCb,
                    should_cancel: CancelCb, phase: str) -> None:
    cmd = [ctx["ytdlp"], "--js-runtimes", "node", "--newline",
           "--ffmpeg-location", ctx["ffmpeg_dir"],
           "-o", str(tmp / "%(title)s.%(ext)s")]
    cmd.append("--yes-playlist" if ctx.get("allow_playlist") else "--no-playlist")
    if fmt:
        cmd += ["-f", fmt]
    cmd += extra + [url]

    def handle(line: str) -> None:
        on_log(line)
        m = _PERCENT_RE.search(line)
        if m:
            on_progress(float(m.group(1)), f"{phase} {m.group(1)}%")
        elif line.startswith(("[ExtractAudio]", "[Merger]",
                              "[VideoConvertor]", "[Fixup")):
            # yt-dlp is running ffmpeg internally — download is done but this
            # can take a while, so don't leave the UI stuck at "100%".
            on_progress(100, "Processing (ffmpeg)…")

    on_progress(0, phase)
    rc = run_stream(cmd, handle, should_cancel, on_log)
    if rc != 0:
        raise RuntimeError(f"yt-dlp exited with code {rc}")


def _run_ffmpeg(cmd: list[str], duration: float, phase: str,
                on_progress: ProgressCb, on_log: LogCb,
                should_cancel: CancelCb) -> None:
    def handle(line: str) -> None:
        if line.startswith("out_time_ms="):
            try:
                ms = int(line.split("=", 1)[1])
                if duration > 0:
                    on_progress(min(99.0, ms / 1e6 / duration * 100), phase)
            except ValueError:
                pass
        elif line.startswith("progress=end"):
            on_progress(100, phase)
        elif "=" not in line and line.strip():
            on_log(line)

    on_progress(0, phase)
    rc = run_stream(cmd, handle, should_cancel, on_log)
    if rc != 0:
        raise RuntimeError(f"ffmpeg exited with code {rc}")


def _convert_to_mp4(ctx: dict, src: Path, force_h264: bool,
                    on_progress: ProgressCb, on_log: LogCb,
                    should_cancel: CancelCb) -> Path:
    vcodec, acodec = probe_codecs(ctx["ffprobe"], src)
    duration = probe_duration(ctx["ffprobe"], src)
    need_reencode = force_h264 or vcodec not in ("h264", "avc1")
    dest = _collision_free(Path(ctx["out_dir"]), src.stem + ".mp4")

    def build(encoder: str) -> list[str]:
        args = [ctx["ffmpeg"], "-hide_banner", "-loglevel", "error", "-nostats",
                "-progress", "pipe:1", "-y", "-i", str(src)]
        if need_reencode:
            args += ["-c:v", encoder] + ENCODER_ARGS.get(
                encoder, ENCODER_ARGS["libx264"])
        else:
            args += ["-c:v", "copy"]
        if acodec is None:
            args += ["-an"]                      # video-only source: no audio
        elif acodec == "aac":
            args += ["-c:a", "copy"]
        else:
            # MP4 + Opus is the bug we hit earlier; always normalize to AAC.
            args += ["-c:a", "aac", "-b:a", "192k"]
        args += ["-movflags", "+faststart", str(dest)]
        return args

    if not need_reencode:
        # Remux/copy is I/O-cheap, so let these run in parallel (no lock).
        on_log("Video is already H.264 — copying stream (instant)")
        _run_ffmpeg(build(ctx["encoder"]), duration, "Converting",
                    on_progress, on_log, should_cancel)
        on_log(f"Saved {dest}")
        return dest

    # Re-encoding is compute-bound. Serialize it with a shared lock so we never
    # run multiple encodes at once (downloads still run in parallel).
    on_log(f"Re-encoding video ({vcodec} -> h264) with {ctx['encoder']}")
    lock = ctx.get("encode_lock")
    if lock is not None and not lock.acquire(blocking=False):
        on_progress(100, "Waiting for encoder…")
        lock.acquire()  # block until the encoder is free
    try:
        try:
            _run_ffmpeg(build(ctx["encoder"]), duration, "Converting",
                        on_progress, on_log, should_cancel)
        except RuntimeError as e:
            # Hardware encoder can be advertised but fail at runtime (e.g. NVENC
            # on a GeForce 930MX). Fall back to software so the file isn't lost.
            if ctx["encoder"] != "libx264":
                on_log(f"{ctx['encoder']} failed ({e}); retrying with libx264…")
                try:
                    dest.unlink()
                except OSError:
                    pass
                _run_ffmpeg(build("libx264"), duration, "Converting (libx264)",
                            on_progress, on_log, should_cancel)
            else:
                raise
    finally:
        if lock is not None:
            lock.release()
    on_log(f"Saved {dest}")
    return dest


# --------------------------------------------------------------------------- #
# public entry point
# --------------------------------------------------------------------------- #

def process_item(ctx: dict, url: str, mode: str, force_h264: bool = False,
                 fmt: str | None = None, on_progress: ProgressCb | None = None,
                 on_log: LogCb | None = None,
                 should_cancel: CancelCb | None = None) -> list[Path]:
    """Download + convert one URL.

    mode:
      'audio' -> audio only, saved as MP3
      'video' -> video only (no audio track), saved as MP4
      'both'  -> combined video + audio, saved as one MP4
    Returns the list of produced output paths.
    """
    on_progress = on_progress or (lambda p, s: None)
    on_log = on_log or (lambda s: None)
    should_cancel = should_cancel or (lambda: False)

    tmp = Path(tempfile.mkdtemp(prefix="ytw_"))
    produced: list[Path] = []
    try:
        if mode == "audio":
            _ytdlp_download(ctx, url, fmt or "ba/b",
                            ["-x", "--audio-format", "mp3", "--audio-quality", "0"],
                            tmp, on_progress, on_log, should_cancel, "Downloading")
            src = _newest_output(tmp)
            dest = _collision_free(Path(ctx["out_dir"]), src.name)
            shutil.move(str(src), str(dest))
            on_log(f"Saved {dest}")
            produced.append(dest)
        else:
            # 'video' = video-only stream; 'both' = video + audio merged.
            default_fmt = "bv*" if mode == "video" else "bv*+ba/b"
            _ytdlp_download(ctx, url, fmt or default_fmt,
                            ["--merge-output-format", "mkv"],
                            tmp, on_progress, on_log, should_cancel, "Downloading")
            src = _newest_output(tmp)
            produced.append(
                _convert_to_mp4(ctx, src, force_h264, on_progress, on_log,
                                should_cancel))
        on_progress(100, "Done")
        return produced
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

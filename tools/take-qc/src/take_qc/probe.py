"""ffprobe / ffmpeg measurements (stdlib only)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any


class ToolMissing(RuntimeError):
    pass


def _which(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise ToolMissing(f"{name} not found on PATH")
    return path


def tool_version(name: str) -> str | None:
    try:
        out = subprocess.run([_which(name), "-version"], capture_output=True, text=True, check=False).stdout
    except ToolMissing:
        return None
    m = re.match(r"\S+ version (\S+)", out)
    return m.group(1) if m else None


@dataclass
class Probe:
    duration_s: float | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    frames: int | None = None
    has_audio: bool = False
    audio_codec: str | None = None
    audio_sample_rate: int | None = None
    mean_volume_db: float | None = None
    max_volume_db: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "duration_s": self.duration_s,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "frames": self.frames,
            "has_audio": self.has_audio,
            "audio_codec": self.audio_codec,
            "audio_sample_rate": self.audio_sample_rate,
            "mean_volume_db": self.mean_volume_db,
            "max_volume_db": self.max_volume_db,
        }


def _rate(value: str | None) -> float | None:
    if not value or value in ("0/0", "0"):
        return None
    try:
        return float(Fraction(value))
    except (ValueError, ZeroDivisionError):
        return None


def parse_ffprobe(data: dict[str, Any]) -> Probe:
    """Turn ``ffprobe -show_streams -show_format -of json`` output into a Probe."""
    probe = Probe()
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video:
        probe.width = video.get("width")
        probe.height = video.get("height")
        probe.fps = _rate(video.get("avg_frame_rate")) or _rate(video.get("r_frame_rate"))
        nb = video.get("nb_frames") or video.get("nb_read_frames")
        if nb not in (None, "N/A"):
            probe.frames = int(nb)
        if video.get("duration") not in (None, "N/A"):
            probe.duration_s = float(video["duration"])
    if probe.duration_s is None:
        fmt_dur = data.get("format", {}).get("duration")
        if fmt_dur not in (None, "N/A"):
            probe.duration_s = float(fmt_dur)
    if probe.frames is None and probe.duration_s and probe.fps:
        probe.frames = round(probe.duration_s * probe.fps)
    if audio:
        probe.has_audio = True
        probe.audio_codec = audio.get("codec_name")
        sr = audio.get("sample_rate")
        probe.audio_sample_rate = int(sr) if sr not in (None, "N/A") else None
    if probe.duration_s is not None:
        probe.duration_s = round(probe.duration_s, 3)
    if probe.fps is not None:
        probe.fps = round(probe.fps, 3)
    return probe


_VOL_RE = re.compile(r"(mean|max)_volume:\s*(-?[\d.]+|-inf) dB")


def parse_volumedetect(stderr: str) -> tuple[float | None, float | None]:
    found: dict[str, float] = {}
    for kind, value in _VOL_RE.findall(stderr):
        found[kind] = float("-inf") if value == "-inf" else float(value)
    return found.get("mean"), found.get("max")


def probe_video(path: str) -> Probe:
    cmd = [_which("ffprobe"), "-v", "error", "-show_streams", "-show_format", "-of", "json", path]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    probe = parse_ffprobe(json.loads(out))
    if probe.has_audio:
        cmd = [
            _which("ffmpeg"),
            "-hide_banner",
            "-nostats",
            "-i",
            path,
            "-vn",
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        ]
        err = subprocess.run(cmd, capture_output=True, text=True, check=False).stderr
        probe.mean_volume_db, probe.max_volume_db = parse_volumedetect(err)
    return probe

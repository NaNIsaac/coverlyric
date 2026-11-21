"""ffmpeg comes from the imageio-ffmpeg package, so the user installs nothing by hand."""

from __future__ import annotations

import ctypes
import os
import re
import subprocess
import sys
from functools import lru_cache


@lru_cache(maxsize=1)
def ffmpeg() -> str:
    if exe := os.environ.get("COVERLYRIC_FFMPEG"):
        return exe
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def quiet() -> dict:
    """Popen arguments that keep a child from opening a console window on Windows."""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def below_normal() -> dict:
    """Popen arguments for a child that yields to the user's other programs."""
    if sys.platform == "win32":
        return {
            "creationflags": subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS
        }
    return {"preexec_fn": lambda: os.nice(5)}


# Each encoder at about the look of libx264 at crf 18. The hardware ones leave the CPU to the frames.
ENCODERS = {
    "h264_nvenc": ["-preset", "p5", "-tune", "hq", "-rc", "vbr", "-cq", "19", "-b:v", "0"],
    "h264_qsv": ["-preset", "medium", "-global_quality", "19"],
    "h264_amf": ["-quality", "quality", "-rc", "cqp", "-qp_i", "18", "-qp_p", "20"],
    "libx264": ["-preset", "veryfast", "-crf", "18", "-threads", "2"],
}


def works(name: str) -> bool:
    """Whether ffmpeg can encode with `name` on this PC: a hardware encoder is listed in every build
    but needs the graphics card and its driver."""
    run = subprocess.run(
        [
            ffmpeg(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=size=640x360:rate=30:duration=0.2",
            "-c:v",
            name,
            *ENCODERS[name],
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        check=False,
        timeout=60,
        **quiet(),
    )
    return run.returncode == 0


@lru_cache(maxsize=1)
def encoder() -> str:
    """The first hardware H.264 encoder that works here, else libx264; COVERLYRIC_ENCODER picks one."""
    if (given := os.environ.get("COVERLYRIC_ENCODER")) in ENCODERS:
        return given
    for name in ("h264_nvenc", "h264_qsv", "h264_amf"):
        try:
            if works(name):
                return name
        except subprocess.TimeoutExpired:
            continue
    return "libx264"


def banner(path: str) -> str:
    run = subprocess.run(
        [ffmpeg(), "-hide_banner", "-i", path],
        capture_output=True,
        check=False,  # ffmpeg exits 1 when given no output; the banner is all we need
        text=True,
        encoding="utf-8",
        errors="replace",
        **quiet(),
    )
    return run.stderr


def recording(path: str) -> float | None:
    """For a file with a moving picture and sound, such as a phone's screen recording, the seconds
    its sound starts after its picture; None for a sound file (a cover picture in it does not
    count)."""
    text = banner(path)
    moving = [row for row in text.splitlines() if " Video: " in row and "attached pic" not in row]
    sound = next((row for row in text.splitlines() if " Audio: " in row), None)
    if not moving or sound is None:
        return None
    m = re.search(r"start (-?\d+(?:\.\d+)?)", sound)
    return float(m[1]) if m else 0.0


def sound_only(source: str, target: str) -> None:
    """The first sound stream of `source` alone, from its own first sample, as FLAC."""
    run = subprocess.run(
        [
            ffmpeg(),
            "-v",
            "error",
            "-y",
            "-i",
            source,
            "-map",
            "0:a:0",
            "-vn",
            "-c:a",
            "flac",
            target,
        ],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
        **quiet(),
    )
    if run.returncode:
        raise ValueError(f"could not take the sound out of {source}: {run.stderr.strip()[-300:]}")


def duration(path: str) -> float:
    """Length of an audio file in seconds, read from ffmpeg's banner (imageio-ffmpeg ships no ffprobe)."""
    if m := re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", banner(path)):
        return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
    raise ValueError(f"not an audio file ffmpeg can read: {path}")


def samples(
    path: str, rate: int, channels: int = 1, start: float = 0.0, length: float | None = None
):
    """The audio as float32 samples, shape (frames, channels), from `start` for `length` seconds."""
    import numpy as np

    cut = ["-ss", f"{max(0.0, start):.3f}"] + (["-t", f"{length:.3f}"] if length else [])
    run = subprocess.run(
        [ffmpeg(), "-v", "error", *cut, "-i", path, "-f", "f32le", "-acodec", "pcm_f32le"]
        + ["-ac", str(channels), "-ar", str(rate), "-"],
        capture_output=True,
        check=False,
        **quiet(),
    )
    if run.returncode or not run.stdout:
        raise ValueError(f"not an audio file ffmpeg can read: {path}")
    return np.frombuffer(run.stdout, np.float32).reshape(-1, channels)


class _Status(ctypes.Structure):
    _fields_ = [
        ("length", ctypes.c_ulong),
        ("load", ctypes.c_ulong),
        ("total", ctypes.c_ulonglong),
        ("available", ctypes.c_ulonglong),
        ("commit_total", ctypes.c_ulonglong),
        ("commit_available", ctypes.c_ulonglong),
        ("rest", ctypes.c_ulonglong * 3),
    ]


def _status() -> _Status | None:
    status = _Status(length=ctypes.sizeof(_Status))
    return status if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)) else None


def commit_mb() -> float | None:
    """On Windows, the memory that can still be committed (physical memory plus paging file) in MB.
    Shared memory blocks are backed by the paging file and count against this, so a PC with free
    RAM but a small paging file runs out here first (#12). None elsewhere or when it cannot be read."""
    if sys.platform != "win32":
        return None
    status = _status()
    return status.commit_available / 2**20 if status else None


def memory_mb() -> tuple[float, float]:
    """Installed and currently available memory in MB, or (0.0, 0.0) when they cannot be read."""
    if sys.platform == "win32":
        status = _status()
        return (status.total / 2**20, status.available / 2**20) if status else (0.0, 0.0)
    try:
        page = os.sysconf("SC_PAGE_SIZE")
        return (
            page * os.sysconf("SC_PHYS_PAGES") / 2**20,
            page * os.sysconf("SC_AVPHYS_PAGES") / 2**20,
        )
    except (ValueError, OSError, AttributeError):
        return 0.0, 0.0

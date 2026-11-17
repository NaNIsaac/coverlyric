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


def duration(path: str) -> float:
    """Length of an audio file in seconds, read from ffmpeg's banner (imageio-ffmpeg ships no ffprobe)."""
    run = subprocess.run(
        [ffmpeg(), "-hide_banner", "-i", path],
        capture_output=True,
        check=False,  # ffmpeg exits 1 when given no output; the banner is all we need
        text=True,
        encoding="utf-8",
        errors="replace",
        **quiet(),
    )
    if m := re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", run.stderr):
        return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
    raise ValueError(f"not an audio file ffmpeg can read: {path}")


def memory_mb() -> tuple[float, float]:
    """Installed and currently available memory in MB, or (0.0, 0.0) when they cannot be read."""
    if sys.platform == "win32":

        class Status(ctypes.Structure):
            _fields_ = [
                ("length", ctypes.c_ulong),
                ("load", ctypes.c_ulong),
                ("total", ctypes.c_ulonglong),
                ("available", ctypes.c_ulonglong),
                ("rest", ctypes.c_ulonglong * 5),
            ]

        status = Status(length=ctypes.sizeof(Status))
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return status.total / 2**20, status.available / 2**20
        return 0.0, 0.0
    try:
        page = os.sysconf("SC_PAGE_SIZE")
        return (
            page * os.sysconf("SC_PHYS_PAGES") / 2**20,
            page * os.sysconf("SC_AVPHYS_PAGES") / 2**20,
        )
    except (ValueError, OSError, AttributeError):
        return 0.0, 0.0

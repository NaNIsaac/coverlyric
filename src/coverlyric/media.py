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


def memory_gb() -> float:
    """Installed memory in GB, or 0.0 when it cannot be read."""
    if sys.platform == "win32":

        class Status(ctypes.Structure):
            _fields_ = [
                ("length", ctypes.c_ulong),
                ("load", ctypes.c_ulong),
                ("total", ctypes.c_ulonglong),
                ("rest", ctypes.c_ulonglong * 6),
            ]

        status = Status(length=ctypes.sizeof(Status))
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return status.total / 2**30
        return 0.0
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30
    except (ValueError, OSError, AttributeError):
        return 0.0

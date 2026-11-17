"""The moving picture: a GIF or a list of images that loops for the whole video, placed like the album.

The frames are decoded and scaled to their placed size once. A render puts them in memory the workers
share, so a song with four workers still holds one copy.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass
from functools import lru_cache
from multiprocessing import shared_memory
from pathlib import Path

from PIL import Image, ImageSequence

SIDE = 360  # px: the longer side of the picture at scale 1
CENTRE = (960, 860)  # px: where the picture sits at offset 0, between the album and the lyrics
MAX_FRAMES = 120
MAX_MB = 96  # all frames together; a bigger picture keeps fewer of them, spread over the same loop
GIF_DELAY = 0.1  # s: what browsers show for a GIF frame without a usable delay
SUFFIXES = {".gif", ".png", ".jpg", ".jpeg", ".webp"}


@dataclass(frozen=True)
class Timing:
    """The size every frame is scaled to, and when each frame ends within one loop (seconds)."""

    size: tuple[int, int]
    ends: tuple[float, ...]

    def index(self, t: float) -> int:
        return bisect.bisect_right(self.ends, t % self.ends[-1]) % len(self.ends)

    def nbytes(self) -> int:
        return self.size[0] * self.size[1] * 4 * len(self.ends)


def decode(paths: tuple[str, ...], fps: float) -> tuple[list[Image.Image], list[float]]:
    """The frames as RGBA and how long each shows. One GIF keeps its own delays; several images
    show in the given order, each for 1/fps."""
    if len(paths) == 1 and Path(paths[0]).suffix.lower() == ".gif":
        frames, delays = [], []
        with Image.open(paths[0]) as gif:
            for f in ImageSequence.Iterator(gif):
                frames.append(f.convert("RGBA"))
                ms = f.info.get("duration") or 0
                delays.append(ms / 1000 if ms >= 20 else GIF_DELAY)
        return frames, delays
    frames = []
    for path in paths:
        with Image.open(path) as img:
            frames.append(img.convert("RGBA"))
    return frames, [1 / max(fps, 0.1)] * len(frames)


def fitted(first: tuple[int, int], scale: float) -> tuple[int, int]:
    side = max(1, round(SIDE * scale))
    k = side / max(first)
    return max(1, round(first[0] * k)), max(1, round(first[1] * k))


def thin(count: int, size: tuple[int, int]) -> int:
    """Keep every k-th frame so the frames fit MAX_FRAMES and MAX_MB."""
    fit = max(1, min(MAX_FRAMES, MAX_MB * 2**20 // (size[0] * size[1] * 4)))
    return math.ceil(count / fit)


@lru_cache(maxsize=2)
def frames(
    paths: tuple[str, ...], stamps: tuple[float, ...], fps: float, scale: float
) -> tuple[Timing, tuple[Image.Image, ...]] | None:
    """The scaled frames and their timing; `stamps` are the files' times, so a replaced file is read
    again. Cached and shared: callers must not draw on the frames."""
    if not paths:
        return None
    decoded, delays = decode(paths, fps)
    size = fitted(decoded[0].size, scale)
    step = thin(len(decoded), size)
    kept, ends, now = [], [], 0.0
    for i in range(0, len(decoded), step):
        now += sum(delays[i : i + step])
        kept.append(decoded[i].resize(size, Image.LANCZOS))
        ends.append(round(now, 6))  # sums of delays like 0.1 + 0.2 must end the loop exactly
    return Timing(size, tuple(ends)), tuple(kept)


def stamps(paths: tuple[str, ...]) -> tuple[float, ...]:
    out = []
    for path in paths:
        try:
            out.append(Path(path).stat().st_mtime)
        except OSError:
            out.append(0.0)
    return tuple(out)


def at(paths: tuple[str, ...], fps: float, scale: float):
    return frames(paths, stamps(paths), fps, scale)


def box(size: tuple[int, int], dx: int, dy: int) -> tuple[int, int, int, int]:
    x0, y0 = CENTRE[0] + dx - size[0] // 2, CENTRE[1] + dy - size[1] // 2
    return x0, y0, x0 + size[0], y0 + size[1]


def share(timing: Timing, pictures: tuple[Image.Image, ...]) -> shared_memory.SharedMemory:
    """The frames in one block of shared memory, in order; the caller closes and unlinks it."""
    entry = timing.size[0] * timing.size[1] * 4
    memory = shared_memory.SharedMemory(create=True, size=entry * len(pictures))
    for k, picture in enumerate(pictures):
        memory.buf[k * entry : (k + 1) * entry] = picture.tobytes()
    return memory


class Shared:
    """A worker's view of the shared frames, keeping the last frame it read."""

    def __init__(self, name: str, timing: Timing):
        self.memory = shared_memory.SharedMemory(name=name)
        self.timing = timing
        self.entry = timing.size[0] * timing.size[1] * 4
        self.last: tuple[int, Image.Image | None] = (-1, None)

    def __getitem__(self, k: int) -> Image.Image:
        if self.last[0] != k:
            with self.memory.buf[k * self.entry : (k + 1) * self.entry] as view:
                self.last = (k, Image.frombytes("RGBA", self.timing.size, view))
        return self.last[1]

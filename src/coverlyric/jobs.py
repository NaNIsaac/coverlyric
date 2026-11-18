"""What the page's render job and the command line share: how many workers, where the finished
video goes, and the files written beside it."""

from __future__ import annotations

import os
from pathlib import Path

from PIL import Image

from . import media, render, timing
from .project import Project

BASE_MB = 250  # kept free; encoder and main process measured about 320 MB with one worker
WORKER_MB = 150  # each extra worker measured about 120 MB in a 60 s 1080p render (issue #3)
# Under this much free memory at most two workers: the render is bound by the encoder, and on a
# 16 GB PC a 60 s part took 65.6 s with two workers at 993 MB against 62.6 s with four at 1831 MB.
LOW_MB, LOW_WORKERS = 2048, 2
# For any failure memory could cause; the raw system text stays in coverlyric.log (#12).
MEMORY_ERROR = "메모리가 부족해 영상을 만들지 못했습니다. 다른 프로그램을 닫고 다시 만듭니다."


def workers() -> int:
    """Render processes: one core is left for the encoder and the page, and the memory available
    when the render starts must hold the encoder plus every worker. That is free physical memory,
    or on Windows the commit still available when it is less (#12). Under LOW_MB there are at most
    two, and with less than the encoder needs, one."""
    try:
        given = int(os.environ.get("COVERLYRIC_WORKERS") or 0)
    except ValueError:
        given = 0  # not a number: decide from this PC rather than fail every render
    if given > 0:
        return min(8, given)
    _, available = media.memory_mb()
    if (commit := media.commit_mb()) is not None:
        available = min(available, commit) if available else commit
    by_memory = int((available - BASE_MB) // WORKER_MB) if available else 6
    if available and available < LOW_MB:
        by_memory = min(by_memory, LOW_WORKERS)
    return max(1, min(6, (os.cpu_count() or 2) - 1, by_memory))


def failure(e: BaseException) -> str:
    """One line for the page: what failed and what to do."""
    if render.out_of_memory(e):
        return MEMORY_ERROR
    return str(e) or type(e).__name__


def place(part: Path, out: Path) -> Path:
    """Move the finished part file to `out`, or to `out (2)` and on when a player holds the old
    video open, which on Windows blocks replacing it."""
    for n in range(1, 100):
        target = out if n == 1 else out.with_name(f"{out.stem} ({n}){out.suffix}")
        try:
            part.replace(target)
        except PermissionError:
            continue
        return target
    raise PermissionError(
        f"{out.name} 파일을 쓸 수 없습니다. 영상을 연 프로그램을 닫고 다시 만듭니다."
    )


def beside(
    out: Path, project: Project, lines: tuple[tuple[float, str], ...], song: render.Song
) -> None:
    """The thumbnail and the timing files next to a finished video."""
    first = next((t for t, text in lines if text), 0.0)
    still = render.frame(min(song.duration, first + 0.6), lines, song, project.style)
    still.resize((1280, 720), Image.LANCZOS).save(out.with_suffix(".png"))
    # The timing files go with the video, so they are on its clock, after the silence before the song.
    timed, video = render.padded(tuple(project.lines), song, project.style)
    out.with_suffix(".lrc").write_text(
        timing.to_lrc(list(timed), project.title, project.artist), encoding="utf-8"
    )
    out.with_suffix(".srt").write_text(timing.to_srt(list(timed), video.duration), encoding="utf-8")

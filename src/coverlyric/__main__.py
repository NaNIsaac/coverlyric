"""Command line: `coverlyric` opens the page; `render` and `still` work from a project file for scripts
and tests."""

from __future__ import annotations

import argparse
import gc
import json
import os
import sys
import traceback
from pathlib import Path

from PIL import Image

from . import __version__, media, render, timing
from .project import Project

BASE_MB = 250  # kept free; encoder and main process measured about 320 MB with one worker
WORKER_MB = 150  # each extra worker measured about 120 MB in a 60 s 1080p render (issue #3)
# Under this much free memory at most two workers: the render is bound by the encoder, and on a
# 16 GB PC a 60 s part took 65.6 s with two workers at 993 MB against 62.6 s with four at 1831 MB.
LOW_MB, LOW_WORKERS = 2048, 2
# For any failure memory could cause; the raw system text stays in coverlyric.log (#12).
MEMORY_ERROR = "메모리가 부족해 영상을 만들지 못했습니다. 다른 프로그램을 닫고 다시 만들어 보세요."


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
        f"{out.name} 파일을 쓸 수 없습니다. 영상을 연 프로그램을 닫고 다시 만드세요."
    )


def run_job(path: Path) -> None:
    """Called by the page in a child process: render the job, print progress lines, write the thumbnail
    and the timing files next to the video."""
    data = json.loads(path.read_text(encoding="utf-8"))
    project = Project.from_dict(path.parent, data)
    out = Path(data["out"])
    song = project.song()
    part = out.with_name(out.stem + ".making.mp4")

    def report(done: float, total: float, frames: int, frames_total: int, left: float | None):
        # The page reads the first two numbers; frames and seconds left (-1: not known yet) follow.
        left_s = -1 if left is None else round(left)
        print(f"progress {done:.1f} {total:.1f} {frames} {frames_total} {left_s}", flush=True)

    def say(text: str) -> None:
        print(f"memory {text}", flush=True)

    count = workers()
    total, available = media.memory_mb()
    commit = media.commit_mb()
    print(
        f"start workers {count} memory {available:.0f} of {total:.0f} MB free"
        + (f", commit {commit:.0f} MB" if commit is not None else "")
        + ", "
        f"song {song.duration:.1f} s, out {out.name}",
        flush=True,
    )
    clip = data.get("clip")
    # A clip is a short look from the page: the preview's lines, small and quick, nothing beside it.
    lines = project.preview_lines() if clip else tuple(timing.ready(project.lines))
    try:
        if clip:
            notice = render.render(
                part, lines, song, project.style, count, tuple(clip), report, True, say
            )
        else:
            notice = render.render(part, lines, song, project.style, count, report=report, note=say)
        out = place(part, out)
    finally:
        part.unlink(missing_ok=True)
    if notice:
        print(f"notice {notice}", flush=True)
    print(f"out {out}", flush=True)
    if clip:
        return
    first = next((t for t, text in lines if text), 0.0)
    still = render.frame(min(song.duration, first + 0.6), lines, song, project.style)
    still.resize((1280, 720), Image.LANCZOS).save(out.with_suffix(".png"))
    out.with_suffix(".lrc").write_text(
        timing.to_lrc(project.lines, project.title, project.artist), encoding="utf-8"
    )
    out.with_suffix(".srt").write_text(
        timing.to_srt(project.lines, song.duration), encoding="utf-8"
    )


def run_auto(path: Path) -> None:
    """Called by the page in a child process: listen to the song, place the lyrics, write the result
    next to the job file and print progress lines."""
    from . import auto

    data = json.loads(path.read_text(encoding="utf-8"))

    def report(phase: str, done: float, total: float) -> None:
        print(f"phase {phase} {done:.1f} {total:.1f}", flush=True)

    def heard(words: list[dict], until: float) -> None:
        print(f"lines {json.dumps(auto.found(data['lyrics'], words, until))}", flush=True)

    name = data["model"]
    while True:
        try:
            words = auto.transcribe(data["audio"], name, report=report, heard=heard)
            break
        except (MemoryError, RuntimeError) as e:
            if not auto.out_of_memory(e):
                raise
            gc.collect()  # let the model that failed go before a smaller one loads
            name = auto.SMALLER.get(name)
            if name is None:
                print("error memory", flush=True)
                raise SystemExit(auto.NO_MEMORY_EXIT) from e
            print(f"smaller {name}", flush=True)
    report("align", 0.0, 0.0)
    lines, notes = auto.align(data["lyrics"], words)
    result = {"lines": [list(line) for line in lines], "notes": notes, "heard": len(words)}
    path.with_name("auto-result.json").write_text(
        json.dumps(result, ensure_ascii=False), encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="coverlyric", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command")
    app = sub.add_parser("app", help="open the page in the browser (the default)")
    app.add_argument("--home", type=Path, help="folder for work and finished videos")
    app.add_argument("--port", type=int, default=0)
    app.add_argument("--no-browser", action="store_true")
    r = sub.add_parser("render", help="render a project file to an mp4")
    r.add_argument("project", type=Path)
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--clip", help="start,end in seconds")
    s = sub.add_parser("still", help="one frame of a project file as a PNG")
    s.add_argument("project", type=Path)
    s.add_argument("--at", type=float, default=0.0, help="time in seconds")
    s.add_argument("--out", type=Path, required=True)
    job = sub.add_parser("render-job")
    job.add_argument("job", type=Path)
    auto_job = sub.add_parser("auto-job")
    auto_job.add_argument("job", type=Path)
    args = parser.parse_args(argv)
    # A pipe or file gets the locale code page on Windows (cp1252 on many PCs), which cannot
    # write Korean; the page reads the job pipes as UTF-8.
    for stream in (sys.stdout, sys.stderr):
        if not stream.isatty():
            stream.reconfigure(encoding="utf-8", errors="replace")

    if args.command in (None, "app"):
        from .server import serve

        home = getattr(args, "home", None) or Path(os.environ.get("COVERLYRIC_HOME") or Path.cwd())
        browser = not getattr(args, "no_browser", False) and not os.environ.get(
            "COVERLYRIC_NO_BROWSER"
        )
        serve(home.resolve(), getattr(args, "port", 0), browser)
    elif args.command == "render":
        project = Project.load(args.project)
        span = tuple(float(x) for x in args.clip.split(",")) if args.clip else None
        render.render(
            args.out,
            tuple(timing.ready(project.lines)),
            project.song(),
            project.style,
            workers(),
            span,
            report=lambda done, total, *_: print(f"{done:6.1f}s of {total:.1f}s", flush=True),
        )
    elif args.command == "still":
        project = Project.load(args.project)
        render.frame(args.at, project.preview_lines(), project.song(), project.style).save(args.out)
    elif args.command == "auto-job":
        try:
            run_auto(args.job)
        except Exception as e:  # noqa: BLE001 - any failure is shown to the user on the page
            print(f"error: {e}", flush=True)
            sys.exit(1)
    elif args.command == "render-job":
        try:
            run_job(args.job)
        except Exception as e:  # noqa: BLE001 - any failure is shown to the user on the page
            print(traceback.format_exc(), flush=True)
            print(f"error: {failure(e)}", flush=True)
            sys.exit(1)


if __name__ == "__main__":
    main()

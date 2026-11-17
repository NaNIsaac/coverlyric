"""Command line: `coverlyric` opens the page; `render` and `still` work from a project file for scripts
and tests."""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

from PIL import Image

from . import __version__, media, render, timing
from .project import Project

BASE_MB = 500  # the encoder and the main render process, measured about 450 MB at 1080p
WORKER_MB = 300  # one worker with its chunks in flight, measured 130 to 210 MB
WORKER_ERROR = (
    "작업 프로세스가 비정상 종료되었습니다. 대부분 메모리 부족이 원인입니다. "
    "다른 프로그램을 닫고 다시 만드세요."
)


def workers() -> int:
    """Render processes: one core is left for the encoder and the page, and the memory available
    when the render starts must hold the encoder plus every worker. A PC with little free memory
    gets one worker."""
    if given := os.environ.get("COVERLYRIC_WORKERS"):
        return max(1, int(given))
    _, available = media.memory_mb()
    by_memory = int((available - BASE_MB) // WORKER_MB) if available else 6
    return max(1, min(6, (os.cpu_count() or 2) - 1, by_memory))


def failure(e: BaseException) -> str:
    """One line for the page: what failed and what to do."""
    if isinstance(e, BrokenProcessPool | MemoryError):
        return WORKER_ERROR
    return str(e) or type(e).__name__


def run_job(path: Path) -> None:
    """Called by the page in a child process: render the job, print progress lines, write the thumbnail
    and the timing files next to the video."""
    data = json.loads(path.read_text(encoding="utf-8"))
    project = Project.from_dict(path.parent, data)
    out = Path(data["out"])
    song = project.song()
    lines = tuple(timing.ready(project.lines))
    part = out.with_name(out.stem + ".making.mp4")

    def report(done: float, total: float) -> None:
        print(f"progress {done:.1f} {total:.1f}", flush=True)

    count = workers()
    total, available = media.memory_mb()
    print(
        f"start workers {count} memory {available:.0f} of {total:.0f} MB free, "
        f"song {song.duration:.1f} s, out {out.name}",
        flush=True,
    )
    render.render(part, lines, song, project.style, count, report=report)
    part.replace(out)
    first = next((t for t, text in lines if text), 0.0)
    still = render.frame(min(song.duration, first + 0.6), lines, song, project.style)
    still.resize((1280, 720), Image.LANCZOS).save(out.with_suffix(".png"))
    out.with_suffix(".lrc").write_text(
        timing.to_lrc(project.lines, project.title, project.artist), encoding="utf-8"
    )
    out.with_suffix(".srt").write_text(
        timing.to_srt(project.lines, song.duration), encoding="utf-8"
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
            report=lambda done, total: print(f"{done:6.1f}s of {total:.1f}s", flush=True),
        )
    elif args.command == "still":
        project = Project.load(args.project)
        render.frame(args.at, project.preview_lines(), project.song(), project.style).save(args.out)
    elif args.command == "render-job":
        try:
            run_job(args.job)
        except Exception as e:  # noqa: BLE001 - any failure is shown to the user on the page
            print(traceback.format_exc(), flush=True)
            print(f"error: {failure(e)}", flush=True)
            sys.exit(1)


if __name__ == "__main__":
    main()

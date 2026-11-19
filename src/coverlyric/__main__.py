"""Command line: `coverlyric` opens the page; `make`, `project`, `auto`, `words`, `render` and `still`
(in cli.py) work on project folders for people and agents; `render-job`, `auto-job` and
`pick-folder` are the page's child processes."""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path

from . import __version__, cli, media, render, timing
from .jobs import beside, failure, place, workers
from .project import Project


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
    beside(out, project, lines, song)


def run_auto(path: Path) -> None:
    """Called by the page in a child process: listen to the song, place the lyrics, write the result
    next to the job file and print progress lines."""
    from . import auto

    data = json.loads(path.read_text(encoding="utf-8"))

    def report(phase: str, done: float, total: float) -> None:
        print(f"phase {phase} {done:.1f} {total:.1f}", flush=True)

    def heard(words: list[dict], until: float) -> None:
        print(f"lines {json.dumps(auto.found(data['lyrics'], words, until))}", flush=True)

    def smaller(name: str) -> None:
        print(f"smaller {name}", flush=True)

    try:
        words, _ = auto.listen(data["audio"], data["model"], report, heard, smaller)
    except auto.NoMemory as e:
        print("error memory", flush=True)
        raise SystemExit(auto.NO_MEMORY_EXIT) from e
    report("align", 0.0, 0.0)
    lines, notes = auto.align(data["lyrics"], words)
    result = {"lines": [list(line) for line in lines], "notes": notes, "heard": len(words)}
    path.with_name("auto-result.json").write_text(
        json.dumps(result, ensure_ascii=False), encoding="utf-8"
    )


def pick_folder(start: Path) -> str:
    """The folder the user picks in the system's dialog, or "" when cancelled. Called by the page in
    a child process."""
    import tkinter
    from tkinter import filedialog

    root = tkinter.Tk()
    root.withdraw()
    root.attributes("-topmost", True)  # over the browser that asked for it
    try:
        return (
            filedialog.askdirectory(
                parent=root, initialdir=str(start), mustexist=True, title="영상을 저장할 폴더"
            )
            or ""
        )
    finally:
        root.destroy()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="coverlyric", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command")
    app = sub.add_parser("app", help="open the page in the browser (the default)")
    app.add_argument("--home", type=Path, help="folder for work and finished videos")
    app.add_argument("--port", type=int, default=0)
    app.add_argument("--no-browser", action="store_true")
    cli.add_commands(sub)
    job = sub.add_parser("render-job")
    job.add_argument("job", type=Path)
    auto_job = sub.add_parser("auto-job")
    auto_job.add_argument("job", type=Path)
    pick = sub.add_parser("pick-folder")
    pick.add_argument("start", type=Path)
    # A pipe, a file or an old console gets the locale code page on Windows (cp1252 or cp949),
    # which cannot write every Korean line; the page reads the job pipes as UTF-8.
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    args = parser.parse_args(argv)

    if args.command in (None, "app"):
        from .server import serve

        home = getattr(args, "home", None) or Path(os.environ.get("COVERLYRIC_HOME") or Path.cwd())
        browser = not getattr(args, "no_browser", False) and not os.environ.get(
            "COVERLYRIC_NO_BROWSER"
        )
        serve(home.resolve(), getattr(args, "port", 0), browser)
    elif args.command in ("render", "still", "project", "auto", "words", "make", "chorus"):
        sys.exit(cli.main(args))
    elif args.command == "auto-job":
        try:
            run_auto(args.job)
        except Exception as e:  # noqa: BLE001 - any failure is shown to the user on the page
            print(f"error: {e}", flush=True)
            sys.exit(1)
    elif args.command == "pick-folder":
        print(pick_folder(args.start), flush=True)
    elif args.command == "render-job":
        try:
            run_job(args.job)
        except Exception as e:  # noqa: BLE001 - any failure is shown to the user on the page
            print(traceback.format_exc(), flush=True)
            print(f"error: {failure(e)}", flush=True)
            sys.exit(1)


if __name__ == "__main__":
    main()

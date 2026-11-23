"""coverlyric mcp: the command line as tools for an AI client, over stdio on this computer only.

Each tool runs one coverlyric command on a project folder and answers what that command answers with
--json. project.json is the only state: nothing is kept between calls, every change is saved at once,
and a page open on the same project takes the change when its window gets the focus back or saves.
stdout carries the protocol, so nothing a tool runs may print there.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

from mcp.server.mcpserver import Context, Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import cli, jobs

server = MCPServer(
    "coverlyric",
    instructions=(
        "Lyric videos from a song, a cover and its lyrics. Every tool takes `project`, the project "
        "folder (or its project.json) on this computer. A song can have several outputs (a wide "
        "video, Shorts); `output` picks one, default the current one (output_list shows which). "
        "Changes are saved at once. Times are seconds (72.4) or m:ss (1:12.4), always on the "
        "song's clock, also for a Short whose part starts later (clip_from). Lines are numbered "
        "from 1, as project_show lists them. To check a change, look at a still first, then a "
        "clip_render of the few seconds around it; run render, which takes about as long as the "
        "video, only when the user asks for the finished video. project_set refuses an unknown key "
        "with the list of keys. open_page shows the project in the browser only when the user asks "
        "for it."
    ),
)


def opt(flag: str, value) -> list[str]:
    return [flag, str(value)] if value not in (None, "") else []


def command(*argv) -> dict:
    """One command line, answered as `coverlyric <argv> --json` answers it, or a ToolError."""
    from .__main__ import build_parser

    try:
        args = build_parser().parse_args([str(a) for a in argv])
    except SystemExit:
        raise ToolError(f"not a valid command: coverlyric {' '.join(map(str, argv))}") from None
    try:
        with contextlib.redirect_stdout(sys.stderr):
            return cli.run(args)
    except cli.Usage as e:
        raise ToolError(str(e)) from None
    except Exception as e:  # noqa: BLE001 - the client gets the sentence the command line prints
        raise ToolError(jobs.failure(e)) from None


def scratch(project: str) -> Path:
    """`.cache/mcp` in the project folder: stills and clips the tools make, safe to delete."""
    folder = cli.project_file(Path(project)).parent / ".cache" / "mcp"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


@server.tool()
def project_show(project: str, output: str | None = None) -> dict:
    """The project: title, artist, files, the look (style keys that differ from the default), the
    outputs and every line with its number, start time in seconds and text."""
    return command("project", "show", project, *opt("--output", output))


@server.tool()
def project_set(project: str, pairs: list[str], output: str | None = None) -> dict:
    """Change keys as key=value: title, artist, album, released, clean_tags, video (a file path;
    empty takes it out), title_image (a picture of dark lettering; empty takes it out) and the look
    keys of the output, e.g. lead=2, fps=30, shape=tall, clip_from=42, clip_to=72. An unknown key
    is refused with the list of keys."""
    return command("project", "set", project, *pairs, *opt("--output", output))


@server.tool()
def lines_get(project: str, first: int | None = None, last: int | None = None) -> dict:
    """Lines `first` to `last` (1-based, both included; default all) with their times."""
    shown = command("project", "show", project)
    lo, hi = first or 1, last or len(shown["lines"])
    return {
        "lines": [row for row in shown["lines"] if lo <= row["n"] <= hi],
        "timed": shown["timed"],
        "count": len(shown["lines"]),
    }


@server.tool()
def lines_set_text(project: str, line: int, text: str) -> dict:
    """Line `line` (1-based) reads `text`; its time stays."""
    return command("project", "lines", project, "--text", f"{line}={text}")


@server.tool()
def lines_set_time(project: str, line: int, time: str) -> dict:
    """Line `line` (1-based) starts at `time`: seconds (72.4) or m:ss (1:12.4); "-" untimes it."""
    return command("project", "lines", project, "--set", f"{line}={time}")


@server.tool()
def lines_shift(project: str, by: str, lines: str | None = None) -> dict:
    """Move timed lines by `by` seconds (e.g. -0.3): every line, or `lines` "N" or "N-M"."""
    return command("project", "lines", project, "--shift", by, *opt("--range", lines))


@server.tool()
def output_list(project: str) -> dict:
    """The outputs (videos made from the song): id, shape, file and which one is current."""
    return command("output", "list", project)


@server.tool()
def output_add(project: str, id: str, source: str | None = None, shape: str | None = None) -> dict:
    """A new output `id` (lowercase letters, digits and -), copied from `source` (default: the
    current output), in `shape`: wide, tall (9:16), square or portrait (4:5)."""
    return command("output", "add", project, id, *opt("--from", source), *opt("--shape", shape))


@server.tool()
def output_use(project: str, id: str) -> dict:
    """Make output `id` the current one."""
    return command("output", "use", project, id)


@server.tool()
def still(project: str, at: str = "0", output: str | None = None) -> Image:
    """One frame of the video at time `at` (seconds or m:ss), as a PNG image."""
    out = scratch(project) / "still.png"
    command("still", project, "--at", at, "--out", out, *opt("--output", output))
    return Image(data=out.read_bytes(), format="png")


@server.tool()
def clip_render(project: str, start: str, end: str, output: str | None = None) -> dict:
    """A quick small video of `start` to `end` (seconds or m:ss), to look at; answers its path."""
    out = scratch(project) / "clip.mp4"
    return command(
        "render",
        project,
        "--clip",
        f"{start},{end}",
        "--quick",
        "--out",
        out,
        *opt("--output", output),
    )


@server.tool()
async def render(project: str, ctx: Context, output: str | None = None) -> dict:
    """The whole video of the output, with its thumbnail and SRT/LRC beside it in the project
    folder; answers their paths. Takes about as long as the song; progress is reported."""
    try:
        loaded, _ = cli.load(Path(project), output)
    except cli.Usage as e:
        raise ToolError(str(e)) from None
    except Exception as e:  # noqa: BLE001
        raise ToolError(jobs.failure(e)) from None
    seen = {"done": 0.0, "total": 0.0}
    stderr = cli.progress("render")

    def report(done: float, total: float, *rest) -> None:
        seen["done"], seen["total"] = done, total
        stderr(done, total, *rest)

    def work() -> dict:
        with contextlib.redirect_stdout(sys.stderr):
            return cli.make_video(loaded, None, None, False, report)

    task = asyncio.create_task(asyncio.to_thread(work))
    while not task.done():
        await asyncio.wait({task}, timeout=1.0)
        if seen["total"]:
            with contextlib.suppress(ValueError):  # no client request to report to (in-process)
                await ctx.report_progress(seen["done"], seen["total"], "render")
    try:
        return task.result()
    except Exception as e:  # noqa: BLE001
        raise ToolError(jobs.failure(e)) from None


def running_page(folder: Path) -> str | None:
    """The address of the page already open on this project folder, if it still answers."""
    try:
        url = json.loads((folder / ".cache" / "page" / "page.json").read_text(encoding="utf-8"))[
            "url"
        ]
        with urllib.request.urlopen(f"{url}api/state", timeout=2) as res:
            state = json.loads(res.read())
    except (OSError, ValueError, KeyError):
        return None
    return url if Path(state.get("folder", "")) == folder else None


@server.tool()
def open_page(project: str) -> dict:
    """Show the project in the browser page, where the user can go on changing it by hand. The page
    already open on this project is shown again; otherwise one is started, on its own, and stays
    after this client ends. Only when the user asks for the page."""
    file = cli.project_file(Path(project))
    if not file.is_file():
        raise ToolError(f"no project at {project} (a folder with project.json, or the file)")
    folder = file.parent.resolve()
    if url := running_page(folder):
        webbrowser.open(url)
        return {"url": url, "started": False}
    page = folder / ".cache" / "page" / "page.json"
    page.unlink(missing_ok=True)
    detached = (
        {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
        if sys.platform == "win32"
        else {"start_new_session": True}
    )
    subprocess.Popen(
        [sys.executable, "-m", "coverlyric", "app", str(folder)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={k: v for k, v in os.environ.items() if k != "COVERLYRIC_NO_BROWSER"},
        **detached,
    )
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if url := running_page(folder):
            return {"url": url, "started": True}
        threading.Event().wait(0.2)
    raise ToolError("the page did not start within 20 s; run `coverlyric app <project>` to see why")


def run_stdio() -> None:
    server.run("stdio")

"""The command line for people and agents: a project is a folder, each fix is one command, and every
command can answer in JSON."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import sys
import time
from dataclasses import fields, replace
from pathlib import Path

from . import auto, jobs, media, render, tall, timing
from .project import Project

NOTE_TEXT = {
    "unplaced": "not found: placed between the lines around it",
    "doubtful": "within 1 s of the line before",
    "differs": "heard differently",
}
CHECK = ("unplaced", "doubtful")  # notes that make --strict exit 4; "differs" only reports
TEXT_KEYS = ("title", "artist", "album", "released")
STYLE_KEYS = tuple(f.name for f in fields(render.Style))
COMMANDS = ("render", "still", "project", "auto", "words", "make", "chorus", "align", "sections")


class Usage(Exception):
    """A command that cannot run as given; exit code 2, like argparse."""


def seconds(text: str) -> float:
    """A time as typed: 72.4, 1:12.4, 1:02:03 or with a sign for a shift (-0.3, +1)."""
    raw = text.strip()
    sign = -1.0 if raw.startswith("-") else 1.0
    parts = raw.lstrip("+-").split(":")
    try:
        if not 1 <= len(parts) <= 3 or any(p == "" for p in parts):
            raise ValueError
        value = sum(float(p) * 60**i for i, p in enumerate(reversed(parts)))
    except ValueError:
        raise Usage(f"not a time: {text!r} (use 72.4 or 1:12.4)") from None
    return sign * value


def clock(t: float | None) -> str:
    if t is None:
        return "-"
    cs = round(t * 100)
    return f"{cs // 6000}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def project_file(path: Path) -> Path:
    return path / "project.json" if path.is_dir() else path


def load(path: Path) -> tuple[Project, Path]:
    file = project_file(path)
    if not file.is_file():
        raise FileNotFoundError(f"no project at {path} (a folder with project.json, or the file)")
    return Project.load(file), file


def copy_in(source: Path, folder: Path, stem: str) -> str:
    """Copy a song or cover into the project folder as stem + its suffix. Files already in the folder
    are never replaced: another file under that name stops the command."""
    if not source.is_file():
        raise FileNotFoundError(f"no file at {source}")
    target = folder / f"{stem}{source.suffix.lower()}"
    if target.exists():
        if target.resolve() == source.resolve():
            return target.name
        raise Usage(f"{target} already exists; use an empty folder for a new project")
    shutil.copyfile(source, target)
    return target.name


def lines_from(path: Path, clean: bool) -> list[timing.Line]:
    found = timing.parse(path.name, path.read_text(encoding="utf-8-sig"), clean)
    if not found:
        raise ValueError(f"no lyric lines in {path}")
    return found


def new_project(
    folder: Path,
    audio: Path,
    cover: Path,
    lyrics: Path | None = None,
    title: str = "",
    artist: str = "",
    clean: bool = True,
) -> Project:
    folder.mkdir(parents=True, exist_ok=True)
    if (folder / "project.json").exists():
        raise FileExistsError(
            f"{folder} already holds a project; change it with 'project set/lines'"
        )
    project = Project(folder, title=title or audio.stem, artist=artist, clean_tags=clean)
    project.audio = copy_in(audio, folder, "song")
    project.art = copy_in(cover, folder, "cover")
    project.duration = media.duration(project.path(project.audio))
    if lyrics:
        project.lines = lines_from(lyrics, clean)
    project.save(folder / "project.json")
    return project


def show(project: Project, file: Path) -> dict:
    notes = {note["n"]: note for note in project.notes}
    default = render.Style().to_dict()
    rows = []
    for n, (t, text) in enumerate(project.lines, 1):
        row = {"n": n, "time": t, "text": text}
        if n in notes:
            row["note"] = notes[n]["kind"]
            if notes[n].get("heard"):
                row["heard"] = notes[n]["heard"]
        rows.append(row)
    return {
        "project": str(file),
        "title": project.title,
        "artist": project.artist,
        "album": project.album,
        "released": project.released,
        "audio": project.path(project.audio),
        "cover": project.path(project.art),
        "video": project.path(project.video),
        "duration": project.duration,
        "clean_tags": project.clean_tags,
        "style": {k: v for k, v in project.style.to_dict().items() if v != default[k]},
        "lines": rows,
        "timed": sum(t is not None for t, _ in project.lines),
        "notes": len(project.notes),
    }


def show_text(data: dict) -> str:
    head = data["title"] + (f" - {data['artist']}" if data["artist"] else "")
    out = [
        (
            f"{head}  ({clock(data['duration'])}, {len(data['lines'])} lines, {data['timed']} timed,"
            f" {data['notes']} to check)"
        )
    ]
    if data["style"]:
        out.append("style: " + ", ".join(f"{k}={v}" for k, v in data["style"].items()))
    for row in data["lines"]:
        note = ""
        if "note" in row:
            note = f"   [{NOTE_TEXT.get(row['note'], row['note'])}"
            note += f": {row['heard']}]" if row.get("heard") else "]"
        out.append(f"{row['n']:3d}  {clock(row['time']):>9}  {row['text']}{note}")
    return "\n".join(out)


def truth(text: str) -> bool:
    lowered = text.strip().lower()
    if lowered in ("1", "true", "yes", "on"):
        return True
    if lowered in ("0", "false", "no", "off"):
        return False
    raise Usage(f"not on or off: {text!r}")


def set_keys(project: Project, pairs: list[str]) -> list[str]:
    """Apply key=value pairs; the keys are TEXT_KEYS, clean_tags, video and the style's own keys."""
    style = project.style.to_dict()
    changed = []
    for pair in pairs:
        key, sep, value = pair.partition("=")
        key = key.strip()
        if not sep:
            raise Usage(f"not key=value: {pair!r}")
        if key in TEXT_KEYS:
            setattr(project, key, value)
        elif key == "clean_tags":
            project.clean_tags = truth(value)
        elif key == "video":
            project.video = put_video(project, value.strip())
        elif key in STYLE_KEYS:
            default = getattr(render.Style, key)
            try:
                style[key] = truth(value) if isinstance(default, bool) else type(default)(value)
            except ValueError:
                raise Usage(f"{key} takes a {type(default).__name__}: {value!r}") from None
        else:
            keys = ", ".join((*TEXT_KEYS, "clean_tags", "video", *STYLE_KEYS))
            raise Usage(f"unknown key {key!r}; keys: {keys}")
        changed.append(key)
    project.style = render.Style.from_dict(style)
    return changed


def put_video(project: Project, value: str) -> str:
    """The project's video after `video=value`: the file copied in as video + its suffix in place
    of the one before, or none for an empty value."""
    from . import overlay

    source = Path(value) if value else None
    if source is not None:
        if not source.is_file():
            raise FileNotFoundError(f"no file at {source}")
        try:
            overlay.length(str(source))
        except ValueError:
            raise Usage(f"not a video ffmpeg can read: {source}") from None
    for old in project.folder.glob("video.*"):
        if source is None or old.resolve() != source.resolve():
            old.unlink()
    return copy_in(source, project.folder, "video") if source is not None else ""


def line_number(project: Project, text: str) -> int:
    try:
        n = int(text)
    except ValueError:
        raise Usage(f"not a line number: {text!r}") from None
    if not 1 <= n <= len(project.lines):
        raise Usage(f"line {n} does not exist; the project has {len(project.lines)} lines")
    return n


def edit_lines(project: Project, args: argparse.Namespace) -> list[str]:
    """The line changes in a fixed order: replace the lines, then move all, then set single lines."""
    done = []
    if args.from_lyrics:
        project.lines = [
            (None, text) for _, text in lines_from(args.from_lyrics, project.clean_tags)
        ]
        project.notes = []
        done.append(f"lines from {args.from_lyrics.name}")
    if args.import_file:
        project.lines = lines_from(args.import_file, project.clean_tags)
        project.notes = []
        done.append(f"times from {args.import_file.name}")
    if args.shift:
        by = seconds(args.shift)
        project.lines = [(None if t is None else max(0.0, t + by), x) for t, x in project.lines]
        done.append(f"shifted {by:+.2f} s")
    for item in args.set or []:
        n, sep, value = item.partition("=")
        if not sep:
            raise Usage(f"--set takes N=TIME: {item!r}")
        k = line_number(project, n)
        t = None if value.strip() in ("", "-") else max(0.0, seconds(value))
        project.lines[k - 1] = (t, project.lines[k - 1][1])
        project.notes = [note for note in project.notes if note["n"] != k]
        done.append(f"line {k} at {clock(t)}")
    for item in args.text or []:
        n, sep, value = item.partition("=")
        if not sep:
            raise Usage(f"--text takes N=TEXT: {item!r}")
        k = line_number(project, n)
        project.lines[k - 1] = (project.lines[k - 1][0], value.strip())
        done.append(f"line {k} text")
    if not done:
        raise Usage("nothing to change: give --shift, --set, --text, --import or --from-lyrics")
    return done


def video_name(project: Project) -> str:
    from .server import video_file

    return video_file(project.title, project.style)


def say(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


def progress(phase: str, unit=clock):
    """A report function that writes a line to stderr every 5 percent."""
    last = [-1]

    def report(done: float, total: float, *_) -> None:
        share = int(done / total * 20) if total else 0
        if share != last[0]:
            last[0] = share
            say(f"{phase} {unit(done)} / {unit(total)} {share * 5}%")

    return report


def listening():
    """The report function for automatic timing: model download in MB, then the song in time."""
    shown = {
        "download": progress("download", lambda mb: f"{mb:.0f} MB"),
        "listen": progress("listen"),
    }

    def report(phase: str, done: float, total: float) -> None:
        if phase in shown:
            shown[phase](done, total)
        else:
            say(phase)

    return report


def hear(audio: str, model: str, clip: tuple[float, float] | None = None) -> tuple[list[dict], str]:
    """Words heard in the song and the model used: the largest from `model` down that fits."""
    if model not in auto.MODELS:
        raise Usage(f"unknown model {model!r}; models: {', '.join(auto.MODELS)}")
    if not importlib.util.find_spec("faster_whisper"):
        raise ValueError(
            "automatic timing needs the 'auto' extra: uv run --extra auto coverlyric ..."
            " or pip install 'coverlyric[auto]'"
        )
    picked = auto.fitting(model, media.commit_mb())
    if picked is None:
        raise auto.NoMemory("not enough free memory for even the smallest listening model")
    if picked != model:
        say(f"smaller {picked}")
    # The public models need no token; the plain download shows progress as the file grows.
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
    return auto.listen(
        audio, picked, listening(), smaller=lambda name: say(f"smaller {name}"), clip=clip
    )


def song_length(path: str) -> float | None:
    """The song's length for automatic timing, or None when ffmpeg cannot tell."""
    try:
        return media.duration(path)
    except (OSError, ValueError):
        return None


def auto_time(project: Project, model: str) -> dict:
    """Time the project's lyrics from its song: the lines get times and the unsure ones a note.
    Returns the model used and the seconds it took; the caller saves."""
    lyrics = [text for _, text in project.lines if text]
    if not lyrics:
        raise ValueError("the project has no lyrics; add them with 'project lines --from-lyrics'")
    started = time.monotonic()
    words, used = hear(project.path(project.audio), model)
    say("align")
    length = project.duration or song_length(project.path(project.audio))
    lines, notes = auto.align(lyrics, words, length)
    number = [n for n, (_, text) in enumerate(lines, 1) if text]
    project.lines = lines
    project.notes = [
        {"n": number[note["line"]], "kind": note["kind"], "heard": note["heard"]} for note in notes
    ]
    return {"model": used, "heard": len(words), "seconds": round(time.monotonic() - started, 1)}


def to_check(project: Project) -> dict:
    """The lines automatic timing was unsure of, by kind."""
    found = {kind: [] for kind in CHECK}
    for note in project.notes:
        if note["kind"] in found:
            t, text = project.lines[note["n"] - 1]
            found[note["kind"]].append({"n": note["n"], "time": t, "text": text})
    return found


def words_in(path: Path, start: float, end: float, model: str) -> dict:
    """Word timestamps for one stretch of a song file or of a project's song."""
    if path.is_dir() or path.suffix == ".json":
        project, _ = load(path)
        path = Path(project.path(project.audio))
    elif not path.is_file():
        raise FileNotFoundError(f"no file at {path}")
    if end <= start:
        raise Usage("--to must be after --from")
    words, used = hear(str(path), model, (start, end))
    inside = [
        {**w, "word": w["word"].strip()} for w in words if start - 0.5 <= w["start"] <= end + 0.5
    ]
    return {"audio": str(path), "from": start, "to": end, "model": used, "words": inside}


def style_from(text: str) -> dict:
    """Style keys from JSON text or a JSON file."""
    path = Path(text)
    try:
        data = json.loads(path.read_text(encoding="utf-8") if path.is_file() else text)
    except json.JSONDecodeError as e:
        raise Usage(f"--style is not JSON: {e}") from None
    if not isinstance(data, dict):
        raise Usage("--style takes a JSON object or a file holding one")
    if unknown := sorted(set(data) - set(STYLE_KEYS)):
        raise Usage(f"unknown style key {unknown[0]!r}; keys: {', '.join(STYLE_KEYS)}")
    return data


def make(args: argparse.Namespace) -> dict:
    """Project, timing, video and timing files together in OUT/<title>/."""
    from .server import safe_name

    style = style_from(args.style) if args.style else {}
    pairs = [
        f"{key}={value}"
        for key in ("lead", "tail", "height", "fps")
        if (value := getattr(args, key)) is not None
    ]
    set_keys(Project(args.out), pairs)  # a wrong value stops before any folder is made
    folder = args.out / safe_name(args.title)
    project = new_project(
        folder,
        args.audio,
        args.cover,
        args.timing or args.lyrics,
        args.title,
        args.artist,
        not args.keep_tags,
    )
    file = folder / "project.json"
    project.style = render.Style.from_dict({**project.style.to_dict(), **style})
    set_keys(project, pairs)
    project.save(file)
    summary = {"folder": str(folder), "project": str(file)}
    took = {}
    if any(t is None for t, _ in project.lines):
        heard = auto_time(project, args.model)
        project.save(file)
        summary["model"] = heard["model"]
        took["auto"] = heard["seconds"]
    made = make_video(project, None)
    took["render"] = made.pop("seconds")
    check = to_check(project)
    sung = sum(1 for _, text in project.lines if text)
    return {
        **made,
        **summary,
        "sung": sung,
        "placed": sung - len(check["unplaced"]),
        **check,
        "seconds": took,
    }


def make_video(
    project: Project,
    out: Path | None,
    clip: tuple[float, float] | None = None,
    quick: bool = False,
) -> dict:
    """Render the project; a whole video gets its thumbnail and timing files beside it."""
    out = out or project.folder / video_name(project)
    out.parent.mkdir(parents=True, exist_ok=True)
    song = project.song()
    lines = project.preview_lines() if clip else tuple(timing.ready(project.lines))
    part = out.with_name(out.stem + ".making.mp4")
    started = time.monotonic()
    try:
        notice = render.render(
            part,
            lines,
            song,
            project.style,
            jobs.workers(),
            clip,
            progress("render"),
            quick,
            note=lambda text: print(f"memory {text}", file=sys.stderr, flush=True),
        )
        out = jobs.place(part, out)
    finally:
        part.unlink(missing_ok=True)
    result = {"video": str(out), "seconds": round(time.monotonic() - started, 1)}
    if notice:
        result["notice"] = notice
    if not clip:
        jobs.beside(out, project, lines, song)
        for kind in ("srt", "lrc", "png"):
            result[kind] = str(out.with_suffix(f".{kind}"))
    return result


def align_letters(project: Project, file: Path, start: str | None, end: str | None) -> dict:
    """Align the letters of the lines starting in the part (an upright project's clip, else the
    whole song, unless --from and --to say) and save them into the project."""
    from . import align

    if why := align.missing():
        raise ValueError(why)
    song = project.song()
    first, last = tall.span(project.style, song) if render.is_upright(project.style) else (0, 0)
    first = seconds(start) if start else first
    last = seconds(end) if end else (last or song.duration)
    found = align.align(song.audio, project.lines, first, last, note=say)
    project.letters = align.merged(project.letters, found)
    project.save(file)
    return {"aligned": [e["n"] for e in found], "from": first, "to": last}


def loop_sections(project: Project, file: Path, length: float, apply: int | None) -> dict:
    """The loop sections of the song; with `apply`, the project becomes a looping Short of one."""
    from . import align, sections

    if why := align.missing(("librosa",)):
        raise ValueError(why)
    lines = tuple(timing.ready(project.lines))
    song = project.song()
    found = sections.sections(lines, sections.grid(song.audio), song.duration, length)
    if not found:
        raise ValueError("no section of that length fits the song")
    if apply is not None:
        pick = next((s for s in found if s["n"] == apply), None)
        if pick is None:
            raise Usage(f"no section {apply}; there are {len(found)}")
        shape = project.style.shape if render.is_upright(project.style) else "tall"
        project.style = replace(
            tall.shorts(project.style, shape), clip_from=pick["from"], clip_to=pick["to"], loop=True
        )
        project.save(file)
    return {"sections": found, "applied": apply}


def add_commands(sub) -> None:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="answer with one JSON object")

    r = sub.add_parser("render", parents=[common], help="render a project to an mp4")
    r.add_argument("project", type=Path, help="project folder or its project.json")
    r.add_argument("--out", type=Path, help="the mp4 (default: <title>.mp4 in the project folder)")
    r.add_argument("--clip", help="only from START to END, e.g. 1:00,1:10")
    r.add_argument("--quick", action="store_true", help="small and at half the frame rate")

    s = sub.add_parser("still", parents=[common], help="one frame of a project as a PNG")
    s.add_argument("project", type=Path)
    s.add_argument("--at", default="0", help="time, e.g. 72.4 or 1:12.4")
    s.add_argument("--out", type=Path, help="the PNG (default: still.png in the project folder)")

    c = sub.add_parser(
        "chorus", parents=[common], help="the most repeated block of lines, as a Short's part"
    )
    c.add_argument("project", type=Path)
    c.add_argument("--length", type=float, default=30, help="seconds (15, 30, 60, ...)")
    c.add_argument("--apply", action="store_true", help="make the project a Short of that part")

    al = sub.add_parser(
        "align", parents=[common], help="when each letter is sung, for highlight=letter"
    )
    al.add_argument("project", type=Path)
    al.add_argument("--from", dest="start", help="first line start, e.g. 1:35 (default: the part)")
    al.add_argument("--to", dest="end", help="last line start (default: the part's end)")

    se = sub.add_parser(
        "sections", parents=[common], help="loop sections a whole number of bars long"
    )
    se.add_argument("project", type=Path)
    se.add_argument("--length", type=float, default=30, help="seconds (15, 30, 60, ...)")
    se.add_argument("--apply", type=int, metavar="N", help="make the project a Short of section N")

    p = sub.add_parser("project", help="make, look at and change a project")
    ps = p.add_subparsers(dest="action", required=True)
    new = ps.add_parser(
        "new", parents=[common], help="a project folder from a song, cover and lyrics"
    )
    new.add_argument("folder", type=Path)
    new.add_argument("--audio", type=Path, required=True)
    new.add_argument("--cover", type=Path, required=True)
    new.add_argument("--lyrics", type=Path, help="text, SRT, LRC or VTT")
    new.add_argument("--title", default="")
    new.add_argument("--artist", default="")
    new.add_argument("--keep-tags", action="store_true", help="keep [..] marks and # lines")
    look = ps.add_parser("show", parents=[common], help="title, style and every line with its time")
    look.add_argument("project", type=Path)
    keys = ps.add_parser(
        "set",
        parents=[common],
        help="change title, artist, album, released, the video or style keys",
    )
    keys.add_argument("project", type=Path)
    keys.add_argument("pairs", nargs="+", metavar="KEY=VALUE")
    lines = ps.add_parser("lines", parents=[common], help="change line times or text")
    lines.add_argument("project", type=Path)
    lines.add_argument("--shift", help="move every timed line, e.g. -0.3")
    lines.add_argument("--set", action="append", metavar="N=TIME", help="line N starts at TIME")
    lines.add_argument("--text", action="append", metavar="N=TEXT", help="line N reads TEXT")
    lines.add_argument(
        "--import", dest="import_file", type=Path, help="lines and times from SRT/LRC/VTT"
    )
    lines.add_argument("--from-lyrics", type=Path, help="new lines from a text file, without times")

    strict = argparse.ArgumentParser(add_help=False)
    strict.add_argument(
        "--strict", action="store_true", help="exit 4 when lines were not found or are doubtful"
    )
    model = argparse.ArgumentParser(add_help=False)
    model.add_argument("--model", default="small", choices=tuple(auto.MODELS))

    a = sub.add_parser(
        "auto", parents=[common, strict, model], help="time a project's lyrics from its song"
    )
    a.add_argument("project", type=Path)
    a.add_argument("--apply", action="store_true", help="save the times into the project")

    w = sub.add_parser("words", parents=[common, model], help="the words heard in one stretch")
    w.add_argument("audio", type=Path, help="a song file, or a project folder for its song")
    w.add_argument("--from", dest="start", required=True, help="e.g. 1:10")
    w.add_argument("--to", dest="end", required=True, help="e.g. 1:20")

    m = sub.add_parser(
        "make", parents=[common, strict, model], help="a project, its timing and the video at once"
    )
    m.add_argument("--audio", type=Path, required=True)
    m.add_argument("--cover", type=Path, required=True)
    given = m.add_mutually_exclusive_group(required=True)
    given.add_argument("--lyrics", type=Path, help="lyrics text, timed by listening to the song")
    given.add_argument("--timing", type=Path, help="lines with times (SRT, LRC or VTT)")
    m.add_argument("--title", required=True, help="also the folder and file name")
    m.add_argument("--artist", default="")
    m.add_argument("--lead", help="seconds of silence before the song")
    m.add_argument("--tail", help="seconds of silence after the song")
    m.add_argument("--height", help="1080 or 720")
    m.add_argument("--fps", help="24 or 30")
    m.add_argument("--style", help="style keys as JSON, or a JSON file")
    m.add_argument("--keep-tags", action="store_true", help="keep [..] marks and # lines")
    m.add_argument("--out", type=Path, required=True, help="the song's folder is made in here")


def run(args: argparse.Namespace) -> dict:
    if args.command == "make":
        return make(args)
    if args.command == "words":
        return words_in(args.audio, seconds(args.start), seconds(args.end), args.model)
    if args.command == "auto":
        project, file = load(args.project)
        heard = auto_time(project, args.model)
        if args.apply:
            project.save(file)
        return {**show(project, file), **heard, **to_check(project), "applied": args.apply}
    if args.command == "render":
        project, _ = load(args.project)
        clip = None
        if args.clip:
            a, sep, b = args.clip.partition(",")
            if not sep:
                raise Usage(f"--clip takes START,END: {args.clip!r}")
            clip = (seconds(a), seconds(b))
        return make_video(project, args.out, clip, args.quick)
    if args.command == "chorus":
        project, file = load(args.project)
        found = tall.chorus(tuple(project.lines), project.duration, args.length)
        if found is None:
            raise ValueError("no line comes back, so there is no chorus to find")
        if args.apply:
            shape = project.style.shape if render.is_upright(project.style) else "tall"
            project.style = replace(
                tall.shorts(project.style, shape), clip_from=found[0], clip_to=found[1]
            )
            project.save(file)
        return {"from": found[0], "to": found[1], "applied": args.apply}
    if args.command == "align":
        project, file = load(args.project)
        return align_letters(project, file, args.start, args.end)
    if args.command == "sections":
        project, file = load(args.project)
        return loop_sections(project, file, args.length, args.apply)
    if args.command == "still":
        project, _ = load(args.project)
        out = args.out or project.folder / "still.png"
        at = seconds(args.at)
        frame = render.frame(at, project.preview_lines(), project.song(), project.style)
        frame.save(out)
        return {"still": str(out), "at": at}
    if args.action == "new":
        project = new_project(
            args.folder,
            args.audio,
            args.cover,
            args.lyrics,
            args.title,
            args.artist,
            not args.keep_tags,
        )
        return show(project, args.folder / "project.json")
    project, file = load(args.project)
    if args.action == "set":
        changed = set_keys(project, args.pairs)
        project.save(file)
        return {**show(project, file), "changed": changed}
    if args.action == "lines":
        changed = edit_lines(project, args)
        project.save(file)
        return {**show(project, file), "changed": changed}
    return show(project, file)


def text(result: dict) -> str:
    if "sections" in result:
        return "\n".join(
            f"{s['n']}. {clock(s['from'])} - {clock(s['to'])}  {s['bars']} bars  {s['score']:+.1f}"
            f"  {s['text']}"
            for s in result["sections"]
        )
    if "words" in result:
        return "\n".join(f"{clock(w['start'])}  {w['word']}" for w in result["words"])
    if "timed" in result:
        said = show_text(result)
        return "\n".join(result.get("changed", [])) + ("\n" if result.get("changed") else "") + said
    return "\n".join(f"{k}: {v}" for k, v in result.items())


def main(args: argparse.Namespace) -> int:
    """Run one command; print the answer and return the exit code."""
    try:
        result = run(args)
    except Usage as e:
        return fail(args, str(e), 2)
    except auto.NoMemory as e:
        return fail(args, str(e), 3)
    except Exception as e:  # noqa: BLE001 - the command line says what failed, and how
        code = 3 if jobs.failure(e) == jobs.MEMORY_ERROR else 1
        return fail(args, jobs.failure(e), code)
    print(json.dumps(result, ensure_ascii=False) if args.json else text(result), flush=True)
    if getattr(args, "strict", False) and any(result.get(kind) for kind in CHECK):
        return 4
    return 0


def fail(args: argparse.Namespace, message: str, code: int) -> int:
    if getattr(args, "json", False):
        print(json.dumps({"error": message, "exit": code}, ensure_ascii=False), flush=True)
    print(f"error: {message}", file=sys.stderr, flush=True)
    return code

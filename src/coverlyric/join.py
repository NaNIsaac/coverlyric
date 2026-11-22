"""Two projects of one song joined: the other project's video becomes an output of this one. The other
project is only read, and no file of this one is replaced."""

from __future__ import annotations

import filecmp
import os
import shutil
from dataclasses import replace
from pathlib import Path

from . import fonts
from .project import Output, Project

SAME = 0.001  # s: the page saves line times to the millisecond
SONG_KEYS = ("title", "artist", "album", "released")
SONG_FILES = ("audio", "art", "title_image")


def same_times(a: list[float], b: list[float]) -> bool:
    return len(a) == len(b) and all(abs(x - y) < SAME for x, y in zip(a, b, strict=True))


def differences(here: Project, other: Project) -> list[str]:
    """One text for each line whose time, words or letter times are not the same in both. Letter
    times whose line reads differently now do not count, as they are not drawn."""

    def told(line: tuple[float | None, str] | None) -> str:
        if line is None:
            return "no line"
        t, text = line
        return f"{'untimed' if t is None else f'{t:.3f} s'} {text!r}"

    def letters(project: Project, n: int, text: str) -> list[float]:
        found = (e for e in project.letters if e.get("n") == n and e.get("text") == text)
        return next((list(e.get("times", [])) for e in found), [])

    out = []
    for n in range(1, max(len(here.lines), len(other.lines)) + 1):
        mine = here.lines[n - 1] if n <= len(here.lines) else None
        theirs = other.lines[n - 1] if n <= len(other.lines) else None
        if (
            mine is None
            or theirs is None
            or mine[1] != theirs[1]
            or (mine[0] is None) != (theirs[0] is None)
            or (mine[0] is not None and not same_times([mine[0]], [theirs[0]]))
        ):
            out.append(f"line {n}: {told(mine)} here, {told(theirs)} in the other")
        elif not same_times(letters(here, n, mine[1]), letters(other, n, mine[1])):
            out.append(f"line {n}: the letter times differ")
    return out


def not_imported(here: Project, other: Project) -> list[str]:
    """The song's own fields that read differently in the other project: this project's are kept."""
    out = [key for key in SONG_KEYS if getattr(here, key) != getattr(other, key)]
    for key in SONG_FILES:
        mine, theirs = here.path(getattr(here, key)), other.path(getattr(other, key))
        if bool(mine) != bool(theirs) or (mine and not identical(Path(mine), Path(theirs))):
            out.append(key)
    return out


def identical(a: Path, b: Path) -> bool:
    return a.is_file() and b.is_file() and filecmp.cmp(a, b, shallow=False)


def inside(path: str | Path, folder: Path) -> bool:
    # Compared as text: looking up a UNC path would already log in to that host (fonts.allowed).
    return Path(os.path.abspath(path)).is_relative_to(os.path.abspath(folder))


def source(other: Project, name: str) -> Path:
    path = other.folder / name
    if not inside(path, other.folder):
        raise ValueError(f"{name} is outside the other project's folder")
    if not path.is_file():
        raise FileNotFoundError(f"no file at {path}")
    return path


def bring(path: Path, folder: Path, stem: str) -> Path:
    """`path` in `folder`: the file of its name already there when it is the same, else a copy as
    stem + its suffix, numbered past the names that are taken."""
    if identical(path, folder / path.name):
        return folder / path.name
    suffix, n = path.suffix.lower(), 1
    target = folder / f"{stem}{suffix}"
    while target.exists():
        n += 1
        target = folder / f"{stem}-{n}{suffix}"
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, target)
    return target


def take(here: Project, other: Project) -> Output:
    """The other project's current output added here and made current, with copies of its moving
    picture, its video and a font kept in its folder. Every file is found before one is copied."""
    given = other.output
    pictures = [source(other, name) for name in given.anim]
    video = source(other, given.video) if given.video else None
    style, font = given.style, None
    if style.font not in fonts.BUNDLED and inside(style.font, other.folder):
        font = source(other, os.path.abspath(style.font))

    new = here.free_id(style.shape)
    anim = [f"anim/{bring(p, here.folder / 'anim', p.stem).name}" for p in pictures]
    name = bring(video, here.folder, f"video-{new}").name if video else ""
    if font:
        style = replace(style, font=str(bring(font, here.folder / "fonts", font.stem).resolve()))
    made = Output(new, style, anim, name)
    here.outputs.append(made)
    here.current, here.chosen = new, None
    return made

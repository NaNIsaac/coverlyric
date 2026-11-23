"""A project: one song (the sound, the cover, the lines with their times) and the videos made from it,
its outputs, each with its own style; kept as one JSON file whose paths are relative to it.

Format 2 lists the outputs. A file without a format is format 1, one song with one style, and loads as
one output. Saving also writes the current output's style, moving picture and video at the top level,
as format 1 had them, so the release before format 2 can still open the file."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from . import media, timing
from .render import Song, Style

FORMAT = 2
# The first output's id by shape, for a format 1 file.
FIRST_ID = {"wide": "wide", "tall": "short", "square": "square", "portrait": "portrait"}


LOCK = Path(".cache", "project.lock")


class Changed(ValueError):
    """project.json changed on disk since this copy of it was read: saving would undo that change."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_bytes(path: Path) -> bytes:
    """The file's bytes; on Windows a reader can meet the moment another process replaces it."""
    for wait in (0.02, 0.05, 0.1, 0.2, 0.4):
        try:
            return path.read_bytes()
        except PermissionError:
            time.sleep(wait)
    return path.read_bytes()


@contextlib.contextmanager
def locked(folder: Path) -> Iterator[None]:
    """One writer at a time for the project in `folder`, across processes: the page, a command and
    a tool each read, change and write project.json under it."""
    path = folder / LOCK
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+b") as f:
        if sys.platform == "win32":
            import msvcrt

            while True:
                try:
                    msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
                    break
                except OSError:
                    continue
            try:
                yield
            finally:
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)


def replace_file(path: Path, data: bytes) -> None:
    """`data` as the whole of `path`, never half written: a temp file beside it, then a rename."""
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_bytes(data)
    for wait in (0.02, 0.05, 0.1, 0.2, 0.4, 0.8):
        try:
            os.replace(temp, path)
            return
        except PermissionError:
            time.sleep(wait)
    os.replace(temp, path)


@dataclass
class Output:
    """One video made from the song: how it looks, and what it puts over or under the lyrics."""

    id: str = "wide"
    style: Style = field(default_factory=Style)
    anim: list[str] = field(default_factory=list)  # the moving picture: one GIF or images in order
    video: str = ""  # the user's own video under the lyrics, in place of the cover

    @classmethod
    def from_dict(cls, data: dict) -> Output:
        return cls(
            id=str(data.get("id", "")),
            style=Style.from_dict(data.get("style", {})),
            anim=[str(name) for name in data.get("anim", [])],
            video=str(data.get("video", "")),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "style": self.style.to_dict(),
            "anim": list(self.anim),
            "video": self.video,
        }


@dataclass
class Project:
    folder: Path
    audio: str = ""
    art: str = ""
    title: str = ""
    artist: str = ""
    album: str = ""  # the player look's line under the title
    released: str = ""  # the player look's date badge, as typed
    duration: float = 0.0
    lines: list[timing.Line] = field(default_factory=list)
    title_image: str = ""  # lettering of the title, drawn in its place in the opening panel
    clean_tags: bool = True  # lyrics put in lose [..] notes and # lines (timing.sung)
    # What automatic timing said about a line: {"n": line number from 1, "kind": unplaced | doubtful
    # | differs, "heard": the words heard, for differs}. Kept so a later look can list them.
    notes: list[dict] = field(default_factory=list)
    # When each letter of a line is sung: {"n": line number from 1, "text": the line as it was timed,
    # "times": seconds}. An entry whose line text has changed since is left out of the render.
    letters: list[dict] = field(default_factory=list)
    outputs: list[Output] = field(default_factory=lambda: [Output()])
    current: str = "wide"  # the output the page and the commands work on when none is named
    # The output one command works on (--output), in place of the current one; never saved.
    chosen: str | None = field(default=None, compare=False, repr=False)
    # (file, hash of its bytes) as this copy last read or wrote it; save refuses a file changed since.
    read: tuple[str, str] | None = field(default=None, compare=False, repr=False)

    @property
    def output(self) -> Output:
        want = self.chosen or self.current
        return next((o for o in self.outputs if o.id == want), self.outputs[0])

    def free_id(self, shape: str) -> str:
        """An id no output has, for a new one of `shape`: its first id, else that with -2, -3, ..."""
        taken = {o.id for o in self.outputs}
        base = new = FIRST_ID.get(shape, "wide")
        n = 1
        while new in taken:
            n += 1
            new = f"{base}-{n}"
        return new

    def nth(self) -> int:
        """Which output of its shape the current one is, from 1, for its file name."""
        shape = self.style.shape
        before = self.outputs[: self.outputs.index(self.output)]
        return 1 + sum(o.style.shape == shape for o in before)

    @property
    def style(self) -> Style:
        return self.output.style

    @style.setter
    def style(self, value: Style) -> None:
        self.output.style = value

    @property
    def anim(self) -> list[str]:
        return self.output.anim

    @anim.setter
    def anim(self, value: list[str]) -> None:
        self.output.anim = value

    @property
    def video(self) -> str:
        return self.output.video

    @video.setter
    def video(self, value: str) -> None:
        self.output.video = value

    @classmethod
    def load(cls, path: Path) -> Project:
        raw = read_bytes(path)
        project = cls.from_dict(path.parent, json.loads(raw.decode("utf-8")))
        project.read = (str(path.resolve()), digest(raw))
        return project

    @classmethod
    def from_dict(cls, folder: Path, data: dict) -> Project:
        lines = [(None if t is None else float(t), str(text)) for t, text in data.get("lines", [])]
        outputs = [Output.from_dict(o) for o in data.get("outputs", [])]
        if not outputs:
            style = Style.from_dict(data.get("style", {}))
            outputs = [
                Output(
                    id=FIRST_ID.get(style.shape, "wide"),
                    style=style,
                    anim=[str(name) for name in data.get("anim", [])],
                    video=str(data.get("video", "")),
                )
            ]
        current = str(data.get("current", ""))
        if current not in {o.id for o in outputs}:
            current = outputs[0].id
        return cls(
            folder=folder,
            audio=data.get("audio", ""),
            art=data.get("art", ""),
            title=data.get("title", ""),
            artist=data.get("artist", ""),
            album=data.get("album", ""),
            released=data.get("released", ""),
            duration=float(data.get("duration", 0.0)),
            lines=lines,
            title_image=str(data.get("title_image", "")),
            clean_tags=bool(data.get("clean_tags", True)),
            notes=[dict(note) for note in data.get("notes", [])],
            letters=[dict(entry) for entry in data.get("letters", [])],
            outputs=outputs,
            current=current,
        )

    def flat(self) -> dict:
        """The song with the current output, in format 1: what a render job reads."""
        return {
            "audio": self.audio,
            "art": self.art,
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "released": self.released,
            "duration": self.duration,
            "lines": [list(line) for line in self.lines],
            "style": self.style.to_dict(),
            "anim": list(self.anim),
            "video": self.video,
            "title_image": self.title_image,
            "clean_tags": self.clean_tags,
            "notes": list(self.notes),
            "letters": list(self.letters),
        }

    def to_dict(self) -> dict:
        ids = {o.id for o in self.outputs}
        return {
            "format": FORMAT,
            **self.flat(),
            "outputs": [o.to_dict() for o in self.outputs],
            "current": self.current if self.current in ids else self.outputs[0].id,
        }

    def save(self, path: Path) -> None:
        """Write project.json. A copy read from this file refuses (Changed) when the file changed
        since: another program wrote it, and writing now would undo that."""
        data = json.dumps(self.to_dict(), ensure_ascii=False, indent=1).encode("utf-8")
        where = str(path.resolve())
        if not path.exists():
            path.write_bytes(data)
        else:
            with locked(path.parent):
                if self.read and self.read[0] == where and digest(read_bytes(path)) != self.read[1]:
                    raise Changed(
                        f"{path} changed since it was read; read it again and redo the change"
                    )
                replace_file(path, data)
        self.read = (where, digest(data))

    def changed_on_disk(self, path: Path) -> bool:
        """This copy came from `path`, and the file differs now from what it last read or wrote."""
        if self.read is None or self.read[0] != str(path.resolve()):
            return False
        try:
            return digest(read_bytes(path)) != self.read[1]
        except FileNotFoundError:
            return False

    def path(self, name: str) -> str:
        return str((self.folder / name).resolve()) if name else ""

    def song(self) -> Song:
        duration = self.duration
        if not duration and self.audio:
            duration = media.duration(self.path(self.audio))
        return Song(
            audio=self.path(self.audio),
            art=self.path(self.art),
            title=self.title,
            artist=self.artist,
            duration=duration,
            anim=tuple(self.path(name) for name in self.anim),
            video=self.path(self.video),
            title_image=self.path(self.title_image),
            letters=self.letter_times(),
            album=self.album,
            released=self.released,
        )

    def letter_times(self) -> tuple[tuple[float, str, tuple[float, ...]], ...]:
        """The letter times that still fit their line: the line is timed and reads as it did."""
        out = []
        for entry in self.letters:
            n = int(entry.get("n", 0)) - 1
            if not 0 <= n < len(self.lines):
                continue
            start, text = self.lines[n]
            if start is None or text != entry.get("text"):
                continue
            try:
                times = timing.letter_times(text, list(entry.get("times", [])))
            except (TypeError, ValueError):
                continue
            if times:
                out.append((float(start), text, times))
        return tuple(out)

    def preview_lines(self) -> tuple[tuple[float, str], ...]:
        """Timed lines for a still. Before any line has a time, the lines are spread 4 s apart so the
        preview still shows the text in the chosen font."""
        timed = [(t, text) for t, text in self.lines if t is not None]
        if timed:
            return tuple(sorted(timed, key=lambda r: r[0]))
        return tuple((2.0 + 4.0 * i, text) for i, (_, text) in enumerate(self.lines))

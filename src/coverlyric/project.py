"""A project: the song, the cover, the lines with their times and the style, kept as one JSON file whose
paths are relative to it."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import media, timing
from .render import Song, Style


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
    style: Style = field(default_factory=Style)
    anim: list[str] = field(default_factory=list)  # the moving picture: one GIF or images in order
    clean_tags: bool = True  # lyrics put in lose [..] notes and # lines (timing.sung)
    # What automatic timing said about a line: {"n": line number from 1, "kind": unplaced | doubtful
    # | differs, "heard": the words heard, for differs}. Kept so a later look can list them.
    notes: list[dict] = field(default_factory=list)
    # When each letter of a line is sung: {"n": line number from 1, "text": the line as it was timed,
    # "times": seconds}. An entry whose line text has changed since is left out of the render.
    letters: list[dict] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> Project:
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(path.parent, data)

    @classmethod
    def from_dict(cls, folder: Path, data: dict) -> Project:
        lines = [(None if t is None else float(t), str(text)) for t, text in data.get("lines", [])]
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
            style=Style.from_dict(data.get("style", {})),
            anim=[str(name) for name in data.get("anim", [])],
            clean_tags=bool(data.get("clean_tags", True)),
            notes=[dict(note) for note in data.get("notes", [])],
            letters=[dict(entry) for entry in data.get("letters", [])],
        )

    def to_dict(self) -> dict:
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
            "clean_tags": self.clean_tags,
            "notes": list(self.notes),
            "letters": list(self.letters),
        }

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")

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

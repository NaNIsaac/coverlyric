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
    duration: float = 0.0
    lines: list[timing.Line] = field(default_factory=list)
    style: Style = field(default_factory=Style)
    anim: list[str] = field(default_factory=list)  # the moving picture: one GIF or images in order
    clean_tags: bool = True  # lyrics put in lose [..] notes and # lines (timing.sung)

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
            duration=float(data.get("duration", 0.0)),
            lines=lines,
            style=Style.from_dict(data.get("style", {})),
            anim=[str(name) for name in data.get("anim", [])],
            clean_tags=bool(data.get("clean_tags", True)),
        )

    def to_dict(self) -> dict:
        return {
            "audio": self.audio,
            "art": self.art,
            "title": self.title,
            "artist": self.artist,
            "duration": self.duration,
            "lines": [list(line) for line in self.lines],
            "style": self.style.to_dict(),
            "anim": list(self.anim),
            "clean_tags": self.clean_tags,
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
        )

    def preview_lines(self) -> tuple[tuple[float, str], ...]:
        """Timed lines for a still. Before any line has a time, the lines are spread 4 s apart so the
        preview still shows the text in the chosen font."""
        timed = [(t, text) for t, text in self.lines if t is not None]
        if timed:
            return tuple(sorted(timed, key=lambda r: r[0]))
        return tuple((2.0 + 4.0 * i, text) for i, (_, text) in enumerate(self.lines))

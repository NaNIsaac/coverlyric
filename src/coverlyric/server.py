"""The local web page: a small HTTP server on 127.0.0.1 that serves the page, keeps the project in the work
folder, draws previews and runs the render in a child process."""

from __future__ import annotations

import base64
import colorsys
import contextlib
import functools
import importlib.util
import io
import json
import logging
import math
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from dataclasses import replace
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from PIL import Image

from . import __version__, anim, auto, cli, fonts, looks, media, overlay, render, tall, timing
from .project import Changed, Project, kept_parts
from .render import Style

WEB = Path(__file__).parent / "web"
DEMO = Path(__file__).parent / "demo"
PROJECT = Path(__file__).resolve().parents[2]  # the folder with pyproject.toml, for uv run
TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".mp4": "video/mp4",
}
LOG = logging.getLogger("coverlyric")
AUTO_NO_MEMORY = (
    "메모리가 부족해 자동 맞추기를 하지 못했습니다. "
    "채팅 AI로 맞추기나 재생하며 직접 맞추기를 쓸 수 있습니다."
)
# The timing options the page offers instead when memory is short; neither needs memory here.
AUTO_INSTEAD = ["chat", "tap"]
AUTO_FAILED = (
    "자동 맞추기를 하지 못했습니다. 인터넷 연결을 확인하고 다시 합니다. "
    "자세한 내용은 데이터 폴더의 coverlyric.log 에 있습니다."
)
# What a process that ran out of memory leaves in its output when it dies before Python can
# say so itself.
NO_MEMORY_SIGNS = ("mkl_malloc", "failed to allocate", "MemoryError", "bad_alloc")


def luminance(rgb: tuple[int, int, int]) -> float:
    """Relative luminance (WCAG) of an RGB colour in 0-255 ints."""
    lin = [
        c / 255 / 12.92 if c / 255 <= 0.04045 else ((c / 255 + 0.055) / 1.055) ** 2.4 for c in rgb
    ]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    """WCAG contrast ratio of two 0-255 colours, 1 to 21."""
    la, lb = sorted((luminance(a), luminance(b)))
    return (lb + 0.05) / (la + 0.05)


AUDIO = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac"}
IMAGES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
VIDEOS = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}
CLIP_S = 10.0  # seconds in the preview clip


def start_log(home: Path) -> Path:
    """Render events go to the terminal window and to a small rotating log file in the program
    folder, so a failed render can be read afterwards."""
    path = home / "coverlyric.log"
    LOG.setLevel(logging.INFO)
    if not LOG.handlers:
        file = RotatingFileHandler(path, maxBytes=256_000, backupCount=1, encoding="utf-8")
        file.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%Y-%m-%d %H:%M:%S"))
        terminal = logging.StreamHandler(sys.stdout)
        terminal.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
        LOG.addHandler(file)
        LOG.addHandler(terminal)
    return path


def new_group() -> dict:
    """Popen arguments that let kill_tree end the child and everything it starts."""
    return {} if sys.platform == "win32" else {"start_new_session": True}


def kill_tree(proc: subprocess.Popen) -> None:
    """End a job child with its own children: `uv run` starts the transcriber, and the render
    starts its workers and ffmpeg. Killing only the parent leaves those running."""
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
            check=False,
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if proc.poll() is None:
        proc.kill()


def remove_part(path: Path, wait: float = 5.0) -> bool:
    """Delete a stopped render's part file. On Windows a killed ffmpeg holds the file until it has
    fully exited, a moment after the kill, so a held file is tried again until `wait` runs out."""
    end = time.monotonic() + wait
    while True:
        try:
            path.unlink(missing_ok=True)
            return True
        except PermissionError as e:
            if time.monotonic() >= end:
                LOG.warning("could not remove %s: %s", path.name, e)
                return False
            time.sleep(0.1)


# What a finished video takes on disk, to check before a render: megabytes per second of video at
# each height (above what x264 makes of a busy frame), and room for the encoder's own files.
VIDEO_MB_S = {1080: 0.6, 720: 0.3}
VIDEO_MB_EXTRA = 50


def video_mb(seconds: float, style: render.Style) -> int:
    """About how many megabytes a video of this length and style needs while it is made."""
    rate = VIDEO_MB_S[1080] if render.is_upright(style) else VIDEO_MB_S.get(style.height, 0.6)
    return math.ceil(seconds * rate) + VIDEO_MB_EXTRA


def safe_name(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return name or "가사영상"


def video_file(title: str, style: render.Style, nth: int = 1) -> str:
    """The video's file name: the title, with _shorts, _1x1 or _4x5 for an upright shape so it
    does not replace the wide video, and -2, -3 for the second and third output of one shape."""
    return f"{safe_name(title)}{tall.SUFFIX.get(style.shape, '')}{f'-{nth}' if nth > 1 else ''}.mp4"


OWN_FOLDER = "프로젝트 폴더에서는 새로 시작하거나 예제를 열 수 없습니다. 그 폴더의 파일을 지키기 위해서입니다."


def editing(method):
    """A change to the project: project.json is read again first when another program changed it,
    and one change runs at a time."""

    @functools.wraps(method)
    def run(self, *args, **kwargs):
        with self.edit_lock:
            self.sync()
            return method(self, *args, **kwargs)

    return run


class App:
    def __init__(self, home: Path, folder: Path | None = None):
        self.home = home
        # A project folder of the user's (`coverlyric app <project>`): the page works in it, keeps
        # its own files in .cache/page, saves videos beside the project and never starts over there.
        self.own_folder = folder is not None
        self.work = folder if folder is not None else home / "작업 중"
        self.scratch = self.work / ".cache" / "page" if folder is not None else self.work
        self.default_output = self.work if folder is not None else home / "만든 영상"
        self.settings = home / "settings.json"
        saved = None if self.own_folder else self.saved_output()
        self.output = saved or self.default_output
        self.work.mkdir(parents=True, exist_ok=True)
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.output.mkdir(parents=True, exist_ok=True)
        self.file = self.work / "project.json"
        self.lock = threading.Lock()
        self.edit_lock = threading.RLock()
        self.starting = threading.Lock()  # a double click must not start two jobs
        # Sent with the state and back with each save: new only when project.json changed elsewhere.
        self.rev = secrets.token_hex(4)
        self.project = Project.load(self.file) if self.file.exists() else Project(self.work)
        # Written when a render starts and removed when it ends: still there now, the program was
        # closed or the PC went off in the middle of one.
        self.marker = self.scratch / "rendering.json"
        self.job: dict = self.interrupted() or {"state": "idle"}
        self.log = home / "coverlyric.log"
        self.auto: dict = {"state": "idle"}
        self.auto_proc: subprocess.Popen | None = None
        self.auto_texts: list[str] | None = None  # the lyrics an automatic timing run was given
        self.beat_grid: tuple = (None, None)  # (song file and its time, sections.Grid)
        self.proc: subprocess.Popen | None = None
        self.clip: dict = {"state": "idle"}
        self.clip_proc: subprocess.Popen | None = None
        self.clip_file = self.scratch / "preview-clip.mp4"

    def save(self) -> None:
        self.project.save(self.file)

    def sync(self) -> None:
        """Take project.json as it is when another program changed it since this page last read or
        wrote it: a command, a tool or a second page."""
        with self.edit_lock:
            if self.project.changed_on_disk(self.file):
                self.project = Project.load(self.file)
                self.rev = secrets.token_hex(4)
                render.forget_art()

    def interrupted(self) -> dict | None:
        """The job left by a render that never finished, after its half-made video is removed."""
        if not self.marker.exists():
            return None
        try:
            out = Path(json.loads(self.marker.read_text(encoding="utf-8"))["out"])
        except (OSError, ValueError, KeyError, TypeError):
            out = None
        if not self.own_folder:
            # Beside a project another program may be rendering into a making file right now.
            parts = {out.with_name(out.stem + ".making.mp4")} if out else set()
            parts.update(self.output.glob("*.making.mp4"))
            for part in parts:
                remove_part(part, wait=0)
        with contextlib.suppress(OSError):
            self.marker.unlink(missing_ok=True)
        LOG.info("the last render did not finish: %s", out.name if out else "?")
        return {"state": "interrupted", "out": str(out) if out else ""}

    def saved_output(self) -> Path | None:
        """The folder the user picked for finished videos, while it is still there (a USB drive may
        be gone); None for the default."""
        try:
            folder = json.loads(self.settings.read_text(encoding="utf-8")).get("output") or ""
        except (OSError, ValueError, AttributeError):
            return None
        return Path(folder) if folder and Path(folder).is_dir() else None

    def set_output(self, folder: str) -> dict:
        """Finished videos and saved timing files go to this folder from now on, and after a restart;
        an empty name goes back to the default."""
        path = Path(folder).resolve() if folder else self.default_output
        path.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.TemporaryFile(dir=path):
                pass
        except OSError as e:
            raise ValueError("이 폴더에는 저장할 수 없습니다. 다른 폴더를 고릅니다.") from e
        self.output = path
        if not self.own_folder:  # a project's page chooses for this run only
            chosen = "" if path == self.default_output else str(path)
            self.settings.write_text(
                json.dumps({"output": chosen}, ensure_ascii=False), encoding="utf-8"
            )
        LOG.info("output folder: %s", path)
        return self.state()

    def pick_output(self) -> dict:
        """Ask for the folder with the system's folder dialog; cancelled, nothing changes."""
        picked = ask_folder(self.output)
        return self.set_output(str(picked)) if picked else self.state()

    def save_timing(self, fmt: str) -> dict:
        """Write the timing list as SRT or LRC into the output folder, under the video's name."""
        if not any(t is not None for t, _ in self.project.lines):
            raise ValueError("시간이 맞춰진 줄이 없습니다. 먼저 타이밍을 맞춥니다.")
        name, text = self.export(fmt)
        path = self.output / name
        path.write_text(text, encoding="utf-8")
        saved = {"path": str(path), "name": name, "folder": str(self.output)}
        p = self.project
        if fmt == "srt" and render.is_upright(p.style):
            # The short's own SRT beside the song's, on the short's clock with its loop lead.
            rows, _ = tall.cues(p.style, p.song(), p.lines)
            short = self.output / f"{Path(video_file(p.title, p.style, p.nth())).stem}.srt"
            short.write_text(timing.srt(rows), encoding="utf-8")
            saved |= {"path": f"{path}, {short.name}", "short": str(short)}
        return saved

    def state(self) -> dict:
        self.sync()
        data = self.project.to_dict()
        data["rev"] = self.rev
        data["own_folder"] = self.own_folder
        data["folder"] = str(self.work.resolve())
        data["has_audio"] = bool(self.project.audio)
        data["has_art"] = bool(self.project.art)
        data["has_video"] = bool(self.project.video)
        data["has_title_image"] = bool(self.project.title_image)
        data["output"] = str(self.output)
        data["output_default"] = self.output == self.default_output
        data["version"] = __version__
        data["outputs"] = cli.outputs(self.project)
        return data

    @editing
    def choose_output(self, data: dict) -> dict:
        """Saves what the page holds, then changes its output: {"use": id} makes one current;
        {"shape": s} makes the first output of that shape current, adding one copied from the
        current output when the song has none. One request, so no save falls between the two."""
        self.update(data)
        p = self.project
        if "use" in data:
            if str(data["use"]) not in {o.id for o in p.outputs}:
                raise ValueError("그 영상이 프로젝트에 없습니다. 페이지를 다시 엽니다.")
            p.current = str(data["use"])
        else:
            shape = str(data.get("shape", ""))
            if shape != "wide" and shape not in render.UPRIGHT:
                raise ValueError(f"unknown shape {shape}")
            same = next((o for o in p.outputs if o.style.shape == shape), None)
            if same is not None:
                p.current = same.id
            else:
                cli.add_output(p, p.free_id(shape), None, shape)
        self.save()
        return self.state()

    @editing
    def update(self, data: dict) -> None:
        if "rev" in data and str(data["rev"]) != self.rev:
            raise Changed(
                "다른 곳(명령이나 다른 창)에서 프로젝트가 바뀌었습니다. 바뀐 내용을 다시 읽었습니다."
            )
        p = self.project
        before = cli.listed_files(p)
        if data.get("current", p.current) != p.current:
            # Sent before a switch or from a second window: its look is another output's.
            data = {k: v for k, v in data.items() if k not in ("style", "anim", "video", "parts")}
        p.title = str(data.get("title", p.title))
        p.artist = str(data.get("artist", p.artist))
        p.album = str(data.get("album", p.album))
        p.released = str(data.get("released", p.released))
        if "lines" in data:
            p.lines = [
                (None if t is None else round(float(t), 3), str(text)) for t, text in data["lines"]
            ]
        if "clean_tags" in data:
            p.clean_tags = bool(data["clean_tags"])
        if "style" in data:
            style = Style.from_dict(data["style"])
            if not fonts.allowed(style.font, self.work):
                raise ValueError(
                    "이 글꼴은 쓸 수 없습니다. 목록의 글꼴을 고르거나 글꼴 파일을 넣습니다."
                )
            p.style = style
        if "video" in data and not data["video"]:
            p.video = ""
        if "parts" in data:
            p.parts = kept_parts(data["parts"])
        if "title_image" in data and not data["title_image"]:
            p.title_image = ""
        if "anim" in data:
            # Reorder or remove the moving picture's files; new ones come through upload.
            kept = [str(name) for name in data["anim"] if str(name) in p.anim]
            self.drop_anim(set(p.anim) - set(kept))
            p.anim = kept
        self.save()
        cli.delete_replaced(p, before)

    def drop_anim(self, names: set[str]) -> None:
        folder = (self.work / "anim").resolve()
        others = {n for o in self.project.outputs if o is not self.project.output for n in o.anim}
        for name in names - others:
            path = (self.work / name).resolve()
            if path.parent == folder:  # never a file outside the project's anim folder
                path.unlink(missing_ok=True)

    @editing
    def upload(self, kind: str, name: str, body: bytes) -> dict:
        """A file put into the project. Only the file the project listed for it is replaced, and
        it goes once the project is saved; the new file never writes over another of the folder."""
        suffix = Path(name).suffix.lower()
        p = self.project
        before = cli.listed_files(p)
        if kind == "audio":
            if suffix not in AUDIO:
                raise ValueError(
                    "지원하지 않는 노래 파일 형식입니다. mp3, wav, m4a, flac, ogg 파일을 고릅니다."
                )
            # Read the new file under another name first: a file that is not a song must not cost
            # the song already in the project.
            trial = self.scratch / f"upload{suffix}"
            trial.write_bytes(body)
            try:
                length = media.duration(str(trial))
            except ValueError:
                trial.unlink()
                raise ValueError(
                    "노래 파일을 읽을 수 없습니다. 다른 파일을 고릅니다 (mp3, wav, m4a, flac, ogg)."
                ) from None
            target = cli.free_file(p, p.audio, "song", suffix)
            trial.replace(target)
            self.project.audio = target.name
            self.project.duration = length
            if not self.project.title:
                self.project.title = Path(name).stem
        elif kind == "art":
            if suffix not in IMAGES:
                raise ValueError("지원하지 않는 그림 형식입니다. png, jpg, webp 파일을 고릅니다.")
            try:
                with Image.open(io.BytesIO(body)) as picture:
                    picture.load()
            except (OSError, SyntaxError, Image.DecompressionBombError):
                raise ValueError("그림 파일을 읽을 수 없습니다. 다른 파일을 고릅니다.") from None
            target = cli.free_file(p, p.art, "cover", suffix)
            target.write_bytes(body)
            self.project.art = target.name
        elif kind == "title":
            if suffix not in IMAGES:
                raise ValueError("지원하지 않는 그림 형식입니다. png, jpg, webp 파일을 고릅니다.")
            trial = self.scratch / f"upload{suffix}"
            trial.write_bytes(body)
            if render.title_lettering(str(trial), 10, 10, (0, 0, 0)) is None:
                trial.unlink()
                raise ValueError(
                    "글씨를 찾을 수 없습니다. 흰 바탕이나 투명한 바탕에 어두운 글씨 그림을 고릅니다."
                )
            target = cli.free_file(p, p.title_image, "title", suffix)
            trial.replace(target)
            self.project.title_image = target.name
        elif kind == "font":
            if suffix not in fonts.SUFFIXES:
                raise ValueError("지원하지 않는 글꼴 형식입니다. ttf, otf, ttc 파일을 고릅니다.")
            folder = self.work / "fonts"
            folder.mkdir(exist_ok=True)
            target = folder / safe_name(Path(name).name)
            target.write_bytes(body)
            self.project.style = replace(self.project.style, font=str(target))
        elif kind == "anim":
            # A GIF is the whole moving picture; images are its frames, added one by one in order.
            if suffix not in anim.SUFFIXES:
                raise ValueError("움직이는 그림은 gif, png, jpg, webp 파일만 넣을 수 있습니다.")
            try:
                Image.open(io.BytesIO(body)).verify()
            except (OSError, SyntaxError) as e:
                raise ValueError("그림 파일을 읽을 수 없습니다. 다른 파일을 고릅니다.") from e
            if suffix == ".gif" or any(name.lower().endswith(".gif") for name in p.anim):
                self.drop_anim(set(p.anim))
                p.anim = []
            folder = self.work / "anim"
            folder.mkdir(exist_ok=True)
            stem, n = safe_name(Path(name).stem), 1
            target = folder / f"{stem}{suffix}"
            while target.exists():
                n += 1
                target = folder / f"{stem}-{n}{suffix}"
            target.write_bytes(body)
            p.anim.append(f"anim/{target.name}")
        elif kind == "video":
            if suffix not in VIDEOS:
                raise ValueError(
                    "지원하지 않는 영상 형식입니다. mp4, mov, webm, mkv, avi 파일을 고릅니다."
                )
            trial = self.scratch / f"upload{suffix}"
            trial.write_bytes(body)
            if not overlay.streams(str(trial))[0]:
                trial.unlink()
                raise ValueError("영상 파일을 읽을 수 없습니다. 다른 파일을 고릅니다.")
            target = cli.free_file(p, p.video, cli.video_stem(p), suffix)
            trial.replace(target)
            self.project.video = target.name
        else:
            raise ValueError(f"unknown upload kind {kind}")
        render.forget_art()
        self.save()
        cli.delete_replaced(p, before)
        return self.state()

    @editing
    def demo(self) -> dict:
        if self.own_folder:
            raise ValueError(OWN_FOLDER)
        before = cli.listed_files(self.project)
        for old in [*self.work.glob("song.*"), *self.work.glob("cover.*")]:
            old.unlink()
        self.drop_anim(set(self.project.anim))
        shutil.copy(DEMO / "tone.wav", self.work / "song.wav")
        shutil.copy(DEMO / "cover.png", self.work / "cover.png")
        demo = Project.load(DEMO / "demo.json")
        demo.folder = self.work
        demo.audio, demo.art = "song.wav", "cover.png"
        demo.duration = media.duration(str(self.work / "song.wav"))
        self.project = demo
        render.forget_art()
        self.save()
        cli.delete_replaced(demo, before)
        return self.state()

    @editing
    def reset(self) -> dict:
        if self.own_folder:
            raise ValueError(OWN_FOLDER)
        if self.job.get("state") == "running":
            raise ValueError(
                "영상을 만드는 중에는 새로 시작할 수 없습니다. 끝나거나 멈춘 뒤 다시 합니다."
            )
        self.drop_anim(set(self.project.anim))
        for old in self.work.iterdir():
            if old.is_file():
                old.unlink()
        self.project = Project(self.work)
        self.job = {"state": "idle"}
        if self.auto.get("state") != "running":
            self.auto = {"state": "idle"}
        render.forget_art()
        self.save()
        return self.state()

    def preview(self, t: float, width: int = 1280) -> tuple[bytes, dict, list]:
        """A JPEG of the frame at time t, as wide as the page shows it (320 to 1280 px), the boxes
        the page can drag, and how each lyric line fits the panel."""
        p = self.project
        if not p.art:
            raise ValueError("앨범 표지가 없습니다. 노래·표지 단계에서 표지를 넣습니다.")
        if render.is_upright(p.style):
            # An upright video is on the song's own clock, as render() makes it: no silence before or after.
            lines, song = p.preview_lines(), p.song()
        else:
            lines, song = render.padded(p.preview_lines(), p.song(), p.style)
            t = render.video_time(t, p.style)
        with self.lock:
            img = render.frame(t, lines, song, p.style)
        width = min(1280, max(320, width))
        small = img.resize((width, round(width * img.height / img.width)), Image.LANCZOS)
        buf = io.BytesIO()
        small.save(buf, "JPEG", quality=88)
        fits = render.line_fits(tuple(p.lines), p.style)
        return buf.getvalue(), render.boxes(p.style, t, song), fits

    def find_chorus(self, length: float) -> dict:
        """후렴 찾기: the Short's part from the most repeated block of lines, or none."""
        p = self.project
        found = tall.chorus(tuple(p.lines), p.duration, length)
        first, last = found or (None, None)
        return {"from": first, "to": last}

    def song_grid(self, song: render.Song):
        """The song's beat grid, worked out once per song file."""
        from . import sections

        key = (song.audio, os.path.getmtime(song.audio))
        if self.beat_grid[0] != key:
            self.beat_grid = (key, sections.grid(song.audio))
        return self.beat_grid[1]

    def find_sections(self, length: float) -> dict:
        """반복 구간 찾기: loop sections a whole number of bars long, best first."""
        from . import align, sections

        if why := align.missing(("librosa",)):
            raise ValueError(f"반복 구간 찾기에는 추가 설치가 필요합니다. {why}")
        p = self.project
        if not p.audio:
            raise ValueError("노래 파일이 없습니다. 노래·표지 단계에서 넣습니다.")
        song = p.song()
        lines = tuple(timing.ready([line for line in p.lines if line[0] is not None]))
        return {"sections": sections.sections(lines, self.song_grid(song), song.duration, length)}

    def pick_part(
        self, first: float, last: float, end: str = "", by: int = 0, unit: str = "beat"
    ) -> dict:
        """The Short's part from `first` to `last`, with `end` moved `by` beats or bars when given,
        and what it holds (part.describe). The beat grid comes from the align extra; without it, or
        when the song has no steady beat, the ends move by 0.1 s and from line start to line start."""
        from . import align, part

        p = self.project
        song = p.song()
        beats = None
        if p.audio and not align.missing(("librosa",)):
            with contextlib.suppress(ValueError):
                beats = tuple(float(b) for b in self.song_grid(song).beats)
        starts = [t for t, text in p.lines if t is not None and text.strip()]
        if end in ("from", "to") and by:
            first, last = part.move(first, last, end, by, unit, song.duration, beats, starts)
        return part.describe(first, last, p.lines, song.duration, beats, song.letters)

    def look_stills(self, t: float, width: int = 320) -> dict:
        """Each look's keys and a small JPEG of the frame at time t in it, for the 꾸미기 cards."""
        p = self.project
        if not p.art:
            raise ValueError("앨범 표지가 없습니다. 노래·표지 단계에서 표지를 넣습니다.")
        lines, song = render.padded(p.preview_lines(), p.song(), p.style)
        t = render.video_time(t, p.style)
        stills = {}
        for name in looks.LOOKS:
            with self.lock:
                img = render.frame(t, lines, song, looks.apply(p.style, name))
            buf = io.BytesIO()
            img.resize((width, round(width * 9 / 16)), Image.LANCZOS).save(buf, "JPEG", quality=85)
            stills[name] = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
        return {"looks": looks.LOOKS, "current": looks.current(p.style), "stills": stills}

    def band_from_cover(self) -> str:
        """The cover's own colour as #rrggbb for the lyric band, made darker (light lyrics) or lighter
        (dark lyrics) until the lyric colour on it reads at least as well as white on the default band."""
        p = self.project
        if not p.art:
            raise ValueError("앨범 표지가 없습니다. 노래·표지 단계에서 표지를 넣습니다.")
        song = p.song()
        with self.lock:
            cover = render.cover_colour(song.art, render.stamp(song.art))
        ink = render.hex_rgb(p.style.lyric_colour)
        need = contrast(render.hex_rgb(render.Style().band), (255, 255, 255))
        light_ink = luminance(ink) > 0.4
        hue, sat, val = colorsys.rgb_to_hsv(*(c / 255 for c in cover))

        def rgb() -> tuple[int, int, int]:
            return tuple(round(c * 255) for c in colorsys.hsv_to_rgb(hue, sat, val))

        for _ in range(300):
            if contrast(rgb(), ink) >= need:
                break
            if light_ink:
                val *= 0.97
            elif val < 1:
                val = min(1.0, val + 0.02)
            else:
                sat *= 0.95
        r, g, b = rgb()
        return f"#{r:02x}{g:02x}{b:02x}"

    def job_data(self) -> dict:
        """The project for a render child, with every file by its full path: the job file may be
        outside the project folder."""
        p = self.project
        data = p.flat()
        data["audio"], data["art"] = p.path(p.audio), p.path(p.art)
        data["anim"] = [p.path(name) for name in p.anim]
        data["video"], data["title_image"] = p.path(p.video), p.path(p.title_image)
        return data

    def start_render(self) -> dict:
        self.sync()
        with self.starting:
            return self.begin_render()

    def begin_render(self) -> dict:
        if self.job.get("state") == "running":
            return self.job
        self.stop_clip()  # the video wins over a look at it
        if self.auto.get("state") == "running":
            # Both at once need about 2 GB, more than a 4 GB PC has free.
            raise ValueError(
                "자동 맞추기가 진행 중입니다. 끝나거나 취소한 뒤에 영상을 만들 수 있습니다."
            )
        p = self.project
        if not p.audio or not p.art:
            raise ValueError("노래 파일과 앨범 표지가 필요합니다. 노래·표지 단계에서 넣습니다.")
        if not p.lines:
            raise ValueError("가사가 없습니다. 가사 단계에서 가사를 넣습니다.")
        timing.ready(p.lines)
        out = self.output / video_file(p.title, p.style, p.nth())
        total = p.duration + p.style.lead + p.style.tail
        if render.is_upright(p.style):
            first, last = tall.span(p.style, p.song())
            total = last - first
        self.check_room(total, p.style)
        job = self.scratch / "job.json"
        data = self.job_data()
        data["out"] = str(out)
        job.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        self.marker.write_text(json.dumps({"out": str(out)}, ensure_ascii=False), encoding="utf-8")
        cmd = [sys.executable, "-m", "coverlyric", "render-job", str(job)]
        self.proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            **media.below_normal(),
            **new_group(),
        )
        self.job = {"state": "running", "done": 0.0, "total": total, "started": time.time()}
        LOG.info("render started: %s (%.1f s)", out.name, p.duration)
        threading.Thread(target=self.watch, args=(self.proc, out), daemon=True).start()
        return self.job

    def watch(self, proc: subprocess.Popen, out: Path) -> None:
        """Follow the render child: progress into the job, every tenth into the log, and any other
        output (a traceback, ffmpeg's message) kept for the error."""
        part = out.with_name(out.stem + ".making.mp4")
        tail: list[str] = []
        said = notice = ""
        logged = 0
        for raw in proc.stdout:
            if self.proc is not proc:
                break
            line = raw.rstrip()
            if m := re.match(r"progress ([\d.]+) ([\d.]+)", line):
                done, total = float(m[1]), float(m[2])
                self.job["done"], self.job["total"] = done, total
                if total and done / total >= (logged + 1) / 10:
                    logged = int(done / total * 10)
                    LOG.info("render %d%% (%.0f of %.0f s)", logged * 10, done, total)
            elif line.startswith("out "):
                out = Path(line[4:])  # another name when the old video was held open
            elif line.startswith(("start ", "memory ")):
                LOG.info("render %s", line)
            elif line.startswith("notice "):
                notice = line[7:]
                LOG.info("render %s", line)
            elif line.startswith("error: "):
                said = line[7:]
            elif line:
                tail = (tail + [line])[-40:]
        code = proc.wait()
        # A stopped or crashed child cannot remove its own part file.
        remove_part(part)
        if self.proc is not proc:  # stopped and replaced by a newer render
            return
        with contextlib.suppress(OSError):  # a stale marker only shows one needless line later
            self.marker.unlink(missing_ok=True)
        if code == 0 and out.exists():
            spent = time.time() - self.job.get("started", time.time())
            LOG.info("render done in %.0f s: %s", spent, out)
            files = [p.name for p in (out, out.with_suffix(".srt"), out.with_suffix(".lrc"))]
            self.job = {
                "state": "done",
                "out": str(out),
                "folder": str(out.parent),
                "files": [name for name in files if (out.parent / name).exists()],
                "length": self.job.get("total", 0.0),
                "size": out.stat().st_size,
            }
            if notice:
                self.job["note"] = notice
            return
        if self.job.get("state") == "stopped":
            LOG.info("render stopped by the user")
            return
        if code == 0:
            said = said or "영상 파일이 만들어지지 않았습니다."
        reason = said or (tail[-1] if tail else "") or "렌더링 프로세스가 갑자기 종료되었습니다."
        for line in tail:
            LOG.info("  %s", line)
        LOG.error("render failed (exit code %s): %s", code, reason)
        self.job = {
            "state": "error",
            "message": f"{reason} (종료 코드 {code})",
            "log": str(self.log),
        }

    def start_clip(self, at: float) -> dict:
        """A CLIP_S second look from time `at`, small and quick, rendered like the video."""
        if self.clip.get("state") == "running":
            return self.clip
        if self.job.get("state") == "running" or self.auto.get("state") == "running":
            raise ValueError(
                "영상 만들기나 자동 맞추기가 끝난 뒤에 미리보기 영상을 만들 수 있습니다."
            )
        self.sync()
        p = self.project
        if not p.audio or not p.art:
            raise ValueError("노래 파일과 앨범 표지가 필요합니다. 노래·표지 단계에서 넣습니다.")
        _, song = render.padded((), p.song(), p.style)
        start = min(render.video_time(max(0.0, at), p.style), max(0.0, song.duration - 1.0))
        end = min(song.duration, start + CLIP_S)
        out = self.clip_file
        job = self.scratch / "clip-job.json"
        data = self.job_data()
        data["out"], data["clip"] = str(out), [start, end]
        job.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        cmd = [sys.executable, "-m", "coverlyric", "render-job", str(job)]
        self.clip_proc = proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            **new_group(),
        )
        self.clip = {"state": "running", "done": 0.0, "total": end - start, "at": start}
        threading.Thread(target=self.watch_clip, args=(proc, out, start), daemon=True).start()
        return self.clip

    def watch_clip(self, proc: subprocess.Popen, out: Path, start: float) -> None:
        tail: list[str] = []
        said = notice = ""
        for raw in proc.stdout:
            line = raw.rstrip()
            if m := re.match(r"progress ([\d.]+) ([\d.]+)", line):
                self.clip["done"], self.clip["total"] = float(m[1]), float(m[2])
            elif line.startswith("out "):
                out = Path(line[4:])  # another name while the page still holds the last clip
            elif line.startswith(("memory ", "notice ")):
                LOG.info("preview clip %s", line)
                notice = line[7:] if line.startswith("notice ") else notice
            elif line.startswith("error: "):
                said = line[7:]  # the words for the page; the traceback before it goes to the log
            elif line and not line.startswith("start "):
                tail = (tail + [line])[-20:]
        code = proc.wait()
        if self.clip_proc is not proc or self.clip.get("state") == "stopped":
            return
        if code == 0 and out.exists():
            version = int(out.stat().st_mtime * 1000)
            self.clip_file = out
            self.clip = {"state": "done", "url": f"/media/clip?v={version}", "at": start}
            if notice:
                self.clip["note"] = notice
            return
        for line in tail:
            LOG.info("  %s", line)
        LOG.error("preview clip failed (exit code %s): %s", code, said)
        reason = said or (tail[-1] if tail else "미리보기 영상을 만들지 못했습니다.")
        self.clip = {"state": "error", "message": f"{reason} (종료 코드 {code})"}

    def stop_clip(self) -> dict:
        if self.clip_proc and self.clip_proc.poll() is None:
            self.clip = {"state": "stopped"}
            kill_tree(self.clip_proc)
        return self.clip

    def stop_render(self) -> dict:
        if self.proc and self.proc.poll() is None:
            self.job = {"state": "stopped"}
            LOG.info("render stop requested")
            kill_tree(self.proc)
        return self.job

    def progress(self) -> dict:
        job = dict(self.job)
        if job.get("state") == "running" and job.get("done"):
            spent = time.time() - job["started"]
            job["eta"] = math.ceil(spent / job["done"] * (job["total"] - job["done"]))
        return job

    def models(self) -> dict:
        return {
            name: {"size_mb": size, "ready": auto.has_model(name)}
            for name, (_, size) in auto.MODELS.items()
        }

    def check_room(self, seconds: float, style: render.Style) -> None:
        """A full drive would stop the render near its end, after minutes of work."""
        mb = video_mb(seconds, style)
        free = shutil.disk_usage(self.output)[2] / 1e6
        if free < mb:
            raise ValueError(
                f"디스크 공간 부족: 이 영상을 만들려면 {self.output.anchor or self.output}에 "
                f"여유 공간 약 {mb} MB가 필요합니다 (현재 {free:.0f} MB). "
                "공간을 늘리거나 저장 위치를 바꾼 뒤 다시 누릅니다."
            )

    def check_disk(self, model: str) -> None:
        """The first run installs faster-whisper into the program's environment and downloads the
        model into the Hugging Face cache; a full drive would fail half way with a vague message."""
        need: list[tuple[Path, int]] = []
        if not auto.has_model(model):
            need.append((auto.model_cache(), auto.MODELS[model][1] + 100))
        if importlib.util.find_spec("faster_whisper") is None:
            need.append((PROJECT, 300))
        for folder, mb in need:
            while not folder.exists() and folder.parent != folder:
                folder = folder.parent
            free = shutil.disk_usage(folder)[2] / 1e6
            if free < mb:
                raise ValueError(
                    f"디스크 공간 부족: 자동 맞추기를 처음 쓰려면 {folder.anchor or folder}에 "
                    f"여유 공간 {mb} MB가 필요합니다 (현재 {free:.0f} MB). "
                    "공간을 늘린 뒤 다시 누릅니다."
                )

    def start_auto(self, model: str) -> dict:
        self.sync()
        with self.starting:
            return self.begin_auto(model)

    def begin_auto(self, model: str) -> dict:
        if self.auto.get("state") == "running":
            return self.auto
        if self.job.get("state") == "running":
            raise ValueError("영상을 만드는 중입니다. 끝난 뒤 다시 합니다.")
        p = self.project
        if not p.audio:
            raise ValueError("노래 파일이 없습니다. 노래·표지 단계에서 넣습니다.")
        lyrics = [text for _, text in p.lines if text]
        if not lyrics:
            raise ValueError("가사가 없습니다. 가사 단계에서 가사를 넣습니다.")
        if model not in auto.MODELS:
            raise ValueError(f"unknown model {model}")
        # A model that cannot get memory fails only after a minute of loading; the free commit
        # says beforehand which one fits (#16).
        picked = auto.fitting(model, media.commit_mb())
        if picked is None:
            # Polled by the page like a run that failed, so both show the same choices.
            self.auto = {"state": "error", "message": AUTO_NO_MEMORY, "instead": AUTO_INSTEAD}
            return self.auto
        self.check_disk(picked)
        if importlib.util.find_spec("faster_whisper"):
            # Already installed: started directly, without uv's own process in between.
            cmd = [sys.executable]
        else:
            uv = os.environ.get("COVERLYRIC_UV") or shutil.which("uv")
            if not uv:
                raise ValueError(
                    "uv를 찾지 못했습니다. 시작 메뉴의 coverlyric 으로 다시 실행합니다."
                )
            cmd = [uv, "run", "--frozen", "--no-dev", "--extra", "auto", "--project", str(PROJECT)]
            cmd += ["python"]
        cmd += ["-m", "coverlyric", "auto-job"]
        job = self.scratch / "auto-job.json"
        (self.scratch / "auto-result.json").unlink(missing_ok=True)
        self.auto_texts = [text for _, text in p.lines]
        job.write_text(
            json.dumps(
                {"audio": p.path(p.audio), "lyrics": lyrics, "model": picked},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.auto_proc = subprocess.Popen(
            [*cmd, str(job)],
            # hf-xet holds the model in memory until it is complete, so the download bar would
            # not move; the plain HTTP download writes the cache file as it goes.
            # No token is needed for the public models; the lookup only prints warnings.
            env={**os.environ, "HF_HUB_DISABLE_XET": "1", "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1"},
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            **media.below_normal(),
            **new_group(),
        )
        self.auto = {"state": "running", "phase": "install", "done": 0.0, "total": p.duration}
        self.auto["started"] = self.auto["phase_started"] = time.time()
        if picked != model:
            self.auto["smaller"] = picked
        threading.Thread(target=self.watch_auto, args=(self.auto_proc,), daemon=True).start()
        return self.auto

    def watch_auto(self, proc: subprocess.Popen) -> None:
        tail = []
        for raw in proc.stdout:
            if self.auto_proc is not proc:
                break
            if m := re.match(r"phase (\w+) ([\d.]+) ([\d.]+)", raw):
                if m[1] != self.auto.get("phase"):
                    self.auto["phase_started"] = time.time()
                    self.auto.pop("eta", None)
                self.auto["phase"] = m[1]
                self.auto["done"], self.auto["total"] = float(m[2]), float(m[3])
            elif raw.startswith("lines "):
                self.auto["partial"] = json.loads(raw[6:])
            elif raw.startswith("smaller "):
                self.auto["smaller"] = raw.split()[1]
            else:
                tail = (tail + [raw.rstrip()])[-40:]
                if self.auto.get("phase") == "install" and raw.strip():
                    self.auto["detail"] = raw.strip()[:80]
        code = proc.wait()
        if self.auto_proc is not proc:  # cancelled and replaced by a newer run
            return
        result = self.scratch / "auto-result.json"
        if code == 0 and result.exists():
            data = json.loads(result.read_text(encoding="utf-8"))
            # Saved here, not by the page, so a page reloaded during the run still gets the times;
            # not over lyrics another program changed during the run.
            with self.edit_lock:
                self.sync()
                texts = self.auto_texts
                if texts is None or [text for _, text in self.project.lines] == texts:
                    self.project.lines = [(t, text) for t, text in data["lines"]]
                    with contextlib.suppress(Changed):
                        self.save()
                else:
                    LOG.info("automatic timing not saved: the lyrics changed during the run")
            smaller = {"smaller": self.auto["smaller"]} if "smaller" in self.auto else {}
            self.auto = {"state": "done", **data, **smaller}
        elif self.auto.get("state") != "stopped":
            # Install logs and library warnings go to the log file; the page gets a sentence.
            LOG.error("automatic timing failed (exit code %s):\n%s", code, "\n".join(tail))
            short = code == auto.NO_MEMORY_EXIT or any(
                s in line for line in tail for s in NO_MEMORY_SIGNS
            )
            self.auto = (
                {"state": "error", "message": AUTO_NO_MEMORY, "instead": AUTO_INSTEAD}
                if short
                else {"state": "error", "message": AUTO_FAILED}
            )

    def stop_auto(self) -> dict:
        if self.auto_proc and self.auto_proc.poll() is None:
            self.auto = {"state": "stopped"}
            kill_tree(self.auto_proc)
        return self.auto

    def auto_progress(self) -> dict:
        job = dict(self.auto)
        measured = job.get("phase") in ("download", "listen")
        if job.get("state") == "running" and measured and job.get("done") and job.get("total"):
            spent = time.time() - job["phase_started"]
            job["eta"] = max(0, math.ceil(spent / job["done"] * (job["total"] - job["done"])))
        return job

    def export(self, fmt: str) -> tuple[str, str]:
        p = self.project
        name = safe_name(p.title)
        if fmt == "srt":
            return f"{name}.srt", timing.to_srt(p.lines, p.duration or None)
        return f"{name}.lrc", timing.to_lrc(p.lines, p.title, p.artist)


def ask_folder(start: Path) -> Path | None:
    """The system's folder dialog, in a child process: Tk wants the main thread of its own process,
    and the server answers from worker threads."""
    done = subprocess.run(
        [sys.executable, "-m", "coverlyric", "pick-folder", str(start)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    picked = done.stdout.strip()
    return Path(picked) if done.returncode == 0 and picked else None


def open_folder(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def open_video(job: dict) -> None:
    """The finished video in the computer's own player."""
    out = Path(job["out"]) if job.get("state") == "done" else None
    if not out or not out.exists():
        raise ValueError("만든 영상이 없습니다.")
    open_folder(out)


def handler(app: App, server_ref: list) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:
            pass

        def send(self, code: int, body: bytes, ctype: str, headers: dict | None = None) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def json(self, data, code: int = 200) -> None:
            self.send(code, json.dumps(data, ensure_ascii=False).encode(), "application/json")

        def trusted(self) -> bool:
            """Only the page this server sent may use it. Another site in the same browser
            reaches 127.0.0.1 too: a DNS-rebinding page names its own host, a cross-site
            request carries its own Origin, and a form or no-cors fetch can only send simple
            content types, so a POST must use JSON or the upload name header, which the
            browser does not send cross-site without asking this server first."""
            port = self.server.server_address[1]
            own = {f"127.0.0.1:{port}", f"localhost:{port}"}
            if self.headers.get("Host") not in own:
                return False
            origin = self.headers.get("Origin")
            if origin is not None and origin not in {f"http://{h}" for h in own}:
                return False
            if self.command == "POST":
                ctype = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
                return ctype == "application/json" or "X-Name" in self.headers
            return True

        def body(self) -> bytes:
            return self.rfile.read(int(self.headers.get("Content-Length") or 0))

        def file(self, path: Path) -> None:
            if not path.is_file():
                self.send(404, b"not found", "text/plain")
                return
            size = path.stat().st_size
            ctype = TYPES.get(path.suffix.lower(), "application/octet-stream")
            start, end = 0, size - 1
            if m := re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", "")):
                if m[1]:
                    start = int(m[1])
                    end = int(m[2]) if m[2] else end
                else:
                    start = max(0, size - int(m[2] or 0))
                end = min(end, size - 1)
                if start > end:
                    self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_response(HTTPStatus.PARTIAL_CONTENT)
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            else:
                self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            with path.open("rb") as f:
                f.seek(start)
                left = end - start + 1
                while left > 0 and (chunk := f.read(min(left, 1 << 20))):
                    self.wfile.write(chunk)
                    left -= len(chunk)

        def do_GET(self) -> None:
            if not self.trusted():
                self.send(403, b"forbidden", "text/plain")
                return
            url = urlparse(self.path)
            query = parse_qs(url.query)
            try:
                if url.path == "/":
                    self.file(WEB / "index.html")
                elif url.path in ("/app.js", "/clock.js", "/merge.js", "/seam.js", "/app.css"):
                    self.file(WEB / url.path[1:])
                elif url.path == "/api/state":
                    self.json(app.state())
                elif url.path == "/api/band-from-cover":
                    self.json({"band": app.band_from_cover()})
                elif url.path == "/api/fonts":
                    self.json(fonts.choices())
                elif url.path == "/api/render":
                    self.json(app.progress())
                elif url.path == "/api/clip":
                    self.json(app.clip)
                elif url.path == "/media/clip":
                    self.file(app.clip_file)
                elif url.path == "/api/auto":
                    self.json({**app.auto_progress(), "models": app.models()})
                elif url.path == "/api/prompt":
                    own = [text for _, text in app.project.lines if text]
                    self.json(
                        {"prompt": timing.ai_prompt(own, app.project.title), "lines": len(own)}
                    )
                elif url.path == "/media/anim":
                    # Only a file the project lists, for the frame thumbnails on the page.
                    name = query.get("name", [""])[0]
                    listed = name in app.project.anim
                    self.file(app.work / name if listed else app.work / "missing")
                elif url.path in ("/media/audio", "/media/art"):
                    name = app.project.audio if url.path.endswith("audio") else app.project.art
                    self.file(app.work / name if name else app.work / "missing")
                elif url.path == "/api/export":
                    name, text = app.export(query.get("fmt", ["lrc"])[0])
                    disposition = f"attachment; filename*=UTF-8''{quote(name)}"
                    self.send(
                        200,
                        text.encode("utf-8"),
                        "text/plain; charset=utf-8",
                        {"Content-Disposition": disposition},
                    )
                else:
                    self.send(404, b"not found", "text/plain")
            except Changed as e:
                self.json({"error": str(e), "state": app.state()}, 409)
            except (ValueError, OSError) as e:
                self.json({"error": str(e)}, 400)

        def do_POST(self) -> None:
            if not self.trusted():
                self.send(403, b"forbidden", "text/plain")
                return
            url = urlparse(self.path)
            query = parse_qs(url.query)
            try:
                if url.path == "/api/state":
                    app.update(json.loads(self.body() or b"{}"))
                    self.json(app.state())
                elif url.path == "/api/choose-output":
                    self.json(app.choose_output(json.loads(self.body() or b"{}")))
                elif url.path == "/api/upload":
                    name = unquote(self.headers.get("X-Name", "file"))
                    self.json(app.upload(query.get("kind", [""])[0], name, self.body()))
                elif url.path == "/api/import":
                    name = unquote(self.headers.get("X-Name", "lyrics.txt"))
                    text = self.body().decode("utf-8-sig", errors="replace")
                    clean = self.headers.get("X-Clean")
                    if clean is not None:
                        app.project.clean_tags = clean != "0"
                    lines = timing.parse(name, text, app.project.clean_tags)
                    if not lines:
                        raise ValueError(
                            "이 파일에서 가사 줄을 찾지 못했습니다. SRT, LRC, VTT 파일인지 확인합니다."
                        )
                    own = [text for _, text in app.project.lines if text]
                    diff = timing.check(own, lines) if own else [None] * len(lines)
                    self.json(
                        {"lines": [list(line) for line in lines], "diff": diff, "own": len(own)}
                    )
                elif url.path == "/api/preview":
                    data = json.loads(self.body() or b"{}")
                    if data:
                        app.update(data)
                    jpeg, boxes, fits = app.preview(
                        float(query.get("t", ["0"])[0]), int(query.get("w", ["1280"])[0])
                    )
                    headers = {"X-Boxes": json.dumps(boxes), "X-Fit": json.dumps(fits)}
                    self.send(200, jpeg, "image/jpeg", headers)
                elif url.path == "/api/looks":
                    data = json.loads(self.body() or b"{}")
                    if data:
                        app.update(data)
                    self.json(app.look_stills(float(query.get("t", ["0"])[0])))
                elif url.path == "/api/chorus":
                    data = json.loads(self.body() or b"{}")
                    if data:
                        app.update(data)
                    self.json(app.find_chorus(float(query.get("len", ["30"])[0])))
                elif url.path == "/api/sections":
                    data = json.loads(self.body() or b"{}")
                    if data:
                        app.update(data)
                    self.json(app.find_sections(float(query.get("len", ["30"])[0])))
                elif url.path == "/api/part":
                    data = json.loads(self.body() or b"{}")
                    if data:
                        app.update(data)
                    q = {k: v[0] for k, v in query.items()}
                    self.json(
                        app.pick_part(
                            float(q.get("from", 0)),
                            float(q.get("to", 0)),
                            q.get("end", ""),
                            int(q.get("by", 0)),
                            q.get("unit", "beat"),
                        )
                    )
                elif url.path == "/api/render":
                    self.json(app.start_render())
                elif url.path == "/api/auto":
                    data = json.loads(self.body() or b"{}")
                    self.json(app.start_auto(str(data.get("model", "medium"))))
                elif url.path == "/api/auto/stop":
                    self.json(app.stop_auto())
                elif url.path == "/api/render/stop":
                    self.json(app.stop_render())
                elif url.path == "/api/clip":
                    self.json(app.start_clip(float(query.get("t", ["0"])[0])))
                elif url.path == "/api/clip/stop":
                    self.json(app.stop_clip())
                elif url.path == "/api/demo":
                    self.json(app.demo())
                elif url.path == "/api/new":
                    self.json(app.reset())
                elif url.path == "/api/open":
                    open_folder(app.output)
                    self.json({"ok": True})
                elif url.path == "/api/open-video":
                    open_video(app.job)
                    self.json({"ok": True})
                elif url.path == "/api/output":
                    folder = json.loads(self.body() or b"{}").get("folder")
                    self.json(app.pick_output() if folder is None else app.set_output(str(folder)))
                elif url.path == "/api/save-timing":
                    self.json(app.save_timing(query.get("fmt", ["srt"])[0]))
                elif url.path == "/api/quit":
                    app.stop_render()
                    app.stop_auto()
                    self.json({"ok": True})
                    threading.Thread(target=server_ref[0].shutdown, daemon=True).start()
                else:
                    self.send(404, b"not found", "text/plain")
            except Changed as e:
                self.json({"error": str(e), "state": app.state()}, 409)
            except (ValueError, OSError, json.JSONDecodeError) as e:
                self.json({"error": str(e)}, 400)

    return Handler


def serve(home: Path, port: int = 0, browser: bool = True, folder: Path | None = None) -> None:
    home.mkdir(parents=True, exist_ok=True)  # the log file opens before App makes its folders
    start_log(home)
    app = App(home, folder)
    ref: list = []
    server = ThreadingHTTPServer(("127.0.0.1", port), handler(app, ref))
    ref.append(server)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    page = app.scratch / "page.json" if folder is not None else None
    if page is not None:
        # How `open_page` finds this page again instead of starting a second one on the project.
        page.write_text(json.dumps({"url": url, "pid": os.getpid()}), encoding="utf-8")
    print(f"coverlyric 가사 영상 만들기: {url}")
    print("프로그램을 끝내려면 이 창을 닫거나 페이지의 [끝내기]를 누릅니다.", flush=True)
    if browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.stop_render()
        server.server_close()
        if page is not None:
            with contextlib.suppress(OSError):
                page.unlink(missing_ok=True)

"""The local web page: a small HTTP server on 127.0.0.1 that serves the page, keeps the project in the work
folder, draws previews and runs the render in a child process."""

from __future__ import annotations

import io
import json
import logging
import math
import os
import re
import shutil
import subprocess
import sys
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

from . import fonts, media, render, timing
from .project import Project
from .render import Style

WEB = Path(__file__).parent / "web"
DEMO = Path(__file__).parent / "demo"
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
}
LOG = logging.getLogger("coverlyric")
AUDIO = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac"}
IMAGES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


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


def safe_name(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return name or "가사영상"


class App:
    def __init__(self, home: Path):
        self.home = home
        self.work = home / "작업 중"
        self.output = home / "만든 영상"
        self.work.mkdir(parents=True, exist_ok=True)
        self.output.mkdir(parents=True, exist_ok=True)
        self.file = self.work / "project.json"
        self.lock = threading.Lock()
        self.project = Project.load(self.file) if self.file.exists() else Project(self.work)
        self.job: dict = {"state": "idle"}
        self.log = home / "coverlyric.log"
        self.proc: subprocess.Popen | None = None

    def save(self) -> None:
        self.project.save(self.file)

    def state(self) -> dict:
        data = self.project.to_dict()
        data["has_audio"] = bool(self.project.audio)
        data["has_art"] = bool(self.project.art)
        data["output"] = str(self.output)
        return data

    def update(self, data: dict) -> None:
        p = self.project
        p.title = str(data.get("title", p.title))
        p.artist = str(data.get("artist", p.artist))
        if "lines" in data:
            p.lines = [
                (None if t is None else round(float(t), 3), str(text)) for t, text in data["lines"]
            ]
        if "style" in data:
            p.style = Style.from_dict(data["style"])
        self.save()

    def upload(self, kind: str, name: str, body: bytes) -> dict:
        suffix = Path(name).suffix.lower()
        if kind == "audio":
            if suffix not in AUDIO:
                raise ValueError("노래 파일은 mp3, wav, m4a, flac, ogg 중 하나여야 해요.")
            for old in self.work.glob("song.*"):
                old.unlink()
            target = self.work / f"song{suffix}"
            target.write_bytes(body)
            self.project.audio = target.name
            self.project.duration = media.duration(str(target))
            if not self.project.title:
                self.project.title = Path(name).stem
        elif kind == "art":
            if suffix not in IMAGES:
                raise ValueError("표지는 png, jpg, webp 그림이어야 해요.")
            for old in self.work.glob("cover.*"):
                old.unlink()
            target = self.work / f"cover{suffix}"
            target.write_bytes(body)
            self.project.art = target.name
        elif kind == "font":
            if suffix not in fonts.SUFFIXES:
                raise ValueError("글꼴 파일은 ttf, otf, ttc 중 하나여야 해요.")
            folder = self.work / "fonts"
            folder.mkdir(exist_ok=True)
            target = folder / safe_name(Path(name).name)
            target.write_bytes(body)
            self.project.style = replace(self.project.style, font=str(target))
        else:
            raise ValueError(f"unknown upload kind {kind}")
        render.scene.cache_clear()
        self.save()
        return self.state()

    def demo(self) -> dict:
        for old in [*self.work.glob("song.*"), *self.work.glob("cover.*")]:
            old.unlink()
        shutil.copy(DEMO / "tone.wav", self.work / "song.wav")
        shutil.copy(DEMO / "cover.png", self.work / "cover.png")
        demo = Project.load(DEMO / "demo.json")
        demo.folder = self.work
        demo.audio, demo.art = "song.wav", "cover.png"
        demo.duration = media.duration(str(self.work / "song.wav"))
        self.project = demo
        render.scene.cache_clear()
        self.save()
        return self.state()

    def reset(self) -> dict:
        if self.job.get("state") == "running":
            raise ValueError("영상을 만드는 중에는 새로 시작할 수 없어요.")
        for old in self.work.iterdir():
            if old.is_file():
                old.unlink()
        self.project = Project(self.work)
        render.scene.cache_clear()
        self.save()
        return self.state()

    def preview(self, t: float) -> tuple[bytes, dict]:
        p = self.project
        if not p.art:
            raise ValueError("먼저 앨범 표지를 넣어 주세요.")
        song = p.song()
        with self.lock:
            img = render.frame(t, p.preview_lines(), song, p.style)
        small = img.resize((1280, 720), Image.LANCZOS)
        buf = io.BytesIO()
        small.save(buf, "JPEG", quality=88)
        return buf.getvalue(), render.boxes(p.style)

    def start_render(self) -> dict:
        if self.job.get("state") == "running":
            return self.job
        p = self.project
        if not p.audio or not p.art:
            raise ValueError("노래 파일과 앨범 표지를 먼저 넣어 주세요.")
        if not p.lines:
            raise ValueError("가사가 없어요.")
        timing.ready(p.lines)
        name = safe_name(p.title)
        out = self.output / f"{name}.mp4"
        job = self.work / "job.json"
        data = p.to_dict()
        data["audio"], data["art"] = p.path(p.audio), p.path(p.art)
        data["out"] = str(out)
        job.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        cmd = [sys.executable, "-m", "coverlyric", "render-job", str(job)]
        self.proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            **media.below_normal(),
        )
        self.job = {"state": "running", "done": 0.0, "total": p.duration, "started": time.time()}
        LOG.info("render started: %s (%.1f s)", out.name, p.duration)
        threading.Thread(target=self.watch, args=(self.proc, out), daemon=True).start()
        return self.job

    def watch(self, proc: subprocess.Popen, out: Path) -> None:
        """Follow the render child: progress into the job, every tenth into the log, and any other
        output (a traceback, ffmpeg's message) kept for the error."""
        tail: list[str] = []
        said = ""
        logged = 0
        for raw in proc.stdout:
            line = raw.rstrip()
            if m := re.match(r"progress ([\d.]+) ([\d.]+)", line):
                done, total = float(m[1]), float(m[2])
                self.job["done"], self.job["total"] = done, total
                if total and done / total >= (logged + 1) / 10:
                    logged = int(done / total * 10)
                    LOG.info("render %d%% (%.0f of %.0f s)", logged * 10, done, total)
            elif line.startswith("start "):
                LOG.info("render %s", line)
            elif line.startswith("error: "):
                said = line[7:]
            elif line:
                tail = (tail + [line])[-40:]
        code = proc.wait()
        if code == 0 and out.exists():
            spent = time.time() - self.job.get("started", time.time())
            LOG.info("render done in %.0f s: %s", spent, out)
            self.job = {"state": "done", "out": str(out), "folder": str(self.output)}
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

    def stop_render(self) -> dict:
        if self.proc and self.proc.poll() is None:
            self.job = {"state": "stopped"}
            LOG.info("render stop requested")
            self.proc.kill()
        return self.job

    def progress(self) -> dict:
        job = dict(self.job)
        if job.get("state") == "running" and job.get("done"):
            spent = time.time() - job["started"]
            job["eta"] = math.ceil(spent / job["done"] * (job["total"] - job["done"]))
        return job

    def export(self, fmt: str) -> tuple[str, str]:
        p = self.project
        name = safe_name(p.title)
        if fmt == "srt":
            return f"{name}.srt", timing.to_srt(p.lines, p.duration or None)
        return f"{name}.lrc", timing.to_lrc(p.lines, p.title, p.artist)


def open_folder(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


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
                    start = size - int(m[2])
                end = min(end, size - 1)
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
                self.wfile.write(f.read(end - start + 1))

        def do_GET(self) -> None:
            url = urlparse(self.path)
            query = parse_qs(url.query)
            try:
                if url.path == "/":
                    self.file(WEB / "index.html")
                elif url.path in ("/app.js", "/clock.js", "/app.css"):
                    self.file(WEB / url.path[1:])
                elif url.path == "/api/state":
                    self.json(app.state())
                elif url.path == "/api/fonts":
                    self.json(fonts.choices())
                elif url.path == "/api/render":
                    self.json(app.progress())
                elif url.path == "/api/prompt":
                    own = [text for _, text in app.project.lines if text]
                    self.json(
                        {"prompt": timing.ai_prompt(own, app.project.title), "lines": len(own)}
                    )
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
            except (ValueError, OSError) as e:
                self.json({"error": str(e)}, 400)

        def do_POST(self) -> None:
            url = urlparse(self.path)
            query = parse_qs(url.query)
            try:
                if url.path == "/api/state":
                    app.update(json.loads(self.body() or b"{}"))
                    self.json(app.state())
                elif url.path == "/api/upload":
                    name = unquote(self.headers.get("X-Name", "file"))
                    self.json(app.upload(query.get("kind", [""])[0], name, self.body()))
                elif url.path == "/api/import":
                    name = unquote(self.headers.get("X-Name", "lyrics.txt"))
                    text = self.body().decode("utf-8-sig", errors="replace")
                    lines = timing.parse(name, text)
                    if not lines:
                        raise ValueError("이 파일에서 가사를 찾지 못했어요.")
                    own = [text for _, text in app.project.lines if text]
                    diff = timing.check(own, lines) if own else [None] * len(lines)
                    self.json(
                        {"lines": [list(line) for line in lines], "diff": diff, "own": len(own)}
                    )
                elif url.path == "/api/preview":
                    data = json.loads(self.body() or b"{}")
                    if data:
                        app.update(data)
                    jpeg, boxes = app.preview(float(query.get("t", ["0"])[0]))
                    self.send(200, jpeg, "image/jpeg", {"X-Boxes": json.dumps(boxes)})
                elif url.path == "/api/render":
                    self.json(app.start_render())
                elif url.path == "/api/render/stop":
                    self.json(app.stop_render())
                elif url.path == "/api/demo":
                    self.json(app.demo())
                elif url.path == "/api/new":
                    self.json(app.reset())
                elif url.path == "/api/open":
                    open_folder(app.output)
                    self.json({"ok": True})
                elif url.path == "/api/quit":
                    app.stop_render()
                    self.json({"ok": True})
                    threading.Thread(target=server_ref[0].shutdown, daemon=True).start()
                else:
                    self.send(404, b"not found", "text/plain")
            except (ValueError, OSError, json.JSONDecodeError) as e:
                self.json({"error": str(e)}, 400)

    return Handler


def serve(home: Path, port: int = 0, browser: bool = True) -> None:
    start_log(home)
    app = App(home)
    ref: list = []
    server = ThreadingHTTPServer(("127.0.0.1", port), handler(app, ref))
    ref.append(server)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"coverlyric 가사 영상 만들기: {url}")
    print("이 창을 닫거나 화면의 [끝내기]를 누르면 프로그램이 끝나요.", flush=True)
    if browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.stop_render()
        server.server_close()

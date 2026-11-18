"""A failed render must reach the page with its reason, never end silently (issue #3)."""

import json
import logging
import sys
import time
from concurrent.futures.process import BrokenProcessPool

import pytest

from coverlyric import __main__ as cli
from coverlyric import jobs, media, render, server


@pytest.fixture(autouse=True)
def fresh_ffmpeg():
    media.ffmpeg.cache_clear()
    yield
    media.ffmpeg.cache_clear()


def wait(app, seconds=120):
    end = time.time() + seconds
    while app.job.get("state") == "running" and time.time() < end:
        time.sleep(0.2)
    return app.job


def test_a_failing_encoder_is_shown_with_its_message(tmp_path, monkeypatch, caplog):
    app = server.App(tmp_path)
    app.demo()
    # Python stands in for ffmpeg in the render child: it refuses ffmpeg's options and exits 2.
    monkeypatch.setenv("COVERLYRIC_FFMPEG", sys.executable)
    monkeypatch.setenv("COVERLYRIC_WORKERS", "1")
    with caplog.at_level(logging.INFO, logger="coverlyric"):
        app.start_render()
        job = wait(app)
    assert job["state"] == "error"
    assert "ffmpeg 오류" in job["message"] and "종료 코드 1" in job["message"]
    assert job["log"].endswith("coverlyric.log")
    assert "render failed (exit code 1)" in caplog.text
    assert not list((tmp_path / "만든 영상").glob("*.mp4"))


def test_a_killed_worker_names_memory(tmp_path, monkeypatch, capsys):
    def broken(*args, **kwargs):
        raise BrokenProcessPool("A process in the process pool was terminated abruptly")

    monkeypatch.setattr(render, "render", broken)
    app = server.App(tmp_path)
    app.demo()
    job = tmp_path / "job.json"
    data = app.project.to_dict()
    data["audio"], data["art"] = app.project.path("song.wav"), app.project.path("cover.png")
    data["out"] = str(tmp_path / "out.mp4")
    job.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(SystemExit) as end:
        cli.main(["render-job", str(job)])
    assert end.value.code == 1
    out = capsys.readouterr().out
    assert "start workers" in out
    assert f"error: {jobs.MEMORY_ERROR}" in out


def test_a_child_that_dies_without_a_word_still_gives_a_reason(tmp_path):
    app = server.App(tmp_path)
    proc = server.subprocess.Popen(
        [sys.executable, "-I", "-c", "import os; os._exit(3)"],
        stdout=server.subprocess.PIPE,
        text=True,
    )
    app.proc = proc
    app.job = {"state": "running", "started": time.time()}
    app.watch(proc, tmp_path / "never.mp4")
    assert app.job["state"] == "error"
    assert "갑자기 종료" in app.job["message"] and "종료 코드 3" in app.job["message"]


def test_an_empty_memory_error_gets_words():
    assert cli.failure(MemoryError()) == jobs.MEMORY_ERROR
    assert cli.failure(ValueError("")) == "ValueError"


def write_job(app, tmp_path, out):
    job = tmp_path / "job.json"
    data = app.project.to_dict()
    data["audio"], data["art"] = app.project.path("song.wav"), app.project.path("cover.png")
    data["out"] = str(out)
    job.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return job


def test_a_failed_render_leaves_no_part_file(tmp_path, monkeypatch):
    def half(part, *args, **kwargs):
        part.write_bytes(b"half a video")
        raise RuntimeError("ffmpeg 오류")

    monkeypatch.setattr(render, "render", half)
    app = server.App(tmp_path)
    app.demo()
    job = write_job(app, tmp_path, tmp_path / "out.mp4")
    with pytest.raises(SystemExit):
        cli.main(["render-job", str(job)])
    assert not list(tmp_path.glob("*.making.mp4"))


def test_a_stopped_render_leaves_no_part_file(tmp_path):
    app = server.App(tmp_path)
    out = app.output / "song.mp4"
    part = out.with_name("song.making.mp4")
    part.write_bytes(b"half a video")
    proc = server.subprocess.Popen(
        [sys.executable, "-I", "-c", "import time; time.sleep(0.3)"],
        stdout=server.subprocess.PIPE,
        text=True,
    )
    app.proc = proc
    app.job = {"state": "stopped"}
    app.watch(proc, out)
    assert not part.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="an open file blocks a rename only on Windows")
def test_an_old_video_open_in_a_player_gets_a_new_name(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(render, "render", lambda part, *a, **k: part.write_bytes(b"new video"))
    app = server.App(tmp_path)
    app.demo()
    out = tmp_path / "song.mp4"
    out.write_bytes(b"old video")
    job = write_job(app, tmp_path, out)
    with out.open("rb"):  # a player holding the old file
        cli.main(["render-job", str(job)])
    again = tmp_path / "song (2).mp4"
    assert again.read_bytes() == b"new video" and out.read_bytes() == b"old video"
    assert f"out {again}" in capsys.readouterr().out
    assert again.with_suffix(".srt").exists()

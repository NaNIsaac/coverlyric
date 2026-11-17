"""A failed render must reach the page with its reason, never end silently (issue #3)."""

import json
import logging
import sys
import time
from concurrent.futures.process import BrokenProcessPool

import pytest

from coverlyric import __main__ as cli
from coverlyric import media, render, server


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
    assert f"error: {cli.WORKER_ERROR}" in out


def test_a_child_that_dies_without_a_word_still_gives_a_reason(tmp_path):
    app = server.App(tmp_path)
    proc = server.subprocess.Popen(
        [sys.executable, "-I", "-c", "import os; os._exit(3)"],
        stdout=server.subprocess.PIPE,
        text=True,
    )
    app.job = {"state": "running", "started": time.time()}
    app.watch(proc, tmp_path / "never.mp4")
    assert app.job["state"] == "error"
    assert "갑자기 종료" in app.job["message"] and "종료 코드 3" in app.job["message"]


def test_an_empty_memory_error_gets_words():
    assert cli.failure(MemoryError()) == cli.WORKER_ERROR
    assert cli.failure(ValueError("")) == "ValueError"

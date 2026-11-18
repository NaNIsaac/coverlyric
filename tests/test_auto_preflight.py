"""Automatic timing checks free memory before it starts: the largest model that fits is used, and a
PC that cannot hold even the smallest one hears so at once (#16)."""

import importlib.util
import json
import sys
import threading

import pytest

from coverlyric import auto, media, server

REAL_FIND_SPEC = importlib.util.find_spec


@pytest.mark.parametrize(
    ("free", "model"),
    [(None, "small"), (2000, "small"), (600, "base"), (400, "tiny"), (300, None), (60, None)],
)
def test_the_largest_model_that_fits_is_picked(free, model):
    assert auto.fitting("small", free) == model


def test_a_smaller_model_asked_for_is_not_raised():
    assert auto.fitting("tiny", 2000) == "tiny"


@pytest.fixture()
def started(tmp_path, monkeypatch):
    app = server.App(tmp_path)
    app.demo()
    monkeypatch.setattr(server.App, "check_disk", lambda self, model: None)
    runs = []
    ended = threading.Event()  # the fake child runs until the test is over

    class Fake:
        stdout = iter(())
        pid = 0

        def __init__(self, cmd, **kwargs):
            runs.append(cmd)

        def wait(self):
            ended.wait(10)
            return 1

        def poll(self):
            return 1

    monkeypatch.setattr(server.subprocess, "Popen", Fake)
    yield app, runs
    ended.set()


def installed(monkeypatch, present: bool) -> None:
    def find_spec(name, *args):
        if name == "faster_whisper":
            return object() if present else None
        return REAL_FIND_SPEC(name, *args)

    monkeypatch.setattr(server.importlib.util, "find_spec", find_spec)


def test_a_pc_with_room_for_base_starts_with_base(started, monkeypatch):
    app, runs = started
    monkeypatch.setattr(media, "commit_mb", lambda: 600.0)
    state = app.start_auto("small")
    assert state["smaller"] == "base"
    job = json.loads((app.work / "auto-job.json").read_text(encoding="utf-8"))
    assert job["model"] == "base" and len(runs) == 1


def test_a_pc_with_room_for_small_gets_no_note(started, monkeypatch):
    app, _ = started
    monkeypatch.setattr(media, "commit_mb", lambda: 4000.0)
    assert "smaller" not in app.start_auto("small")


def test_no_room_even_for_tiny_is_said_at_once(started, monkeypatch):
    app, runs = started
    monkeypatch.setattr(media, "commit_mb", lambda: 250.0)
    state = app.start_auto("small")
    # The page polls this like a run that failed and offers the chat-AI and tap-along options.
    assert state == {"state": "error", "message": server.AUTO_NO_MEMORY, "instead": ["chat", "tap"]}
    assert runs == [] and app.auto_progress() == state


def test_an_installed_transcriber_starts_without_uv(started, monkeypatch):
    app, runs = started
    monkeypatch.setattr(media, "commit_mb", lambda: None)
    monkeypatch.delenv("COVERLYRIC_UV", raising=False)
    monkeypatch.setattr(server.shutil, "which", lambda name: None)
    installed(monkeypatch, True)
    app.start_auto("small")
    assert runs[0][:4] == [sys.executable, "-m", "coverlyric", "auto-job"]


def test_the_first_run_installs_the_transcriber_with_uv(started, monkeypatch):
    app, runs = started
    monkeypatch.setattr(media, "commit_mb", lambda: None)
    monkeypatch.setenv("COVERLYRIC_UV", "uv-here")
    installed(monkeypatch, False)
    app.start_auto("small")
    assert runs[0][:2] == ["uv-here", "run"] and "--extra" in runs[0]

"""A render on a PC short of memory (#12): workers sized from the commit left, fewer workers and then
no shared CD turn when memory runs out, and words for the page instead of the system's text."""

import errno
import logging
import sys
import time
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

import pytest

from coverlyric import __main__ as cli
from coverlyric import media, render, server
from coverlyric.project import Project

DEMO = Path(render.__file__).parent / "demo" / "demo.json"


class PagingFileTooSmall(OSError):
    """What Windows raises when a shared block cannot be committed; set on the class so the test
    runs the same on every system."""

    winerror = 1455


def paging_error() -> OSError:
    return PagingFileTooSmall(22, "The paging file is too small for this operation to complete")


def test_steps_halve_the_workers_then_drop_the_shared_turn():
    assert render.steps(6) == [(6, True), (3, True), (1, True), (1, False)]
    assert render.steps(2) == [(2, True), (1, True), (1, False)]
    assert render.steps(1) == [(1, True), (1, False)]


@pytest.mark.parametrize(
    ("error", "memory"),
    [
        (MemoryError(), True),
        (BrokenProcessPool("terminated abruptly"), True),
        (paging_error(), True),
        (OSError(errno.ENOMEM, "Cannot allocate memory"), True),
        (OSError(errno.ENOENT, "No such file"), False),
        (ValueError("bad"), False),
    ],
)
def test_out_of_memory(error, memory):
    assert render.out_of_memory(error) is memory


def fake_encode(monkeypatch, fails: int, error=None):
    calls, notes = [], []

    def encode(out, lines, song, style, workers, span, report, codec, quick, shared):
        calls.append((workers, shared))
        if len(calls) <= fails:
            raise error or paging_error()

    monkeypatch.setattr(render, "encode", encode)
    monkeypatch.setattr(media, "encoder", lambda: "libx264")
    return calls, notes


def test_a_render_short_of_memory_tries_again_with_less(monkeypatch, tmp_path):
    calls, notes = fake_encode(monkeypatch, fails=3)
    demo = Project.load(DEMO)
    render.render(tmp_path / "out.mp4", (), demo.song(), render.Style(), 6, note=notes.append)
    assert calls == [(6, True), (3, True), (1, True), (1, False)]
    assert (
        len(notes) == 3 and "1 worker" in notes[-1] and "CD turn drawn on each frame" in notes[-1]
    )


def test_when_nothing_is_left_to_try_the_error_goes_up(monkeypatch, tmp_path):
    calls, notes = fake_encode(monkeypatch, fails=99)
    demo = Project.load(DEMO)
    with pytest.raises(PagingFileTooSmall) as caught:
        render.render(tmp_path / "out.mp4", (), demo.song(), render.Style(), 2, note=notes.append)
    assert calls == [(2, True), (1, True), (1, False)]
    message = cli.failure(caught.value)
    assert message == cli.MEMORY_ERROR
    assert "paging" not in message.lower() and "1455" not in message


def test_other_errors_are_not_tried_again(monkeypatch, tmp_path):
    calls, _ = fake_encode(monkeypatch, fails=1, error=ValueError("bad lyrics"))
    demo = Project.load(DEMO)
    with pytest.raises(ValueError):
        render.render(tmp_path / "out.mp4", (), demo.song(), render.Style(), 4)
    assert calls == [(4, True)]


def test_workers_follow_the_commit_left(monkeypatch):
    monkeypatch.delenv("COVERLYRIC_WORKERS", raising=False)
    monkeypatch.setattr(cli.os, "cpu_count", lambda: 12)
    monkeypatch.setattr(media, "memory_mb", lambda: (8000.0, 6000.0))
    monkeypatch.setattr(media, "commit_mb", lambda: None)
    assert cli.workers() == 6
    monkeypatch.setattr(media, "commit_mb", lambda: 900.0)  # free RAM, but a small paging file
    assert cli.workers() == 2
    monkeypatch.setattr(media, "commit_mb", lambda: 300.0)
    assert cli.workers() == 1


def test_room_for_shared_blocks(monkeypatch):
    monkeypatch.setattr(media, "commit_mb", lambda: None)
    assert render.room_for(10_000)
    monkeypatch.setattr(media, "commit_mb", lambda: 400.0)
    assert render.room_for(200) and not render.room_for(201)


class Recording:
    """SharedMemory that records the sizes made here and can refuse one size as Windows does."""

    made: list[int] = []
    refuse: int | None = None

    def __new__(cls, name=None, create=False, size=0):
        if create:
            if size == cls.refuse:
                raise paging_error()
            cls.made.append(size)
        return render_shared(name=name, create=create, size=size)


render_shared = render.shared_memory.SharedMemory


@pytest.fixture
def recording(monkeypatch):
    Recording.made, Recording.refuse = [], None
    monkeypatch.setattr(render.shared_memory, "SharedMemory", Recording)
    return Recording


def turn_block() -> int:
    return render.turns_bytes(*render.turn_set(render.Style()))


def test_short_commit_draws_the_turn_on_each_frame(monkeypatch, tmp_path, recording):
    monkeypatch.setattr(media, "commit_mb", lambda: 200.0)
    demo = Project.load(DEMO)
    out = tmp_path / "out.mp4"
    render.render(
        out, demo.preview_lines(), demo.song(), render.Style(), 1, (3.0, 4.0), lambda *a: None
    )
    assert out.stat().st_size > 0
    assert turn_block() not in recording.made


def test_a_refused_turn_block_still_makes_the_video(tmp_path, recording):
    recording.refuse = turn_block()
    demo = Project.load(DEMO)
    out, notes = tmp_path / "out.mp4", []
    render.render(
        out,
        demo.preview_lines(),
        demo.song(),
        render.Style(),
        2,
        (3.0, 4.0),
        lambda *a: None,
        note=notes.append,
    )
    assert out.stat().st_size > 0
    assert "CD turn drawn on each frame" in notes[-1]
    assert media.duration(str(out)) == pytest.approx(1.0, abs=0.1)


def test_the_log_says_which_step_was_taken(tmp_path, caplog):

    app = server.App(tmp_path)
    proc = server.subprocess.Popen(
        [sys.executable, "-I", "-c", "print('memory short (OSError): again with 1 worker(s)')"],
        stdout=server.subprocess.PIPE,
        text=True,
    )
    app.proc = proc
    app.job = {"state": "running", "started": time.time()}
    with caplog.at_level(logging.INFO, logger="coverlyric"):
        app.watch(proc, tmp_path / "never.mp4")
    assert "render memory short (OSError): again with 1 worker(s)" in caplog.text

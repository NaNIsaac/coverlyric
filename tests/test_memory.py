"""A render on a PC short of memory (#12): workers sized from the commit left, fewer workers and then
no shared CD turn when memory runs out, and words for the page instead of the system's text."""

import errno
import logging
import sys
import time
from concurrent.futures.process import BrokenProcessPool
from dataclasses import replace
from pathlib import Path
from typing import ClassVar

import pytest

from coverlyric import __main__ as cli
from coverlyric import jobs, media, render, server
from coverlyric.project import Project

DEMO = Path(render.__file__).parent / "demo" / "demo.json"


class PagingFileTooSmall(OSError):
    """What Windows raises when a shared block cannot be committed; set on the class so the test
    runs the same on every system."""

    winerror = 1455


def paging_error() -> OSError:
    return PagingFileTooSmall(22, "The paging file is too small for this operation to complete")


def test_steps_halve_the_workers_then_drop_the_shared_turn():
    shared, alone, bare = (True, True), (False, True), (False, False)
    assert render.steps(6) == [
        (6, *shared, False),
        (3, *shared, False),
        (1, *shared, False),
        (1, *alone, False),
    ]
    assert render.steps(2) == [(2, *shared, False), (1, *shared, False), (1, *alone, False)]
    assert render.steps(1, anim=True) == [
        (1, *shared, False),
        (1, *alone, False),
        (1, *bare, False),
    ]
    assert render.steps(1, anim=True, smaller=True)[-2:] == [(1, *bare, False), (1, *bare, True)]
    assert render.steps(1, smaller=True)[-1] == (1, *alone, True)


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

    def encode(out, lines, song, style, workers, span, report, codec, quick, shared, lead=0.0):
        calls.append((workers, shared, bool(song.anim)) + ((720,) if style.height == 720 else ()))
        if len(calls) <= fails:
            raise error or paging_error()

    monkeypatch.setattr(render, "encode", encode)
    monkeypatch.setattr(media, "encoder", lambda: "libx264")
    return calls, notes


def test_a_render_short_of_memory_tries_again_with_less(monkeypatch, tmp_path):
    calls, notes = fake_encode(monkeypatch, fails=3)
    demo = Project.load(DEMO)
    render.render(tmp_path / "out.mp4", (), demo.song(), render.Style(), 6, note=notes.append)
    assert calls == [(6, True, False), (3, True, False), (1, True, False), (1, False, False)]
    assert (
        len(notes) == 3 and "1 worker" in notes[-1] and "CD turn drawn on each frame" in notes[-1]
    )


def test_when_nothing_is_left_to_try_the_error_goes_up(monkeypatch, tmp_path):
    calls, notes = fake_encode(monkeypatch, fails=99)
    demo = Project.load(DEMO)
    with pytest.raises(PagingFileTooSmall) as caught:
        render.render(tmp_path / "out.mp4", (), demo.song(), render.Style(), 2, note=notes.append)
    assert calls == [(2, True, False), (1, True, False), (1, False, False), (1, False, False, 720)]
    message = cli.failure(caught.value)
    assert message == jobs.MEMORY_ERROR
    assert "paging" not in message.lower() and "1455" not in message


def test_other_errors_are_not_tried_again(monkeypatch, tmp_path):
    calls, _ = fake_encode(monkeypatch, fails=1, error=ValueError("bad lyrics"))
    demo = Project.load(DEMO)
    with pytest.raises(ValueError):
        render.render(tmp_path / "out.mp4", (), demo.song(), render.Style(), 4)
    assert calls == [(4, True, False)]


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

    made: ClassVar[list[int]] = []
    refuse: ClassVar[int | None] = None

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


def test_the_moving_picture_is_kept_without_shared_memory(monkeypatch, tmp_path):
    calls, notes = fake_encode(monkeypatch, fails=2)
    song = replace(Project.load(DEMO).song(), anim=("a.gif",))
    said = render.render(tmp_path / "out.mp4", (), song, render.Style(), 2, note=notes.append)
    assert calls == [(2, True, True), (1, True, True), (1, False, True)]
    assert said == ""
    assert "moving picture loaded in the worker" in notes[-1]


def test_the_moving_picture_goes_last_and_the_user_is_told(monkeypatch, tmp_path):
    calls, notes = fake_encode(monkeypatch, fails=3)
    song = replace(Project.load(DEMO).song(), anim=("a.gif",))
    said = render.render(tmp_path / "out.mp4", (), song, render.Style(), 2, note=notes.append)
    assert calls[-1] == (1, False, False)
    assert len(calls) == 4
    assert said == render.ANIM_DROPPED
    assert "without the moving picture" in notes[-1]


def watched(app, method, script, *args):
    proc = server.subprocess.Popen(
        [sys.executable, "-I", "-X", "utf8", "-c", script],
        stdout=server.subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    return proc, lambda: method(proc, *args)


def test_the_done_line_carries_the_notice(tmp_path, caplog):
    app = server.App(tmp_path)
    out = tmp_path / "song.mp4"
    out.write_bytes(b"video")
    proc, run = watched(app, app.watch, f"print('notice {render.ANIM_DROPPED}')", out)
    app.proc = proc
    app.job = {"state": "running", "started": time.time()}
    with caplog.at_level(logging.INFO, logger="coverlyric"):
        run()
    assert app.job["state"] == "done" and app.job["note"] == render.ANIM_DROPPED
    assert render.ANIM_DROPPED in caplog.text


def test_a_failed_clip_shows_words_not_the_traceback(tmp_path):
    app = server.App(tmp_path)
    script = (
        "print('Traceback (most recent call last):'); "
        "print('OSError: [WinError 1455] The paging file is too small'); "
        f"print('error: {jobs.MEMORY_ERROR}'); import sys; sys.exit(1)"
    )
    proc, run = watched(app, app.watch_clip, script, tmp_path / "clip.mp4", 0.0)
    app.clip_proc = proc
    app.clip = {"state": "running"}
    run()
    assert app.clip["state"] == "error"
    assert app.clip["message"].startswith(jobs.MEMORY_ERROR) and "1455" not in app.clip["message"]


@pytest.mark.parametrize(
    ("said", "kind"),
    [
        ("x264 [error]: malloc of size 12116928 failed\nError encoding a frame", MemoryError),
        ("[in#0] Error during demuxing: Cannot allocate memory", MemoryError),
        ("song.wav: Invalid data found when processing input", RuntimeError),
    ],
)
def test_ffmpeg_out_of_memory_is_a_memory_error(said, kind):
    error = render.ffmpeg_failure(3752568763, said)
    assert type(error) is kind
    assert render.out_of_memory(error) is (kind is MemoryError)


FAKE_FFMPEG = """
import sys
sys.stdin.buffer.read({size})
sys.stderr.write({said!r})
sys.exit(0)
"""


@pytest.mark.parametrize(
    ("said", "kind"),
    [("[in#0] Error during demuxing: Cannot allocate memory\n", MemoryError), ("", RuntimeError)],
)
def test_ffmpeg_that_stops_early_is_never_a_finished_video(monkeypatch, tmp_path, said, kind):
    # Out of memory, ffmpeg can take the failed read as the end of the input and exit 0 (#15).
    fake = tmp_path / "ffmpeg.py"
    fake.write_text(FAKE_FFMPEG.format(size=2 * render.FRAME, said=said), encoding="utf-8")
    popen = server.subprocess.Popen

    def run(cmd, **kw):
        return popen([sys.executable, "-I", str(fake)] if cmd[0] == "ffmpeg" else cmd, **kw)

    monkeypatch.setattr(media, "ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(render.subprocess, "Popen", run)
    demo = Project.load(DEMO)
    with pytest.raises(kind):
        render.encode(
            tmp_path / "out.mp4",
            demo.preview_lines(),
            demo.song(),
            render.Style(),
            1,
            (3.0, 5.0),
            lambda *a: None,
            "libx264",
            shared=False,
        )


def test_a_1080p_video_short_of_memory_is_made_at_720p_and_the_user_is_told(monkeypatch, tmp_path):
    calls, notes = fake_encode(monkeypatch, fails=4)
    song = replace(Project.load(DEMO).song(), anim=("a.gif",))
    said = render.render(tmp_path / "out.mp4", (), song, render.Style(), 2, note=notes.append)
    assert calls[-2:] == [(1, False, False), (1, False, False, 720)]
    assert said == f"{render.ANIM_DROPPED} {render.SMALLER}"
    assert "at 720p" in notes[-1]


def test_no_720p_step_for_720p_or_a_clip(monkeypatch, tmp_path):
    calls, _ = fake_encode(monkeypatch, fails=99)
    demo = Project.load(DEMO)
    for style, quick in ((render.Style(height=720), False), (render.Style(), True)):
        calls.clear()
        with pytest.raises(PagingFileTooSmall):
            render.render(tmp_path / "out.mp4", (), demo.song(), style, 1, quick=quick)
        assert [c[:3] for c in calls] == [(1, True, False), (1, False, False)]

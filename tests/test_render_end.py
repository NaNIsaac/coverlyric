"""How a render ends on the page: the finished video's length and size, room on the drive checked
before it starts, and a render cut off by closing the program shown and cleaned up on the next start."""

import json

import pytest

from coverlyric import render, server


class Done:
    stdout = iter(())
    pid = 0

    def __init__(self, *args, **kwargs):
        pass

    def wait(self):
        return 0

    def poll(self):
        return 0


def test_a_finished_video_comes_with_its_length_and_size(tmp_path):
    app = server.App(tmp_path)
    out = app.output / "봄 노래.mp4"
    out.write_bytes(b"x" * 4000)
    app.proc = proc = Done()
    app.job = {"state": "running", "started": 0, "total": 18.4}
    app.watch(proc, out)
    assert app.job["state"] == "done"
    assert (app.job["length"], app.job["size"]) == (18.4, 4000)


def test_a_video_needs_room_by_its_length_and_height():
    style = render.Style()
    assert server.video_mb(100, style) == 60 + server.VIDEO_MB_EXTRA
    assert server.video_mb(100, render.Style(height=720)) == 30 + server.VIDEO_MB_EXTRA
    assert server.video_mb(100, render.Style(shape="tall", height=720)) == 110


def test_a_render_without_room_on_the_drive_does_not_start(tmp_path, monkeypatch):
    app = server.App(tmp_path)
    app.demo()
    started = []
    monkeypatch.setattr(server.subprocess, "Popen", lambda *a, **k: started.append(1))
    monkeypatch.setattr(server.shutil, "disk_usage", lambda path: (100e9, 99.99e9, 10e6))
    with pytest.raises(ValueError, match="디스크 공간 부족") as e:
        app.start_render()
    assert "현재 10 MB" in str(e.value) and "저장 위치" in str(e.value)
    assert not started and app.job == {"state": "idle"}
    assert not app.marker.exists()


def test_a_render_marks_itself_until_it_ends(tmp_path, monkeypatch):
    app = server.App(tmp_path)
    app.demo()
    watch = server.App.watch
    monkeypatch.setattr(server.subprocess, "Popen", Done)
    monkeypatch.setattr(server.App, "watch", lambda self, proc, out: None)
    app.start_render()
    out = json.loads(app.marker.read_text(encoding="utf-8"))["out"]
    assert out.endswith(".mp4")
    app.job = {"state": "stopped"}
    watch(app, app.proc, app.output / "none.mp4")
    assert not app.marker.exists()


def test_a_render_cut_off_is_shown_and_its_half_video_removed(tmp_path):
    app = server.App(tmp_path)
    out = app.output / "봄 노래.mp4"
    part = out.with_name("봄 노래.making.mp4")
    part.write_bytes(b"half a video")
    stray = app.output / "다른 노래.making.mp4"
    stray.write_bytes(b"half a video")
    finished = app.output / "지난 노래.mp4"
    finished.write_bytes(b"a whole video")
    app.marker.write_text(json.dumps({"out": str(out)}, ensure_ascii=False), encoding="utf-8")

    again = server.App(tmp_path)
    assert again.job == {"state": "interrupted", "out": str(out)}
    assert not part.exists() and not stray.exists() and finished.exists()
    assert not again.marker.exists()
    assert server.App(tmp_path).job == {"state": "idle"}


def test_a_broken_marker_still_counts_as_cut_off(tmp_path):
    app = server.App(tmp_path)
    app.marker.write_text("{", encoding="utf-8")
    assert server.App(tmp_path).job == {"state": "interrupted", "out": ""}

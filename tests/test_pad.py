"""Silence before and after the song: the video starts on the cover, the song and the lyrics a little later."""

import json
from pathlib import Path

import pytest
from test_fade import DEMO, loudness

from coverlyric import media, render, server
from coverlyric.project import Project

LEAD, TAIL = 1.0, 1.5
PAD = render.Style(lead=LEAD, tail=TAIL, fade=False)


def test_the_lines_move_on_the_video_clock_and_the_project_keeps_song_times():
    song = render.Song("a.wav", "c.png", "t", duration=10.0)
    lines = ((2.0, "a"), (4.5, "b"))
    moved, video = render.padded(lines, song, PAD)
    assert moved == ((3.0, "a"), (5.5, "b"))
    assert video.duration == 12.5 and (video.lead, video.tail) == (LEAD, TAIL)
    assert render.padded(moved, video, PAD) == (moved, video), "padding twice adds nothing"
    assert render.padded(lines, song, render.Style()) == (lines, song)


def test_a_moment_of_the_song_in_the_video():
    assert render.video_time(4.0, PAD) == 5.0
    assert render.video_time(0.0, PAD) == 0.0, "the song's start shows the silence before it"
    assert render.video_time(4.0, render.Style()) == 4.0


def test_a_style_saved_without_them_has_no_silence():
    style = render.Style.from_dict({"lead": "1.5"})
    assert (style.lead, style.tail) == (1.5, 0.0)


def make(tmp_path: Path, span, style: render.Style, quick: bool = False) -> Path:
    demo = Project.load(DEMO)
    out = tmp_path / "pad.mp4"
    render.render(out, demo.preview_lines(), demo.song(), style, 2, span, lambda *_: None, quick)
    return out


def test_the_song_starts_after_the_silence_before_it(tmp_path):
    (tmp_path / "pad").mkdir()
    (tmp_path / "plain").mkdir()
    pad = make(tmp_path / "pad", (0.0, 2.5), PAD)
    plain = make(tmp_path / "plain", (0.0, 1.5), render.Style(fade=False))
    assert loudness(pad, 0.1, 0.8) < 1
    assert loudness(plain, 0.2) > 100
    assert loudness(pad, LEAD + 0.2) == pytest.approx(loudness(plain, 0.2), rel=0.1)
    assert media.duration(str(pad)) == pytest.approx(2.5, abs=0.1)


def test_the_video_is_as_long_as_the_song_and_both_silences(tmp_path):
    song = Project.load(DEMO).song().duration
    out = make(tmp_path, None, PAD, quick=True)
    assert media.duration(str(out)) == pytest.approx(song + LEAD + TAIL, abs=0.15)
    assert loudness(out, song + LEAD - 0.6, 0.3) > 1
    assert loudness(out, song + LEAD + 0.3, 1.0) < 1


def test_the_page_maps_the_preview_time_onto_the_video(tmp_path):
    app = server.App(tmp_path)
    app.demo()
    app.update({"style": {"lead": LEAD, "tail": TAIL}})
    song = app.project.song().duration
    app.job = {"state": "idle"}
    assert app.preview(0.0)[0][:2] == b"\xff\xd8"
    app.start_clip(4.0)
    assert app.clip["at"] == pytest.approx(4.0 + LEAD)
    app.stop_clip()
    app.start_clip(0.0)
    assert app.clip["at"] == 0.0
    app.stop_clip()
    app.start_clip(song + 5.0)
    assert app.clip["at"] == pytest.approx(song + LEAD + TAIL - 1.0)
    app.stop_clip()


def test_a_render_job_counts_the_padded_length(tmp_path, monkeypatch):
    app = server.App(tmp_path)
    app.demo()
    app.update({"style": {"lead": LEAD, "tail": TAIL}})
    started = []
    monkeypatch.setattr(
        server.subprocess, "Popen", lambda cmd, **kw: started.append(cmd) or FakeProc()
    )
    monkeypatch.setattr(app, "watch", lambda *a: None)
    job = app.begin_render()
    assert job["total"] == pytest.approx(app.project.duration + LEAD + TAIL)
    data = json.loads((app.work / "job.json").read_text(encoding="utf-8"))
    assert (data["style"]["lead"], data["style"]["tail"]) == (LEAD, TAIL)


class FakeProc:
    stdout = iter(())
    pid = 0

    def wait(self):
        return 0

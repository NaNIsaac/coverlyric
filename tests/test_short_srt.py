"""The short's own SRT: the clip on its own clock, with a loop lead's line at the end (tall.cues), from
the command line, the page and beside a made short; and letter times typed by hand (--letters)."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from coverlyric import __main__ as entry
from coverlyric import cli, jobs, render, server, tall, timing
from coverlyric.project import Project

DEMO = Path(render.__file__).parent / "demo"
LINES = [(2.0, "하나 줄"), (5.0, "둘 줄"), (8.0, "셋 줄"), (12.0, "넷 줄"), (16.0, "다섯 줄")]
SHORT = render.Style(shape="tall", fps=30, clip_from=8.0, clip_to=14.0, loop=True)
SONG = render.Song("song.wav", "cover.png", "t", duration=20.0)


def test_the_short_is_the_clip_on_its_own_clock():
    rows, length = tall.cues(SHORT, SONG, LINES)
    assert length == pytest.approx(6.0)
    assert rows == [(0.0, 4.0, "셋 줄"), (4.0, 6.0, "넷 줄")]


def test_a_loop_lead_s_line_closes_the_short():
    rows, length = tall.cues(replace(SHORT, loop_lead_line=True), SONG, LINES)
    # The lead is 5.0 to 8.0; the clip's last 0.5 s blends into it, so it starts at 5.5.
    assert length == pytest.approx(6.0 + 3.0 - tall.LOOP)
    assert rows == [(0.0, 4.0, "셋 줄"), (4.0, 5.5, "넷 줄"), (5.5, 8.5, "둘 줄")]
    rows, _ = tall.cues(replace(SHORT, loop_lead=2.0), SONG, LINES)
    assert rows[-1] == (5.5, 7.5, "둘 줄"), "two seconds of the line before"


def test_a_line_cut_short_at_the_clip_s_start():
    rows, _ = tall.cues(replace(SHORT, clip_from=7.6), SONG, LINES)
    assert rows[0][2] == "셋 줄", "0.4 s of the line before is left out"
    rows, _ = tall.cues(replace(SHORT, clip_from=7.0), SONG, LINES)
    assert rows[0] == (0.0, 1.0, "둘 줄")


def run(capsys, *argv) -> tuple[int, dict]:
    with pytest.raises(SystemExit) as done:
        entry.main([*argv, "--json"])
    out = capsys.readouterr().out.strip().splitlines()
    return done.value.code, json.loads(out[-1])


@pytest.fixture()
def song(tmp_path) -> Path:
    lyrics = tmp_path / "lyrics.txt"
    lyrics.write_text("\n".join(text for _, text in LINES), encoding="utf-8")
    folder = tmp_path / "작은 노래"
    p = cli.new_project(folder, DEMO / "tone.wav", DEMO / "cover.png", lyrics, "작은 노래")
    p.lines, p.duration, p.style = list(LINES), 20.0, replace(SHORT, loop_lead_line=True)
    p.save(folder / "project.json")
    return folder


def cue_texts(path: Path) -> list[str]:
    return [b.split("\n")[2] for b in path.read_text("utf-8").strip().split("\n\n")]


def test_the_srt_command_writes_the_song_s_and_the_short_s(capsys, song):
    code, data = run(capsys, "srt", str(song))
    assert code == 0, data
    whole, short = song / "작은 노래.srt", song / "작은 노래_shorts.srt"
    assert data["srt"] == str(whole) and data["short_srt"] == str(short)
    assert data["short_length"] == pytest.approx(8.5)
    assert cue_texts(whole) == [text for _, text in LINES]
    assert cue_texts(short) == ["셋 줄", "넷 줄", "둘 줄"]
    assert "00:00:05,500 --> 00:00:08,500\n둘 줄" in short.read_text("utf-8")


def test_a_16_9_project_writes_only_the_song_s(capsys, song, tmp_path):
    p = Project.load(song / "project.json")
    p.style = replace(p.style, shape="wide")
    p.save(song / "project.json")
    code, data = run(capsys, "srt", str(song), "--out", str(tmp_path / "out"))
    assert code == 0 and "short_srt" not in data
    assert (tmp_path / "out" / "작은 노래.srt").is_file()


def test_the_page_saves_the_short_s_srt_beside_the_song_s(tmp_path):
    app = server.App(tmp_path)
    app.update({"title": "봄 노래", "lines": [list(line) for line in LINES]})
    app.project.duration = 20.0
    app.project.style = replace(SHORT, loop_lead=3.0)
    app.set_output(str(tmp_path / "videos"))
    saved = app.save_timing("srt")
    short = tmp_path / "videos" / "봄 노래_shorts.srt"
    assert saved["short"] == str(short.resolve())
    assert cue_texts(short) == ["셋 줄", "넷 줄", "둘 줄"]
    assert (tmp_path / "videos" / "봄 노래.srt").is_file()


def test_beside_a_made_short(song, tmp_path):
    p = Project.load(song / "project.json")
    out = tmp_path / "x_shorts.mp4"
    out.write_bytes(b"")
    jobs.beside(out, p, tuple(p.lines), p.song())
    assert cue_texts(out.with_suffix(".srt")) == ["셋 줄", "넷 줄", "둘 줄"]


def test_letter_times_typed_by_hand(capsys, song):
    code, data = run(capsys, "project", "lines", str(song), "--letters", "3=8.0,8.4")
    assert code == 0, data
    p = Project.load(song / "project.json")
    assert p.letters == [{"n": 3, "text": "셋 줄", "times": [8.0, 8.4]}]
    assert p.song().letters == ((8.0, "셋 줄", (8.0, 8.4)),)
    code, data = run(capsys, "project", "lines", str(song), "--letters", "3=8.0")
    assert code == 2 and "takes 2 times" in data["error"]
    run(capsys, "project", "lines", str(song), "--letters", "3=9,9.3")
    assert Project.load(song / "project.json").letters[0]["times"] == [9.0, 9.3], "replaced"
    run(capsys, "project", "lines", str(song), "--text", "3=셋째 줄")
    assert Project.load(song / "project.json").song().letters == (), "the text moved on"


def test_the_srt_cues_are_the_old_ones():
    lines = [(1.0, "a"), (2.5, ""), (4.0, "b")]
    assert timing.srt(timing.cues(lines, 6.0)) == timing.to_srt(lines, 6.0)
    assert timing.cues(lines, 6.0) == [(1.0, 2.5, "a"), (4.0, 6.0, "b")]

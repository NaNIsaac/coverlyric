"""The output commands: list, show, add, use and remove the videos made from one song; --output works
on one output without changing the current one; make --short adds a Short of a part."""

import json
from pathlib import Path

import pytest

from coverlyric import __main__ as entry
from coverlyric import cli, overlay
from coverlyric.project import Project

DEMO = Path(cli.__file__).parent / "demo"
SRT = "1\n00:00:03,000 --> 00:00:06,000\n첫 줄\n\n2\n00:00:06,000 --> 00:00:09,000\n둘째 줄\n"


def run(capsys, *argv) -> tuple[int, dict]:
    with pytest.raises(SystemExit) as done:
        entry.main([*argv, "--json"])
    out = capsys.readouterr().out.strip().splitlines()
    return done.value.code, json.loads(out[-1])


@pytest.fixture()
def song(tmp_path) -> Path:
    lyrics = tmp_path / "lyrics.txt"
    lyrics.write_text("첫 줄\n둘째 줄", encoding="utf-8")
    folder = tmp_path / "노래"
    cli.new_project(folder, DEMO / "tone.wav", DEMO / "cover.png", lyrics, "노래")
    return folder


def ids(data: dict) -> list[tuple[str, str, bool]]:
    return [(o["id"], o["file"], o["current"]) for o in data["outputs"]]


def test_a_new_project_has_one_output(capsys, song):
    code, data = run(capsys, "output", "list", str(song))
    assert code == 0 and ids(data) == [("wide", "노래.mp4", True)]


def test_add_a_short_and_another_of_its_shape(capsys, song):
    code, data = run(capsys, "output", "add", str(song), "short", "--shape", "tall")
    assert code == 0
    assert ids(data) == [("wide", "노래.mp4", False), ("short", "노래_shorts.mp4", True)]
    p = Project.load(song / "project.json")
    assert p.style.shape == "tall" and p.outputs[0].style.shape == "wide"
    code, data = run(capsys, "output", "add", str(song), "short-2", "--from", "short")
    assert ids(data)[2] == ("short-2", "노래_shorts-2.mp4", True)
    assert data["outputs"][2]["clip"] == data["outputs"][1]["clip"]


def test_output_flag_works_on_one_output_and_keeps_the_current(capsys, song):
    run(capsys, "output", "add", str(song), "short", "--shape", "tall")
    code, data = run(capsys, "project", "set", str(song), "--output", "wide", "lead=1")
    assert code == 0 and data["output"] == "wide"
    p = Project.load(song / "project.json")
    assert p.current == "short" and p.outputs[0].style.lead == 1.0 and p.style.lead == 0.0
    code, shown = run(capsys, "output", "show", str(song), "wide")
    assert shown["output"] == "wide" and shown["style"]["lead"] == 1.0


def test_use_and_remove(capsys, song):
    run(capsys, "output", "add", str(song), "short", "--shape", "tall")
    code, data = run(capsys, "output", "use", str(song), "wide")
    assert [o["current"] for o in data["outputs"]] == [True, False]
    code, data = run(capsys, "output", "remove", str(song), "short")
    assert ids(data) == [("wide", "노래.mp4", True)]
    code, data = run(capsys, "output", "remove", str(song), "wide")
    assert code == 2 and "last output" in data["error"]


@pytest.mark.parametrize(
    "argv",
    [
        ("output", "use", "{song}", "gone"),
        ("output", "add", "{song}", "Bad Id"),
        ("output", "add", "{song}", "wide"),
        ("render", "{song}", "--output", "gone"),
    ],
)
def test_a_wrong_output_is_refused(capsys, song, argv):
    code, data = run(capsys, *(a.format(song=song) for a in argv))
    assert code == 2, data


def test_each_output_keeps_its_own_video(capsys, song, tmp_path, monkeypatch):
    monkeypatch.setattr(overlay, "length", lambda path: 2.0)
    a, b = tmp_path / "a.mp4", tmp_path / "b.mp4"
    a.write_bytes(b"a")
    b.write_bytes(b"b")
    run(capsys, "project", "set", str(song), f"video={a}")
    run(capsys, "output", "add", str(song), "short", "--shape", "tall")
    run(capsys, "project", "set", str(song), f"video={b}")
    p = Project.load(song / "project.json")
    assert [o.video for o in p.outputs] == ["video.mp4", "video-short.mp4"]
    assert (song / "video.mp4").read_bytes() == b"a"
    run(capsys, "project", "set", str(song), "video=")
    assert (song / "video.mp4").exists() and not (song / "video-short.mp4").exists()


def test_make_with_a_short_renders_both(capsys, tmp_path, monkeypatch):
    made = []

    def fake(project, out, clip=None, quick=False):
        made.append((project.output.id, project.style.shape, project.style.clip_from))
        return {"video": str(project.folder / cli.video_name(project)), "seconds": 0.0}

    monkeypatch.setattr(cli, "make_video", fake)
    srt = tmp_path / "t.srt"
    srt.write_text(SRT, encoding="utf-8")
    argv = ["make", "--audio", str(DEMO / "tone.wav"), "--cover", str(DEMO / "cover.png")]
    argv += ["--timing", str(srt), "--title", "노래", "--out", str(tmp_path / "out")]
    code, data = run(capsys, *argv, "--short", "0:03,0:09")
    assert code == 0, data
    assert made == [("wide", "wide", 0.0), ("short", "tall", 3.0)]
    assert data["short"]["video"].endswith("노래_shorts.mp4")
    p = Project.load(Path(data["project"]))
    assert p.current == "wide" and [o.id for o in p.outputs] == ["wide", "short"]
    code, data = run(capsys, *argv[:-2], "--out", str(tmp_path / "o2"), "--short", "3")
    assert code == 2


def test_a_failed_short_render_leaves_the_wide_one_current(capsys, tmp_path, monkeypatch):
    def fake(project, out, clip=None, quick=False):
        if project.output.id == "short":
            raise RuntimeError("encoder stopped")
        return {"video": str(project.folder / cli.video_name(project)), "seconds": 0.0}

    monkeypatch.setattr(cli, "make_video", fake)
    srt = tmp_path / "t.srt"
    srt.write_text(SRT, encoding="utf-8")
    argv = ["make", "--audio", str(DEMO / "tone.wav"), "--cover", str(DEMO / "cover.png")]
    argv += ["--timing", str(srt), "--title", "노래", "--out", str(tmp_path / "out")]
    code, data = run(capsys, *argv, "--short", "0:03,0:09")
    assert code == 1 and "encoder stopped" in data["error"]
    p = Project.load(tmp_path / "out" / "노래" / "project.json")
    assert p.current == "wide" and [o.id for o in p.outputs] == ["wide", "short"]
